"""Command-line interface for verification, analysis, and human play."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import sys

from .core import (
    BLACK,
    RED,
    DEFAULT_RULES,
    Rules,
    apply_move,
    format_board,
    format_position,
    initial_state,
    legal_moves,
    parse_position,
    perft,
    terminal_status,
)
from .exact import ExactSolver
from .arena import compare_modes_against_shallow_opponent, paired_match
from .audit_rules import IndependentRulesAuditor
from .verify import verify_one_vs_one
from .native_verify import verify_native_moves
from .native_tablebase import NativeTablebase
from .native import (
    NativeSearch,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
    project_native_library,
)
from .parallel_native import ParallelNativeSearch
from .eval import trace_evaluation
from .eval_corpus import build_exact_wdl_corpus
from .eval_tune import audit_and_fit_corpus
from .middlegame_corpus import build_middlegame_corpus
from .game_analysis import (
    GAME_ANALYSIS_FORMAT,
    EXTERNAL_NO_REPETITION_RULES,
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
from .ranked_tablebase import RankedTablebase
from .provenance import DEFAULT_MANIFEST_PATH
from .policy_value import EmpiricalPolicyValueModel
from .selfplay import train_self_play
from .tb4_verify import verify_ranked_tablebase
from .proof import (
    EndgameOracle,
    NonLossProver,
    ProofBudgetExceeded,
    load_proof_strategy,
    proof_no_progress_plies,
    write_certificate,
)
from .search import Engine, Mode, SearchLimits, TimeManager


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
    _set_windows_process_priority(0x00004000)
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
    from .sprt import SPRTResult

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


def _player(value: str) -> int:
    normalized = value.lower()
    if normalized in ("black", "b", "ดำ"):
        return BLACK
    if normalized in ("red", "r", "แดง"):
        return RED
    raise argparse.ArgumentTypeError("use black or red")


def _print_result(result) -> None:
    pv = " ".join(move.notation for move in result.pv)
    print(f"move: {result.move.notation}")
    print(f"score: {result.score}")
    exact = result.bound.exact_outcome
    if exact is not None:
        wdl_text = exact.name
    elif result.bound.lower == -1 and result.bound.upper == 1:
        wdl_text = "UNKNOWN"
    else:
        wdl_text = f"{result.bound.lower.name}..{result.bound.upper.name}"
    print(f"wdl: {wdl_text}")
    if result.proof_strategy_used:
        print("proof strategy: verified safe move set")
    estimate = result.policy_value
    print(
        f"self-play W/D/L: {estimate.win:.3f}/{estimate.draw:.3f}/"
        f"{estimate.loss:.3f}  policy: {estimate.policy:.3f}  "
        f"effective evidence: {estimate.samples:g}"
    )
    if result.distance.dtm is not None:
        print(f"DTM: {result.distance.dtm} plies (exact under no-progress rules)")
    elif result.distance.dtr is not None:
        print(
            f"DTR: {result.distance.dtr} plies "
            "(exact to reset/terminal under no-progress rules)"
        )
    else:
        print("endgame distance: unknown")
    print(
        f"depth: {result.depth}  nodes: {result.nodes}  "
        f"tablebase hits: {result.tablebase_hits}  time: {result.elapsed_ms} ms"
    )
    print(f"pv: {pv}")


def command_perft(args: argparse.Namespace) -> int:
    state = _get_state(args)
    for depth in range(1, args.depth + 1):
        print(f"depth {depth}: {perft(state, depth)}")
    return 0


def command_bestmove(args: argparse.Namespace) -> int:
    state = _get_state(args)
    engine = _get_engine(args)
    if (
        engine.proof_strategy is not None and
        state.turn != engine.proof_strategy.root_player
    ):
        raise ValueError("proof strategy belongs to the other side")
    result = engine.search(
        state,
        SearchLimits(args.depth, args.time_ms, args.win_margin),
        mode=args.mode,
    )
    print(format_board(state))
    _print_result(result)
    return 0


def command_play(args: argparse.Namespace) -> int:
    state = _get_state(args)
    engine = _get_engine(args)
    if (
        engine.proof_strategy is not None and
        args.human == engine.proof_strategy.root_player
    ):
        raise ValueError("proof strategy belongs to the human side, not the engine")
    history: Counter = Counter({state.position_key: 1})
    while True:
        print()
        print(format_board(state))
        status = terminal_status(
            state,
            repetition_count=history[state.position_key],
            rules=engine.rules,
        )
        if status.terminal:
            if status.winner is None:
                print(f"draw: {status.reason}")
            else:
                winner = "BLACK" if status.winner == BLACK else "RED"
                print(f"winner: {winner} ({status.reason})")
            return 0

        moves = legal_moves(state)
        if state.turn == args.human:
            print("legal moves:", " ".join(move.notation for move in moves))
            entered = input("your move (or quit): ").strip().lower()
            if entered in ("q", "quit", "exit"):
                return 0
            move = next((move for move in moves if move.notation.lower() == entered), None)
            if move is None:
                print("invalid move")
                continue
        else:
            result = engine.search(
                state,
                SearchLimits(args.depth, args.time_ms, args.win_margin),
                mode=args.mode,
                history=history,
            )
            move = result.move
            _print_result(result)
        state = apply_move(state, move, validate=False)
        history[state.position_key] += 1


def command_solve(args: argparse.Namespace) -> int:
    if not args.position:
        raise SystemExit("solve requires --position")
    state = parse_position(args.position, reversible_plies=args.clock)
    rules = DEFAULT_RULES.__class__(
        name=DEFAULT_RULES.name + "-exact",
        starting_player=DEFAULT_RULES.starting_player,
        repetition_limit=None,
        no_progress_plies=args.no_progress,
    )
    result = ExactSolver(rules, max_states=args.max_states).solve(state)
    print(format_board(state))
    print(f"outcome for side-to-move: {result.outcome.name}")
    print(f"distance: {result.distance if result.distance is not None else '-'}")
    print(f"states: {result.states}")
    print("best moves:", " ".join(move.notation for move in result.best_moves) or "-")
    return 0


def command_arena(args: argparse.Namespace) -> int:
    score = paired_match(
        pairs=args.pairs,
        mode_a=args.mode_a,
        mode_b=args.mode_b,
        limits=SearchLimits(args.depth, args.time_ms, args.win_margin),
        opening_plies=args.opening_plies,
        seed=args.seed,
        exact_piece_limit=args.exact_pieces,
        exact_max_states=args.max_states,
    )
    print(f"A ({args.mode_a}) wins: {score.a_wins}")
    print(f"draws: {score.draws}")
    print(f"B ({args.mode_b}) wins: {score.b_wins}")
    for number, game in enumerate(score.games, 1):
        winner = "draw" if game.winner is None else ("black" if game.winner == BLACK else "red")
        print(f"game {number}: {winner}, {game.reason}, {len(game.moves)} plies")
    return 0


def command_train_selfplay(args: argparse.Namespace) -> int:
    state = _get_state(args)
    engine = _get_engine(args)
    summary = train_self_play(
        engine.policy_value_model,
        engine,
        SearchLimits(args.depth, args.time_ms, args.win_margin),
        games=args.games,
        rules=engine.rules,
        seed=args.seed,
        exploration_rate=args.exploration_rate,
        exploration_score_margin=args.exploration_score_margin,
        temperature=args.temperature,
        max_game_plies=args.max_game_plies,
        start=state,
    )
    engine.policy_value_model.save(args.output_model)
    print(
        f"self-play games: {summary.games}  black/draw/red: "
        f"{summary.black_wins}/{summary.draws}/{summary.red_wins}"
    )
    print(
        f"new samples: {summary.samples}  plies: {summary.plies}  "
        f"truncated (not labeled): {summary.truncated}"
    )
    print(
        f"model totals: {engine.policy_value_model.games} games, "
        f"{engine.policy_value_model.samples} samples"
    )
    print(f"model: {args.output_model}")
    return 0


def command_verify_endgames(args: argparse.Namespace) -> int:
    result = verify_one_vs_one(
        no_progress_plies=args.no_progress,
        max_states=args.max_states,
    )
    print("verified material: one piece vs one piece")
    print(f"root positions: {result.positions}")
    print(f"side-to-move W/D/L: {result.wins}/{result.draws}/{result.losses}")
    print(f"unique solved states: {result.solved_states}")
    print(f"time: {result.elapsed_ms} ms")
    return 0


def command_gauntlet(args: argparse.Namespace) -> int:
    score = compare_modes_against_shallow_opponent(
        pairs=args.pairs,
        mode_a=args.mode_a,
        mode_b=args.mode_b,
        challenger_limits=SearchLimits(args.depth, args.time_ms, args.win_margin),
        opponent_limits=SearchLimits(args.opponent_depth, args.opponent_time_ms),
        opening_plies=args.opening_plies,
        seed=args.seed,
        exact_piece_limit=args.exact_pieces,
        exact_max_states=args.max_states,
        opponent_error_rate=args.opponent_error_rate,
        opponent_temperature=args.opponent_temperature,
    )
    print(
        f"against best/depth-{args.opponent_depth} opponent "
        f"with error rate {args.opponent_error_rate:.1%}"
    )
    print(
        f"A ({args.mode_a}) W/D/L: "
        f"{score.mode_a.wins}/{score.mode_a.draws}/{score.mode_a.losses}"
    )
    print(
        f"B ({args.mode_b}) W/D/L: "
        f"{score.mode_b.wins}/{score.mode_b.draws}/{score.mode_b.losses}"
    )
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
    from .native_benchmark import compare_native_libraries

    report = compare_native_libraries(
        args.candidate_library,
        args.baseline_library,
        count=args.cases,
        depth=args.depth,
        repetitions=args.repetitions,
        seed=args.seed,
        hash_power=args.search_hash_power,
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
    from .native_benchmark import generate_native_benchmark_cases

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


def command_verify_tablebase(args: argparse.Namespace) -> int:
    result = verify_ranked_tablebase(
        args.tablebase,
        no_progress_plies=args.no_progress,
        samples=args.samples,
        seed=args.seed,
        max_states=args.max_states,
        tactical=args.tactical,
        captures_only=args.captures_only,
        min_captures=args.min_captures,
    )
    print(f"{result.piece_count}-piece positions compared: {result.samples}")
    print(f"sample W/D/L: {result.wins}/{result.draws}/{result.losses}")
    print(f"unique Python oracle states: {result.oracle_states}")
    print("ranked tablebase differential verification: PASS")
    return 0


def command_verify_tablebase_provenance(args: argparse.Namespace) -> int:
    for path in args.tablebase:
        with RankedTablebase(path) as tablebase:
            binding = tablebase.verify_provenance(args.manifest)
            print(
                f"{binding.piece_count}-piece tablebase provenance: PASS "
                f"({binding.sha256})"
            )
    print("ruleset, generator source, and tablebase SHA-256 bindings: PASS")
    return 0


def _verify_requested_provenance(
    tablebase: RankedTablebase,
    args: argparse.Namespace,
) -> None:
    if getattr(args, "verify_tablebase_provenance", False):
        tablebase.verify_provenance(
            getattr(args, "tablebase_provenance_manifest", None)
        )


def _open_proof_oracle(
    args: argparse.Namespace,
    no_progress_plies: int,
) -> tuple[EndgameOracle, NativeTablebase | None, list[RankedTablebase]]:
    ranked_paths = args.ranked_tablebase or []
    if isinstance(ranked_paths, str):
        ranked_paths = [ranked_paths]
    ranked: list[RankedTablebase] = []
    try:
        for path in ranked_paths:
            tablebase = RankedTablebase(path)
            try:
                _verify_requested_provenance(tablebase, args)
                if tablebase.no_progress_plies != no_progress_plies:
                    raise ValueError(
                        "ranked tablebase no-progress rule mismatch"
                    )
            except Exception:
                tablebase.close()
                raise
            ranked.append(tablebase)
    except Exception:
        for tablebase in ranked:
            tablebase.close()
        raise
    native = None
    if args.native_tablebase or ranked:
        native = NativeTablebase(
            args.native_library,
            no_progress_plies=no_progress_plies,
            hash_power=args.native_hash_power,
        )
    return (
        EndgameOracle(native=native, ranked_tablebases=ranked),
        native,
        ranked,
    )


def command_prove_nonloss(args: argparse.Namespace) -> int:
    state = parse_position(args.position, reversible_plies=args.clock)
    rules = Rules(
        name="thai-makhos-proof",
        starting_player=DEFAULT_RULES.starting_player,
        repetition_limit=None,
        no_progress_plies=args.no_progress,
    )
    oracle, native, ranked = _open_proof_oracle(args, args.no_progress)
    try:
        prover = NonLossProver(
            rules,
            oracle,
            node_budget=args.node_budget,
            collect_all_choices=args.all_safe_choices,
        )
        try:
            certificate, stats = prover.prove(state, args.root_player)
        except (ProofBudgetExceeded, RecursionError) as error:
            print("result: UNKNOWN")
            print(str(error))
            return 2
        if certificate is None:
            print("result: FORCED LOSS")
            print(f"expanded nodes: {stats.expanded}")
            return 1
        print("result: PROVEN NON-LOSS")
        print(f"expanded nodes: {stats.expanded}")
        print(f"certificate nodes: {stats.certificate_nodes}")
        if args.certificate:
            write_certificate(certificate, args.certificate)
            print(f"certificate: {args.certificate}")
        return 0
    finally:
        for tablebase in ranked:
            tablebase.close()
        if native is not None:
            native.close()


def command_check_proof(args: argparse.Namespace) -> int:
    no_progress = proof_no_progress_plies(args.certificate)
    oracle, native, ranked = _open_proof_oracle(args, no_progress)
    try:
        rules_auditor = (
            IndependentRulesAuditor() if args.independent_rules_audit else None
        )
        strategy = load_proof_strategy(
            args.certificate,
            oracle,
            rules_auditor=rules_auditor,
        )
        checked = strategy.checked_nodes
        print(f"certificate nodes checked: {checked}")
        if rules_auditor is not None:
            print("independent rules audit: PASS")
        print("non-loss proof certificate: PASS")
        close = getattr(strategy, "close", None)
        if close is not None:
            close()
        return 0
    finally:
        for tablebase in ranked:
            tablebase.close()
        if native is not None:
            native.close()


def _get_state(args: argparse.Namespace):
    if getattr(args, "position", None):
        return parse_position(args.position, reversible_plies=getattr(args, "clock", 0))
    return initial_state(args.first)


def _get_engine(args: argparse.Namespace) -> Engine:
    rules = Rules(
        name=DEFAULT_RULES.name,
        starting_player=DEFAULT_RULES.starting_player,
        repetition_limit=DEFAULT_RULES.repetition_limit,
        no_progress_plies=getattr(
            args, "no_progress", DEFAULT_RULES.no_progress_plies
        ),
    )
    native = None
    native_search = None
    ranked: list[RankedTablebase] = []
    ranked_paths = getattr(args, "ranked_tablebase", None) or []
    if isinstance(ranked_paths, str):
        ranked_paths = [ranked_paths]
    try:
        for ranked_path in ranked_paths:
            tablebase = RankedTablebase(
                ranked_path,
                verify_checksum=getattr(
                    args, "verify_tablebase_checksum", False
                ),
            )
            try:
                _verify_requested_provenance(tablebase, args)
            except Exception:
                tablebase.close()
                raise
            ranked.append(tablebase)
            print(
                f"ranked {tablebase.piece_count}-piece tablebase ready: "
                f"{tablebase.total_states:,} states"
            )
    except Exception:
        for tablebase in ranked:
            tablebase.close()
        raise
    if (
        getattr(args, "native_tablebase", False) or
        ranked or
        getattr(args, "proof_strategy", None)
    ):
        native = NativeTablebase(
            args.native_library,
            no_progress_plies=rules.no_progress_plies,
            hash_power=args.native_hash_power,
        )
        print(
            f"native 3-piece tablebase ready: {native.state_count:,} states, "
            f"{native.root_count:,} roots"
        )
    if not getattr(args, "python_search", False):
        native_library = Path(args.native_library)
        if native_library.is_file():
            native_search = NativeSearch(
                native_library,
                hash_power=getattr(args, "search_hash_power", 20),
            )
    model_path = getattr(args, "policy_model", None)
    if model_path:
        model = EmpiricalPolicyValueModel.load(model_path)
        print(
            f"policy-value model ready: {model.games} games, "
            f"{model.samples} samples"
        )
    else:
        model = EmpiricalPolicyValueModel()
    proof_strategy = None
    proof_path = getattr(args, "proof_strategy", None)
    if proof_path:
        proof_strategy = load_proof_strategy(
            proof_path,
            EndgameOracle(native=native, ranked_tablebases=ranked),
        )
        print(
            f"proof strategy ready: {proof_strategy.checked_nodes:,} "
            "verified nodes"
        )
    return Engine(
        rules=rules,
        exact_piece_limit=args.exact_pieces,
        exact_max_states=args.max_states,
        native_tablebase=native,
        ranked_tablebases=ranked,
        policy_value_model=model,
        distance_max_nodes=getattr(args, "distance_nodes", 0),
        proof_strategy=proof_strategy,
        native_search=native_search,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="makhos", description="Thai Makhos reference engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    perft_parser = subparsers.add_parser("perft", help="count legal move-tree leaves")
    perft_parser.add_argument("--depth", type=int, default=5)
    perft_parser.add_argument("--first", type=_player, default=BLACK)
    perft_parser.add_argument("--position")
    perft_parser.add_argument("--clock", type=int, default=0)
    perft_parser.set_defaults(func=command_perft)

    best_parser = subparsers.add_parser("bestmove", help="search the initial position")
    _add_search_arguments(best_parser)
    best_parser.set_defaults(func=command_bestmove)

    play_parser = subparsers.add_parser("play", help="play against the engine")
    _add_search_arguments(play_parser)
    play_parser.add_argument("--human", type=_player, default=RED)
    play_parser.set_defaults(func=command_play)

    solve_parser = subparsers.add_parser("solve", help="exactly solve a small position")
    solve_parser.add_argument("--position", required=True)
    solve_parser.add_argument("--clock", type=int, default=0)
    solve_parser.add_argument("--no-progress", type=int, default=80)
    solve_parser.add_argument("--max-states", type=int, default=1_000_000)
    solve_parser.set_defaults(func=command_solve)

    arena_parser = subparsers.add_parser("arena", help="run paired engine matches")
    arena_parser.add_argument("--pairs", type=int, default=1)
    arena_parser.add_argument("--mode-a", choices=[mode.value for mode in Mode], default=Mode.WIN.value)
    arena_parser.add_argument("--mode-b", choices=[mode.value for mode in Mode], default=Mode.BEST.value)
    arena_parser.add_argument("--depth", type=int, default=4)
    arena_parser.add_argument("--time-ms", type=int)
    arena_parser.add_argument("--win-margin", type=int, default=0)
    arena_parser.add_argument("--opening-plies", type=int, default=4)
    arena_parser.add_argument("--seed", type=int, default=1)
    arena_parser.add_argument("--exact-pieces", type=int, default=2)
    arena_parser.add_argument("--max-states", type=int, default=250_000)
    arena_parser.set_defaults(func=command_arena)

    train_parser = subparsers.add_parser(
        "train-selfplay", help="train a policy-value model from proof-guided self-play"
    )
    _add_search_arguments(train_parser)
    train_parser.add_argument("--games", type=int, default=10)
    train_parser.add_argument("--seed", type=int, default=1)
    train_parser.add_argument("--exploration-rate", type=float, default=0.15)
    train_parser.add_argument("--exploration-score-margin", type=int, default=50)
    train_parser.add_argument("--temperature", type=float, default=1.0)
    train_parser.add_argument("--max-game-plies", type=int, default=300)
    train_parser.add_argument("--output-model", required=True)
    train_parser.set_defaults(func=command_train_selfplay)

    verify_parser = subparsers.add_parser(
        "verify-endgames", help="exhaustively classify all one-vs-one positions"
    )
    verify_parser.add_argument("--no-progress", type=int, default=80)
    verify_parser.add_argument("--max-states", type=int, default=2_000_000)
    verify_parser.set_defaults(func=command_verify_endgames)

    gauntlet_parser = subparsers.add_parser(
        "gauntlet", help="compare policies against the same shallower opponent"
    )
    gauntlet_parser.add_argument("--pairs", type=int, default=2)
    gauntlet_parser.add_argument("--mode-a", choices=[mode.value for mode in Mode], default=Mode.WIN.value)
    gauntlet_parser.add_argument("--mode-b", choices=[mode.value for mode in Mode], default=Mode.BEST.value)
    gauntlet_parser.add_argument("--depth", type=int, default=4)
    gauntlet_parser.add_argument("--opponent-depth", type=int, default=2)
    gauntlet_parser.add_argument("--time-ms", type=int)
    gauntlet_parser.add_argument("--opponent-time-ms", type=int)
    gauntlet_parser.add_argument("--opponent-error-rate", type=float, default=0.15)
    gauntlet_parser.add_argument("--opponent-temperature", type=float, default=100.0)
    gauntlet_parser.add_argument("--win-margin", type=int, default=0)
    gauntlet_parser.add_argument("--opening-plies", type=int, default=4)
    gauntlet_parser.add_argument("--seed", type=int, default=1)
    gauntlet_parser.add_argument("--exact-pieces", type=int, default=2)
    gauntlet_parser.add_argument("--max-states", type=int, default=250_000)
    gauntlet_parser.set_defaults(func=command_gauntlet)

    native_parser = subparsers.add_parser(
        "verify-native", help="compare native legal moves with the Python reference"
    )
    native_parser.add_argument(
        "--executable", default="build/makhos_native.exe"
    )
    native_parser.add_argument("--samples", type=int, default=200)
    native_parser.add_argument("--exact-samples", type=int, default=10)
    native_parser.add_argument("--exact-no-progress", type=int, default=8)
    native_parser.add_argument("--seed", type=int, default=0x4D414B484F53)
    native_parser.set_defaults(func=command_verify_native)

    benchmark_parser = subparsers.add_parser(
        "bench-native",
        help="compare two native-search DLLs on deterministic fixed-depth positions",
    )
    benchmark_parser.add_argument(
        "--candidate-library", default="build/makhos_native.dll"
    )
    benchmark_parser.add_argument(
        "--baseline-library", default="build/makhos_native_lmr_control.dll"
    )
    benchmark_parser.add_argument("--cases", type=int, default=24)
    benchmark_parser.add_argument("--depth", type=int, default=14)
    benchmark_parser.add_argument("--repetitions", type=int, default=2)
    benchmark_parser.add_argument("--seed", type=int, default=0x4D414B484F53)
    benchmark_parser.add_argument("--search-hash-power", type=int, default=18)
    benchmark_parser.set_defaults(func=command_bench_native)

    profile_parser = subparsers.add_parser(
        "profile-native",
        help="aggregate ABI-6 native-search telemetry on deterministic positions",
    )
    profile_parser.add_argument(
        "--library", default="build/makhos_native_telemetry_candidate.dll"
    )
    profile_parser.add_argument("--cases", type=int, default=96)
    profile_parser.add_argument("--depth", type=int, default=15)
    profile_parser.add_argument("--seed", type=int, default=0x4D414B484F53)
    profile_parser.add_argument("--search-hash-power", type=int, default=17)
    profile_parser.set_defaults(func=command_profile_native)

    eval_corpus_parser = subparsers.add_parser(
        "build-eval-corpus",
        help="sample a balanced quiet-position corpus from exact tablebases",
    )
    eval_corpus_parser.add_argument(
        "--tablebase",
        action="append",
        default=None,
        help="ranked tablebase path; repeat for 4/5/6 pieces",
    )
    eval_corpus_parser.add_argument(
        "--output",
        default="corpora/exact_wdl_eval_v1.jsonl",
    )
    eval_corpus_parser.add_argument(
        "--samples-per-outcome",
        type=int,
        default=1000,
    )
    eval_corpus_parser.add_argument("--seed", type=int, default=20260910)
    eval_corpus_parser.add_argument(
        "--validation-percent",
        type=int,
        default=20,
    )
    eval_corpus_parser.add_argument(
        "--skip-checksum",
        action="store_true",
        help="skip the full read-only FNV integrity scan",
    )
    eval_corpus_parser.set_defaults(func=command_build_eval_corpus)

    eval_fit_parser = subparsers.add_parser(
        "fit-eval",
        help="fit handcrafted weights on train data and audit held-out WDL loss",
    )
    eval_fit_parser.add_argument(
        "--corpus",
        default="corpora/exact_wdl_eval_v1.jsonl",
    )
    eval_fit_parser.add_argument(
        "--output",
        default="build/exact_wdl_eval_fit_v1.json",
    )
    eval_fit_parser.add_argument("--ridge", type=float, default=1.0)
    eval_fit_parser.set_defaults(func=command_fit_eval)

    analyze_game_parser = subparsers.add_parser(
        "analyze-game",
        help="validate a GUI game record and compare search decisions by time budget",
    )
    analyze_game_parser.add_argument("--game", required=True)
    analyze_game_parser.add_argument(
        "--library",
        default=str(project_native_library()),
    )
    analyze_game_parser.add_argument(
        "--side",
        choices=("engine", "black", "red", "both"),
        default="engine",
    )
    analyze_game_parser.add_argument(
        "--rules-profile",
        choices=("project", "external-no-repetition"),
        default="project",
        help="draw-rule profile used for replay and search",
    )
    analyze_game_parser.add_argument(
        "--budget-ms",
        type=int,
        action="append",
        default=None,
        help="search budget; repeat for each comparison (default: 2000, 5000, 20000)",
    )
    analyze_game_parser.add_argument("--threads", type=int, default=1)
    analyze_game_parser.add_argument("--hash-mb", type=int, default=64)
    analyze_game_parser.add_argument("--depth", type=int, default=64)
    analyze_game_parser.add_argument(
        "--ply",
        type=int,
        action="append",
        help="analyse a specific recorded ply; repeat to select several",
    )
    analyze_game_parser.add_argument(
        "--max-positions",
        type=int,
        default=1,
        help="safety cap for expensive multi-budget analysis",
    )
    analyze_game_parser.add_argument("--min-ply", type=int, default=1)
    analyze_game_parser.add_argument("--max-ply", type=int)
    analyze_game_parser.add_argument("--output")
    analyze_game_parser.set_defaults(func=command_analyze_game)

    middlegame_corpus_parser = subparsers.add_parser(
        "build-middlegame-corpus",
        help="validate multi-budget game analyses into a search-stability corpus",
    )
    middlegame_corpus_parser.add_argument(
        "--analysis",
        action="append",
        required=True,
        help="GAME_ANALYSIS JSON report; repeat for multiple games or builds",
    )
    middlegame_corpus_parser.add_argument(
        "--output",
        default="corpora/middlegame_search_v1.jsonl",
    )
    middlegame_corpus_parser.add_argument("--min-pieces", type=int, default=8)
    middlegame_corpus_parser.add_argument("--max-pieces", type=int, default=24)
    middlegame_corpus_parser.add_argument(
        "--stable-only",
        action="store_true",
        help="keep only positions whose last two budgets select the same move",
    )
    middlegame_corpus_parser.set_defaults(func=command_build_middlegame_corpus)

    tablebase_parser = subparsers.add_parser(
        "verify-tablebase",
        help="compare a ranked tablebase with the Python exact solver",
    )
    tablebase_parser.add_argument("--tablebase", required=True)
    tablebase_parser.add_argument("--no-progress", type=int, required=True)
    tablebase_parser.add_argument("--samples", type=int, default=50)
    tablebase_parser.add_argument("--seed", type=int, default=0x54423457444C)
    tablebase_parser.add_argument("--max-states", type=int, default=5_000_000)
    tablebase_parser.add_argument("--tactical", action="store_true")
    tablebase_parser.add_argument(
        "--captures-only",
        action="store_true",
        help="sample forced-capture roots (useful for larger tablebases)",
    )
    tablebase_parser.add_argument(
        "--min-captures",
        type=int,
        default=0,
        help="require every legal root move to capture at least this many pieces",
    )
    tablebase_parser.set_defaults(func=command_verify_tablebase)

    provenance_parser = subparsers.add_parser(
        "verify-tablebase-provenance",
        help="verify committed rules, generator source, and tablebase SHA-256 bindings",
    )
    provenance_parser.add_argument(
        "--tablebase",
        action="append",
        required=True,
        help="accepted ranked tablebase file (repeat for each frontier)",
    )
    provenance_parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST_PATH),
    )
    provenance_parser.set_defaults(func=command_verify_tablebase_provenance)

    proof_parser = subparsers.add_parser(
        "prove-nonloss", help="build a bounded exact non-loss proof certificate"
    )
    proof_parser.add_argument("--position", required=True)
    proof_parser.add_argument("--clock", type=int, default=0)
    proof_parser.add_argument("--root-player", type=_player, default=BLACK)
    proof_parser.add_argument("--no-progress", type=int, default=80)
    proof_parser.add_argument("--node-budget", type=int, default=1_000_000)
    proof_parser.add_argument(
        "--all-safe-choices",
        action="store_true",
        help="retain every proven-safe engine move instead of the first one",
    )
    proof_parser.add_argument("--certificate")
    proof_parser.add_argument("--ranked-tablebase", action="append")
    proof_parser.add_argument("--native-tablebase", action="store_true")
    proof_parser.add_argument("--native-library", default=str(project_native_library()))
    proof_parser.add_argument("--native-hash-power", type=int, default=25)
    _add_tablebase_provenance_arguments(proof_parser)
    proof_parser.set_defaults(func=command_prove_nonloss)

    check_parser = subparsers.add_parser(
        "check-proof", help="independently verify a non-loss proof certificate"
    )
    check_parser.add_argument("--certificate", required=True)
    check_parser.add_argument("--ranked-tablebase", action="append")
    check_parser.add_argument("--native-tablebase", action="store_true")
    check_parser.add_argument("--native-library", default=str(project_native_library()))
    check_parser.add_argument("--native-hash-power", type=int, default=25)
    _add_tablebase_provenance_arguments(check_parser)
    check_parser.add_argument(
        "--independent-rules-audit",
        action="store_true",
        help=(
            "cross-check every proof edge with the standalone bitboard "
            "rules implementation"
        ),
    )
    check_parser.set_defaults(func=command_check_proof)

    uci_parser = subparsers.add_parser(
        "uci", help="run engine in UCI/UGI protocol mode for GUI integration"
    )
    _add_search_arguments(uci_parser)
    uci_parser.set_defaults(func=command_uci)

    gui_parser = subparsers.add_parser(
        "gui", help="launch interactive web GUI server in browser"
    )
    gui_parser.add_argument("--port", type=int, default=8000, help="HTTP server port")
    gui_parser.add_argument("--no-browser", action="store_true", help="do not open browser automatically")
    gui_parser.add_argument("--native-library", help="explicit opt-in native-search DLL")
    gui_parser.add_argument("--nnue-model", help="explicit NNUE model for the selected DLL")
    gui_parser.add_argument("--release-pointer", help="GUI release selection JSON")
    gui_parser.add_argument("--release-profile", choices=["nnue", "hce"])
    gui_parser.set_defaults(func=command_gui)

    sprt_parser = subparsers.add_parser(
        "sprt", help="run SPRT match (10s+0.1s) to test candidate evaluation tweak"
    )
    sprt_parser.add_argument("--pairs", type=int, default=10000, help="maximum game pairs to run")
    sprt_parser.add_argument("--elo0", type=float, default=0.0, help="H0 Elo bound")
    sprt_parser.add_argument("--elo1", type=float, default=2.0, help="H1 Elo bound")
    sprt_parser.add_argument("--time", type=float, default=10.0, help="initial time per player in seconds")
    sprt_parser.add_argument("--inc", type=float, default=0.1, help="increment per move in seconds")
    sprt_parser.add_argument("--seed", type=int, default=1, help="random opening seed")
    sprt_parser.add_argument("--opening-plies", type=int, default=6)
    sprt_parser.add_argument(
        "--max-game-plies", type=int, default=300,
        help="fail closed if either paired game is unfinished after this many plies",
    )
    sprt_parser.add_argument(
        "--dev-library", default="build/makhos_native.dll",
        help="candidate native-search DLL",
    )
    sprt_parser.add_argument(
        "--master-library", default="build/makhos_native_baseline.dll",
        help="accepted baseline native-search DLL",
    )
    sprt_parser.add_argument(
        "--dev-nnue-model",
        default=None,
        help="explicit NNUE model for the candidate DLL",
    )
    sprt_parser.add_argument(
        "--master-nnue-model",
        default=None,
        help="explicit NNUE model for the baseline DLL",
    )
    sprt_parser.add_argument(
        "--ranked-tablebase",
        action="append",
        default=None,
        help=(
            "ranked WDL tablebase used by both engines; repeat for 4/5/6 "
            "pieces (defaults to the production files when present)"
        ),
    )
    sprt_parser.add_argument(
        "--no-tablebase",
        action="store_true",
        help="disable production tablebases for a diagnostic match",
    )
    sprt_parser.add_argument("--search-hash-power", type=int, default=20)
    sprt_parser.add_argument(
        "--threads",
        type=int,
        choices=range(1, 13),
        default=1,
        help="Threads per engine (1..12)",
    )
    sprt_parser.add_argument(
        "--dev-threads",
        type=int,
        choices=range(1, 13),
        default=None,
        help="candidate Threads override; defaults to --threads",
    )
    sprt_parser.add_argument(
        "--master-threads",
        type=int,
        choices=range(1, 13),
        default=None,
        help="baseline Threads override; defaults to --threads",
    )
    sprt_parser.add_argument(
        "--hash-mb",
        type=int,
        default=None,
        help=(
            "total Hash budget per engine in MiB; defaults to 64 for "
            "multi-thread tests, while one-thread tests retain "
            "--search-hash-power compatibility"
        ),
    )
    sprt_parser.add_argument(
        "--selective-root",
        action="store_true",
        help="enable experimental selective root deepening for candidate only",
    )
    sprt_parser.add_argument(
        "--shared-tt",
        action="store_true",
        help="enable experimental shared TT for candidate Threads only",
    )
    sprt_parser.add_argument(
        "--root-alpha",
        action="store_true",
        help="candidate-only parallel root PVS with a shared alpha bound",
    )
    sprt_parser.add_argument(
        "--root-alpha-margin",
        type=int,
        default=32,
        help="initial root aspiration margin for --root-alpha",
    )
    sprt_parser.add_argument(
        "--root-alpha-min-depth",
        type=int,
        default=16,
        help="first root depth eligible for --root-alpha",
    )
    sprt_parser.add_argument(
        "--shared-tt-group-size",
        type=int,
        choices=range(2, 13),
        default=4,
        help="workers per shared-TT cluster (candidate only)",
    )
    sprt_parser.add_argument("--selective-reserve", type=float, default=0.60)
    sprt_parser.add_argument("--selective-candidates", type=int, default=4)
    sprt_parser.add_argument("--selective-margin", type=int, default=160)
    sprt_parser.add_argument(
        "--move-time-cap-ms",
        type=int,
        default=None,
        help="optional per-move cap for cheap screening only",
    )
    sprt_parser.add_argument(
        "--fixed-move-time-ms", type=int, default=None,
        help="fixed budget for every move instead of clock allocation; excludes --move-time-cap-ms",
    )
    sprt_parser.add_argument(
        "--persistent-search",
        action="store_true",
        help=(
            "reuse each engine's native TT across moves within a game; "
            "requires search ABI 3 for both DLLs"
        ),
    )
    sprt_parser.add_argument(
        "--parallel-games", type=int, choices=(1, 2), default=1,
        help="play both colours of each opening concurrently",
    )
    sprt_parser.add_argument(
        "--output",
        help="write the final configuration and pentanomial result as JSON",
    )
    sprt_parser.add_argument(
        "--resume",
        action="store_true",
        help="atomically checkpoint each completed pair and resume --output",
    )
    sprt_parser.add_argument(
        "--native-endgame",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="toggle native endgame search (C4) in SPRT engines (default: enabled)",
    )
    sprt_parser.add_argument(
        "--native-endgame-library",
        default=None,
        help="isolated C2/C3/C4 endgame DLL",
    )
    sprt_parser.set_defaults(func=command_sprt)

    return parser


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


def command_sprt(args: argparse.Namespace) -> int:
    from .sprt import run_sprt_match
    from .search import Engine
    from .core import DEFAULT_RULES
    from .workload_isolation import BatchWorkLease

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
                project_root = Path(__file__).resolve().parents[1]
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

                from .compact_tb3 import CompactTablebase, DEFAULT_ARTIFACT
                from .native_endgame import NativeEndgameTablebase

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
    print(
        "SPRT_CONFIG " + json.dumps(sprt_config, sort_keys=True),
        flush=True,
    )

    from .native_endgame_search import (
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
        return Engine(
            DEFAULT_RULES,
            exact_piece_limit=2,
            native_tablebase=native_tablebase,
            ranked_tablebases=ranked,
            native_search=make_native_search(
                dev_library,
                threads=candidate_threads,
                nnue_model=dev_nnue_model,
                selective_root=args.selective_root,
                root_alpha=args.root_alpha,
                shared_tt=args.shared_tt,
            ),
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
        project_root = Path(__file__).resolve().parents[1]
        with BatchWorkLease(project_root) as batch_lease:
            result = run_sprt_match(
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


def command_gui(args: argparse.Namespace) -> int:
    from .server import run_server
    run_server(
        port=args.port,
        open_browser=not args.no_browser,
        native_library=args.native_library,
        nnue_model=args.nnue_model,
        release_pointer=args.release_pointer,
        release_profile=args.release_profile,
    )
    return 0


def command_uci(args: argparse.Namespace) -> int:
    engine = _get_engine(args)
    state = _get_state(args)
    history: Counter = Counter({state.position_key: 1})

    while True:
        try:
            line = sys.stdin.readline()
        except (KeyboardInterrupt, EOFError):
            break
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        tokens = line.split()
        cmd = tokens[0].lower()

        if cmd in ("uci", "ugi"):
            print("id name ThaiMakhos 2.0")
            print("id author Pinggo")
            print("option name Mode type combo default win var win var best")
            print("uciok" if cmd == "uci" else "ugiok")
            sys.stdout.flush()
        elif cmd == "isready":
            print("readyok")
            sys.stdout.flush()
        elif cmd == "ucinewgame":
            state = _get_state(args)
            history = Counter({state.position_key: 1})
            engine._tt.clear()
            engine._move_hints.clear()
            if engine.native_search is not None and engine.native_search.persistent:
                engine.native_search.clear()
        elif cmd == "position":
            idx = 1
            if idx < len(tokens) and tokens[idx].lower() == "startpos":
                state = _get_state(args)
                history = Counter({state.position_key: 1})
                idx += 1
            elif idx < len(tokens) and tokens[idx].lower() in ("fen", "pos"):
                idx += 1
                if idx < len(tokens):
                    state = parse_position(tokens[idx])
                    history = Counter({state.position_key: 1})
                    idx += 1

            if idx < len(tokens) and tokens[idx].lower() == "moves":
                idx += 1
                while idx < len(tokens):
                    move_str = tokens[idx].lower()
                    moves = legal_moves(state)
                    found = next((m for m in moves if m.notation.lower() == move_str), None)
                    if found:
                        state = apply_move(state, found, validate=False)
                        history[state.position_key] += 1
                    idx += 1
        elif cmd == "go":
            depth = args.depth
            time_limit_ms = args.time_ms
            wtime = btime = winc = binc = movestogo = None

            i = 1
            while i < len(tokens):
                t = tokens[i].lower()
                if t == "depth" and i + 1 < len(tokens):
                    depth = int(tokens[i + 1])
                    i += 2
                elif t == "movetime" and i + 1 < len(tokens):
                    time_limit_ms = int(tokens[i + 1])
                    i += 2
                elif t == "wtime" and i + 1 < len(tokens):
                    wtime = int(tokens[i + 1]); i += 2
                elif t == "btime" and i + 1 < len(tokens):
                    btime = int(tokens[i + 1]); i += 2
                elif t == "winc" and i + 1 < len(tokens):
                    winc = int(tokens[i + 1]); i += 2
                elif t == "binc" and i + 1 < len(tokens):
                    binc = int(tokens[i + 1]); i += 2
                elif t == "movestogo" and i + 1 < len(tokens):
                    movestogo = int(tokens[i + 1]); i += 2
                else:
                    i += 1

            if time_limit_ms is None and (wtime is not None or btime is not None):
                my_time = wtime or 0
                my_inc = winc or 0
                if state.turn == BLACK:
                    my_time = btime or 0
                    my_inc = binc or 0
                time_limit_ms = TimeManager.allocate_time(
                    my_time_ms=my_time,
                    my_inc_ms=my_inc,
                    moves_to_go=movestogo,
                )

            limits = SearchLimits(depth=depth, time_ms=time_limit_ms, win_margin=args.win_margin)
            result = engine.search(state, limits, mode=args.mode, history=history)
            pv_str = " ".join(m.notation for m in result.pv)
            print(f"info depth {result.depth} score cp {result.score} nodes {result.nodes} time {result.elapsed_ms} pv {pv_str}")
            print(f"bestmove {result.move.notation}")
            sys.stdout.flush()
        elif cmd in ("quit", "exit"):
            break

    return 0


def _add_search_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--time-ms", type=int)
    parser.add_argument("--mode", choices=[mode.value for mode in Mode], default=Mode.BEST.value)
    parser.add_argument("--win-margin", type=int, default=0)
    parser.add_argument("--first", type=_player, default=BLACK)
    parser.add_argument("--position")
    parser.add_argument("--clock", type=int, default=0)
    parser.add_argument("--no-progress", type=int, default=80)
    parser.add_argument("--exact-pieces", type=int, default=2)
    parser.add_argument("--max-states", type=int, default=250_000)
    parser.add_argument("--policy-model", help="versioned JSON self-play model")
    parser.add_argument(
        "--proof-strategy",
        help="verified non-loss certificate restricting play to safe moves",
    )
    parser.add_argument(
        "--distance-nodes",
        type=int,
        default=0,
        help="on-demand WDL-only DTM/DTR nodes per candidate (0 = direct distances only)",
    )
    parser.add_argument("--native-tablebase", action="store_true")
    parser.add_argument("--native-library", default=str(project_native_library()))
    parser.add_argument("--native-hash-power", type=int, default=25)
    parser.add_argument(
        "--search-hash-power",
        type=int,
        default=20,
        help="native alpha-beta transposition table power (12..24)",
    )
    parser.add_argument(
        "--python-search",
        action="store_true",
        help="disable the native alpha-beta core",
    )
    parser.add_argument(
        "--ranked-tablebase",
        action="append",
        help="ranked tablebase file (repeat for 4-, 5-, and 6-piece files)",
    )
    parser.add_argument("--verify-tablebase-checksum", action="store_true")
    _add_tablebase_provenance_arguments(parser)


def _add_tablebase_provenance_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument(
        "--verify-tablebase-provenance",
        action="store_true",
        help="verify ruleset, generator-source, and complete-file SHA-256 bindings",
    )
    parser.add_argument(
        "--tablebase-provenance-manifest",
        default=str(DEFAULT_MANIFEST_PATH),
        help="committed tablebase provenance manifest",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
