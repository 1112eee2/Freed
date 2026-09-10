"""Opt-in native endgame search bridge.

The C2 kernel remains a small, history-aware 1T search.  C3 adds an
optional NNUE candidate DLL and exposes the same root candidates to the
normal Python root policy; importing this module or constructing a session
does not change the production Engine route.
"""
from collections import Counter
import ctypes as C
from dataclasses import dataclass
import os
from pathlib import Path
import threading

from .core import State, Move, Rules, apply_move, legal_moves
from .native import _PackedMove, _unpack_move
from .native_endgame import NativeEndgameTablebase, Position
from .search import Engine, Mode, RootCandidate, WDLBound
from .exact import Outcome

DEFAULT_LIBRARY = Path(__file__).resolve().parents[1] / (
    'build/native_endgame_c2/makhos_endgame_search' + ('.dll' if os.name == 'nt' else '.so'))


class History(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in ('red', 'black', 'kings', 'turn', 'count')]


class Root(C.Structure):
    _fields_ = [('struct_size', C.c_uint32), ('version', C.c_uint32),
                ('score', C.c_int32), ('lower', C.c_int32), ('upper', C.c_int32),
                ('depth', C.c_uint32), ('pv_count', C.c_uint32), ('pv', _PackedMove * 96)]


class Summary(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in (
        'struct_size', 'version', 'completed_depth', 'root_count', 'terminal_reason')]
    _fields_ += [(name, C.c_int32) for name in ('score', 'lower', 'upper')]
    _fields_ += [('nodes', C.c_uint64), ('tb_hits', C.c_uint64 * 7), ('repetition_draws', C.c_uint64)]


def position(state):
    if len(state.board) != 32 or state.turn not in (1, 2) or not 0 <= state.reversible_plies <= 200:
        raise ValueError('invalid endgame position')
    red = black = kings = 0
    for square, piece in enumerate(state.board):
        if piece not in (0, 1, 2, 3, 4):
            raise ValueError('invalid piece')
        if piece in (1, 3): red |= 1 << square
        if piece in (2, 4): black |= 1 << square
        if piece in (3, 4): kings |= 1 << square
    return Position(red, black, kings, state.turn, state.reversible_plies)


@dataclass(frozen=True)
class NativeRoot:
    score: int
    bound: WDLBound
    pv: tuple[Move, ...]


@dataclass(frozen=True)
class EndgameResult:
    status: int
    depth: int
    roots: tuple[NativeRoot, ...]
    terminal_reason: int
    terminal_score: int | None
    terminal_bound: WDLBound | None
    nodes: int
    tb_hits: tuple[int, ...]
    repetition_draws: int

    def candidates(self, policy: Engine, state: State, mode=Mode.BEST, win_margin=0):
        """Convert native roots to the existing Python root-policy contract.

        Native search owns terminal/TB proof and returns every completed root.
        The policy layer still owns pressure, distance, BEST/WIN selection and
        safety ranking, so routing does not create a second root behaviour.
        """
        if not self.roots:
            raise ValueError('no completed native root layer')
        mode = Mode(mode)
        if any(not root.pv for root in self.roots):
            raise ValueError('native root is missing its first move')
        moves = tuple(root.pv[0] for root in self.roots)
        predictions = policy.policy_value_model.predict(state, moves)
        candidates = tuple(RootCandidate(
            root.pv[0], root.score, root.pv,
            policy._human_pressure(apply_move(state, root.pv[0]), state.turn),
            root.bound, predictions[root.pv[0]],
        ) for root in self.roots)
        return policy._attach_distances(state, candidates, mode, win_margin)

    def choose(self, policy: Engine, state: State, mode=Mode.BEST, win_margin=0):
        """Apply the normal Python root policy to completed native roots."""

        candidates = self.candidates(policy, state, mode, win_margin)
        return policy._choose(candidates, Mode(mode), win_margin)


class NativeEndgameSearch:
    """Own an independent 1T session. TB may close after session creation.

    search/close serialize; cancel may run concurrently and requests unwind.
    All rule/history inputs are copied. Scalar TT allocation/reuse is absent.
    """
    def __init__(self, tb: NativeEndgameTablebase, *, nnue_model=None):
        self._lock = threading.RLock()
        self._lifetime = threading.Lock()
        self._handle = C.c_void_p()
        self._dll = dll = tb._dll
        self.horizon = tb.no_progress_plies
        self.tablebase = tb
        self.evaluator = "hce"
        self.nnue_enabled = False
        self.nnue_model_path = None
        self.nnue_model_sha256 = None
        self.nnue_source_model_sha256 = None
        self.nnue_feature_abi = None
        if not hasattr(dll, 'makhos_endgame_search_version'):
            raise ValueError('native endgame search requires the isolated C2/C3 DLL')
        dll.makhos_endgame_search_version.restype = C.c_uint32
        if dll.makhos_endgame_search_version() != 1:
            raise ValueError('unsupported endgame search ABI')
        self._configure_nnue_candidate(nnue_model)
        dll.makhos_endgame_session_create.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
        dll.makhos_endgame_session_create.restype = C.c_int32
        for name in ('makhos_endgame_session_destroy', 'makhos_endgame_cancel'):
            getattr(dll, name).argtypes = [C.c_void_p]
            getattr(dll, name).restype = None
        dll.makhos_endgame_run.argtypes = [C.c_void_p, C.POINTER(Position), C.POINTER(History),
            C.c_uint32, C.c_uint32, C.c_uint32, C.c_uint32, C.c_uint32, C.c_uint64]
        dll.makhos_endgame_run.restype = C.c_int32
        dll.makhos_endgame_results.argtypes = [C.c_void_p, C.POINTER(Summary), C.POINTER(Root), C.c_uint32]
        dll.makhos_endgame_results.restype = C.c_int32
        with tb._lock:
            if not tb._handle:
                raise RuntimeError('tablebase is closed')
            status = dll.makhos_endgame_session_create(tb._handle, C.byref(self._handle))
        if status:
            raise ValueError(f'endgame session creation failed: status={status}')

    def _configure_nnue_candidate(self, model):
        """Load the production NNUE model only in an explicit C3 candidate.

        The C2/HCE DLL has no NNUE symbols and remains valid with no model.
        A model passed to such a DLL fails closed instead of silently using
        HCE, matching the GUI provenance contract.
        """
        names = (
            'makhos_search_nnue_load_model',
            'makhos_search_nnue_ready',
            'makhos_search_nnue_feature_abi',
            'makhos_search_nnue_model_sha256',
            'makhos_search_nnue_source_model_sha256',
            'makhos_search_nnue_last_error',
        )
        candidate = all(hasattr(self._dll, name) for name in names)
        if not candidate:
            if model is not None:
                raise ValueError('nnue_model requires the isolated C3 NNUE DLL')
            return
        if model is None:
            raise ValueError('C3 NNUE DLL requires an explicit nnue_model')
        path = Path(model).resolve()
        if not path.is_file():
            raise FileNotFoundError(f'NNUE model not found: {path}')
        self._dll.makhos_search_nnue_load_model.argtypes = [C.c_char_p]
        self._dll.makhos_search_nnue_load_model.restype = C.c_int
        self._dll.makhos_search_nnue_ready.argtypes = []
        self._dll.makhos_search_nnue_ready.restype = C.c_int
        for name in names[2:]:
            function = getattr(self._dll, name)
            function.argtypes = []
            function.restype = C.c_char_p
        status = int(self._dll.makhos_search_nnue_load_model(
            str(path).encode('utf-8')
        ))
        if status != 0 or not self._dll.makhos_search_nnue_ready():
            encoded = self._dll.makhos_search_nnue_last_error()
            detail = encoded.decode('utf-8', errors='replace') if encoded else ''
            raise RuntimeError(
                f'NNUE endgame candidate model load failed ({status})'
                + (f': {detail}' if detail else '')
            )
        self.evaluator = 'nnue'
        self.nnue_enabled = True
        self.nnue_model_path = path
        self.nnue_model_sha256 = self._dll.makhos_search_nnue_model_sha256().decode('ascii')
        self.nnue_source_model_sha256 = self._dll.makhos_search_nnue_source_model_sha256().decode('ascii')
        self.nnue_feature_abi = self._dll.makhos_search_nnue_feature_abi().decode('ascii')

    def supports_position(self, state: State) -> bool:
        """Return whether C3 owns this endgame/transition root.

        Seven-piece positions are admitted only when a legal move crosses into
        the native TB boundary.  This keeps ordinary midgame routing untouched
        while allowing the capture transition to retain native speed.
        """
        pieces = sum(piece != 0 for piece in state.board)
        if pieces <= 6:
            return True
        if pieces != 7:
            return False
        return any(sum(piece != 0 for piece in apply_move(state, move, validate=False).board) <= 6
                   for move in legal_moves(state))

    def clear(self):
        """Reset the transient cancellation bit at a game boundary."""
        # The C session owns no persistent TT or root policy state.  A fresh
        # run resets cancellation internally; retaining this no-op lets Engine
        # clear all configured backends uniformly.
        return None

    def search(self, state, depth=1, *, history=None, rules=Rules(), time_ms=0, node_limit=0):
        if not isinstance(depth, int) or not 1 <= depth < 95:
            raise ValueError('depth must be 1..94')
        repetition = rules.repetition_limit or 0
        if rules.no_progress_plies != self.horizon or not 0 <= repetition <= 255:
            raise ValueError('rules mismatch or invalid repetition limit')
        if not isinstance(time_ms, int) or not 0 <= time_ms <= 2**32-1:
            raise ValueError('invalid time limit')
        if not isinstance(node_limit, int) or not 0 <= node_limit <= 2**64-1:
            raise ValueError('invalid node limit')
        native_position = position(state)
        counts = Counter(history or {})
        counts[state.position_key] = max(1, counts[state.position_key])
        entries = []
        for (board, turn), count in counts.items():
            if not isinstance(count, int) or not 0 <= count <= 255:
                raise ValueError('history counts must be 0..255')
            if not count:
                continue
            p = position(State(board, turn))
            entries.append(History(p.red, p.black, p.kings, p.turn, count))
        if len(entries) > 65535:
            raise ValueError('history too large')
        native_history = (History * len(entries))(*entries)
        with self._lock:
            if not self._handle:
                raise RuntimeError('native endgame search is closed')
            status = self._dll.makhos_endgame_run(self._handle, C.byref(native_position),
                native_history, len(entries), depth, self.horizon, repetition, time_ms, node_limit)
            if status not in (0, 2):
                raise ValueError(f'native endgame search failed: status={status}')
            summary = Summary(C.sizeof(Summary), 1)
            result = self._dll.makhos_endgame_results(self._handle, C.byref(summary), None, 0)
            if result not in (0, 5):
                raise ValueError(f'native endgame snapshot failed: status={result}')
            roots = (Root * summary.root_count)()
            result = self._dll.makhos_endgame_results(self._handle, C.byref(summary), roots, len(roots))
            if result:
                raise ValueError(f'native endgame results failed: status={result}')
            return EndgameResult(status, summary.completed_depth, tuple(NativeRoot(
                root.score, WDLBound(Outcome(root.lower), Outcome(root.upper)),
                tuple(_unpack_move(root.pv[i]) for i in range(root.pv_count)),
            ) for root in roots), summary.terminal_reason,
                summary.score if summary.terminal_reason else None,
                WDLBound(Outcome(summary.lower), Outcome(summary.upper)) if summary.terminal_reason else None,
                summary.nodes, tuple(summary.tb_hits), summary.repetition_draws)

    def cancel(self):
        with self._lifetime:
            if self._handle:
                self._dll.makhos_endgame_cancel(self._handle)

    def close(self):
        with self._lock, self._lifetime:
            if self._handle:
                self._dll.makhos_endgame_session_destroy(self._handle)
                self._handle = C.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
