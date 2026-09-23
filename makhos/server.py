"""Lightweight Web GUI Server for Thai Makhos Engine.

Serves the web GUI frontend and provides JSON API endpoints for move generation,
engine search (bestmove), move application, and game state management.
HTTP adapter and facade delegating engine lifecycle and state to makhos.engine_manager.
"""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import threading
import time
import types
import urllib.parse
import webbrowser

from .core import (
    BLACK,
    EMPTY,
    RED,
    apply_move,
    format_position,
    initial_state,
    legal_moves,
    parse_position,
    terminal_status,
)
from .parallel_native import MAX_PARALLEL_NATIVE_THREADS, ParallelNativeSearch
from .search import Mode, SearchLimits
from .workload_isolation import InteractiveSessionLease
from .game_records import MAX_RECORD_BYTES, save_game_record
from .search_profile import RequestProfiler
from .endgame_routing import is_native_endgame_position
from .native import NativeLazySmpSearch, NativeSearch
from .gui_release import DEFAULT_POINTER, load_release

# Import authoritative engine manager
from . import engine_manager
from .engine_manager import (
    DEFAULT_ENGINE_HASH_MB,
    DEFAULT_ENGINE_THREADS,
    DEFAULT_NATIVE_ENDGAME_C2_LIBRARY,
    DEFAULT_NATIVE_ENDGAME_C3_LIBRARY,
    DEFAULT_NATIVE_ENDGAME_C4_LIBRARY,
    DEFAULT_NATIVE_ENDGAME_ENABLED,
    ENGINE_SEARCH_LOCK,
    EXTERNAL_NO_REPETITION_RULES,
    GLOBAL_ENGINE,
    GLOBAL_ENGINE_CONFIG,
    GLOBAL_ENGINE_PROVENANCE,
    GUI_NATIVE_ENDGAME_ENABLED_OVERRIDE,
    GUI_NATIVE_ENDGAME_LIBRARY_OVERRIDE,
    GUI_NATIVE_LIBRARY_OVERRIDE,
    GUI_NNUE_MODEL_OVERRIDE,
    GUI_RELEASE,
    GUI_SEARCH_DEPTH,
    PROJECT_ROOT,
    RULE_PROFILES,
    TB3_SERVICE,
    _attach_native_tablebase,
    _close_engine_resources,
    _create_native_search,
    _native_search_provenance,
    _sha256_file,
    close_global_engine,
    configure_gui_native_search,
    configured_gui_native_endgame_library,
    configured_gui_native_library,
    engine_search_provenance,
    ensure_native_endgame_ready,
    ensure_native_tablebase_ready,
    get_default_engine,
    parse_position_history,
    parse_rules_profile,
    production_native_library,
    start_native_tablebase_warmup,
)

WEB_DIR = str(PROJECT_ROOT / "web")
GAME_RECORDS_DIR = PROJECT_ROOT / "saved_games"
WEB_ASSET_VERSION = "20260909-1"


class MakhosHTTPServer(ThreadingHTTPServer):
    """Browser-friendly HTTP server that owns its port exclusively."""

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        super().server_bind()


class EngineRequestHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def end_headers(self) -> None:
        # The GUI is under active development; a normal refresh must pick up
        # the latest settings behavior instead of a stale cached app.js.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path == "/api/readiness":
            # This must remain available while a search or slow disk IO runs.
            self.send_json({"tb3": engine_manager.TB3_SERVICE.status()})
            return
        super().do_GET()

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/save-game":
            self.handle_save_game()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}

        if path == "/api/state":
            self.handle_get_state(data)
        elif path == "/api/legal-moves":
            self.handle_legal_moves(data)
        elif path == "/api/apply-move":
            self.handle_apply_move(data)
        elif path == "/api/bestmove":
            try:
                self.handle_bestmove(data)
            except (OSError, RuntimeError, ValueError) as error:
                self.send_json({"error": str(error), "engine_unavailable": True}, 503)
        elif path == "/api/engine":
            try:
                with engine_manager.ENGINE_SEARCH_LOCK:
                    settings = {} if engine_manager.GUI_RELEASE is None else engine_manager.GUI_RELEASE["settings"]
                    engine = engine_manager.GLOBAL_ENGINE or engine_manager.get_default_engine(
                        threads=settings.get("threads", DEFAULT_ENGINE_THREADS),
                        hash_mb=settings.get("hash_mb_total", DEFAULT_ENGINE_HASH_MB))
                    native = engine.native_search
                    self.send_json({
                        **engine_manager.engine_search_provenance(engine),
                        "configured_backend": (
                            "native-lazy-smp" if isinstance(native, NativeLazySmpSearch)
                            else "native-root-split" if isinstance(native, ParallelNativeSearch)
                            else "native-single" if native else "unavailable"
                        ),
                        "threads": engine_manager.GLOBAL_ENGINE_CONFIG[0], "hash_mb": engine_manager.GLOBAL_ENGINE_CONFIG[1],
                        "hash_allocated_mb": getattr(native, "allocated_hash_mb", 0),
                        "ranked_tablebase_pieces": sorted(engine.ranked_tablebases),
                        "tb3": engine_manager.TB3_SERVICE.status(),
                        "defaults": engine_manager.GUI_RELEASE["settings"] if engine_manager.GUI_RELEASE else {
                            "threads": DEFAULT_ENGINE_THREADS, "hash_mb_total": DEFAULT_ENGINE_HASH_MB},
                    })
            except (OSError, RuntimeError, ValueError) as error:
                self.send_json({"error": str(error), "engine_unavailable": True}, 503)
        else:
            self.send_error(404, "API endpoint not found")

    def handle_save_game(self) -> None:
        # This endpoint writes only to a server-owned directory. Requiring JSON
        # also prevents cross-origin HTML forms from creating game files.
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self.send_json({"error": "Content-Type must be application/json"}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_RECORD_BYTES:
                self.send_json({"error": "game record must be between 1 byte and 4 MiB"}, 413)
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("engine"), dict):
                raise ValueError("game record and engine must be JSON objects")
            _, rules = parse_rules_profile(payload["engine"])
            path = save_game_record(payload, GAME_RECORDS_DIR, rules=rules)
        except (ValueError, UnicodeError, RecursionError) as error:
            self.send_json({"error": f"invalid game record: {error}"}, 400)
            return
        except OSError:
            self.send_json({"error": "cannot write saved_games; check folder permissions and free space"}, 500)
            return
        self.send_json({"saved": True, "filename": path.name, "path": f"saved_games/{path.name}"}, 201)

    def send_json(self, response_dict: dict, status_code: int = 200) -> None:
        body = json.dumps(response_dict).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # A cancelled browser request cannot consume this response.

    def handle_get_state(self, data: dict) -> None:
        pos_str = data.get("position")
        clock = data.get("clock", 0)
        first = data.get("first", BLACK)

        try:
            rules_profile, rules = parse_rules_profile(data)
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
            return

        if pos_str:
            state = parse_position(pos_str, reversible_plies=clock)
        else:
            # Do not wait for background engine warm-up just to draw a board.
            # A newly-created engine is already clear; an existing one is
            # serialized before its persistent TT and heuristics are reset.
            if engine_manager.GLOBAL_ENGINE is not None:
                with engine_manager.ENGINE_SEARCH_LOCK:
                    engine_manager.GLOBAL_ENGINE.clear()
            state = initial_state(first)

        moves = legal_moves(state)
        status = terminal_status(state, rules=rules)

        self.send_json({
            "position": format_position(state),
            "turn": "black" if state.turn == BLACK else "red",
            "board": list(state.board),
            "reversible_plies": state.reversible_plies,
            "legal_moves": [
                {
                    "notation": m.notation,
                    "path": list(m.path),
                    "captures": list(m.captures),
                    "promotes": m.promotes,
                    "start": m.start,
                    "end": m.end,
                }
                for m in moves
            ],
            "terminal": status.terminal,
            "winner": "black" if status.winner == BLACK else ("red" if status.winner == RED else None),
            "reason": status.reason,
            "rules_profile": rules_profile,
        })

    def handle_legal_moves(self, data: dict) -> None:
        pos_str = data.get("position")
        clock = data.get("clock", 0)
        if not pos_str:
            self.send_json({"error": "missing position"}, 400)
            return

        state = parse_position(pos_str, reversible_plies=clock)
        moves = legal_moves(state)
        self.send_json({
            "turn": "black" if state.turn == BLACK else "red",
            "legal_moves": [
                {
                    "notation": m.notation,
                    "path": list(m.path),
                    "captures": list(m.captures),
                    "promotes": m.promotes,
                    "start": m.start,
                    "end": m.end,
                }
                for m in moves
            ],
        })

    def handle_apply_move(self, data: dict) -> None:
        pos_str = data.get("position")
        move_notation = data.get("move")
        clock = data.get("clock", 0)

        if not pos_str or not move_notation:
            self.send_json({"error": "missing position or move"}, 400)
            return

        try:
            state = parse_position(pos_str, reversible_plies=clock)
            history = parse_position_history(data, state)
            rules_profile, rules = parse_rules_profile(data)
        except ValueError as error:
            self.send_json({"error": f"invalid position history: {error}"}, 400)
            return
        root_status = terminal_status(
            state,
            repetition_count=history[state.position_key],
            rules=rules,
        )
        if root_status.terminal:
            self.send_json({
                "error": f"game is already terminal: {root_status.reason}",
                "terminal": True,
                "winner": (
                    "black" if root_status.winner == BLACK
                    else "red" if root_status.winner == RED
                    else None
                ),
                "reason": root_status.reason,
            }, 409)
            return
        moves = legal_moves(state)
        target_move = next((m for m in moves if m.notation.lower() == move_notation.lower()), None)

        if not target_move:
            self.send_json({"error": f"illegal move: {move_notation}"}, 400)
            return

        new_state = apply_move(state, target_move, validate=False)
        history[new_state.position_key] += 1
        new_moves = legal_moves(new_state)
        status = terminal_status(
            new_state,
            repetition_count=history[new_state.position_key],
            rules=rules,
        )

        self.send_json({
            "board": list(new_state.board),
            "turn": "black" if new_state.turn == BLACK else "red",
            "reversible_plies": new_state.reversible_plies,
            "legal_moves": [
                {
                    "notation": m.notation,
                    "path": list(m.path),
                    "captures": list(m.captures),
                    "promotes": m.promotes,
                    "start": m.start,
                    "end": m.end,
                }
                for m in new_moves
            ],
            "terminal": status.terminal,
            "winner": "black" if status.winner == BLACK else ("red" if status.winner == RED else None),
            "reason": status.reason,
            "rules_profile": rules_profile,
        })

    def handle_bestmove(self, data: dict) -> None:
        request_started = time.perf_counter()
        pos_str = data.get("position")
        clock = data.get("clock", 0)
        profile_request = data.get("profile_request", False)
        if not isinstance(profile_request, bool):
            self.send_json({"error": "profile_request must be a boolean"}, 400)
            return

        if not pos_str:
            self.send_json({"error": "missing position"}, 400)
            return

        try:
            time_sec = float(data.get("time_sec", 1.0))
            depth = int(data.get("depth", GUI_SEARCH_DEPTH))
            threads = int(data.get("threads", DEFAULT_ENGINE_THREADS))
            hash_mb = int(data.get("hash_mb", DEFAULT_ENGINE_HASH_MB))
            mode = Mode(data.get("mode", "win"))
            rules_profile, rules = parse_rules_profile(data)
            native_endgame_request = data.get("native_endgame")
            if native_endgame_request is not None and not isinstance(native_endgame_request, bool):
                raise ValueError("native_endgame must be a boolean")
        except (TypeError, ValueError) as error:
            self.send_json({"error": f"invalid engine setting: {error}"}, 400)
            return
        if not 0.01 <= time_sec <= 3600:
            self.send_json({"error": "time_sec must be in 0.01..3600"}, 400)
            return
        if not 1 <= depth <= 94:
            self.send_json({"error": "depth must be in 1..94"}, 400)
            return
        if not 1 <= threads <= MAX_PARALLEL_NATIVE_THREADS:
            self.send_json({"error": "threads must be in 1..12"}, 400)
            return
        if not 4 <= hash_mb <= 1024:
            self.send_json({"error": "hash_mb must be in 4..1024"}, 400)
            return

        try:
            state = parse_position(pos_str, reversible_plies=clock)
            history = parse_position_history(data, state)
        except ValueError as error:
            self.send_json({"error": f"invalid position history: {error}"}, 400)
            return
        root_status = terminal_status(
            state,
            repetition_count=history[state.position_key],
            rules=rules,
        )
        if root_status.terminal:
            self.send_json({
                "error": f"game is already terminal: {root_status.reason}",
                "terminal": True,
                "winner": (
                    "black" if root_status.winner == BLACK
                    else "red" if root_status.winner == RED
                    else None
                ),
                "reason": root_status.reason,
            }, 409)
            return
        time_ms = int(time_sec * 1000)
        # A time-controlled GUI search must not stop just because the old depth
        # cap was reached. Forced moves and exact tablebase results may still
        # return immediately because no extra search can improve them.
        if data.get("use_full_time", True):
            depth = max(depth, GUI_SEARCH_DEPTH)
        limits = SearchLimits(depth=depth, time_ms=time_ms)
        # Native Engine state and persistent TT are shared between requests.
        # Serialize engine mutation while still allowing static files and cheap
        # state/move APIs to use separate HTTP worker threads.
        profiler = RequestProfiler(profile_request)
        lock_requested = time.perf_counter()
        with engine_manager.ENGINE_SEARCH_LOCK:
            lock_acquired = time.perf_counter()
            with profiler:
                engine = engine_manager.get_default_engine(
                    threads=threads,
                    hash_mb=hash_mb,
                    rules_profile=rules_profile,
                    native_endgame=native_endgame_request,
                )
                engine_ready = time.perf_counter()
                tb3_ready_before = engine.native_tablebase is not None
                tb3_load_attempted = False
                regular_endgame = (
                    sum(piece != EMPTY for piece in state.board)
                    <= max((3, *engine.ranked_tablebases))
                    and len(legal_moves(state)) > 1
                )
                native_endgame_position = (
                    engine.native_endgame_enabled
                    and len(legal_moves(state)) > 1
                    and is_native_endgame_position(state)
                )
                if regular_endgame or native_endgame_position:
                    # Include 4..6 -> 3 transitions. A missing oracle must not
                    # silently fall back to expensive/incomplete Python solving.
                    tb3_load_attempted = not tb3_ready_before
                    if not engine_manager.ensure_native_tablebase_ready(engine):
                        status = engine_manager.TB3_SERVICE.status()
                        self.send_json({
                            "error": "TB3 ยังไม่พร้อม กรุณารอให้โหลดเสร็จแล้วกดเล่นต่อ; "
                                     "ถ้าสถานะ error/timeout ให้ตรวจไฟล์แล้วเริ่มเซิร์ฟเวอร์ใหม่",
                            "engine_unavailable": True, "tb3": status,
                        }, 503)
                        return
                if native_endgame_position:
                    # The candidate is created only after TB3 is ready. If it
                    # is unavailable, Engine.search performs a visible Python
                    # fallback and provenance reports the reason.
                    engine_manager.ensure_native_endgame_ready(engine)
                search_started = time.perf_counter()
                result = engine.search(
                    state,
                    limits=limits,
                    mode=mode,
                    history=history,
                )
                search_finished = time.perf_counter()
            provenance = engine_manager.engine_search_provenance(engine)
            if engine_manager.GUI_NNUE_MODEL_OVERRIDE is not None and (
                not provenance["nnue_enabled"] or provenance["native_error"]
                or provenance["search_backend"] == "python-fallback"
            ):
                raise RuntimeError(f"NNUE search unavailable: {provenance['native_error']}")

            # Snapshot shared resources under the same lock as the search.
            # A later request can reconfigure the engine before JSON is written.
            worker_count = (
                len(engine.native_search._workers)
                if isinstance(engine.native_search, ParallelNativeSearch)
                else int(getattr(engine.native_search, "threads", 1) or 1)
                if isinstance(engine.native_search, NativeLazySmpSearch)
                else (1 if engine.native_search else 0)
            )
            resource_snapshot = {
                "hash_allocated_mb": round(getattr(engine.native_search, "allocated_hash_mb", 0.0), 1),
                "native_tablebase_ready": engine.native_tablebase is not None,
                "native_tablebase_error": engine_manager.TB3_SERVICE.status()["error"],
                "tb3": engine_manager.TB3_SERVICE.status(),
                "ranked_tablebase_pieces": sorted(engine.ranked_tablebases),
                "worker_count": worker_count,
                "native_endgame_ready": bool(provenance.get("native_endgame_ready", False)),
                "native_endgame_evaluator": provenance.get("native_endgame_evaluator"),
                "search_thread_capacity": (
                    provenance.get("native_endgame_threads", 1)
                    if provenance.get("search_backend") == "native-endgame"
                    else worker_count
                    if provenance.get("search_backend") in ("native-root-split", "native-lazy-smp")
                    else 0 if provenance.get("search_backend") == "forced" else 1
                ),
            }
            provenance_finished = time.perf_counter()

        pv_notation = [m.notation for m in result.pv]
        wdl_text = "UNKNOWN"
        exact = result.bound.exact_outcome
        if exact is not None:
            wdl_text = exact.name
        elif result.bound.lower == -1 and result.bound.upper == 1:
            wdl_text = "UNKNOWN"
        else:
            wdl_text = f"{result.bound.lower.name}..{result.bound.upper.name}"

        profile_report = profiler.report()
        response_ready = time.perf_counter()
        milestones = (
            ("validation", request_started, lock_requested),
            ("engine_lock_wait", lock_requested, lock_acquired),
            ("engine_setup", lock_acquired, engine_ready),
            ("tb3_prepare", engine_ready, search_started),
            ("search", search_started, search_finished),
            ("provenance", search_finished, provenance_finished),
            ("response_prepare", provenance_finished, response_ready),
        )
        timings_ms = {name: round((end - start) * 1000, 3) for name, start, end in milestones}
        request_elapsed_ms = round((response_ready - request_started) * 1000, 3)

        self.send_json({
            "bestmove": result.move.notation,
            "score": result.score,
            "depth": result.depth,
            "common_depth": (
                result.common_depth
                if result.common_depth is not None
                else result.depth
            ),
            "selective_root": result.selective_root,
            "nodes": result.nodes,
            "elapsed_ms": result.elapsed_ms,
            # Ends before JSON serialization/socket write; the HTTP benchmark
            # separately records client wall time. Search budget is unchanged.
            "request_elapsed_ms": request_elapsed_ms,
            "pre_search_setup_ms": round((search_started - lock_acquired) * 1000, 3),
            "timings_ms": timings_ms,
            "request_overshoot_ms": round(max(0.0, request_elapsed_ms - time_ms), 3),
            "tb3_ready_before": tb3_ready_before,
            "tb3_load_attempted": tb3_load_attempted,
            "python_profile": profile_report,
            "pv": pv_notation,
            "wdl": wdl_text,
            "tablebase_hits": result.tablebase_hits,
            "requested_time_ms": time_ms,
            "depth_limit": depth,
            "threads": threads,
            "hash_mb": hash_mb,
            "mode": mode.value,
            "rules_profile": rules_profile,
            "runtime_isolation": getattr(getattr(self, "server", None), "runtime_isolation", "interactive-exclusive-v1"),
            **resource_snapshot,
            **provenance,
        })


def run_server(
    port: int = 8000,
    open_browser: bool = True,
    *,
    native_library: str | Path | None = None,
    nnue_model: str | Path | None = None,
    native_endgame: bool = DEFAULT_NATIVE_ENDGAME_ENABLED,
    native_endgame_library: str | Path | None = None,
    lazy_smp: bool | None = None,
    release_pointer: str | Path | None = None,
    release_profile: str | None = None,
) -> None:
    if native_library is not None and (release_pointer is not None or release_profile is not None):
        raise ValueError("Select explicit native files or a release, not both")
    release = None
    if native_library is None and nnue_model is None:
        release = load_release(DEFAULT_POINTER if release_pointer is None else Path(release_pointer).resolve(),
                               profile=release_profile)
        if release is not None:
            native_library, nnue_model = release["native_library"], release["nnue_model"]
    engine_manager.configure_gui_native_search(
        native_library,
        nnue_model,
        native_endgame=native_endgame,
        native_endgame_library=native_endgame_library,
        lazy_smp=lazy_smp,
    )
    engine_manager.GUI_RELEASE = release
    if release is not None:
        with NativeSearch(native_library, hash_power=12, persistent=True, nnue_model=nnue_model) as probe:
            if probe.abi_version != release["native_search_abi"] or probe.nnue_feature_abi != release["nnue_feature_abi"]:
                raise ValueError("GUI release ABI mismatch")
    server_address = ("", port)
    url = f"http://localhost:{port}/?v={WEB_ASSET_VERSION}"
    try:
        httpd = MakhosHTTPServer(server_address, EngineRequestHandler)
    except OSError as error:
        address_in_use = (
            getattr(error, "winerror", None) == 10048 or
            error.errno in (48, 98, 10048)
        )
        if not address_in_use:
            raise
        print(f"Thai Makhos Engine is already running on {url}")
        if open_browser:
            webbrowser.open(url)
        return

    interactive_lease = InteractiveSessionLease(PROJECT_ROOT)
    try:
        interactive_lease.acquire(timeout_sec=15.0)
    except Exception:
        httpd.server_close()
        raise

    print(f"==================================================")
    print(f"  Thai Makhos Engine Web GUI running on {url}")
    print("  Search engine is warming up without blocking the browser.")
    print(f"==================================================")

    def warm_engine() -> None:
        try:
            with engine_manager.ENGINE_SEARCH_LOCK:
                settings = {} if engine_manager.GUI_RELEASE is None else engine_manager.GUI_RELEASE["settings"]
                engine_manager.get_default_engine(threads=settings.get("threads", DEFAULT_ENGINE_THREADS),
                                                   hash_mb=settings.get("hash_mb_total", DEFAULT_ENGINE_HASH_MB))
                engine_manager.ensure_native_tablebase_ready(engine_manager.GLOBAL_ENGINE)
        except Exception as error:
            print(f"Notice: background engine warm-up failed: {error}", file=sys.stderr)

    engine_manager.start_native_tablebase_warmup()
    threading.Thread(
        target=warm_engine,
        name="makhos-engine-warmup",
        daemon=True,
    ).start()

    if open_browser:
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down GUI server.")
    finally:
        engine_manager.close_global_engine()
        httpd.server_close()
        interactive_lease.close()


# Module delegation proxy ensuring zero divergent state between server and engine_manager
_ENGINE_MANAGER_SYMBOLS = {
    "GLOBAL_ENGINE",
    "GLOBAL_ENGINE_CONFIG",
    "GLOBAL_ENGINE_PROVENANCE",
    "GUI_NATIVE_LIBRARY_OVERRIDE",
    "GUI_NNUE_MODEL_OVERRIDE",
    "GUI_NATIVE_ENDGAME_ENABLED_OVERRIDE",
    "GUI_NATIVE_ENDGAME_LIBRARY_OVERRIDE",
    "GUI_RELEASE",
    "TB3_SERVICE",
    "ENGINE_SEARCH_LOCK",
    "DEFAULT_ENGINE_THREADS",
    "DEFAULT_ENGINE_HASH_MB",
    "GUI_SEARCH_DEPTH",
    "DEFAULT_NATIVE_ENDGAME_ENABLED",
    "DEFAULT_NATIVE_ENDGAME_C2_LIBRARY",
    "DEFAULT_NATIVE_ENDGAME_C3_LIBRARY",
    "DEFAULT_NATIVE_ENDGAME_C4_LIBRARY",
    "EXTERNAL_NO_REPETITION_RULES",
    "RULE_PROFILES",
    "parse_rules_profile",
    "parse_position_history",
    "production_native_library",
    "configured_gui_native_library",
    "configured_gui_native_endgame_library",
    "configure_gui_native_search",
    "engine_search_provenance",
    "_close_engine_resources",
    "_create_native_search",
    "_native_search_provenance",
    "_attach_native_tablebase",
    "_sha256_file",
    "start_native_tablebase_warmup",
    "ensure_native_tablebase_ready",
    "ensure_native_endgame_ready",
    "close_global_engine",
    "get_default_engine",
}


class _ServerModule(types.ModuleType):
    """Facade module proxy that delegates state to makhos.engine_manager."""

    def __getattribute__(self, name: str):
        if name in _ENGINE_MANAGER_SYMBOLS:
            return getattr(engine_manager, name)
        return super().__getattribute__(name)

    def __setattr__(self, name: str, val):
        if name in _ENGINE_MANAGER_SYMBOLS:
            setattr(engine_manager, name, val)
        super().__setattr__(name, val)

    def __delattr__(self, name: str):
        if name in _ENGINE_MANAGER_SYMBOLS and hasattr(engine_manager, name):
            delattr(engine_manager, name)
        super().__delattr__(name)


sys.modules[__name__].__class__ = _ServerModule


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Thai Makhos Web GUI Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to run HTTP server")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--native-library", help="explicit opt-in native-search DLL")
    parser.add_argument("--nnue-model", help="explicit NNUE model for the selected DLL")
    parser.add_argument(
        "--native-endgame",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="toggle native endgame search (default: enabled)",
    )
    parser.add_argument(
        "--native-endgame-library",
        help="isolated C2/C3/C4 endgame DLL",
    )
    parser.add_argument("--release-pointer", help="GUI release selection JSON")
    parser.add_argument("--release-profile", choices=["nnue", "hce"])
    args = parser.parse_args()
    native_endgame = args.native_endgame
    if native_endgame is None and args.native_endgame_library is not None:
        native_endgame = True
    run_server(
        port=args.port,
        open_browser=not args.no_browser,
        native_library=args.native_library,
        nnue_model=args.nnue_model,
        native_endgame=DEFAULT_NATIVE_ENDGAME_ENABLED if native_endgame is None else native_endgame,
        native_endgame_library=args.native_endgame_library,
        release_pointer=args.release_pointer,
        release_profile=args.release_profile,
    )
