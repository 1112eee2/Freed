"""Strict game-record ingestion and positional diagnostics.

The web GUI emits ``thai-makhos-game-v1`` JSON.  This module treats that record
as evidence: every move is replayed with the verified Python rules before a
position can enter a regression or tuning corpus.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import (
    BLACK,
    RED,
    DEFAULT_RULES,
    Move,
    Rules,
    State,
    apply_move,
    format_position,
    legal_moves,
    opponent,
    parse_position,
    terminal_status,
)


GAME_RECORD_FORMAT = "thai-makhos-game-v1"
GAME_ANALYSIS_FORMAT = "thai-makhos-analysis-v1"
SEARCH_PROVENANCE_VERSION = "search-v1"
SEARCH_PROVENANCE_FIELDS = (
    "provenance_version",
    "requested_time_ms",
    "elapsed_ms",
    "depth_limit",
    "depth",
    "common_depth",
    "nodes",
    "score",
    "pv",
    "rules_profile",
    "search_backend",
    "native_library",
    "native_library_sha256",
    "native_search_abi",
    "native_error",
)
EXTERNAL_NO_REPETITION_RULES = Rules(
    name="external-no-repetition-np80",
    starting_player=DEFAULT_RULES.starting_player,
    repetition_limit=None,
    no_progress_plies=DEFAULT_RULES.no_progress_plies,
)


class GameRecordError(ValueError):
    """Raised when a game record cannot be trusted as position evidence."""


@dataclass(frozen=True, slots=True)
class RecordedMove:
    ply: int
    player: int
    notation: str
    actor: str | None = None
    engine: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class GameRecord:
    game_id: str
    start: State
    moves: tuple[RecordedMove, ...]
    final_position: str | None
    final_reversible_plies: int | None
    engine: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ReplayedPly:
    ply: int
    player: int
    notation: str
    state: State
    move: Move
    child: State
    history: Mapping[tuple[tuple[int, ...], int], int]
    actor: str | None = None
    engine: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ReplayedGame:
    record: GameRecord
    plies: tuple[ReplayedPly, ...]
    final: State
    history: Mapping[tuple[tuple[int, ...], int], int]


@dataclass(frozen=True, slots=True)
class RootMoveObservation:
    move: str
    score: int
    depth: int
    nodes: int
    pv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SearchObservation:
    budget_ms: int
    move: str
    score: int
    depth: int
    nodes: int
    elapsed_ms: int
    pv: tuple[str, ...]
    root_moves: tuple[RootMoveObservation, ...] = ()
    common_depth: int | None = None
    selective_root: bool = False


def player_name(player: int) -> str:
    return "black" if player == BLACK else "red"


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GameRecordError(f"{name} must be a JSON object")
    return value


def _require_nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GameRecordError(f"{name} must be a non-negative integer")
    return value


def parse_game_record(payload: Mapping[str, Any]) -> GameRecord:
    """Parse metadata without trusting any recorded transition yet."""

    data = _require_mapping(payload, "game record")
    if data.get("format") != GAME_RECORD_FORMAT:
        raise GameRecordError(f"format must be {GAME_RECORD_FORMAT!r}")

    start_text = data.get("start_position")
    if not isinstance(start_text, str) or not start_text.strip():
        raise GameRecordError("start_position must be a non-empty string")
    start_clock = _require_nonnegative_int(
        data.get("start_reversible_plies", 0),
        "start_reversible_plies",
    )
    try:
        start = parse_position(start_text, reversible_plies=start_clock)
    except ValueError as error:
        raise GameRecordError(f"invalid start_position: {error}") from error

    raw_moves = data.get("moves")
    if not isinstance(raw_moves, list):
        raise GameRecordError("moves must be a JSON array")
    moves: list[RecordedMove] = []
    for index, raw_move in enumerate(raw_moves, start=1):
        item = _require_mapping(raw_move, f"moves[{index - 1}]")
        ply = _require_nonnegative_int(item.get("ply"), f"moves[{index - 1}].ply")
        if ply != index:
            raise GameRecordError(
                f"moves[{index - 1}].ply must be {index}, got {ply}"
            )
        raw_player = item.get("player")
        if raw_player not in ("black", "red"):
            raise GameRecordError(
                f"moves[{index - 1}].player must be 'black' or 'red'"
            )
        notation = item.get("notation")
        if not isinstance(notation, str) or not notation.strip():
            raise GameRecordError(
                f"moves[{index - 1}].notation must be a non-empty string"
            )
        actor = item.get("actor")
        if actor is not None and actor not in ("human", "engine"):
            raise GameRecordError(
                f"moves[{index - 1}].actor must be 'human' or 'engine'"
            )
        move_engine_raw = item.get("engine")
        move_engine = (
            None
            if move_engine_raw is None
            else dict(_require_mapping(move_engine_raw, f"moves[{index - 1}].engine"))
        )
        if actor != "engine" and move_engine is not None:
            raise GameRecordError(
                f"moves[{index - 1}].engine requires actor 'engine'"
            )
        moves.append(
            RecordedMove(
                ply=ply,
                player=BLACK if raw_player == "black" else RED,
                notation=notation.strip(),
                actor=actor,
                engine=move_engine,
            )
        )

    final_position = data.get("final_position")
    if final_position is not None and (
        not isinstance(final_position, str) or not final_position.strip()
    ):
        raise GameRecordError("final_position must be a non-empty string")
    final_clock_raw = data.get("reversible_plies")
    final_clock = (
        None
        if final_clock_raw is None
        else _require_nonnegative_int(final_clock_raw, "reversible_plies")
    )
    engine_raw = data.get("engine", {})
    engine = dict(_require_mapping(engine_raw, "engine"))

    canonical = {
        "format": GAME_RECORD_FORMAT,
        "start_position": format_position(start),
        "start_reversible_plies": start_clock,
        "moves": [
            {
                "ply": move.ply,
                "player": player_name(move.player),
                "notation": move.notation,
                "actor": move.actor,
                "engine": move.engine,
            }
            for move in moves
        ],
    }
    game_id = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return GameRecord(
        game_id=game_id,
        start=start,
        moves=tuple(moves),
        final_position=final_position,
        final_reversible_plies=final_clock,
        engine=engine,
    )


def load_game_record(path: str | Path) -> GameRecord:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GameRecordError(f"cannot read game record {source}: {error}") from error
    return parse_game_record(_require_mapping(payload, "game record"))


def replay_game(
    record: GameRecord,
    *,
    rules: Rules = DEFAULT_RULES,
) -> ReplayedGame:
    """Rebuild every edge and reject records inconsistent with the rules."""

    state = record.start
    history: Counter[tuple[tuple[int, ...], int]] = Counter({state.position_key: 1})
    replayed: list[ReplayedPly] = []
    for item in record.moves:
        status = terminal_status(
            state,
            repetition_count=history[state.position_key],
            rules=rules,
        )
        if status.terminal:
            raise GameRecordError(
                f"ply {item.ply} occurs after terminal state ({status.reason})"
            )
        if item.player != state.turn:
            raise GameRecordError(
                f"ply {item.ply} says {player_name(item.player)}, but "
                f"{player_name(state.turn)} is to move"
            )
        matches = tuple(
            move
            for move in legal_moves(state)
            if move.notation.lower() == item.notation.lower()
        )
        if len(matches) != 1:
            raise GameRecordError(
                f"ply {item.ply} is not a unique legal move: {item.notation}"
            )
        move = matches[0]
        child = apply_move(state, move, validate=False)
        replayed.append(
            ReplayedPly(
                ply=item.ply,
                player=item.player,
                notation=move.notation,
                state=state,
                move=move,
                child=child,
                history=dict(history),
                actor=item.actor,
                engine=item.engine,
            )
        )
        state = child
        history[state.position_key] += 1

    if record.final_position is not None:
        try:
            declared = parse_position(
                record.final_position,
                reversible_plies=state.reversible_plies,
            )
        except ValueError as error:
            raise GameRecordError(f"invalid final_position: {error}") from error
        if declared.position_key != state.position_key:
            raise GameRecordError(
                "final_position does not match the position reconstructed from moves"
            )
    if (
        record.final_reversible_plies is not None
        and record.final_reversible_plies != state.reversible_plies
    ):
        raise GameRecordError(
            "reversible_plies does not match the clock reconstructed from moves"
        )
    return ReplayedGame(record, tuple(replayed), state, dict(history))


def inferred_engine_players(record: GameRecord) -> tuple[int, ...] | None:
    """Infer which recorded side was controlled by this engine, if possible."""

    mode = record.engine.get("game_mode")
    if mode == "bot":
        return BLACK, RED
    if mode == "edit":
        return ()
    if mode == "human":
        human = record.engine.get("human_side")
        if human in ("black", "red"):
            human_player = BLACK if human == "black" else RED
            return (opponent(human_player),)
    return None


def classify_search_observations(
    played_move: str,
    observations: Sequence[SearchObservation],
) -> str:
    """Classify move stability across increasing search budgets."""

    if not observations:
        return "unanalysed"
    ordered = tuple(sorted(observations, key=lambda item: item.budget_ms))
    if played_move.lower() != ordered[0].move.lower():
        return "settings-or-version-mismatch"
    moves = tuple(item.move.lower() for item in ordered)
    if len(set(moves)) == 1:
        return "stable"
    if len(moves) >= 3 and moves[-2] == moves[-1] and moves[0] != moves[-1]:
        return "short-search-divergence"
    if moves[-1] != moves[-2]:
        return "long-horizon-divergence"
    return "search-divergence"


def engine_provenance_issues(
    metadata: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Report missing or malformed fields needed to reproduce one GUI search."""

    if metadata is None:
        return ("missing:engine",)
    issues = [
        f"missing:{field}"
        for field in SEARCH_PROVENANCE_FIELDS
        if field not in metadata
    ]
    if (
        "provenance_version" in metadata
        and metadata.get("provenance_version") != SEARCH_PROVENANCE_VERSION
    ):
        issues.append("invalid:provenance_version")
    backend = metadata.get("search_backend")
    if backend is not None and backend not in {
        "native-single",
        "native-root-split",
        "python",
        "python-fallback",
        "forced",
    }:
        issues.append("invalid:search_backend")
    sha256 = metadata.get("native_library_sha256")
    if sha256 is not None and (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in sha256)
    ):
        issues.append("invalid:native_library_sha256")
    return tuple(issues)


def engine_provenance_mismatches(
    metadata: Mapping[str, Any] | None,
    *,
    library_sha256: str,
    native_search_abi: int,
    threads: int,
    hash_mb: int,
    rules_profile: str,
    budget_ms: int,
) -> tuple[str, ...]:
    """Compare recorded per-ply settings with an isolated native replay."""

    if metadata is None:
        return ()
    mismatches: list[str] = []
    recorded_sha = metadata.get("native_library_sha256")
    if (
        isinstance(recorded_sha, str)
        and recorded_sha.lower() != library_sha256.lower()
    ):
        mismatches.append("native_library_sha256")
    recorded_abi = metadata.get("native_search_abi")
    if isinstance(recorded_abi, int) and recorded_abi != native_search_abi:
        mismatches.append("native_search_abi")
    if isinstance(metadata.get("threads"), int) and metadata["threads"] != threads:
        mismatches.append("threads")
    if isinstance(metadata.get("hash_mb"), int) and metadata["hash_mb"] != hash_mb:
        mismatches.append("hash_mb")
    recorded_rules = metadata.get("rules_profile")
    if isinstance(recorded_rules, str) and recorded_rules != rules_profile:
        mismatches.append("rules_profile")
    recorded_budget = metadata.get("requested_time_ms")
    if not isinstance(recorded_budget, int):
        think_seconds = metadata.get("think_time_seconds")
        if isinstance(think_seconds, (int, float)) and not isinstance(
            think_seconds, bool
        ):
            recorded_budget = round(think_seconds * 1000)
    if isinstance(recorded_budget, int) and recorded_budget != budget_ms:
        mismatches.append("requested_time_ms")
    recorded_backend = metadata.get("search_backend")
    expected_backend = "native-single" if threads == 1 else "native-root-split"
    if isinstance(recorded_backend, str) and recorded_backend != expected_backend:
        mismatches.append("search_backend")
    return tuple(mismatches)
