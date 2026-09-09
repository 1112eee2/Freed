"""Lightweight Web GUI Server for Thai Makhos Engine.

Serves the web GUI frontend and provides JSON API endpoints for move generation,
engine search (bestmove), move application, and game state management.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser

from .core import (
    BLACK,
    EMPTY,
    RED,
    DEFAULT_RULES,
    Rules,
    apply_move,
    format_board,
    format_position,
    initial_state,
    legal_moves,
    parse_position,
    terminal_status,
)
from .native_tablebase import NativeTablebase
from .native import NativeSearch, hash_power_for_megabytes, native_tt_entry_bytes
from .parallel_native import MAX_PARALLEL_NATIVE_THREADS, ParallelNativeSearch
from .ranked_tablebase import RankedTablebase
from .search import Engine, Mode, SearchLimits
from .workload_isolation import InteractiveSessionLease
from .gui_release import DEFAULT_POINTER, load_release
from .game_records import MAX_RECORD_BYTES, save_game_record
from .search_profile import RequestProfiler


# Global engine instance shared by HTTP requests
GLOBAL_ENGINE: Engine | None = None
GLOBAL_ENGINE_CONFIG: tuple[int, int, str, str, str | None] | None = None
GLOBAL_ENGINE_PROVENANCE: dict[str, object] | None = None
GUI_NATIVE_LIBRARY_OVERRIDE: Path | None = None
GUI_NNUE_MODEL_OVERRIDE: Path | None = None
GUI_RELEASE: dict | None = None
NATIVE_TABLEBASE_WARMUP_THREAD: threading.Thread | None = None
NATIVE_TABLEBASE_WARMUP_ERROR: str | None = None
ENGINE_SEARCH_LOCK = threading.RLock()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = str(PROJECT_ROOT / "web")
GAME_RECORDS_DIR = PROJECT_ROOT / "saved_games"
DEFAULT_ENGINE_THREADS = 1
DEFAULT_ENGINE_HASH_MB = 64
GUI_SEARCH_DEPTH = 64
WEB_ASSET_VERSION = "20260909-1"
EXTERNAL_NO_REPETITION_RULES = Rules(
    name="external-no-repetition",
    starting_player=BLACK,
    repetition_limit=None,
    no_progress_plies=DEFAULT_RULES.no_progress_plies,
)
RULE_PROFILES = {
    "project": DEFAULT_RULES,
    "external-no-repetition": EXTERNAL_NO_REPETITION_RULES,
}


def parse_rules_profile(data: dict) -> tuple[str, Rules]:
    profile = data.get("rules_profile", "project")
    if not isinstance(profile, str) or profile not in RULE_PROFILES:
        raise ValueError(
            "rules_profile must be project or external-no-repetition"
        )
    return profile, RULE_PROFILES[profile]


def parse_position_history(data: dict, state) -> Counter:
    """Validate browser-supplied repetition history against the current root."""

    raw_history = data.get("history")
    if raw_history is None:
        return Counter({state.position_key: 1})
    if not isinstance(raw_history, list) or not 1 <= len(raw_history) <= 1000:
        raise ValueError("history must be a JSON array with 1..1000 positions")
    counts: Counter = Counter()
    last_key = None
    for index, text in enumerate(raw_history):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"history[{index}] must be a position string")
        historical = parse_position(text)
        counts[historical.position_key] += 1
        last_key = historical.position_key
    if last_key != state.position_key:
        raise ValueError("history must end at the current position")
    return counts


def production_native_library(project_root: Path = PROJECT_ROOT) -> Path:
    """Prefer the strength-tested build without hiding the current candidate."""

    build_dir = project_root / "build"
    accepted = build_dir / "makhos_native_accepted.dll"
    return accepted if accepted.is_file() else build_dir / "makhos_native.dll"


def configure_gui_native_search(
    native_library: str | Path | None = None,
    nnue_model: str | Path | None = None,
) -> None:
    """Select an explicit GUI candidate without changing the production default."""

    global GUI_NATIVE_LIBRARY_OVERRIDE, GUI_NNUE_MODEL_OVERRIDE, GUI_RELEASE
    if native_library is None and nnue_model is not None:
        raise ValueError("--nnue-model requires an explicit --native-library")
    library = None if native_library is None else Path(native_library).resolve()
    model = None if nnue_model is None else Path(nnue_model).resolve()
    if library is not None and not library.is_file():
        raise FileNotFoundError(f"GUI native library not found: {library}")
    if model is not None and not model.is_file():
        raise FileNotFoundError(f"GUI NNUE model not found: {model}")
    if library is not None:
        with NativeSearch(
            library,
            hash_power=12,
            persistent=True,
            nnue_model=model,
        ):
            pass
    close_global_engine()
    GUI_NATIVE_LIBRARY_OVERRIDE = library
    GUI_NNUE_MODEL_OVERRIDE = model
    GUI_RELEASE = None


def configured_gui_native_library() -> Path:
    return GUI_NATIVE_LIBRARY_OVERRIDE or production_native_library()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def engine_search_provenance(engine: Engine) -> dict[str, object]:
    """Describe the backend that actually produced the most recent result."""

    configured = dict(GLOBAL_ENGINE_PROVENANCE or {})
    native_search = engine.native_search
    if not configured and native_search is not None:
        library = Path(native_search.path).resolve()
        configured = {
            "native_library": str(library),
            "native_library_sha256": _sha256_file(library),
            "native_search_abi": getattr(native_search, "abi_version", None),
        }

    backend = engine.last_search_backend
    if backend == "native":
        backend = (
            "native-root-split"
            if isinstance(native_search, ParallelNativeSearch)
            else "native-single"
        )
    elif backend == "python-fallback":
        backend = "python-fallback"
    elif backend == "forced":
        backend = "forced"
    else:
        backend = "python"

    native_load_error = configured.pop("_native_load_error", None)
    configured["provenance_version"] = "search-v1"
    configured["search_backend"] = backend
    configured["native_error"] = engine.last_native_error or native_load_error
    configured["release_id"] = None if GUI_RELEASE is None else GUI_RELEASE["release_id"]
    configured["release_manifest_sha256"] = None if GUI_RELEASE is None else GUI_RELEASE["manifest_sha256"]
    configured["evaluator_used"] = (
        "nnue" if backend.startswith("native-") and configured.get("nnue_enabled")
        else "hce" if backend.startswith("native-") else backend
    )
    configured.setdefault("native_library", None)
    configured.setdefault("native_library_sha256", None)
    configured.setdefault("native_search_abi", None)
    configured.setdefault("nnue_enabled", False)
    configured.setdefault("nnue_feature_abi", None)
    configured.setdefault("nnue_model", None)
    configured.setdefault("nnue_model_sha256", None)
    configured.setdefault("nnue_source_model_sha256", None)
    return configured


def _close_engine_resources(engine: Engine) -> None:
    if engine.native_search is not None:
        engine.native_search.close()
    for tablebase in engine.ranked_tablebases.values():
        tablebase.close()
    if engine.native_tablebase is not None:
        engine.native_tablebase.close()


def _create_native_search(
    native_dll: Path,
    *,
    threads: int,
    hash_mb: int,
    nnue_model: Path | None = None,
):
    """Create only the search resource for one GUI Threads/Hash setting."""

    tt_entry_bytes = native_tt_entry_bytes(native_dll)
    hash_power = hash_power_for_megabytes(
        hash_mb,
        partitions=threads,
        entry_bytes=tt_entry_bytes,
    )
    if threads == 1:
        return NativeSearch(
            native_dll,
            hash_power=hash_power,
            persistent=True,
            nnue_model=nnue_model,
        )
    return ParallelNativeSearch(
        native_dll,
        threads=threads,
        hash_mb=hash_mb,
        nnue_model=nnue_model,
    )


def _native_search_provenance(
    native_dll: Path,
    native_search,
    native_search_error: str | None,
) -> dict[str, object]:
    if not native_dll.is_file():
        return {
            "native_library": None,
            "native_library_sha256": None,
            "native_search_abi": None,
            "_native_load_error": native_search_error,
        }
    resolved = native_dll.resolve()
    try:
        digest = _sha256_file(resolved)
    except OSError as error:
        digest = None
        if native_search_error is None:
            native_search_error = f"cannot fingerprint native DLL: {error}"
    return {
        "native_library": str(resolved),
        "native_library_sha256": digest,
        "native_search_abi": getattr(native_search, "abi_version", None),
        "nnue_enabled": bool(getattr(native_search, "nnue_enabled", False)),
        "nnue_feature_abi": getattr(native_search, "nnue_feature_abi", None),
        "nnue_model": (
            None
            if getattr(native_search, "nnue_model_path", None) is None
            else str(native_search.nnue_model_path)
        ),
        "nnue_model_sha256": getattr(native_search, "nnue_model_sha256", None),
        "nnue_source_model_sha256": getattr(
            native_search,
            "nnue_source_model_sha256",
            None,
        ),
        "_native_load_error": native_search_error,
    }


def start_native_tablebase_warmup() -> threading.Thread | None:
    """Build the expensive three-piece oracle without blocking opening play."""

    global NATIVE_TABLEBASE_WARMUP_THREAD, NATIVE_TABLEBASE_WARMUP_ERROR
    with ENGINE_SEARCH_LOCK:
        engine = GLOBAL_ENGINE
        if engine is None:
            raise RuntimeError("GUI engine must exist before tablebase warm-up")
        if engine.native_tablebase is not None:
            return None
        current = NATIVE_TABLEBASE_WARMUP_THREAD
        if current is not None and current.is_alive():
            return current
        native_dll = production_native_library()
        if not native_dll.is_file():
            NATIVE_TABLEBASE_WARMUP_ERROR = f"native DLL not found: {native_dll}"
            return None
        target_engine = engine
        NATIVE_TABLEBASE_WARMUP_ERROR = None

        def load_and_attach() -> None:
            global NATIVE_TABLEBASE_WARMUP_THREAD, NATIVE_TABLEBASE_WARMUP_ERROR
            tablebase = None
            error = None
            try:
                tablebase = NativeTablebase(native_dll)
            except Exception as caught:
                error = str(caught)
            with ENGINE_SEARCH_LOCK:
                try:
                    if error is not None:
                        NATIVE_TABLEBASE_WARMUP_ERROR = error
                        print(
                            f"Notice: background three-piece tablebase warm-up failed: {error}",
                            file=sys.stderr,
                        )
                    elif GLOBAL_ENGINE is target_engine and tablebase is not None:
                        _attach_native_tablebase(target_engine, tablebase)
                        tablebase = None
                    NATIVE_TABLEBASE_WARMUP_THREAD = None
                finally:
                    if tablebase is not None:
                        tablebase.close()

        thread = threading.Thread(
            target=load_and_attach,
            name="makhos-tb3-warmup",
            daemon=True,
        )
        NATIVE_TABLEBASE_WARMUP_THREAD = thread
        thread.start()
        return thread


def _attach_native_tablebase(engine: Engine, tablebase: NativeTablebase) -> None:
    """Attach one immutable TB3 oracle at a serialized engine boundary."""

    engine.native_tablebase = tablebase
    engine._distance.native = tablebase
    engine._distance._dtm_cache.clear()
    engine._distance._dtr_cache.clear()


def ensure_native_tablebase_ready(engine: Engine) -> bool:
    """Preserve exact three-piece strength without taxing opening search."""

    global NATIVE_TABLEBASE_WARMUP_ERROR
    if engine.native_tablebase is not None:
        return True
    native_dll = production_native_library()
    try:
        tablebase = NativeTablebase(native_dll)
    except Exception as error:
        NATIVE_TABLEBASE_WARMUP_ERROR = str(error)
        print(
            f"Notice: on-demand three-piece tablebase load failed: {error}",
            file=sys.stderr,
        )
        return False
    _attach_native_tablebase(engine, tablebase)
    NATIVE_TABLEBASE_WARMUP_ERROR = None
    return True


def close_global_engine() -> None:
    """Close GUI-owned native search and tablebase resources."""

    global GLOBAL_ENGINE, GLOBAL_ENGINE_CONFIG, GLOBAL_ENGINE_PROVENANCE
    with ENGINE_SEARCH_LOCK:
        if GLOBAL_ENGINE is not None:
            _close_engine_resources(GLOBAL_ENGINE)
        GLOBAL_ENGINE = None
        GLOBAL_ENGINE_CONFIG = None
        GLOBAL_ENGINE_PROVENANCE = None


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


def get_default_engine(
    *,
    threads: int = DEFAULT_ENGINE_THREADS,
    hash_mb: int = DEFAULT_ENGINE_HASH_MB,
    rules_profile: str = "project",
) -> Engine:
    """Return the GUI engine configured with real Threads and total Hash."""

    global GLOBAL_ENGINE, GLOBAL_ENGINE_CONFIG, GLOBAL_ENGINE_PROVENANCE
    if not 1 <= threads <= MAX_PARALLEL_NATIVE_THREADS:
        raise ValueError("threads must be in 1..12")
    if not 4 <= hash_mb <= 1024:
        raise ValueError("hash_mb must be in 4..1024")
    if rules_profile not in RULE_PROFILES:
        raise ValueError("unsupported rules profile")
    rules = RULE_PROFILES[rules_profile]
    native_dll = configured_gui_native_library()
    nnue_model = GUI_NNUE_MODEL_OVERRIDE
    if nnue_model is not None and not native_dll.is_file():
        raise RuntimeError(f"NNUE library unavailable: {native_dll}")
    config = (
        threads,
        hash_mb,
        rules_profile,
        str(native_dll.resolve()),
        None if nnue_model is None else str(nnue_model.resolve()),
    )
    if GLOBAL_ENGINE is None:
        ranked = []
        for tb_path in (
            "build/tb4_np80.compact.bin",
            "build/tb5_np80.compact.bin",
            "build/tb6_np80.compact.bin",
        ):
            absolute_tb_path = PROJECT_ROOT / tb_path
            if absolute_tb_path.exists():
                try:
                    ranked.append(RankedTablebase(absolute_tb_path))
                except Exception as err:
                    print(f"Notice: could not load tablebase {tb_path}: {err}", file=sys.stderr)

        native_search = None
        native_search_error = None
        if native_dll.exists():
            try:
                native_search = _create_native_search(
                    native_dll,
                    threads=threads,
                    hash_mb=hash_mb,
                    nnue_model=nnue_model,
                )
            except Exception as err:
                if nnue_model is not None:
                    for tablebase in ranked:
                        tablebase.close()
                    raise RuntimeError(f"NNUE initialization failed: {err}") from err
                print(f"Notice: could not load native search {native_dll}: {err}", file=sys.stderr)
                native_search_error = str(err)

        GLOBAL_ENGINE = Engine(
            rules=rules,
            ranked_tablebases=ranked,
            native_tablebase=None,
            native_search=native_search,
        )
        GLOBAL_ENGINE_CONFIG = config
        GLOBAL_ENGINE_PROVENANCE = _native_search_provenance(
            native_dll,
            native_search,
            native_search_error,
        )
        if native_search_error is not None:
            GLOBAL_ENGINE.last_native_error = native_search_error
    elif GLOBAL_ENGINE_CONFIG != config:
        (
            old_threads,
            old_hash_mb,
            old_rules_profile,
            old_native_dll,
            old_nnue_model,
        ) = GLOBAL_ENGINE_CONFIG
        native_search_error = None
        if (
            threads,
            hash_mb,
            str(native_dll.resolve()),
            None if nnue_model is None else str(nnue_model.resolve()),
        ) != (old_threads, old_hash_mb, old_native_dll, old_nnue_model):
            replacement = None
            if native_dll.exists():
                try:
                    replacement = _create_native_search(
                        native_dll,
                        threads=threads,
                        hash_mb=hash_mb,
                        nnue_model=nnue_model,
                    )
                except Exception as err:
                    if nnue_model is not None:
                        raise RuntimeError(f"NNUE reconfiguration failed: {err}") from err
                    print(
                        f"Notice: could not reconfigure native search {native_dll}: {err}",
                        file=sys.stderr,
                    )
                    native_search_error = str(err)
            previous = GLOBAL_ENGINE.native_search
            GLOBAL_ENGINE.native_search = replacement
            if previous is not None:
                previous.close()
        elif old_rules_profile != rules_profile and GLOBAL_ENGINE.native_search is not None:
            # Persistent TT values are not portable between repetition rules.
            GLOBAL_ENGINE.native_search.clear()

        GLOBAL_ENGINE.rules = rules
        GLOBAL_ENGINE._tt.clear()
        GLOBAL_ENGINE._move_hints.clear()
        GLOBAL_ENGINE._exact_failed.clear()
        GLOBAL_ENGINE.last_search_backend = "unsearched"
        GLOBAL_ENGINE.last_native_error = native_search_error
        GLOBAL_ENGINE_CONFIG = config
        GLOBAL_ENGINE_PROVENANCE = _native_search_provenance(
            native_dll,
            GLOBAL_ENGINE.native_search,
            native_search_error,
        )
    return GLOBAL_ENGINE


class EngineRequestHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def end_headers(self) -> None:
        # The GUI is under active development; a normal refresh must pick up
        # the latest settings behavior instead of a stale cached app.js.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

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
                with ENGINE_SEARCH_LOCK:
                    settings = {} if GUI_RELEASE is None else GUI_RELEASE["settings"]
                    engine = GLOBAL_ENGINE or get_default_engine(
                        threads=settings.get("threads", DEFAULT_ENGINE_THREADS),
                        hash_mb=settings.get("hash_mb_total", DEFAULT_ENGINE_HASH_MB))
                    native = engine.native_search
                    self.send_json({
                        **engine_search_provenance(engine),
                        "configured_backend": "native-root-split" if isinstance(native, ParallelNativeSearch) else "native-single" if native else "unavailable",
                        "threads": GLOBAL_ENGINE_CONFIG[0], "hash_mb": GLOBAL_ENGINE_CONFIG[1],
                        "hash_allocated_mb": getattr(native, "allocated_hash_mb", 0),
                        "ranked_tablebase_pieces": sorted(engine.ranked_tablebases),
                        "defaults": GUI_RELEASE["settings"] if GUI_RELEASE else {
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
            if GLOBAL_ENGINE is not None:
                with ENGINE_SEARCH_LOCK:
                    GLOBAL_ENGINE.clear()
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
        # cap was reached.  Forced moves and exact tablebase results may still
        # return immediately because no extra search can improve them.
        if data.get("use_full_time", True):
            depth = max(depth, GUI_SEARCH_DEPTH)
        limits = SearchLimits(depth=depth, time_ms=time_ms)
        # Native Engine state and persistent TT are shared between requests.
        # Serialize engine mutation while still allowing static files and cheap
        # state/move APIs to use separate HTTP worker threads.
        profiler = RequestProfiler(profile_request)
        lock_requested = time.perf_counter()
        with ENGINE_SEARCH_LOCK:
            lock_acquired = time.perf_counter()
            with profiler:
                engine = get_default_engine(
                    threads=threads,
                    hash_mb=hash_mb,
                    rules_profile=rules_profile,
                )
                engine_ready = time.perf_counter()
                tb3_ready_before = engine.native_tablebase is not None
                tb3_load_attempted = False
                if (sum(piece != EMPTY for piece in state.board) <= 3
                        and len(legal_moves(state)) > 1):
                    # Preserve on-demand loading; measure it separately from search.
                    tb3_load_attempted = not tb3_ready_before
                    ensure_native_tablebase_ready(engine)
                search_started = time.perf_counter()
                result = engine.search(
                    state,
                    limits=limits,
                    mode=mode,
                    history=history,
                )
                search_finished = time.perf_counter()
            provenance = engine_search_provenance(engine)
            if GUI_NNUE_MODEL_OVERRIDE is not None and (
                not provenance["nnue_enabled"] or provenance["native_error"]
                or provenance["search_backend"] == "python-fallback"
            ):
                raise RuntimeError(f"NNUE search unavailable: {provenance['native_error']}")

            # Snapshot shared resources under the same lock as the search.
            # A later request can reconfigure the engine before JSON is written.
            worker_count = (
                len(engine.native_search._workers)
                if isinstance(engine.native_search, ParallelNativeSearch)
                else (1 if engine.native_search else 0)
            )
            resource_snapshot = {
                "hash_allocated_mb": round(getattr(engine.native_search, "allocated_hash_mb", 0.0), 1),
                "native_tablebase_ready": engine.native_tablebase is not None,
                "native_tablebase_error": NATIVE_TABLEBASE_WARMUP_ERROR,
                "ranked_tablebase_pieces": sorted(engine.ranked_tablebases),
                "worker_count": worker_count,
                "search_thread_capacity": (
                    worker_count if provenance["search_backend"] == "native-root-split"
                    else 0 if provenance["search_backend"] == "forced" else 1
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
    release_pointer: str | Path | None = None,
    release_profile: str | None = None,
) -> None:
    global GUI_RELEASE
    if native_library is not None and (release_pointer is not None or release_profile is not None):
        raise ValueError("Select explicit native files or a release, not both")
    release = None
    if native_library is None and nnue_model is None:
        release = load_release(DEFAULT_POINTER if release_pointer is None else Path(release_pointer).resolve(),
                               profile=release_profile)
        if release is not None:
            native_library, nnue_model = release["native_library"], release["nnue_model"]
    configure_gui_native_search(native_library, nnue_model)
    GUI_RELEASE = release
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
            with ENGINE_SEARCH_LOCK:
                settings = {} if GUI_RELEASE is None else GUI_RELEASE["settings"]
                get_default_engine(threads=settings.get("threads", DEFAULT_ENGINE_THREADS),
                                   hash_mb=settings.get("hash_mb_total", DEFAULT_ENGINE_HASH_MB))
        except Exception as error:
            print(f"Notice: background engine warm-up failed: {error}", file=sys.stderr)

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
        close_global_engine()
        httpd.server_close()
        interactive_lease.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Thai Makhos Web GUI Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to run HTTP server")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    parser.add_argument("--native-library", help="explicit opt-in native-search DLL")
    parser.add_argument("--nnue-model", help="explicit NNUE model for the selected DLL")
    parser.add_argument("--release-pointer", help="GUI release selection JSON")
    parser.add_argument("--release-profile", choices=["nnue", "hce"])
    args = parser.parse_args()
    run_server(
        port=args.port,
        open_browser=not args.no_browser,
        native_library=args.native_library,
        nnue_model=args.nnue_model,
        release_pointer=args.release_pointer,
        release_profile=args.release_profile,
    )
