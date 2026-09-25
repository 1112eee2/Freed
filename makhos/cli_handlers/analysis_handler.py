"""Game analysis, benchmarks, and corpus CLI command handlers."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from ..core import (
    BLACK,
    DEFAULT_RULES,
    RED,
    apply_move,
    format_position,
    legal_moves,
    perft,
)
from ..eval import trace_evaluation
from ..eval_corpus import build_exact_wdl_corpus
from ..eval_tune import audit_and_fit_corpus
from ..game_analysis import (
    EXTERNAL_NO_REPETITION_RULES,
    GAME_ANALYSIS_FORMAT,
    RootMoveObservation,
    SearchObservation,
    classify_search_observations,
    engine_provenance_issues,
    engine_provenance_mismatches,
    inferred_engine_players,
    load_game_record,
    player_name,
    replay_game,
)
from ..middlegame_corpus import build_middlegame_corpus
from ..native import (
    NativeSearch,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)
from ..native_verify import verify_native_moves
from ..parallel_native import ParallelNativeSearch
from .common import _get_state


def command_perft(args: argparse.Namespace) -> int:
    state = _get_state(args)
    for depth in range(1, args.depth + 1):
        print(f"depth {depth}: {perft(state, depth)}")
    return 0


def command_verify_native(args: argparse.Namespace) -> int:
    result = verify_native_moves(
        args.executable,
        samples=args.samples,
        seed=args.seed,
        exact_samples=args.exact_samples,
        exact_no_progress=args.exact_no_progress,
    )
    print(f"positions compared: {result.samples}")
    print(f"legal moves compared: {result.compared_moves}")
    print(f"exact 3-piece positions compared: {result.exact_samples}")
    print("native differential verification: PASS")
    return 0


def command_bench_native(args: argparse.Namespace) -> int:
    from ..native_benchmark import compare_native_libraries

    report = compare_native_libraries(
        args.candidate_library,
        args.baseline_library,
        count=args.cases,
        depth=args.depth,
        repetitions=args.repetitions,
        seed=args.seed,
        hash_power=args.search_hash_power,
        candidate_nnue_model=args.candidate_nnue_model,
        baseline_nnue_model=args.baseline_nnue_model,
    )
    report_dict = report.as_dict()
    config = {
        key: report_dict[key]
        for key in (
            "candidate_path",
            "candidate_sha256",
            "candidate_abi",
            "baseline_path",
            "baseline_sha256",
            "baseline_abi",
            "seed",
            "hash_power",
            "ply_schedule",
            "candidate_nnue_model_sha256",
            "baseline_nnue_model_sha256",
        )
    }
    config.update(
        {
            "cases": args.cases,
            "depth": args.depth,
            "repetitions": args.repetitions,
        }
    )
    print("NATIVE_BENCH_CONFIG " + json.dumps(config, sort_keys=True), flush=True)
    for row in report.rows:
        node_ratio = row.candidate.nodes / row.baseline.nodes
        print(
            f"Case {row.case:3d} ply {row.target_plies:2d} | "
            f"nodes {row.candidate.nodes}/{row.baseline.nodes} "
            f"({node_ratio:.4f}x) | "
            f"ms {row.candidate.wall_ms:.1f}/{row.baseline.wall_ms:.1f} | "
            f"score {row.candidate.score}/{row.baseline.score} | "
            f"move {row.candidate.move}/{row.baseline.move}",
            flush=True,
        )
    print(
        "NATIVE_BENCH_RESULT "
        + json.dumps(report_dict["summary"], sort_keys=True),
        flush=True,
    )
    return 0


def command_profile_native(args: argparse.Namespace) -> int:
    from ..native_benchmark import generate_native_benchmark_cases

    library = Path(args.library).resolve()
    if not library.is_file():
        raise FileNotFoundError(f"telemetry DLL not found: {library}")
    cases = generate_native_benchmark_cases(count=args.cases, seed=args.seed)
    totals = None
    total_nodes = 0
    forced_capture_roots = 0
    with NativeSearch(
        library,
        hash_power=args.search_hash_power,
        persistent=True,
    ) as engine:
        if engine.abi_version < 6:
            raise RuntimeError(
                f"profile-native requires search ABI 6, got {engine.abi_version}"
            )
        for case in cases:
            engine.clear()
            result = engine.search(
                case.state,
                depth=args.depth,
                time_ms=None,
                no_progress_plies=DEFAULT_RULES.no_progress_plies,
                repetition_limit=DEFAULT_RULES.repetition_limit,
                history=case.history,
            )
            if result.telemetry is None:
                raise RuntimeError("ABI 6 search returned no telemetry")
            totals = (
                result.telemetry
                if totals is None
                else totals + result.telemetry
            )
            total_nodes += result.nodes
            forced_capture_roots += bool(legal_moves(case.state)[0].captures)

    if totals is None:
        raise RuntimeError("profile generated no cases")
    report = asdict(totals)

    def percent(numerator: int, denominator: int) -> float:
        return round(100.0 * numerator / denominator, 2) if denominator else 0.0

    def ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 3) if denominator else 0.0

    report.update(
        {
            "library": str(library),
            "sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            "abi": engine.abi_version,
            "cases": len(cases),
            "forced_capture_roots": forced_capture_roots,
            "depth": args.depth,
            "seed": args.seed,
            "hash_power": args.search_hash_power,
            "nodes": total_nodes,
            "qnode_pct": percent(totals.qnodes, total_nodes),
            "avg_moves_per_generation": ratio(
                totals.moves_generated, totals.movegen_calls
            ),
            "avg_moves_per_ordering": ratio(
                totals.moves_ordered, totals.ordering_calls
            ),
            "tt_hit_pct": percent(totals.tt_hits, totals.tt_probes),
            "tt_cutoff_pct_of_probes": percent(
                totals.tt_cutoffs, totals.tt_probes
            ),
            "tt_collision_pct": percent(
                totals.tt_collisions, totals.tt_probes
            ),
            "tt_replacement_pct_of_stores": percent(
                totals.tt_replacements, totals.tt_stores
            ),
            "null_cutoff_pct": percent(
                totals.null_cutoffs, totals.null_attempts
            ),
            "beta_cutoff_first_pct": percent(
                totals.beta_cutoff_first, totals.beta_cutoffs
            ),
            "avg_beta_cutoff_index": ratio(
                totals.beta_cutoff_index_sum, totals.beta_cutoffs
            ),
            "lmr_research_pct_of_pvs": percent(
                totals.lmr_researches, totals.pvs_researches
            ),
        }
    )
    print("NATIVE_PROFILE " + json.dumps(report, sort_keys=True))
    return 0


def _evaluation_trace_payload(state, perspective: int) -> dict:
    trace = trace_evaluation(state, perspective)
    return {
        "score": trace.score,
        "relative_terms": trace.relative_terms,
        "red": asdict(trace.red),
        "black": asdict(trace.black),
        "terminal_score": trace.terminal_score,
    }


def command_analyze_game(args: argparse.Namespace) -> int:
    """Replay a GUI record and compare move stability at increasing budgets."""

    record = load_game_record(args.game)
    analysis_rules = (
        DEFAULT_RULES
        if args.rules_profile == "project"
        else EXTERNAL_NO_REPETITION_RULES
    )
    replayed = replay_game(record, rules=analysis_rules)
    inferred = inferred_engine_players(record)
    actor_labels_present = any(item.actor is not None for item in replayed.plies)
    if args.side == "engine":
        if actor_labels_present:
            selected_players = {BLACK, RED}
        elif inferred is not None:
            selected_players = set(inferred)
        else:
            raise ValueError(
                "game does not identify engine moves; use --side black, red, or both"
            )
    elif args.side == "both":
        selected_players = {BLACK, RED}
    else:
        selected_players = {BLACK if args.side == "black" else RED}

    requested_budgets = args.budget_ms or (2000, 5000, 20000)
    budgets = tuple(sorted(set(requested_budgets)))
    if not budgets or any(budget < 1 for budget in budgets):
        raise ValueError("--budget-ms values must be positive")
    if len(budgets) < 2:
        raise ValueError("provide at least two distinct --budget-ms values")
    if not 1 <= args.threads <= 12:
        raise ValueError("--threads must be in 1..12")
    if not 4 <= args.hash_mb <= 1024:
        raise ValueError("--hash-mb must be in 4..1024")
    if not 1 <= args.depth <= 94:
        raise ValueError("--depth must be in 1..94")
    if args.max_positions < 1:
        raise ValueError("--max-positions must be positive")
    if args.min_ply < 1 or (
        args.max_ply is not None and args.max_ply < args.min_ply
    ):
        raise ValueError("ply range is invalid")

    requested_plies = set(args.ply or ())
    positions = [
        item
        for item in replayed.plies
        if item.player in selected_players
        and (args.side != "engine" or not actor_labels_present or item.actor == "engine")
        and item.ply >= args.min_ply
        and (args.max_ply is None or item.ply <= args.max_ply)
        and (not requested_plies or item.ply in requested_plies)
        and len(legal_moves(item.state)) > 1
    ]
    if requested_plies:
        missing = requested_plies - {item.ply for item in positions}
        if missing:
            raise ValueError(
                "requested plies are absent, on the other side, or forced: "
                + ", ".join(map(str, sorted(missing)))
            )
        if len(positions) > args.max_positions:
            raise ValueError(
                "requested plies exceed --max-positions; raise the safety cap explicitly"
            )
    positions = positions[:args.max_positions]
    if not positions:
        raise ValueError("game contains no non-forced positions for the selected side")

    library = Path(args.library).resolve()
    if not library.is_file():
        raise FileNotFoundError(f"native search DLL not found: {library}")
    library_sha256 = hashlib.sha256(library.read_bytes()).hexdigest()
    entry_bytes = native_tt_entry_bytes(library)
    if args.threads == 1:
        hash_power = hash_power_for_megabytes(
            args.hash_mb,
            entry_bytes=entry_bytes,
        )
        searcher = NativeSearch(library, hash_power=hash_power, persistent=True)
    else:
        searcher = ParallelNativeSearch(
            library,
            threads=args.threads,
            hash_mb=args.hash_mb,
        )
    analysis_native_search_abi = searcher.abi_version

    position_reports: list[dict] = []
    with searcher:
        for item in positions:
            observations: list[SearchObservation] = []
            child_traces: dict[str, dict] = {}
            legal = legal_moves(item.state)
            for budget in budgets:
                searcher.clear()
                result = searcher.search(
                    item.state,
                    depth=args.depth,
                    time_ms=budget,
                    no_progress_plies=analysis_rules.no_progress_plies,
                    repetition_limit=analysis_rules.repetition_limit,
                    history=item.history,
                )
                observation = SearchObservation(
                    budget_ms=budget,
                    move=result.move.notation,
                    score=result.score,
                    depth=result.depth,
                    nodes=result.nodes,
                    elapsed_ms=result.elapsed_ms,
                    pv=tuple(move.notation for move in result.pv),
                    root_moves=tuple(
                        RootMoveObservation(
                            move=root.move.notation,
                            score=root.score,
                            depth=root.depth,
                            nodes=root.nodes,
                            pv=tuple(move.notation for move in root.pv),
                        )
                        for root in result.root_moves
                    ),
                    common_depth=(
                        result.common_depth
                        if result.common_depth is not None
                        else result.depth
                    ),
                    selective_root=result.selective_root,
                )
                observations.append(observation)
                for root in result.root_moves:
                    if root.move.notation not in child_traces:
                        root_move = next(
                            move for move in legal
                            if move.notation == root.move.notation
                        )
                        child_traces[root.move.notation] = _evaluation_trace_payload(
                            apply_move(item.state, root_move, validate=False),
                            item.player,
                        )
                if observation.move not in child_traces:
                    chosen = next(
                        move for move in legal if move.notation == observation.move
                    )
                    child_traces[observation.move] = _evaluation_trace_payload(
                        apply_move(item.state, chosen, validate=False),
                        item.player,
                    )

            played_trace = _evaluation_trace_payload(item.child, item.player)
            longest = max(observations, key=lambda value: value.budget_ms)
            long_terms = child_traces[longest.move]["relative_terms"]
            played_terms = played_trace["relative_terms"]
            recorded_settings = dict(record.engine)
            if item.engine is not None:
                recorded_settings.update(item.engine)
            provenance_issues = engine_provenance_issues(item.engine)
            provenance_mismatches = engine_provenance_mismatches(
                recorded_settings,
                library_sha256=library_sha256,
                native_search_abi=analysis_native_search_abi,
                threads=args.threads,
                hash_mb=args.hash_mb,
                rules_profile=args.rules_profile,
                budget_ms=budgets[0],
            )
            classification = (
                "settings-or-version-mismatch"
                if provenance_mismatches
                else classify_search_observations(item.notation, observations)
            )
            position_reports.append(
                {
                    "ply": item.ply,
                    "player": player_name(item.player),
                    "position": format_position(item.state),
                    "reversible_plies": item.state.reversible_plies,
                    "legal_moves": len(legal),
                    "played_move": item.notation,
                    "recorded_actor": item.actor,
                    "recorded_engine": item.engine,
                    "provenance_complete": not provenance_issues,
                    "provenance_issues": provenance_issues,
                    "provenance_mismatches": provenance_mismatches,
                    "classification": classification,
                    "root_static": _evaluation_trace_payload(
                        item.state,
                        item.player,
                    ),
                    "played_child_static": played_trace,
                    "candidate_child_static": child_traces,
                    "long_vs_played_static_term_delta": {
                        term: long_terms[term] - played_terms[term]
                        for term in played_terms
                    },
                    "searches": [asdict(observation) for observation in observations],
                }
            )

    report = {
        "format": GAME_ANALYSIS_FORMAT,
        "game_id": record.game_id,
        "source_game": str(Path(args.game).resolve()),
        "library": str(library),
        "library_sha256": library_sha256,
        "native_search_abi": analysis_native_search_abi,
        "threads": args.threads,
        "hash_mb": args.hash_mb,
        "depth_limit": args.depth,
        "rules_profile": args.rules_profile,
        "repetition_limit": analysis_rules.repetition_limit,
        "no_progress_plies": analysis_rules.no_progress_plies,
        "budgets_ms": budgets,
        "source_record_provenance_complete": all(
            item["provenance_complete"] for item in position_reports
        ),
        "positions": position_reports,
    }
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print("GAME_ANALYSIS " + encoded)
    return 0


def command_build_middlegame_corpus(args: argparse.Namespace) -> int:
    metadata = build_middlegame_corpus(
        args.analysis,
        args.output,
        min_pieces=args.min_pieces,
        max_pieces=args.max_pieces,
        stable_only=args.stable_only,
    )
    print(
        "MIDDLEGAME_CORPUS_RESULT "
        + json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        flush=True,
    )
    return 0


def command_build_eval_corpus(args: argparse.Namespace) -> int:
    paths = args.tablebase or [
        "build/tb4_np80.bin",
        "build/tb5_np80.compact.bin",
        "build/tb6_np80.compact.bin",
    ]
    metadata = build_exact_wdl_corpus(
        paths,
        args.output,
        samples_per_outcome=args.samples_per_outcome,
        seed=args.seed,
        validation_percent=args.validation_percent,
        verify_checksums=not args.skip_checksum,
    )
    print(
        "EVAL_CORPUS_RESULT "
        + json.dumps(metadata, sort_keys=True),
        flush=True,
    )
    return 0


def command_fit_eval(args: argparse.Namespace) -> int:
    report = audit_and_fit_corpus(
        args.corpus,
        args.output,
        ridge=args.ridge,
    )
    print("EVAL_FIT_RESULT " + json.dumps(report, sort_keys=True), flush=True)
    return 0
