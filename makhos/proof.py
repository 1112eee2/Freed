"""Bounded non-loss proof construction and independent certificate checking."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import mmap
from pathlib import Path
import struct
from typing import Any, Iterable, Mapping

from .core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    Move,
    RED,
    RED_KING,
    RED_MAN,
    Rules,
    State,
    TerminalStatus,
    apply_move,
    format_position,
    legal_moves,
    parse_position,
    terminal_status,
)
from .audit_rules import IndependentRulesAuditor
from .exact import Outcome
from .native_tablebase import NativeProbe, NativeTablebase
from .ranked_tablebase import RankedTablebase, fnv1a_file_ranges


class ProofBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProofStats:
    expanded: int
    certificate_nodes: int


class EndgameOracle:
    """Exact WDL frontier shared by the prover and certificate checker."""

    def __init__(
        self,
        *,
        native: NativeTablebase | None = None,
        ranked: RankedTablebase | None = None,
        ranked_tablebases: Iterable[RankedTablebase] = (),
    ) -> None:
        self.native = native
        tablebases = list(ranked_tablebases)
        if ranked is not None:
            tablebases.append(ranked)
        self.ranked_tablebases: dict[int, RankedTablebase] = {}
        for tablebase in tablebases:
            if tablebase.piece_count in self.ranked_tablebases:
                raise ValueError(
                    f"duplicate {tablebase.piece_count}-piece ranked tablebase"
                )
            self.ranked_tablebases[tablebase.piece_count] = tablebase
        # Backward-compatible access for existing single-tablebase callers.
        self.ranked = ranked

    def require_no_progress(self, no_progress_plies: int, *, owner: str) -> None:
        """Reject exact frontiers built for a different draw horizon."""

        if (
            self.native is not None and
            getattr(self.native, "no_progress_plies", None) != no_progress_plies
        ):
            raise ValueError(f"{owner}/native tablebase no-progress mismatch")
        if any(
            tablebase.no_progress_plies != no_progress_plies
            for tablebase in self.ranked_tablebases.values()
        ):
            raise ValueError(f"{owner}/ranked tablebase no-progress mismatch")

    def probe(self, state: State) -> NativeProbe | None:
        pieces = sum(piece != 0 for piece in state.board)
        ranked = self.ranked_tablebases.get(pieces)
        if ranked is not None:
            return ranked.probe(state)
        if 1 <= pieces <= 3 and self.native is not None:
            return self.native.probe(state)
        return None


def _state_id(state: State) -> str:
    canonical = (
        f"{format_position(state)}|clock={state.reversible_plies}"
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _exact_state_id(state: State) -> str:
    """Collision-free native-friendly node id used by v2 certificates."""

    red = black = kings = 0
    for square, piece in enumerate(state.board):
        bit = 1 << square
        if piece in (RED_MAN, RED_KING):
            red |= bit
        elif piece in (BLACK_MAN, BLACK_KING):
            black |= bit
        if piece in (RED_KING, BLACK_KING):
            kings |= bit
    return (
        f"{red:08x}-{black:08x}-{kings:08x}-"
        f"{state.turn}-{state.reversible_plies}"
    )


def _state_bitboards(state: State) -> tuple[int, int, int]:
    red = black = kings = 0
    for square, piece in enumerate(state.board):
        bit = 1 << square
        if piece in (RED_MAN, RED_KING):
            red |= bit
        elif piece in (BLACK_MAN, BLACK_KING):
            black |= bit
        if piece in (RED_KING, BLACK_KING):
            kings |= bit
    return red, black, kings


def _state_from_bitboards(
    red: int,
    black: int,
    kings: int,
    turn: int,
    clock: int,
) -> State:
    if red & black or kings & ~(red | black) or turn not in (RED, BLACK):
        raise ValueError("invalid mapped proof-strategy root")
    board = [0] * 32
    for square in range(32):
        bit = 1 << square
        if red & bit:
            board[square] = RED_KING if kings & bit else RED_MAN
        elif black & bit:
            board[square] = BLACK_KING if kings & bit else BLACK_MAN
    return State(tuple(board), turn, clock)


def _proof_edge_state_key(state: State) -> tuple[tuple[int, ...], int, int]:
    return state.board, state.turn, state.reversible_plies


def _proof_status_and_moves(
    state: State,
    rules: Rules,
    rules_auditor: IndependentRulesAuditor | None,
) -> tuple[TerminalStatus, tuple[Move, ...]]:
    """Evaluate a proof node once and optionally cross-check every legal edge."""

    if state.reversible_plies >= rules.no_progress_plies:
        return TerminalStatus(True, None, "no_progress"), ()
    moves = legal_moves(state)
    if rules_auditor is not None:
        reference_edges = tuple(sorted(
            (
                move.notation,
                _proof_edge_state_key(apply_move(state, move, validate=False)),
            )
            for move in moves
        ))
        audited_edges = tuple(sorted(
            (move.notation, _proof_edge_state_key(move.child))
            for move in rules_auditor.legal_moves(state)
        ))
        if reference_edges != audited_edges:
            raise ValueError(
                "independent rules audit mismatch at " + format_position(state)
            )
    if not moves:
        winner = BLACK if state.turn == RED else RED
        return TerminalStatus(True, winner, "no_legal_move"), ()
    return TerminalStatus(False), moves


def _root_outcome(outcome: Outcome, state: State, root_player: int) -> Outcome:
    return outcome if state.turn == root_player else Outcome(-outcome)


def _safe_tablebase_moves(
    state: State,
    root_player: int,
    no_progress_plies: int,
    oracle: EndgameOracle,
) -> tuple[Move, ...]:
    current = oracle.probe(state)
    if current is None:
        raise ValueError("tablebase continuation is outside the exact frontier")
    if _root_outcome(current.outcome, state, root_player) < Outcome.DRAW:
        raise ValueError("tablebase continuation is a root-player loss")
    rules = Rules(
        repetition_limit=None,
        no_progress_plies=no_progress_plies,
    )
    safe: list[Move] = []
    for move in legal_moves(state):
        child = apply_move(state, move, validate=False)
        status = terminal_status(child, rules=rules)
        if status.terminal:
            if status.winner is None or status.winner == root_player:
                safe.append(move)
            continue
        result = oracle.probe(child)
        if result is None:
            raise ValueError("tablebase strategy child is outside the exact frontier")
        if _root_outcome(result.outcome, child, root_player) >= Outcome.DRAW:
            safe.append(move)
    if not safe:
        raise ValueError("non-loss tablebase leaf has no safe legal move")
    return tuple(safe)


class NonLossProver:
    """Construct an AND/OR proof that ``root_player`` can avoid a loss.

    Search is exact and has no heuristic leaf values or forward pruning. Move
    ordering only changes which proof is found first. A failed node budget is
    reported as UNKNOWN, never as a draw.
    """

    def __init__(
        self,
        rules: Rules,
        oracle: EndgameOracle,
        *,
        node_budget: int = 1_000_000,
        collect_all_choices: bool = False,
    ) -> None:
        if rules.repetition_limit is not None:
            raise ValueError("proof search requires repetition_limit=None")
        if node_budget < 1:
            raise ValueError("node_budget must be positive")
        oracle.require_no_progress(
            rules.no_progress_plies,
            owner="proof search",
        )
        self.rules = rules
        self.oracle = oracle
        self.node_budget = node_budget
        self.collect_all_choices = collect_all_choices
        self.expanded = 0
        self._memo: dict[tuple, bool] = {}
        self._nodes: dict[str, dict[str, Any]] = {}
        self._visiting: set[tuple] = set()
        self._root_player = BLACK

    @staticmethod
    def _key(state: State) -> tuple:
        return state.board, state.turn, state.reversible_plies

    def prove(self, state: State, root_player: int) -> tuple[dict[str, Any] | None, ProofStats]:
        if root_player not in (RED, BLACK):
            raise ValueError("invalid root player")
        self.expanded = 0
        self._memo.clear()
        self._nodes.clear()
        self._visiting.clear()
        self._root_player = root_player
        proven = self._prove(state)
        if not proven:
            return None, ProofStats(self.expanded, 0)

        root_id = _state_id(state)
        reachable: dict[str, dict[str, Any]] = {}

        def collect(node_id: str) -> None:
            if node_id in reachable:
                return
            node = self._nodes[node_id]
            reachable[node_id] = node
            for edge in node.get("edges", ()):
                collect(edge["child"])

        collect(root_id)
        certificate = {
            "format": "makhos-nonloss-proof-v1",
            "rules": {
                "repetition_limit": None,
                "no_progress_plies": self.rules.no_progress_plies,
            },
            "root_player": "BLACK" if root_player == BLACK else "RED",
            "root": root_id,
            "nodes": reachable,
        }
        if self.oracle.ranked_tablebases:
            certificate["ranked_tablebase_checksums"] = {
                str(piece_count): f"{tablebase.expected_checksum:016x}"
                for piece_count, tablebase in sorted(
                    self.oracle.ranked_tablebases.items()
                )
            }
        return certificate, ProofStats(self.expanded, len(reachable))

    def _prove(self, state: State) -> bool:
        key = self._key(state)
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        if self.expanded >= self.node_budget:
            raise ProofBudgetExceeded(
                f"proof search exceeded {self.node_budget:,} expanded nodes"
            )
        if key in self._visiting:
            raise RuntimeError("cycle in finite no-progress proof graph")
        self.expanded += 1
        node_id = _state_id(state)

        status = terminal_status(state, rules=self.rules)
        if status.terminal:
            proven = status.winner is None or status.winner == self._root_player
            self._memo[key] = proven
            if proven:
                self._nodes[node_id] = {
                    "position": format_position(state),
                    "clock": state.reversible_plies,
                    "kind": "terminal",
                    "reason": status.reason,
                    "winner": (
                        None if status.winner is None else
                        ("BLACK" if status.winner == BLACK else "RED")
                    ),
                }
            return proven

        tablebase = self.oracle.probe(state)
        if tablebase is not None:
            proven = _root_outcome(
                tablebase.outcome, state, self._root_player
            ) >= Outcome.DRAW
            self._memo[key] = proven
            if proven:
                self._nodes[node_id] = {
                    "position": format_position(state),
                    "clock": state.reversible_plies,
                    "kind": "tablebase",
                    "outcome": tablebase.outcome.name,
                }
            return proven

        moves = sorted(
            legal_moves(state),
            key=lambda move: (
                move.is_capture,
                len(move.captures),
                move.promotes,
                move.notation,
            ),
            reverse=True,
        )
        self._visiting.add(key)
        try:
            if state.turn == self._root_player:
                edges: list[dict[str, str]] = []
                for move in moves:
                    child = apply_move(state, move, validate=False)
                    if self._prove(child):
                        edges.append({
                            "move": move.notation,
                            "child": _state_id(child),
                        })
                        if not self.collect_all_choices:
                            break
                if edges:
                    self._memo[key] = True
                    self._nodes[node_id] = {
                        "position": format_position(state),
                        "clock": state.reversible_plies,
                        "kind": "choice",
                        "edges": edges,
                    }
                    return True
                self._memo[key] = False
                return False

            edges: list[dict[str, str]] = []
            for move in moves:
                child = apply_move(state, move, validate=False)
                if not self._prove(child):
                    self._memo[key] = False
                    return False
                edges.append({"move": move.notation, "child": _state_id(child)})
            self._memo[key] = True
            self._nodes[node_id] = {
                "position": format_position(state),
                "clock": state.reversible_plies,
                "kind": "all",
                "edges": edges,
            }
            return True
        finally:
            self._visiting.remove(key)


class CertificateChecker:
    """Rebuild every certificate edge from the reference rules."""

    def __init__(
        self,
        oracle: EndgameOracle,
        *,
        rules_auditor: IndependentRulesAuditor | None = None,
    ) -> None:
        self.oracle = oracle
        self.rules_auditor = rules_auditor

    def check(self, certificate: dict[str, Any]) -> int:
        certificate_format = certificate.get("format")
        if certificate_format not in (
            "makhos-nonloss-proof-v1",
            "makhos-nonloss-proof-v2",
        ):
            raise ValueError("unsupported proof certificate format")
        node_id_for = (
            _state_id if certificate_format == "makhos-nonloss-proof-v1"
            else _exact_state_id
        )
        rules_data = certificate.get("rules")
        if not isinstance(rules_data, dict) or rules_data.get("repetition_limit") is not None:
            raise ValueError("certificate must use repetition_limit=None")
        rules = Rules(
            repetition_limit=None,
            no_progress_plies=int(rules_data["no_progress_plies"]),
        )
        self.oracle.require_no_progress(
            rules.no_progress_plies,
            owner="certificate",
        )
        if self.oracle.ranked_tablebases:
            actual = {
                str(piece_count): f"{tablebase.expected_checksum:016x}"
                for piece_count, tablebase in sorted(
                    self.oracle.ranked_tablebases.items()
                )
            }
            expected = certificate.get("ranked_tablebase_checksums")
            if expected is None and len(actual) == 1:
                # Accept certificates produced before multi-frontier support.
                expected = {
                    next(iter(actual)): certificate.get(
                        "ranked_tablebase_checksum"
                    )
                }
            if expected != actual:
                raise ValueError("certificate/tablebase checksum mismatch")
            for tablebase in self.oracle.ranked_tablebases.values():
                verify_checksum = getattr(tablebase, "verify_checksum", None)
                if (
                    verify_checksum is not None and
                    not getattr(tablebase, "checksum_verified", False)
                ):
                    if isinstance(tablebase, RankedTablebase):
                        verify_checksum(
                            getattr(self.oracle.native, "path", None)
                        )
                    else:
                        verify_checksum()
        root_player_text = certificate.get("root_player")
        if root_player_text not in ("BLACK", "RED"):
            raise ValueError("certificate root player is invalid")
        root_player = BLACK if root_player_text == "BLACK" else RED
        nodes = certificate.get("nodes")
        if not isinstance(nodes, dict):
            raise ValueError("certificate nodes must be an object")
        root_id = certificate.get("root")
        visiting: set[str] = set()
        checked: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in checked:
                return
            if node_id in visiting:
                raise ValueError("cycle in proof certificate")
            node = nodes.get(node_id)
            if not isinstance(node, dict):
                raise ValueError(f"missing proof node {node_id}")
            state = parse_position(
                node["position"], reversible_plies=int(node["clock"])
            )
            if node_id_for(state) != node_id:
                raise ValueError("proof node id does not match its state")
            visiting.add(node_id)
            kind = node.get("kind")
            status, moves = _proof_status_and_moves(
                state,
                rules,
                self.rules_auditor,
            )
            if kind == "terminal":
                if not status.terminal:
                    raise ValueError("terminal proof node is not terminal")
                if status.winner is not None and status.winner != root_player:
                    raise ValueError("terminal proof node is a root-player loss")
            elif kind == "tablebase":
                if status.terminal:
                    raise ValueError("terminal state mislabeled as tablebase")
                result = self.oracle.probe(state)
                if result is None or result.outcome.name != node.get("outcome"):
                    raise ValueError("tablebase proof leaf does not match oracle")
                if _root_outcome(result.outcome, state, root_player) < Outcome.DRAW:
                    raise ValueError("tablebase proof leaf is a root-player loss")
            elif kind in ("choice", "all"):
                if status.terminal:
                    raise ValueError("internal proof node is terminal")
                if (kind == "choice") != (state.turn == root_player):
                    raise ValueError("AND/OR proof node has the wrong owner")
                legal = {move.notation: move for move in moves}
                edges = node.get("edges")
                if not isinstance(edges, list):
                    raise ValueError("proof node edges must be a list")
                if any(not isinstance(edge, dict) for edge in edges):
                    raise ValueError("proof node edges must be objects")
                if kind == "choice" and not edges:
                    raise ValueError("choice node must contain at least one edge")
                edge_moves = [edge.get("move") for edge in edges]
                if len(edge_moves) != len(set(edge_moves)):
                    raise ValueError("duplicate proof edge")
                if kind == "all" and set(edge_moves) != set(legal):
                    raise ValueError("opponent node does not cover every legal move")
                for edge in edges:
                    notation = edge.get("move")
                    if notation not in legal:
                        raise ValueError("illegal move in proof certificate")
                    child = apply_move(state, legal[notation], validate=False)
                    if node_id_for(child) != edge.get("child"):
                        raise ValueError("proof edge points to the wrong child state")
                    visit(edge["child"])
            else:
                raise ValueError(f"unknown proof node kind {kind!r}")
            visiting.remove(node_id)
            checked.add(node_id)

        if not isinstance(root_id, str):
            raise ValueError("certificate root is missing")
        visit(root_id)
        if checked != set(nodes):
            raise ValueError("certificate contains unreachable nodes")
        return len(checked)


class ProofStrategy:
    """Runtime move oracle backed by an independently checked proof DAG.

    A strategy is never constructed from unchecked JSON. At each reachable
    root-player choice node it returns every certified safe move so the normal
    policy can optimize only inside that set. Tablebase leaves remain under the
    normal exact tablebase policy.
    """

    def __init__(
        self,
        certificate: dict[str, Any],
        oracle: EndgameOracle,
        *,
        rules_auditor: IndependentRulesAuditor | None = None,
    ) -> None:
        self.checked_nodes = CertificateChecker(
            oracle,
            rules_auditor=rules_auditor,
        ).check(certificate)
        self._oracle = oracle
        rules_data = certificate["rules"]
        self.no_progress_plies = int(rules_data["no_progress_plies"])
        self.root_player = (
            BLACK if certificate["root_player"] == "BLACK" else RED
        )
        self.root = str(certificate["root"])
        self._node_id_for = (
            _state_id
            if certificate["format"] == "makhos-nonloss-proof-v1"
            else _exact_state_id
        )
        self._choices: dict[str, tuple[str, ...]] = {}
        self._node_kinds: dict[str, str] = {}
        for node_id, node in certificate["nodes"].items():
            kind = str(node.get("kind"))
            self._node_kinds[str(node_id)] = kind
            if kind != "choice":
                continue
            edges = node["edges"]
            self._choices[str(node_id)] = tuple(
                str(edge["move"]) for edge in edges
            )

    def moves_for(self, state: State) -> tuple[Move, ...]:
        if state.turn != self.root_player:
            raise ValueError("proof strategy cannot choose for the other player")
        if self._oracle.probe(state) is not None:
            return _safe_tablebase_moves(
                state,
                self.root_player,
                self.no_progress_plies,
                self._oracle,
            )
        node_id = self._node_id_for(state)
        kind = self._node_kinds.get(node_id)
        if kind is None:
            raise ValueError("position is outside the verified proof strategy")
        if kind == "tablebase":
            raise ValueError("verified tablebase leaf is no longer probeable")
        if kind != "choice":
            raise ValueError("root-player proof node is not a choice/tablebase node")
        legal = {move.notation: move for move in legal_moves(state)}
        try:
            return tuple(legal[notation] for notation in self._choices[node_id])
        except KeyError as error:
            raise ValueError(
                "verified proof strategy move is no longer legal"
            ) from error

    def move_for(self, state: State) -> Move | None:
        """Return the first certified move for backward-compatible callers."""

        moves = self.moves_for(state)
        return moves[0] if moves else None


_STRATEGY_MAGIC = b"MKSTRAT1"
_STRATEGY_HEADER = struct.Struct("<8s6I7Q3IBB2x")
_STRATEGY_ENTRY = struct.Struct("<IIHBB")
_MASK64 = (1 << 64) - 1


def _dfpn_tablebase_binding(checksums: Mapping[int, int]) -> int:
    """Reproduce the native DFPN binding over TB4 then compact frontiers."""

    if 4 not in checksums:
        raise ValueError("mapped strategy requires a four-piece tablebase")
    binding = int(checksums[4]) & _MASK64
    for piece_count in sorted(piece for piece in checksums if piece != 4):
        payload = struct.pack("<IQ", piece_count, int(checksums[piece_count]))
        for byte in payload:
            binding ^= byte
            binding = (binding * 1_099_511_628_211) & _MASK64
    return binding


def _mix64(value: int) -> int:
    value &= _MASK64
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & _MASK64
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & _MASK64
    value ^= value >> 31
    return value


def _strategy_hash(red: int, black: int, kings: int, turn: int, clock: int) -> int:
    value = _mix64(red)
    value ^= _mix64(black + 0x9E3779B97F4A7C15)
    value ^= _mix64(kings + 0x3C6EF372FE94F82A)
    value ^= _mix64(((turn << 8) | clock) | 0xA54FF53A5F1D36F1)
    return value & _MASK64


def _king_flags(red: int, black: int, kings: int) -> int:
    remaining = red | black
    packed = 0
    index = 0
    while remaining:
        bit = remaining & -remaining
        if kings & bit:
            packed |= 1 << index
        remaining &= remaining - 1
        index += 1
    return packed


class MappedProofStrategy:
    """Memory-mapped proof-closed set exported from a solved DFPN checkpoint.

    The constructor verifies the payload, tablebase bindings, and the complete
    reachable AND/OR closure. It retains only a compact visited bitset, so a
    strategy with hundreds of millions of hash slots does not become a Python
    object graph in memory.
    """

    def __init__(
        self,
        path: str | Path,
        oracle: EndgameOracle,
        *,
        rules_auditor: IndependentRulesAuditor | None = None,
    ) -> None:
        self.path = Path(path).resolve()
        self._file = self.path.open("rb")
        try:
            self._map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
            self._oracle = oracle
            self._rules_auditor = rules_auditor
            self._read_header()
            self._verify_payload_checksum()
            self._verify_tablebases(oracle)
            self._visited = bytearray((self.capacity + 7) // 8)
            self.checked_nodes = self._check_closure()
        except Exception:
            if hasattr(self, "_map"):
                self._map.close()
            self._file.close()
            raise

    def _read_header(self) -> None:
        if len(self._map) < _STRATEGY_HEADER.size:
            raise ValueError("truncated mapped proof strategy")
        (
            magic,
            version,
            header_bytes,
            self.no_progress_plies,
            self.root_player,
            self.hash_power,
            flags,
            self.capacity,
            self.entry_count,
            self.tablebase_binding,
            four_checksum,
            five_checksum,
            six_checksum,
            self.expected_checksum,
            root_red,
            root_black,
            root_kings,
            root_turn,
            root_clock,
        ) = _STRATEGY_HEADER.unpack_from(self._map, 0)
        if (
            magic != _STRATEGY_MAGIC or
            version != 1 or
            header_bytes != _STRATEGY_HEADER.size or
            self.root_player not in (RED, BLACK) or
            root_turn not in (RED, BLACK) or
            not 16 <= self.hash_power <= 29 or
            self.capacity != 1 << self.hash_power or
            self.entry_count > self.capacity * 85 // 100 or
            flags & ~1
        ):
            raise ValueError("invalid mapped proof-strategy header")
        expected_size = header_bytes + self.capacity * _STRATEGY_ENTRY.size
        if len(self._map) != expected_size:
            raise ValueError("mapped proof-strategy size mismatch")
        self._payload_offset = header_bytes
        self.all_choices = bool(flags & 1)
        self._expected_tablebase_checksums = {
            piece_count: f"{checksum:016x}"
            for piece_count, checksum in (
                (4, four_checksum),
                (5, five_checksum),
                (6, six_checksum),
            )
            if checksum
        }
        self.root_state = _state_from_bitboards(
            root_red, root_black, root_kings, root_turn, root_clock
        )
        if root_clock > self.no_progress_plies:
            raise ValueError("mapped proof-strategy root clock is invalid")
        self.root = _exact_state_id(self.root_state)

    def _verify_payload_checksum(self) -> None:
        value = fnv1a_file_ranges(
            self.path,
            ((self._payload_offset, len(self._map)),),
            getattr(self._oracle.native, "path", None),
        )
        if value is None:
            value = 1_469_598_103_934_665_603
            for offset in range(self._payload_offset, len(self._map), 1 << 20):
                for byte in self._map[offset:min(offset + (1 << 20), len(self._map))]:
                    value ^= byte
                    value = (value * 1_099_511_628_211) & _MASK64
        if value != self.expected_checksum:
            raise ValueError("mapped proof-strategy checksum mismatch")

    def _verify_tablebases(self, oracle: EndgameOracle) -> None:
        oracle.require_no_progress(
            self.no_progress_plies,
            owner="mapped strategy",
        )
        actual_values = {
            piece_count: int(tablebase.expected_checksum)
            for piece_count, tablebase in oracle.ranked_tablebases.items()
        }
        actual = {
            piece_count: f"{tablebase.expected_checksum:016x}"
            for piece_count, tablebase in oracle.ranked_tablebases.items()
        }
        if actual != self._expected_tablebase_checksums:
            raise ValueError("mapped strategy/tablebase checksum mismatch")
        if _dfpn_tablebase_binding(actual_values) != self.tablebase_binding:
            raise ValueError("mapped strategy/tablebase binding mismatch")
        for tablebase in oracle.ranked_tablebases.values():
            verify_checksum = getattr(tablebase, "verify_checksum", None)
            if (
                verify_checksum is not None and
                not getattr(tablebase, "checksum_verified", False)
            ):
                if isinstance(tablebase, RankedTablebase):
                    verify_checksum(getattr(oracle.native, "path", None))
                else:
                    verify_checksum()

    @staticmethod
    def _bit_is_set(bits: bytearray, slot: int) -> bool:
        return bool(bits[slot >> 3] & (1 << (slot & 7)))

    @staticmethod
    def _set_bit(bits: bytearray, slot: int) -> None:
        bits[slot >> 3] |= 1 << (slot & 7)

    @staticmethod
    def _clear_bit(bits: bytearray, slot: int) -> None:
        bits[slot >> 3] &= ~(1 << (slot & 7))

    def _lookup_slot(self, state: State) -> int | None:
        red, black, kings = _state_bitboards(state)
        flags = _king_flags(red, black, kings)
        meta = 1 + state.reversible_plies + (127 if state.turn == BLACK else 0)
        if not 0 < meta <= 255:
            return None
        mask = self.capacity - 1
        slot = _strategy_hash(
            red, black, kings, state.turn, state.reversible_plies
        ) & mask
        for _ in range(self.capacity):
            offset = self._payload_offset + slot * _STRATEGY_ENTRY.size
            entry_red, entry_black, entry_flags, entry_meta, padding = (
                _STRATEGY_ENTRY.unpack_from(self._map, offset)
            )
            if entry_meta == 0:
                return None
            if (
                entry_red == red and
                entry_black == black and
                entry_flags == flags and
                entry_meta == meta
            ):
                if padding != 0:
                    raise ValueError("invalid mapped proof-strategy entry")
                return slot
            slot = (slot + 1) & mask
        raise ValueError("mapped proof-strategy hash has no empty slot")

    def _children_to_check(
        self,
        state: State,
        moves: tuple[Move, ...],
    ) -> tuple[State, ...]:
        if state.turn == self.root_player:
            children: list[State] = []
            for move in moves:
                child = apply_move(state, move, validate=False)
                if self._lookup_slot(child) is not None:
                    children.append(child)
                    if not self.all_choices:
                        break
            if not children:
                raise ValueError("mapped engine node has no proven safe choice")
            return tuple(children)
        children = tuple(
            apply_move(state, move, validate=False) for move in moves
        )
        if any(self._lookup_slot(child) is None for child in children):
            raise ValueError("mapped opponent node omits a legal reply")
        return children

    def _check_closure(self) -> int:
        visiting = bytearray((self.capacity + 7) // 8)
        checked = 0
        stack: list[tuple[State, bool, int | None]] = [
            (self.root_state, False, None)
        ]
        rules = Rules(
            repetition_limit=None,
            no_progress_plies=self.no_progress_plies,
        )
        while stack:
            state, leaving, known_slot = stack.pop()
            slot = known_slot if known_slot is not None else self._lookup_slot(state)
            if slot is None:
                raise ValueError("mapped proof strategy is not closed")
            if leaving:
                self._clear_bit(visiting, slot)
                if not self._bit_is_set(self._visited, slot):
                    self._set_bit(self._visited, slot)
                    checked += 1
                continue
            if self._bit_is_set(self._visited, slot):
                continue
            if self._bit_is_set(visiting, slot):
                raise ValueError("cycle in mapped proof strategy")
            self._set_bit(visiting, slot)
            status, moves = _proof_status_and_moves(
                state,
                rules,
                self._rules_auditor,
            )
            if status.terminal:
                if status.winner is not None and status.winner != self.root_player:
                    raise ValueError("mapped terminal node is a root-player loss")
                stack.append((state, True, slot))
                continue
            tablebase = self._oracle.probe(state)
            if tablebase is not None:
                if _root_outcome(
                    tablebase.outcome, state, self.root_player
                ) < Outcome.DRAW:
                    raise ValueError("mapped tablebase leaf is a root-player loss")
                stack.append((state, True, slot))
                continue
            children = self._children_to_check(state, moves)
            stack.append((state, True, slot))
            for child in reversed(children):
                stack.append((child, False, None))
        return checked

    def moves_for(self, state: State) -> tuple[Move, ...]:
        if state.turn != self.root_player:
            raise ValueError("proof strategy cannot choose for the other player")
        if self._oracle.probe(state) is not None:
            return _safe_tablebase_moves(
                state,
                self.root_player,
                self.no_progress_plies,
                self._oracle,
            )
        slot = self._lookup_slot(state)
        if slot is None or not self._bit_is_set(self._visited, slot):
            raise ValueError("position is outside the verified proof strategy")
        safe: list[Move] = []
        for move in legal_moves(state):
            child = apply_move(state, move, validate=False)
            child_slot = self._lookup_slot(child)
            if (
                child_slot is not None and
                self._bit_is_set(self._visited, child_slot)
            ):
                safe.append(move)
                if not self.all_choices:
                    break
        if not safe:
            raise ValueError("verified mapped strategy has no legal safe move")
        return tuple(safe)

    def move_for(self, state: State) -> Move | None:
        moves = self.moves_for(state)
        return moves[0] if moves else None

    def close(self) -> None:
        self._map.close()
        self._file.close()


def load_proof_strategy(
    path: str | Path,
    oracle: EndgameOracle,
    *,
    rules_auditor: IndependentRulesAuditor | None = None,
) -> ProofStrategy | MappedProofStrategy:
    proof_path = Path(path)
    with proof_path.open("rb") as file:
        magic = file.read(8)
    if magic == _STRATEGY_MAGIC:
        return MappedProofStrategy(
            proof_path,
            oracle,
            rules_auditor=rules_auditor,
        )
    return ProofStrategy(
        read_certificate(proof_path),
        oracle,
        rules_auditor=rules_auditor,
    )


def proof_no_progress_plies(path: str | Path) -> int:
    proof_path = Path(path)
    with proof_path.open("rb") as file:
        header = file.read(_STRATEGY_HEADER.size)
    if header[:8] == _STRATEGY_MAGIC:
        if len(header) != _STRATEGY_HEADER.size:
            raise ValueError("truncated mapped proof strategy")
        values = _STRATEGY_HEADER.unpack(header)
        if values[1] != 1 or values[2] != _STRATEGY_HEADER.size:
            raise ValueError("unsupported mapped proof strategy")
        return int(values[3])
    certificate = read_certificate(proof_path)
    return int(certificate["rules"]["no_progress_plies"])


def write_certificate(certificate: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(certificate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_certificate(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("proof certificate must contain a JSON object")
    return value
