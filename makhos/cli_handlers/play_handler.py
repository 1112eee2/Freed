"""Interactive play, GUI, UCI, and engine battle CLI command handlers."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

from ..arena import compare_modes_against_shallow_opponent, paired_match
from ..core import (
    BLACK,
    DEFAULT_RULES,
    RED,
    apply_move,
    format_board,
    legal_moves,
    parse_position,
    terminal_status,
)
from ..exact import ExactSolver
from ..search import SearchLimits
from ..selfplay import train_self_play
from .common import _get_engine, _get_state


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


def command_gui(args: argparse.Namespace) -> int:
    from ..server import run_server
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
    from ..uci import run_protocol
    return run_protocol(
        sys.stdin,
        sys.stdout,
        native_library=args.native_library,
        nnue_model=args.nnue_model,
        release_pointer=args.release_pointer,
        release_profile=args.release_profile,
    )
