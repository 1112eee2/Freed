"""Authoritative engine, tablebase, search and lifecycle manager.

Owns the Engine instance, search lock, native search sessions, tablebase
handles, TB3 warmup/service, configuration, and clear/close lifecycle.
"""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import sys
import threading

from .core import (
    BLACK,
    DEFAULT_RULES,
    EMPTY,
    Rules,
    format_position,
    legal_moves,
    parse_position,
)
from .compact_tb3 import CompactTablebase
from .endgame_routing import is_native_endgame_position
from .tb3_service import TB3Service
from .native import NativeSearch, hash_power_for_megabytes, native_tt_entry_bytes
from .native_endgame import NativeEndgameTablebase
from .native_endgame_search import NativeEndgameSearch, ParallelNativeEndgameSearch
from .parallel_native import MAX_PARALLEL_NATIVE_THREADS, ParallelNativeSearch
from .ranked_tablebase import RankedTablebase
from .search import Engine
from .gui_release import DEFAULT_POINTER, load_release


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENGINE_THREADS = 1
DEFAULT_ENGINE_HASH_MB = 64
MIN_ENGINE_HASH_MB = 4
MAX_ENGINE_HASH_MB = 1024
GUI_SEARCH_DEPTH = 64
MAX_SEARCH_DEPTH = 94
DEFAULT_NATIVE_ENDGAME_ENABLED = True
DEFAULT_NATIVE_ENDGAME_C2_LIBRARY = PROJECT_ROOT / "build" / "native_endgame_c2" / (
    "makhos_endgame_search" + (".dll" if sys.platform == "win32" else ".so")
)
DEFAULT_NATIVE_ENDGAME_C3_LIBRARY = PROJECT_ROOT / "build" / "native_endgame_c3" / (
    "makhos_endgame_search_nnue" + (".dll" if sys.platform == "win32" else ".so")
)
DEFAULT_NATIVE_ENDGAME_C4_LIBRARY = PROJECT_ROOT / "build" / "native_endgame_c4" / (
    "makhos_endgame_search_nnue" + (".dll" if sys.platform == "win32" else ".so")
)

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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Authoritative state owned by engine_manager
GLOBAL_ENGINE: Engine | None = None
GLOBAL_ENGINE_CONFIG: tuple[int, int, str, str, str | None, bool, str | None] | None = None
GLOBAL_ENGINE_PROVENANCE: dict[str, object] | None = None
GUI_NATIVE_LIBRARY_OVERRIDE: Path | None = None
GUI_NNUE_MODEL_OVERRIDE: Path | None = None
GUI_NATIVE_ENDGAME_ENABLED_OVERRIDE: bool | None = None
GUI_NATIVE_ENDGAME_LIBRARY_OVERRIDE: Path | None = None
GUI_RELEASE: dict | None = None
TB3_SERVICE = TB3Service()
ENGINE_SEARCH_LOCK = threading.RLock()


def configure_gui_native_search(
    native_library: str | Path | None = None,
    nnue_model: str | Path | None = None,
    *,
    native_endgame: bool = DEFAULT_NATIVE_ENDGAME_ENABLED,
    native_endgame_library: str | Path | None = None,
) -> None:
    """Select explicit GUI candidates without changing the production default.

    The endgame capability is deliberately default-off. Its DLL is a
    separate artifact and is validated lazily after TB3 is warm, so startup
    never maps multi-gigabyte TB4--TB6 files on the ordinary production path.
    """

    global GUI_NATIVE_LIBRARY_OVERRIDE, GUI_NNUE_MODEL_OVERRIDE
    global GUI_NATIVE_ENDGAME_ENABLED_OVERRIDE, GUI_NATIVE_ENDGAME_LIBRARY_OVERRIDE
    global GUI_RELEASE
    if native_library is None and nnue_model is not None:
        raise ValueError("--nnue-model requires an explicit --native-library")
    library = None if native_library is None else Path(native_library).resolve()
    model = None if nnue_model is None else Path(nnue_model).resolve()
    endgame_library = (
        None if native_endgame_library is None
        else Path(native_endgame_library).resolve()
    )
    if endgame_library is not None:
        native_endgame = True
    if library is not None and not library.is_file():
        raise FileNotFoundError(f"GUI native library not found: {library}")
    if model is not None and not model.is_file():
        raise FileNotFoundError(f"GUI NNUE model not found: {model}")
    if endgame_library is not None and not endgame_library.is_file():
        raise FileNotFoundError(f"GUI native endgame library not found: {endgame_library}")
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
    GUI_NATIVE_ENDGAME_ENABLED_OVERRIDE = bool(native_endgame)
    GUI_NATIVE_ENDGAME_LIBRARY_OVERRIDE = endgame_library
    GUI_RELEASE = None


def configure_engine_release(
    native_library: str | Path | None = None,
    nnue_model: str | Path | None = None,
    *,
    native_endgame: bool = DEFAULT_NATIVE_ENDGAME_ENABLED,
    native_endgame_library: str | Path | None = None,
    release_pointer: str | Path | None = None,
    release_profile: str | None = None,
) -> dict | None:
    """Select the hash-checked release, or explicit files, for the shared engine.

    The GUI server and the text protocol both start here, so they play the
    same engine. Returns the release, or None for explicit files or an
    unconfigured development checkout.
    """

    global GUI_RELEASE
    if native_library is not None and (release_pointer is not None or release_profile is not None):
        raise ValueError("Select explicit native files or a release, not both")
    release = None
    if native_library is None and nnue_model is None:
        release = load_release(DEFAULT_POINTER if release_pointer is None else Path(release_pointer).resolve(),
                               profile=release_profile)
        if release is not None:
            native_library, nnue_model = release["native_library"], release["nnue_model"]
    configure_gui_native_search(
        native_library,
        nnue_model,
        native_endgame=native_endgame,
        native_endgame_library=native_endgame_library,
    )
    GUI_RELEASE = release
    if release is not None:
        with NativeSearch(native_library, hash_power=12, persistent=True, nnue_model=nnue_model) as probe:
            if probe.abi_version != release["native_search_abi"] or probe.nnue_feature_abi != release["nnue_feature_abi"]:
                raise ValueError("GUI release ABI mismatch")
    return release


def configured_gui_native_library() -> Path:
    return GUI_NATIVE_LIBRARY_OVERRIDE or production_native_library()


def configured_gui_native_endgame_library(*, nnue: bool = False) -> Path:
    """Resolve the isolated C2/C3/C4 library without inferring production state."""
    if GUI_NATIVE_ENDGAME_LIBRARY_OVERRIDE is not None:
        return GUI_NATIVE_ENDGAME_LIBRARY_OVERRIDE
    if nnue:
        return (
            DEFAULT_NATIVE_ENDGAME_C4_LIBRARY
            if DEFAULT_NATIVE_ENDGAME_C4_LIBRARY.is_file()
            else DEFAULT_NATIVE_ENDGAME_C3_LIBRARY
        )
    return DEFAULT_NATIVE_ENDGAME_C2_LIBRARY


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
    endgame = getattr(engine, "native_endgame_search", None)
    if backend == "native":
        backend = (
            "native-root-split"
            if isinstance(native_search, ParallelNativeSearch)
            else "native-single"
        )
    elif backend == "native-endgame":
        backend = "native-endgame"
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
    if backend == "native-endgame":
        configured["evaluator_used"] = getattr(endgame, "evaluator", "hce")
    else:
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
    configured["native_endgame_enabled"] = bool(
        getattr(engine, "native_endgame_enabled", False)
    )
    configured["native_endgame_ready"] = endgame is not None
    configured["native_endgame_evaluator"] = (
        None if endgame is None else getattr(endgame, "evaluator", "hce")
    )
    configured["native_endgame_threads"] = (
        None if endgame is None else getattr(endgame, "threads", 1)
    )
    endgame_enabled = bool(getattr(engine, "native_endgame_enabled", False))
    endgame_library = getattr(engine, "native_endgame_library", None)
    if endgame_library is None and endgame_enabled:
        endgame_library = configured_gui_native_endgame_library(
            nnue=bool(getattr(native_search, "nnue_enabled", False))
        )
    configured["native_endgame_library"] = (
        None if endgame_library is None else str(Path(endgame_library).resolve())
    )
    configured["native_endgame_proof_precedence"] = "terminal>tablebase>nnue"
    return configured


def checked_search_provenance(engine: Engine) -> dict[str, object]:
    """Provenance of the last search; a selected NNUE must really have been used."""

    provenance = engine_search_provenance(engine)
    if GUI_NNUE_MODEL_OVERRIDE is not None and (
        not provenance["nnue_enabled"] or provenance["native_error"]
        or provenance["search_backend"] == "python-fallback"
    ):
        raise RuntimeError(f"NNUE search unavailable: {provenance['native_error']}")
    return provenance


def _close_engine_resources(engine: Engine) -> None:
    if getattr(engine, "native_endgame_search", None) is not None:
        engine.native_endgame_search.close()
        engine.native_endgame_search = None
    if getattr(engine, "native_endgame_tablebase", None) is not None:
        engine.native_endgame_tablebase.close()
        engine.native_endgame_tablebase = None
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
    """Load the immutable artifact without holding the engine/search lock."""
    return TB3_SERVICE.start()


def _attach_native_tablebase(engine: Engine, tablebase: CompactTablebase) -> None:
    """Attach one immutable TB3 oracle at a serialized engine boundary."""

    engine.native_tablebase = tablebase
    engine._distance.native = tablebase
    engine._distance._dtm_cache.clear()
    engine._distance._dtr_cache.clear()


def ensure_native_tablebase_ready(engine: Engine) -> bool:
    """Attach already loaded bytes only; never wait, read or solve in a request."""
    if engine.native_tablebase is not None:
        return True
    start_native_tablebase_warmup()
    tablebase = TB3_SERVICE.ready()
    if tablebase is None:
        return False
    _attach_native_tablebase(engine, tablebase)
    return True


def ensure_native_endgame_ready(engine: Engine) -> bool:
    """Create the isolated C3 session after immutable TB bytes are available.

    This function is called only for an explicitly enabled capability and an
    endgame/transition root. It never replaces the Python TB oracle or the
    production native search resource; failures are recorded on the Engine so
    the request can fall back visibly.
    """
    if not getattr(engine, "native_endgame_enabled", False):
        return False
    if getattr(engine, "native_endgame_search", None) is not None:
        return True
    if engine.native_tablebase is None and not ensure_native_tablebase_ready(engine):
        engine.last_native_error = "TB3 is not ready for native endgame search"
        return False
    nnue = bool(getattr(engine.native_search, "nnue_enabled", False))
    library = Path(
        getattr(engine, "native_endgame_library", None)
        or configured_gui_native_endgame_library(nnue=nnue)
    ).resolve()
    if not library.is_file():
        engine.last_native_error = f"native endgame library unavailable: {library}"
        return False
    ranked_paths = tuple(
        tablebase.path
        for pieces, tablebase in sorted(engine.ranked_tablebases.items())
        if pieces in (4, 5, 6) and Path(tablebase.path).is_file()
    )
    owner = None
    try:
        owner = NativeEndgameTablebase(
            engine.native_tablebase,
            library=library,
            ranked_paths=ranked_paths,
            no_progress_plies=engine.rules.no_progress_plies,
        )
        nnue_model = (
            getattr(engine.native_search, "nnue_model_path", None)
            if nnue else None
        )
        threads = int(getattr(engine.native_search, "threads", 1))
        if threads > 1:
            search = ParallelNativeEndgameSearch(
                owner,
                threads=threads,
                nnue_model=nnue_model,
            )
        else:
            search = NativeEndgameSearch(
                owner,
                nnue_model=nnue_model,
            )
    except Exception as error:
        if owner is not None:
            owner.close()
        engine.last_native_error = str(error)
        return False
    engine.native_endgame_tablebase = owner
    engine.native_endgame_search = search
    engine.native_endgame_library = library
    engine.native_endgame_evaluator = search.evaluator
    engine.last_native_error = None
    return True


def prepare_root_search(engine: Engine, state) -> bool | None:
    """Attach the endgame resources a root needs before it is searched.

    Returns None when the root needs none, True when they are attached, and
    False when TB3 is not loaded: such a root must not silently fall back to
    expensive or incomplete Python solving. 4..6 -> 3 transitions count as
    endgame roots; a forced move needs nothing.
    """

    choices = len(legal_moves(state))
    regular_endgame = (
        sum(piece != EMPTY for piece in state.board)
        <= max((3, *engine.ranked_tablebases))
        and choices > 1
    )
    native_endgame_position = (
        engine.native_endgame_enabled
        and choices > 1
        and is_native_endgame_position(state)
    )
    if not (regular_endgame or native_endgame_position):
        return None
    if not ensure_native_tablebase_ready(engine):
        return False
    if native_endgame_position:
        # The candidate is created only after TB3 is ready. If it is
        # unavailable, Engine.search performs a visible Python fallback and
        # provenance reports the reason.
        ensure_native_endgame_ready(engine)
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
        TB3_SERVICE.close()


def get_default_engine(
    *,
    threads: int = DEFAULT_ENGINE_THREADS,
    hash_mb: int = DEFAULT_ENGINE_HASH_MB,
    rules_profile: str = "project",
    native_endgame: bool | None = None,
    native_endgame_library: str | Path | None = None,
) -> Engine:
    """Return the GUI engine configured with real Threads and total Hash."""

    global GLOBAL_ENGINE, GLOBAL_ENGINE_CONFIG, GLOBAL_ENGINE_PROVENANCE
    if not 1 <= threads <= MAX_PARALLEL_NATIVE_THREADS:
        raise ValueError("threads must be in 1..12")
    if not MIN_ENGINE_HASH_MB <= hash_mb <= MAX_ENGINE_HASH_MB:
        raise ValueError(f"hash_mb must be in {MIN_ENGINE_HASH_MB}..{MAX_ENGINE_HASH_MB}")
    if rules_profile not in RULE_PROFILES:
        raise ValueError("unsupported rules profile")
    rules = RULE_PROFILES[rules_profile]
    native_dll = configured_gui_native_library()
    nnue_model = GUI_NNUE_MODEL_OVERRIDE
    configured_endgame = GUI_NATIVE_ENDGAME_ENABLED_OVERRIDE
    endgame_enabled = (
        DEFAULT_NATIVE_ENDGAME_ENABLED
        if native_endgame is None and configured_endgame is None
        else configured_endgame
        if native_endgame is None
        else bool(native_endgame)
    )
    if native_endgame_library is not None:
        endgame_enabled = True
    endgame_library = (
        None
        if native_endgame_library is None
        else str(Path(native_endgame_library).resolve())
    )
    if nnue_model is not None and not native_dll.is_file():
        raise RuntimeError(f"NNUE library unavailable: {native_dll}")
    config = (
        threads,
        hash_mb,
        rules_profile,
        str(native_dll.resolve()),
        None if nnue_model is None else str(nnue_model.resolve()),
        bool(endgame_enabled),
        endgame_library,
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
            native_endgame_enabled=endgame_enabled,
        )
        GLOBAL_ENGINE.native_endgame_library = (
            None if endgame_library is None else Path(endgame_library)
        )
        GLOBAL_ENGINE.native_endgame_tablebase = None
        GLOBAL_ENGINE.native_endgame_evaluator = None
        GLOBAL_ENGINE_CONFIG = config
        GLOBAL_ENGINE_PROVENANCE = _native_search_provenance(
            native_dll,
            native_search,
            native_search_error,
        )
        if native_search_error is not None:
            GLOBAL_ENGINE.last_native_error = native_search_error
    elif GLOBAL_ENGINE_CONFIG != config:
        old_threads, old_hash_mb, old_rules_profile, old_native_dll, old_nnue_model, \
            old_endgame_enabled, old_endgame_library = GLOBAL_ENGINE_CONFIG
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
        if (
            bool(endgame_enabled) != old_endgame_enabled
            or endgame_library != old_endgame_library
            or (old_endgame_enabled and old_nnue_model != config[4])
        ):
            if getattr(GLOBAL_ENGINE, "native_endgame_search", None) is not None:
                GLOBAL_ENGINE.native_endgame_search.close()
            if getattr(GLOBAL_ENGINE, "native_endgame_tablebase", None) is not None:
                GLOBAL_ENGINE.native_endgame_tablebase.close()
            GLOBAL_ENGINE.native_endgame_search = None
            GLOBAL_ENGINE.native_endgame_tablebase = None
            GLOBAL_ENGINE.native_endgame_library = (
                None if endgame_library is None else Path(endgame_library)
            )
            GLOBAL_ENGINE.native_endgame_evaluator = None
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
