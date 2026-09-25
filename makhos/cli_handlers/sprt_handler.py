"""SPRT match orchestrator and checkpoint handlers for Thai Makhos Engine CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from ..core import DEFAULT_RULES
from ..game_analysis import build_match_game_record
from ..native import (
    NativeSearch,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)
from ..native_tablebase import NativeTablebase
from ..parallel_native import ParallelNativeSearch
from ..ranked_tablebase import RankedTablebase
from ..search import Engine
from .. import sprt
from ..sprt import SPRTResult
from ..workload_isolation import BatchWorkLease


def _set_windows_process_priority(priority_class: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.SetPriorityClass.restype = wintypes.BOOL
    if not kernel32.SetPriorityClass(
        kernel32.GetCurrentProcess(), priority_class
    ):
        error = ctypes.get_last_error()
        raise OSError(error, "could not set batch process priority")


def _set_batch_process_priority() -> str:
    if sys.platform != "win32":
        return "platform-default"
    cli_mod = sys.modules.get("makhos.cli")
    fn = getattr(cli_mod, "_set_windows_process_priority", _set_windows_process_priority)
    fn(0x00004000)
    return "BelowNormal"


def _sprt_result_payload(
    *,
    config: dict[str, object],
    result,
    complete: bool,
) -> dict[str, object]:
    return {
        "format": "thai-makhos-sprt-result-v2",
        "complete": complete,
        "config": config,
        "result": {
            "status": result.status,
            "llr": result.llr,
            "elo": result.elo,
            "elo_95_error": result.elo_error,
            "pairs": sum(result.pentanomial),
            "games": result.games,
            "wins": result.wins,
            "draws": result.draws,
            "losses": result.losses,
            "pentanomial": result.pentanomial,
        },
    }


def _write_sprt_checkpoint(
    output: Path,
    *,
    config: dict[str, object],
    result,
    complete: bool,
) -> None:
    payload = _sprt_result_payload(
        config=config,
        result=result,
        complete=complete,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


def _load_sprt_checkpoint(
    output: Path,
    *,
    expected_config: dict[str, object],
):
    payload = json.loads(output.read_text(encoding="utf-8"))
    if payload.get("format") != "thai-makhos-sprt-result-v2":
        raise ValueError("SPRT resume file has an unsupported format")
    if payload.get("config") != expected_config:
        raise ValueError("SPRT resume configuration mismatch")
    raw = payload.get("result")
    if not isinstance(raw, dict):
        raise ValueError("SPRT resume file has no result object")
    result = SPRTResult(
        status=str(raw["status"]),
        llr=float(raw["llr"]),
        elo=float(raw["elo"]),
        elo_error=float(raw["elo_95_error"]),
        wins=int(raw["wins"]),
        draws=int(raw["draws"]),
        losses=int(raw["losses"]),
        games=int(raw["games"]),
        pentanomial=tuple(int(value) for value in raw["pentanomial"]),
    )
    if int(raw["pairs"]) != sum(result.pentanomial):
        raise ValueError("SPRT resume pair count does not match pentanomial")
    complete = payload.get("complete")
    if not isinstance(complete, bool):
        raise ValueError("SPRT resume completion flag is invalid")
    return result, complete


def command_sprt(args: argparse.Namespace) -> int:
    dev_library = Path(args.dev_library).resolve()
    master_library = Path(args.master_library).resolve()
    if not dev_library.is_file():
        raise FileNotFoundError(f"candidate DLL not found: {dev_library}")
    if not master_library.is_file():
        raise FileNotFoundError(f"baseline DLL not found: {master_library}")
    if dev_library == master_library:
        raise ValueError("candidate and baseline DLL must be different files")
    dev_nnue_model = (
        Path(args.dev_nnue_model).resolve()
        if args.dev_nnue_model is not None
        else None
    )
    master_nnue_model = (
        Path(args.master_nnue_model).resolve()
        if args.master_nnue_model is not None
        else None
    )
    for label, model in (
        ("candidate", dev_nnue_model),
        ("baseline", master_nnue_model),
    ):
        if model is not None and not model.is_file():
            raise FileNotFoundError(f"{label} NNUE model not found: {model}")
    candidate_threads = (
        args.dev_threads if args.dev_threads is not None else args.threads
    )
    baseline_threads = (
        args.master_threads if args.master_threads is not None else args.threads
    )
    if args.hash_mb is not None and args.hash_mb < 1:
        raise ValueError("--hash-mb must be positive")
    if args.move_time_cap_ms is not None and args.move_time_cap_ms < 1:
        raise ValueError("--move-time-cap-ms must be positive")
    if args.fixed_move_time_ms is not None:
        if args.fixed_move_time_ms < 1:
            raise ValueError("--fixed-move-time-ms must be positive")
        if args.move_time_cap_ms is not None:
            raise ValueError("fixed move time and clock cap are mutually exclusive")
    if args.selective_root and candidate_threads == 1:
        raise ValueError("--selective-root requires candidate Threads 2 or greater")
    if args.shared_tt and candidate_threads == 1:
        raise ValueError("--shared-tt requires candidate Threads 2 or greater")
    if args.shared_tt and args.selective_root:
        raise ValueError("test --shared-tt and --selective-root separately")
    if args.root_alpha and candidate_threads == 1:
        raise ValueError("--root-alpha requires candidate Threads 2 or greater")
    if args.root_alpha and (args.selective_root or args.shared_tt):
        raise ValueError("test --root-alpha separately from selective-root/shared-TT")
    if args.resume and not args.output:
        raise ValueError("--resume requires --output")
    tb_draw_cutoff = bool(getattr(args, "tb_draw_cutoff", False))
    if tb_draw_cutoff and args.no_tablebase:
        raise ValueError("--tb-draw-cutoff requires tablebases")
    if tb_draw_cutoff and candidate_threads == 1 and not args.persistent_search:
        raise ValueError("--tb-draw-cutoff requires --persistent-search at one thread")

    libraries: dict[str, dict[str, object]] = {}
    for label, library, threads, nnue_model in (
        ("candidate", dev_library, candidate_threads, dev_nnue_model),
        ("baseline", master_library, baseline_threads, master_nnue_model),
    ):
        # Loading a one-shot wrapper does not allocate a search context, so
        # this is a cheap ABI preflight before any games are started.
        probe_persistent = args.persistent_search or threads > 1
        with NativeSearch(
            library,
            hash_power=12,
            persistent=probe_persistent,
            nnue_model=nnue_model,
        ) as probe:
            abi_version = probe.abi_version
            supports_fixed_search = probe.supports_fixed_search
            supports_window_search = probe.supports_window_search
            supports_shared_tt = probe.supports_shared_tt
            nnue_enabled = probe.nnue_enabled
            nnue_model_sha256 = probe.nnue_model_sha256
            nnue_feature_abi = probe.nnue_feature_abi
            if (
                tb_draw_cutoff
                and label == "candidate"
                and not getattr(probe, "supports_tablebase_draw", False)
            ):
                raise RuntimeError(
                    "--tb-draw-cutoff needs a candidate built with MAKHOS_SEARCH_TB_DRAW"
                )
        if args.persistent_search and abi_version < 3:
            raise RuntimeError(
                f"{label} DLL does not support --persistent-search: "
                f"{library} uses search ABI {abi_version}, need ABI 3"
            )
        libraries[label] = {
            "path": str(library),
            "sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            "search_abi": abi_version,
            "fixed_search": supports_fixed_search,
            "window_search": supports_window_search,
            "shared_tt": supports_shared_tt,
            "threads": threads,
            "nnue_enabled": nnue_enabled,
            "nnue_model": None if nnue_model is None else str(nnue_model),
            "nnue_model_sha256": nnue_model_sha256,
            "nnue_feature_abi": nnue_feature_abi,
        }
    if args.selective_root and not libraries["candidate"]["fixed_search"]:
        raise RuntimeError(
            "candidate DLL does not provide the fixed-depth API required by "
            "--selective-root"
        )
    if args.shared_tt and not libraries["candidate"]["shared_tt"]:
        raise RuntimeError(
            "candidate DLL does not provide the shared-TT API required by "
            "--shared-tt"
        )
    if args.root_alpha and not libraries["candidate"]["window_search"]:
        raise RuntimeError(
            "candidate DLL does not provide the windowed API required by "
            "--root-alpha"
        )

    effective_hash_mb = args.hash_mb
    if max(candidate_threads, baseline_threads) > 1 and effective_hash_mb is None:
        effective_hash_mb = 64

    ranked_paths: list[Path] = []
    if not args.no_tablebase:
        requested_ranked = args.ranked_tablebase
        if requested_ranked is None:
            requested_ranked = [
                "build/tb4_np80.compact.bin",
                "build/tb5_np80.compact.bin",
                "build/tb6_np80.compact.bin",
            ]
        ranked_paths = [
            Path(path).resolve()
            for path in requested_ranked
            if Path(path).resolve().is_file()
        ]
        if args.ranked_tablebase is not None and (
            len(ranked_paths) != len(args.ranked_tablebase)
        ):
            raise FileNotFoundError("one or more requested ranked tablebases are absent")

    ranked: list[RankedTablebase] = []
    native_tablebase = None
    shared_endgame_tb = None
    tb3_compact = None
    endgame_lib = None
    native_endgame_requested = getattr(args, "native_endgame", True)
    if native_endgame_requested is None:
        native_endgame_requested = True

    try:
        for path in ranked_paths:
            ranked.append(RankedTablebase(path))
        if not args.no_tablebase:
            native_tablebase = NativeTablebase(master_library)
            if native_endgame_requested:
                project_root = Path(__file__).resolve().parents[2]
                default_c4 = project_root / "build" / "native_endgame_c4" / (
                    "makhos_endgame_search_nnue" + (".dll" if sys.platform == "win32" else ".so")
                )
                default_c2 = project_root / "build" / "native_endgame_c2" / (
                    "makhos_endgame_search" + (".dll" if sys.platform == "win32" else ".so")
                )
                if getattr(args, "native_endgame_library", None) is not None:
                    endgame_lib = Path(args.native_endgame_library).resolve()
                elif (dev_nnue_model is not None or master_nnue_model is not None) and default_c4.is_file():
                    endgame_lib = default_c4
                else:
                    endgame_lib = default_c2

                if not endgame_lib.is_file():
                    raise FileNotFoundError(f"native endgame library not found: {endgame_lib}")

                from ..compact_tb3 import CompactTablebase, DEFAULT_ARTIFACT
                from ..native_endgame import NativeEndgameTablebase

                if DEFAULT_ARTIFACT.is_file():
                    tb3_compact = CompactTablebase(DEFAULT_ARTIFACT)
                shared_endgame_tb = NativeEndgameTablebase(
                    tb3_compact,
                    library=endgame_lib,
                    ranked_paths=tuple(ranked_paths),
                    no_progress_plies=80,
                )
    except Exception:
        for tablebase in ranked:
            tablebase.close()
        if native_tablebase is not None:
            native_tablebase.close()
        if shared_endgame_tb is not None:
            shared_endgame_tb.close()
        if tb3_compact is not None:
            tb3_compact.close()
        raise

    tablebase_config = {
        "native_3_piece": native_tablebase is not None,
        "ranked": [
            {
                "path": str(tablebase.path),
                "piece_count": tablebase.piece_count,
                "no_progress_plies": tablebase.no_progress_plies,
                "header_fnv1a64": f"{tablebase.expected_checksum:016x}",
            }
            for tablebase in ranked
        ],
    }
    if shared_endgame_tb is not None and endgame_lib is not None:
        tablebase_config["native_endgame"] = True
        tablebase_config["native_endgame_library"] = str(endgame_lib)
        tablebase_config["native_endgame_library_sha256"] = hashlib.sha256(
            endgame_lib.read_bytes()
        ).hexdigest()
        tablebase_config["candidate_endgame_threads"] = candidate_threads
        tablebase_config["baseline_endgame_threads"] = baseline_threads

    batch_priority = _set_batch_process_priority()
    sprt_config = {
        "libraries": libraries,
        "persistent_search": bool(
            args.persistent_search or
            candidate_threads > 1 or
            baseline_threads > 1
        ),
        "candidate_persistent_search": bool(
            args.persistent_search or candidate_threads > 1
        ),
        "baseline_persistent_search": bool(
            args.persistent_search or baseline_threads > 1
        ),
        "search_hash_power": args.search_hash_power,
        "threads": args.threads,
        "candidate_threads": candidate_threads,
        "baseline_threads": baseline_threads,
        "hash_mb": effective_hash_mb,
        "selective_root": bool(args.selective_root),
        "root_alpha": bool(args.root_alpha),
        "root_alpha_margin": args.root_alpha_margin,
        "root_alpha_min_depth": args.root_alpha_min_depth,
        "shared_tt": bool(args.shared_tt),
        "shared_tt_group_size": args.shared_tt_group_size,
        "selective_reserve": args.selective_reserve,
        "selective_candidates": args.selective_candidates,
        "selective_margin": args.selective_margin,
        "move_time_cap_ms": args.move_time_cap_ms,
        "max_game_plies": args.max_game_plies,
        "tablebases": tablebase_config,
        "time_seconds": args.time,
        "increment_seconds": args.inc,
        "opening_plies": args.opening_plies,
        "seed": args.seed,
        "parallel_games": args.parallel_games,
        "elo0": args.elo0,
        "elo1": args.elo1,
        "max_pairs": args.pairs,
        "resume": bool(args.resume),
        "workload_isolation": {
            "policy": "interactive-gui-priority-v1",
            "checkpoint_granularity": "before-each-pair-and-ply",
            "process_priority": batch_priority,
        },
    }
    if shared_endgame_tb is not None:
        sprt_config["native_endgame"] = True
        sprt_config["candidate_endgame_threads"] = candidate_threads
        sprt_config["baseline_endgame_threads"] = baseline_threads
    # Preserve legacy clock-mode checkpoint identities byte-for-byte in shape.
    # Fixed-time checkpoints bind their budget explicitly for resume validation.
    if args.fixed_move_time_ms is not None:
        sprt_config["fixed_move_time_ms"] = args.fixed_move_time_ms
    if tb_draw_cutoff:
        # Present only when enabled, so existing checkpoint identities hold.
        if shared_endgame_tb is None:
            raise ValueError("--tb-draw-cutoff requires the native endgame tablebases")
        sprt_config["candidate_tb_draw_cutoff"] = True
        sprt_config["candidate_tb_draw_max_pieces"] = shared_endgame_tb.max_pieces
    print(
        "SPRT_CONFIG " + json.dumps(sprt_config, sort_keys=True),
        flush=True,
    )

    from ..native_endgame_search import (
        NativeEndgameSearch,
        ParallelNativeEndgameSearch,
    )

    def make_native_search(
        library: Path,
        *,
        threads: int,
        nnue_model: Path | None,
        selective_root: bool,
        root_alpha: bool,
        shared_tt: bool,
    ):
        if threads == 1:
            hash_power = args.search_hash_power
            if effective_hash_mb is not None:
                hash_power = hash_power_for_megabytes(
                    effective_hash_mb,
                    entry_bytes=native_tt_entry_bytes(library),
                )
            return NativeSearch(
                library,
                hash_power=hash_power,
                persistent=args.persistent_search,
                nnue_model=nnue_model,
            )
        return ParallelNativeSearch(
            library,
            threads=threads,
            hash_mb=effective_hash_mb,
            selective_root=selective_root,
            selective_reserve=args.selective_reserve,
            selective_candidates=args.selective_candidates,
            selective_margin=args.selective_margin,
            root_alpha=root_alpha,
            root_alpha_margin=args.root_alpha_margin,
            root_alpha_min_depth=args.root_alpha_min_depth,
            shared_tt=shared_tt,
            shared_tt_group_size=args.shared_tt_group_size,
            nnue_model=nnue_model,
        )

    def dev_factory():
        dev_eg_search = None
        if shared_endgame_tb is not None:
            if candidate_threads > 1:
                dev_eg_search = ParallelNativeEndgameSearch(
                    shared_endgame_tb,
                    threads=candidate_threads,
                    nnue_model=dev_nnue_model,
                )
            else:
                dev_eg_search = NativeEndgameSearch(
                    shared_endgame_tb,
                    nnue_model=dev_nnue_model,
                )
        dev_native_search = make_native_search(
            dev_library,
            threads=candidate_threads,
            nnue_model=dev_nnue_model,
            selective_root=args.selective_root,
            root_alpha=args.root_alpha,
            shared_tt=args.shared_tt,
        )
        if tb_draw_cutoff:
            dev_native_search.attach_tablebase(shared_endgame_tb)
        return Engine(
            DEFAULT_RULES,
            exact_piece_limit=2,
            native_tablebase=native_tablebase,
            ranked_tablebases=ranked,
            native_search=dev_native_search,
            native_endgame_search=dev_eg_search,
            native_endgame_enabled=dev_eg_search is not None,
        )

    def master_factory():
        master_eg_search = None
        if shared_endgame_tb is not None:
            if baseline_threads > 1:
                master_eg_search = ParallelNativeEndgameSearch(
                    shared_endgame_tb,
                    threads=baseline_threads,
                    nnue_model=master_nnue_model,
                )
            else:
                master_eg_search = NativeEndgameSearch(
                    shared_endgame_tb,
                    nnue_model=master_nnue_model,
                )
        return Engine(
            DEFAULT_RULES,
            exact_piece_limit=2,
            native_tablebase=native_tablebase,
            ranked_tablebases=ranked,
            native_search=make_native_search(
                master_library,
                threads=baseline_threads,
                nnue_model=master_nnue_model,
                selective_root=False,
                root_alpha=False,
                shared_tt=False,
            ),
            native_endgame_search=master_eg_search,
            native_endgame_enabled=master_eg_search is not None,
        )

    # Game records are an optional side output. The directory stays out of
    # sprt_config so checkpoint resume and multi-seed aggregation are unchanged.
    games_dir = (
        Path(args.games_dir).resolve() if getattr(args, "games_dir", None) else None
    )
    write_game = None
    if games_dir is not None:
        games_dir.mkdir(parents=True, exist_ok=True)
        match_metadata = {
            "tool": "makhos sprt",
            "seed": args.seed,
            "opening_plies": args.opening_plies,
            "time_seconds": args.time,
            "increment_seconds": args.inc,
            "fixed_move_time_ms": args.fixed_move_time_ms,
            "tablebases": tablebase_config,
            **{
                role: {
                    key: libraries[role][key]
                    for key in ("sha256", "search_abi", "threads", "nnue_model_sha256")
                }
                for role in ("candidate", "baseline")
            },
        }

        def write_game(game: dict) -> None:
            record = build_match_game_record(game, match=match_metadata)
            path = games_dir / (
                f"pair{game['pair']:05d}-candidate-{game['candidate_color']}.json"
            )
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(record, indent=1, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)

        print(f"SPRT_GAMES_DIR {games_dir}", flush=True)

    output = Path(args.output).resolve() if args.output else None
    resume_result = None
    if args.resume and output is not None and output.exists():
        resume_result, _complete = _load_sprt_checkpoint(
            output,
            expected_config=sprt_config,
        )
        print(
            f"SPRT_RESUME pairs={sum(resume_result.pentanomial)} "
            f"status={resume_result.status}",
            flush=True,
        )

    def checkpoint_result(result) -> None:
        assert output is not None
        _write_sprt_checkpoint(
            output,
            config=sprt_config,
            result=result,
            complete=False,
        )

    try:
        project_root = Path(__file__).resolve().parents[2]
        with BatchWorkLease(project_root) as batch_lease:
            result = sprt.run_sprt_match(
                dev_factory,
                master_factory,
                max_pairs=args.pairs,
                elo0=args.elo0,
                elo1=args.elo1,
                initial_time_ms=int(args.time * 1000),
                inc_ms=int(args.inc * 1000),
                opening_plies=args.opening_plies,
                parallel_games=args.parallel_games,
                max_game_plies=args.max_game_plies,
                move_time_cap_ms=args.move_time_cap_ms,
                fixed_move_time_ms=args.fixed_move_time_ms,
                seed=args.seed,
                workload_checkpoint=batch_lease.checkpoint,
                resume_result=resume_result,
                on_pair_completed=checkpoint_result if args.resume else None,
                on_game_completed=write_game,
            )
    finally:
        for tablebase in ranked:
            tablebase.close()
        if native_tablebase is not None:
            native_tablebase.close()
        if shared_endgame_tb is not None:
            shared_endgame_tb.close()
        if tb3_compact is not None:
            tb3_compact.close()
    print("\nFinal Result:")
    print(f"  Status: {result.status}")
    print(f"  LLR: {result.llr:+.2f}")
    print(f"  Elo: {result.elo:+.1f} +/-95% {result.elo_error:.1f}")
    print(f"  Games: {result.games} (W:{result.wins} D:{result.draws} L:{result.losses})")
    print(f"  Ptnml(0-2): {' '.join(str(value) for value in result.pentanomial)}")
    if output is not None:
        if args.resume:
            _write_sprt_checkpoint(
                output,
                config=sprt_config,
                result=result,
                complete=True,
            )
        else:
            payload = {
                "format": "thai-makhos-sprt-result-v1",
                "config": sprt_config,
                "result": _sprt_result_payload(
                    config=sprt_config,
                    result=result,
                    complete=True,
                )["result"],
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(output.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            temporary.replace(output)
        print(f"  Output: {output}")
    return 0 if result.status == "PASS" else 1
