"""UCI-style text protocol: a match manager drives the release engine over stdin/stdout.

The framing is UCI; positions and moves use the project's own text
(``B:BM25,26:RK1`` and ``22-18`` / ``11x18x25``):

    uci                       -> id name, id author, option lines, uciok
    isready                   -> loads the engine and TB3, then readyok
    setoption name Threads value N
    setoption name Hash value MB
    ucinewgame                -> clears hash and search history
    position startpos [moves 22-18 11x18 ...]
    position fen B:BM25,26:RK1 [moves ...]
    go [depth N] [movetime MS] [btime MS] [wtime MS] [binc MS] [winc MS] [movestogo N]
    stop | quit

btime/binc belong to side B of the position text (the side that moves first
from startpos) and wtime/winc to side R. Every go is answered by one info line
and ``bestmove <move>``, or by ``bestmove (none)`` after an ``info string``
saying why: the game is over, the position is invalid, or the engine is
unavailable. The search cannot be interrupted, so stop and quit wait for it to
end within its own limits, and go infinite / ponder are refused.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import threading
from typing import TextIO

from . import engine_manager
from .core import BLACK, apply_move, initial_state, legal_moves, parse_position, terminal_status
from .parallel_native import MAX_PARALLEL_NATIVE_THREADS
from .search import Mode, SearchLimits, TimeManager

ENGINE_NAME = "Freed"
ENGINE_AUTHOR = "1112eee2"
GO_FIELDS = frozenset(("depth", "movetime", "btime", "wtime", "binc", "winc", "movestogo"))


class UciSession:
    """One protocol connection; each search runs on a worker thread."""

    def __init__(self, output: TextIO, release: dict | None = None) -> None:
        settings = {} if release is None else release["settings"]
        self.name = ENGINE_NAME if release is None else f"{ENGINE_NAME} {release['release_id']}"
        self.threads = int(settings.get("threads", engine_manager.DEFAULT_ENGINE_THREADS))
        self.hash_mb = int(settings.get("hash_mb_total", engine_manager.DEFAULT_ENGINE_HASH_MB))
        self.mode = Mode(settings.get("mode", Mode.WIN.value))
        self.rules_profile = settings.get("rules_profile", "project")
        self.rules = engine_manager.RULE_PROFILES[self.rules_profile]
        self._options = {
            "threads": (1, MAX_PARALLEL_NATIVE_THREADS),
            "hash": (engine_manager.MIN_ENGINE_HASH_MB, engine_manager.MAX_ENGINE_HASH_MB),
        }
        self._output = output
        self._output_lock = threading.Lock()
        self._search: threading.Thread | None = None
        self.state = initial_state(rules=self.rules)
        self.history = Counter({self.state.position_key: 1})

    def run(self, lines: Iterable[str]) -> int:
        try:
            for line in lines:
                if not self.handle(line):
                    break
        finally:
            self._finish_search()
            engine_manager.close_global_engine()
        return 0

    def handle(self, line: str) -> bool:
        """Process one command line; False after quit."""

        tokens = line.split()
        if not tokens:
            return True
        command, args = tokens[0], tokens[1:]
        if command == "isready" and self._search is not None and self._search.is_alive():
            self._send("readyok")  # UCI: answer at once, the search keeps running
            return True
        self._finish_search()
        if command == "quit":
            return False
        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            self._send(f"info string unknown command: {command}")
        else:
            handler(args)
        return True

    def _send(self, text: str) -> None:
        with self._output_lock:
            self._output.write(text + "\n")
            self._output.flush()

    def _finish_search(self) -> None:
        if self._search is not None:
            self._search.join()
            self._search = None

    def _engine(self):
        return engine_manager.get_default_engine(
            threads=self.threads, hash_mb=self.hash_mb, rules_profile=self.rules_profile)

    def _cmd_uci(self, args: list[str]) -> None:
        self._send(f"id name {self.name}")
        self._send(f"id author {ENGINE_AUTHOR}")
        for name, current in (("Threads", self.threads), ("Hash", self.hash_mb)):
            low, high = self._options[name.lower()]
            self._send(f"option name {name} type spin default {current} min {low} max {high}")
        self._send("uciok")

    def _cmd_isready(self, args: list[str]) -> None:
        # Load what the first search needs now, as the GUI server's warm-up does.
        loading = engine_manager.start_native_tablebase_warmup()
        if loading is not None:
            loading.join(engine_manager.TB3_SERVICE.timeout_sec)
        try:
            with engine_manager.ENGINE_SEARCH_LOCK:
                engine = self._engine()
                tb3_ready = engine_manager.ensure_native_tablebase_ready(engine)
        except Exception as error:
            self._send(f"info string error: {error}")
        else:
            if not tb3_ready:
                status = engine_manager.TB3_SERVICE.status()
                self._send(f"info string TB3 {status['state']}: {status['error']}; "
                           "endgame roots will be refused")
        self._send("readyok")

    def _cmd_stop(self, args: list[str]) -> None:
        """Nothing left to do: handle() already waited for the search to report."""

    def _cmd_setoption(self, args: list[str]) -> None:
        if len(args) != 4 or args[0] != "name" or args[2] != "value":
            self._send("info string error: use setoption name <Threads|Hash> value <N>")
            return
        name = args[1].lower()
        if name not in self._options:
            self._send(f"info string error: unknown option {args[1]}")
            return
        low, high = self._options[name]
        try:
            value = int(args[3])
        except ValueError:
            value = None
        if value is None or not low <= value <= high:
            self._send(f"info string error: {args[1]} must be an integer in {low}..{high}")
            return
        if name == "threads":
            self.threads = value
        else:
            self.hash_mb = value

    def _cmd_ucinewgame(self, args: list[str]) -> None:
        with engine_manager.ENGINE_SEARCH_LOCK:
            if engine_manager.GLOBAL_ENGINE is not None:
                engine_manager.GLOBAL_ENGINE.clear()
        self.state = initial_state(rules=self.rules)
        self.history = Counter({self.state.position_key: 1})

    def _cmd_position(self, args: list[str]) -> None:
        try:
            if args[:1] == ["startpos"]:
                state, rest = initial_state(rules=self.rules), args[1:]
            elif args[:1] == ["fen"] and len(args) >= 2:
                state, rest = parse_position(args[1]), args[2:]
            else:
                raise ValueError("expected position startpos|fen <position> [moves ...]")
            history = Counter({state.position_key: 1})
            if rest and rest[0] != "moves":
                raise ValueError(f"expected moves, got {rest[0]}")
            for text in rest[1:]:
                move = next((m for m in legal_moves(state) if m.notation == text.lower()), None)
                if move is None:
                    raise ValueError(f"illegal move {text}")
                state = apply_move(state, move, validate=False)
                history[state.position_key] += 1
        except ValueError as error:
            self.state = None  # never search a position the manager did not send
            self._send(f"info string error: {error}")
            return
        self.state, self.history = state, history

    def _cmd_go(self, args: list[str]) -> None:
        try:
            if self.state is None:
                raise ValueError("no valid position")
            status = terminal_status(self.state, repetition_count=self.history[self.state.position_key],
                                     rules=self.rules)
            if status.terminal:
                raise ValueError(f"game over: {status.reason}")
            limits = self._limits(args)
        except ValueError as error:
            self._send(f"info string error: {error}")
            self._send("bestmove (none)")
            return
        self._search = threading.Thread(
            target=self._search_and_report, args=(self.state, self.history.copy(), limits),
            name="makhos-uci-search", daemon=True)
        self._search.start()

    def _limits(self, args: list[str]) -> SearchLimits:
        fields: dict[str, int] = {}
        for index in range(0, len(args), 2):
            key = args[index]
            if key not in GO_FIELDS:
                raise ValueError(f"unsupported go parameter: {key}")
            try:
                fields[key] = int(args[index + 1])
            except (IndexError, ValueError):
                raise ValueError(f"{key} needs a non-negative integer") from None
            if fields[key] < 0:
                raise ValueError(f"{key} needs a non-negative integer")
        own, other = ("b", "w") if self.state.turn == BLACK else ("w", "b")
        time_ms = fields.get("movetime")
        if time_ms is None and f"{own}time" in fields:
            time_ms = TimeManager.allocate_time(
                my_time_ms=fields[f"{own}time"],
                opp_time_ms=fields.get(f"{other}time", 0),
                my_inc_ms=fields.get(f"{own}inc", 0),
                opp_inc_ms=fields.get(f"{other}inc", 0),
                moves_to_go=fields.get("movestogo"),
            )
        depth = fields.get("depth")
        if depth is None and time_ms is None:
            raise ValueError(f"go needs depth, movetime or {own}time")
        if depth is not None and not 1 <= depth <= engine_manager.MAX_SEARCH_DEPTH:
            raise ValueError(f"depth must be in 1..{engine_manager.MAX_SEARCH_DEPTH}")
        if time_ms == 0:
            raise ValueError("movetime must be positive")
        # Like the GUI, a timed search is not cut short by a fixed depth cap.
        return SearchLimits(depth=engine_manager.GUI_SEARCH_DEPTH if depth is None else depth,
                            time_ms=time_ms)

    def _search_and_report(self, state, history: Counter, limits: SearchLimits) -> None:
        try:
            with engine_manager.ENGINE_SEARCH_LOCK:
                engine = self._engine()
                if engine_manager.prepare_root_search(engine, state) is False:
                    status = engine_manager.TB3_SERVICE.status()
                    raise RuntimeError(f"TB3 {status['state']}: endgame roots are not searched without it")
                result = engine.search(state, limits=limits, mode=self.mode, history=history)
                engine_manager.checked_search_provenance(engine)
        except Exception as error:  # every go must still end with bestmove
            self._send(f"info string error: {error}")
            self._send("bestmove (none)")
            return
        info = (f"info depth {result.depth} score cp {result.score} nodes {result.nodes} "
                f"nps {result.nodes * 1000 // max(1, result.elapsed_ms)} time {result.elapsed_ms}")
        if result.pv:
            info += " pv " + " ".join(move.notation for move in result.pv)
        self._send(info)
        self._send(f"info string wdl {result.bound.text}")
        self._send(f"bestmove {result.move.notation}")


def run_protocol(
    input_stream: TextIO,
    output: TextIO,
    *,
    native_library: str | None = None,
    nnue_model: str | None = None,
    release_pointer: str | None = None,
    release_profile: str | None = None,
) -> int:
    """Serve the protocol with the same release selection as the GUI server."""

    release = engine_manager.configure_engine_release(
        native_library, nnue_model, release_pointer=release_pointer, release_profile=release_profile)
    return UciSession(output, release).run(iter(input_stream.readline, ""))
