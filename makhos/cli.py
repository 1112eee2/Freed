"""Command-line interface for verification, analysis, and human play.

Modularized router delegating command execution to makhos.cli_handlers while
preserving parser flags, defaults, help text, exit codes, and API exports.
"""

from __future__ import annotations

import argparse
import sys

from .core import BLACK, DEFAULT_RULES, RED
from .native import project_native_library
from .provenance import DEFAULT_MANIFEST_PATH
from .search import Mode

# Re-exports from handlers preserving compatibility
from .cli_handlers.common import (
    _get_engine,
    _get_state,
    _open_proof_oracle,
    _verify_requested_provenance,
)
from .cli_handlers.sprt_handler import (
    _load_sprt_checkpoint,
    _set_batch_process_priority,
    _set_windows_process_priority,
    _sprt_result_payload,
    _write_sprt_checkpoint,
    command_sprt,
)
from .cli_handlers.play_handler import (
    _player,
    _print_result,
    command_arena,
    command_bestmove,
    command_gauntlet,
    command_gui,
    command_play,
    command_solve,
    command_train_selfplay,
    command_uci,
)
from .cli_handlers.proof_handler import (
    command_check_proof,
    command_prove_nonloss,
    command_verify_endgames,
    command_verify_tablebase,
    command_verify_tablebase_provenance,
)
from .cli_handlers.analysis_handler import (
    _evaluation_trace_payload,
    command_analyze_game,
    command_bench_native,
    command_build_eval_corpus,
    command_build_middlegame_corpus,
    command_fit_eval,
    command_perft,
    command_profile_native,
    command_verify_native,
)


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
    benchmark_parser.add_argument(
        "--candidate-nnue-model",
        default=None,
        help="explicit NNUE model for the candidate library",
    )
    benchmark_parser.add_argument(
        "--baseline-nnue-model",
        default=None,
        help="explicit NNUE model for the baseline library",
    )
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
        "--nnue-model",
        help="explicit NNUE model for an NNUE candidate search library",
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
        "uci", help="serve the release engine over the UCI-style text protocol"
    )
    uci_parser.add_argument("--native-library", help="explicit native-search DLL instead of the release")
    uci_parser.add_argument("--nnue-model", help="explicit NNUE model for the selected DLL")
    uci_parser.add_argument("--release-pointer", help="GUI release selection JSON")
    uci_parser.add_argument("--release-profile", choices=["nnue", "hce"])
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
        "--tb-draw-cutoff",
        action="store_true",
        help=(
            "candidate-only: attach the match tablebases to the candidate's "
            "main search for exact-draw cutoffs (needs a MAKHOS_SEARCH_TB_DRAW "
            "library, tablebases and persistent search)"
        ),
    )
    sprt_parser.add_argument(
        "--games-dir",
        default=None,
        help=(
            "write every game of each completed pair as a replay-validated "
            "thai-makhos-game-v1 record into this directory"
        ),
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
