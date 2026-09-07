"""Build a resumable, game-split middlegame search-stability corpus.

The generator mixes accepted-engine fixed-depth play with explicitly tagged
random exploration so later analysis covers more than one principal line.  A
byte-preserved accepted DLL performs every teacher search.  Labels remain
observational search-stability signals and are never described as ground truth.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import (  # noqa: E402
    BLACK_KING,
    DEFAULT_RULES,
    EMPTY,
    RED_KING,
    apply_move,
    format_position,
    initial_state,
    legal_moves,
    parse_position,
    terminal_status,
)
from makhos.eval import trace_evaluation  # noqa: E402
from makhos.game_analysis import (  # noqa: E402
    GAME_ANALYSIS_FORMAT,
    load_game_record,
    player_name,
    replay_game,
)
from makhos.middlegame_corpus import build_middlegame_corpus  # noqa: E402
from makhos.native import (  # noqa: E402
    NativeSearch,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)


FORMAT = "thai-makhos-v5-acquisition-v1"
EXPECTED_ACCEPTED_SHA256 = (
    "FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD"
)
OPENING_SCHEDULE = (2, 4, 6, 8, 10, 12)
EXPLORATION_SCHEDULE = (0.05, 0.10, 0.20, 0.30)
PHASE_QUOTAS = {
    "13_to_16": 4,
    "9_to_12": 6,
    "5_to_8": 6,
}
STRICT_CLASSES = frozenset(("stable", "short-search-divergence"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_locked_json(path: Path, payload: dict) -> None:
    encoded = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise RuntimeError(f"locked acquisition configuration differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def phase_band(piece_count: int) -> str | None:
    if 13 <= piece_count <= 16:
        return "13_to_16"
    if 9 <= piece_count <= 12:
        return "9_to_12"
    if 5 <= piece_count <= 8:
        return "5_to_8"
    return None


def game_schedule(index: int, seed_start: int, games: int) -> dict:
    seed = seed_start + index - 1
    train_games = min(games - 1, math.ceil(games * 0.75))
    split = "train" if index <= train_games else "holdout"
    return {
        "index": index,
        "seed": seed,
        "split": split,
        "opening_plies": OPENING_SCHEDULE[(index - 1) % len(OPENING_SCHEDULE)],
        "exploration_rate": EXPLORATION_SCHEDULE[
            ((index - 1) // len(OPENING_SCHEDULE)) % len(EXPLORATION_SCHEDULE)
        ],
    }


def search_payload(result, *, depth_limit: int, library_sha256: str) -> dict:
    return {
        "search_backend": "native-single-fixed-depth-generation",
        "native_library_sha256": library_sha256,
        "depth_limit": depth_limit,
        "depth": result.depth,
        "nodes": result.nodes,
        "score": result.score,
        "pv": [move.notation for move in result.pv],
    }


def generate_game(
    schedule: dict,
    *,
    searcher: NativeSearch,
    library: Path,
    library_sha256: str,
    generation_depth: int,
    max_game_plies: int,
) -> dict:
    rng = random.Random(schedule["seed"])
    state = initial_state()
    history: Counter = Counter({state.position_key: 1})
    moves: list[dict] = []
    stop_reason = "max-game-plies"
    for ply in range(1, max_game_plies + 1):
        status = terminal_status(
            state,
            repetition_count=history[state.position_key],
            rules=DEFAULT_RULES,
        )
        if status.terminal:
            stop_reason = status.reason
            break
        legal = legal_moves(state)
        random_opening = ply <= schedule["opening_plies"]
        explore = (
            not random_opening
            and len(legal) > 1
            and rng.random() < schedule["exploration_rate"]
        )
        engine_metadata = None
        if random_opening or explore:
            move = rng.choice(legal)
            actor = "human"
        elif len(legal) == 1:
            move = legal[0]
            actor = "engine"
            engine_metadata = {
                "search_backend": "forced",
                "native_library_sha256": library_sha256,
            }
        else:
            searcher.clear()
            result = searcher.search(
                state,
                depth=generation_depth,
                time_ms=None,
                no_progress_plies=DEFAULT_RULES.no_progress_plies,
                repetition_limit=DEFAULT_RULES.repetition_limit,
                history=history,
            )
            move = result.move
            actor = "engine"
            engine_metadata = search_payload(
                result,
                depth_limit=generation_depth,
                library_sha256=library_sha256,
            )
        moves.append(
            {
                "ply": ply,
                "player": player_name(state.turn),
                "notation": move.notation,
                "actor": actor,
                "engine": engine_metadata,
            }
        )
        state = apply_move(state, move, validate=False)
        history[state.position_key] += 1
    else:
        stop_reason = "max-game-plies"

    return {
        "format": "thai-makhos-game-v1",
        "start_position": format_position(initial_state()),
        "start_reversible_plies": 0,
        "moves": moves,
        "final_position": format_position(state),
        "reversible_plies": state.reversible_plies,
        "engine": {
            "game_mode": "accepted-selfplay-synthetic-v5",
            "corpus_role": "regression-search-stability-only",
            "library": str(library.resolve()),
            "library_sha256": library_sha256,
            "generation_depth": generation_depth,
            "random_opening_plies": schedule["opening_plies"],
            "exploration_rate": schedule["exploration_rate"],
            "seed": schedule["seed"],
            "split": schedule["split"],
            "stop_reason": stop_reason,
        },
    }


def evenly_spaced(items: Sequence, count: int) -> list:
    if count <= 0 or not items:
        return []
    if len(items) <= count:
        return list(items)
    if count == 1:
        return [items[len(items) // 2]]
    indices = [round(offset * (len(items) - 1) / (count - 1)) for offset in range(count)]
    return [items[index] for index in indices]


def select_game_positions(replayed, *, samples_per_game: int) -> list:
    candidates = []
    for item in replayed.plies:
        legal = legal_moves(item.state)
        if len(legal) < 2:
            continue
        piece_count = sum(piece != EMPTY for piece in item.state.board)
        band = phase_band(piece_count)
        if band is None:
            continue
        king_count = sum(
            piece in (BLACK_KING, RED_KING) for piece in item.state.board
        )
        candidates.append(
            {
                "item": item,
                "band": band,
                "piece_count": piece_count,
                "king_count": king_count,
                "capture_available": bool(legal[0].is_capture),
            }
        )

    selected: list[dict] = []
    selected_plies: set[int] = set()
    for band, quota in PHASE_QUOTAS.items():
        available = [row for row in candidates if row["band"] == band]
        mixed = [row for row in available if row["king_count"] > 0]
        mixed_quota = min(len(mixed), math.ceil(quota / 2))
        for row in evenly_spaced(mixed, mixed_quota):
            if row["item"].ply not in selected_plies:
                selected.append(row)
                selected_plies.add(row["item"].ply)
        remaining = [
            row for row in available if row["item"].ply not in selected_plies
        ]
        for row in evenly_spaced(remaining, quota - mixed_quota):
            if row["item"].ply not in selected_plies:
                selected.append(row)
                selected_plies.add(row["item"].ply)

    if len(selected) < samples_per_game:
        remaining = [
            row for row in candidates if row["item"].ply not in selected_plies
        ]
        remaining.sort(
            key=lambda row: (
                row["king_count"] == 0,
                row["capture_available"] is False,
                hashlib.sha256(
                    f"{replayed.record.game_id}|{row['item'].ply}".encode("utf-8")
                ).hexdigest(),
            )
        )
        for row in remaining[: samples_per_game - len(selected)]:
            selected.append(row)
            selected_plies.add(row["item"].ply)
    selected.sort(key=lambda row: row["item"].ply)
    return selected[:samples_per_game]


def selection_key(row: dict) -> tuple[str, int]:
    item = row["item"]
    return format_position(item.state), item.state.reversible_plies


def build_selection_manifest(
    game_rows: Sequence[dict],
    *,
    samples_per_game: int,
) -> tuple[dict, dict[str, list]]:
    provisional: dict[str, list[dict]] = {}
    split_by_game: dict[str, str] = {}
    for row in game_rows:
        record = load_game_record(row["path"])
        replayed = replay_game(record, rules=DEFAULT_RULES)
        provisional[record.game_id] = select_game_positions(
            replayed,
            samples_per_game=samples_per_game,
        )
        split_by_game[record.game_id] = row["schedule"]["split"]
        row["game_id"] = record.game_id

    occurrences: dict[tuple[str, int], list[tuple[str, dict]]] = {}
    for game_id, rows in provisional.items():
        for row in rows:
            occurrences.setdefault(selection_key(row), []).append((game_id, row))

    cross_split_keys: set[tuple[str, int]] = set()
    owner: dict[tuple[str, int], tuple[str, int]] = {}
    within_split_duplicates = 0
    for key, rows in occurrences.items():
        splits = {split_by_game[game_id] for game_id, _row in rows}
        if len(splits) > 1:
            cross_split_keys.add(key)
            continue
        chosen_game, chosen_row = min(
            rows,
            key=lambda entry: (entry[0], entry[1]["item"].ply),
        )
        owner[key] = (chosen_game, chosen_row["item"].ply)
        within_split_duplicates += len(rows) - 1

    selected_by_game: dict[str, list] = {}
    manifest_games: list[dict] = []
    for row in game_rows:
        game_id = row["game_id"]
        selected_rows = [
            candidate
            for candidate in provisional[game_id]
            if selection_key(candidate) not in cross_split_keys
            and owner.get(selection_key(candidate))
            == (game_id, candidate["item"].ply)
        ]
        selected = [candidate["item"] for candidate in selected_rows]
        selected_by_game[game_id] = selected
        manifest_games.append(
            {
                **row["schedule"],
                "game_id": game_id,
                "path": str(row["path"].resolve()),
                "sha256": sha256(row["path"]),
                "provisional_positions": len(provisional[game_id]),
                "selected_plies": [item.ply for item in selected],
                "selected_positions": len(selected),
                "selected": [
                    {
                        "ply": candidate["item"].ply,
                        "phase_band": candidate["band"],
                        "piece_count": candidate["piece_count"],
                        "king_count": candidate["king_count"],
                        "capture_available": candidate["capture_available"],
                    }
                    for candidate in selected_rows
                ],
            }
        )
    selected_rows = [
        selected
        for game in manifest_games
        for selected in game["selected"]
    ]
    manifest = {
        "format": FORMAT,
        "kind": "selection-manifest",
        "split_rule": (
            "first min(games-1, ceil(75%)) games train; remaining games holdout"
        ),
        "position_key": "canonical position plus reversible clock",
        "cross_split_duplicate_positions_dropped": len(cross_split_keys),
        "within_split_duplicate_positions_dropped": within_split_duplicates,
        "selected_phase_bands": dict(sorted(Counter(
            row["phase_band"] for row in selected_rows
        ).items())),
        "selected_piece_counts": dict(sorted(Counter(
            row["piece_count"] for row in selected_rows
        ).items())),
        "selected_mixed_king_positions": sum(
            row["king_count"] > 0 for row in selected_rows
        ),
        "games": manifest_games,
    }
    return manifest, selected_by_game


def choose_spread_candidates(candidates: Sequence[dict], count: int) -> list[dict]:
    ordered = sorted(
        candidates,
        key=lambda row: hashlib.sha256(
            (
                f"thai-makhos-v5-early-supplement|{row['game_id']}|"
                f"{row['item'].ply}|{selection_key(row)}"
            ).encode("utf-8")
        ).hexdigest(),
    )
    selected: list[dict] = []
    used_games: set[str] = set()
    for row in ordered:
        if row["game_id"] in used_games:
            continue
        selected.append(row)
        used_games.add(row["game_id"])
        if len(selected) == count:
            return selected
    for row in ordered:
        if row in selected:
            continue
        selected.append(row)
        if len(selected) == count:
            return selected
    raise RuntimeError(f"only {len(selected)} supplement positions exist; need {count}")


def build_early_supplement_manifest(
    game_rows: Sequence[dict],
    main_manifest: dict,
    *,
    target_positions: int,
) -> tuple[dict, dict[str, list]]:
    if target_positions < 1:
        raise ValueError("supplement target must be positive")
    main_by_game = {game["game_id"]: game for game in main_manifest["games"]}
    main_keys: set[tuple[str, int]] = set()
    replayed_by_game = {}
    for row in game_rows:
        record = load_game_record(row["path"])
        replayed = replay_game(record, rules=DEFAULT_RULES)
        replayed_by_game[record.game_id] = replayed
        selected_plies = set(main_by_game[record.game_id]["selected_plies"])
        main_keys.update(
            (format_position(item.state), item.state.reversible_plies)
            for item in replayed.plies
            if item.ply in selected_plies
        )

    occurrences: dict[tuple[str, int], list[dict]] = {}
    for game_id, replayed in replayed_by_game.items():
        game = main_by_game[game_id]
        selected_plies = set(game["selected_plies"])
        for item in replayed.plies:
            if item.ply in selected_plies or len(legal_moves(item.state)) < 2:
                continue
            piece_count = sum(piece != EMPTY for piece in item.state.board)
            if not 13 <= piece_count <= 16:
                continue
            row = {
                "game_id": game_id,
                "split": game["split"],
                "item": item,
                "band": "13_to_16",
                "piece_count": piece_count,
                "king_count": sum(
                    piece in (BLACK_KING, RED_KING) for piece in item.state.board
                ),
                "capture_available": bool(legal_moves(item.state)[0].is_capture),
            }
            key = selection_key(row)
            if key not in main_keys:
                occurrences.setdefault(key, []).append(row)

    candidates: list[dict] = []
    cross_split_dropped = 0
    within_split_dropped = 0
    for rows in occurrences.values():
        if len({row["split"] for row in rows}) > 1:
            cross_split_dropped += 1
            continue
        chosen = min(rows, key=lambda row: (row["game_id"], row["item"].ply))
        candidates.append(chosen)
        within_split_dropped += len(rows) - 1

    train_target = min(
        target_positions - 1,
        math.ceil(target_positions * 0.75),
    )
    holdout_target = target_positions - train_target
    selected = choose_spread_candidates(
        [row for row in candidates if row["split"] == "train"],
        train_target,
    ) + choose_spread_candidates(
        [row for row in candidates if row["split"] == "holdout"],
        holdout_target,
    )
    selected.sort(key=lambda row: (row["split"], row["game_id"], row["item"].ply))
    selected_by_game: dict[str, list] = {}
    manifest_games: list[dict] = []
    for game_id in sorted({row["game_id"] for row in selected}):
        game_rows_selected = [row for row in selected if row["game_id"] == game_id]
        game = main_by_game[game_id]
        items = [row["item"] for row in game_rows_selected]
        selected_by_game[game_id] = items
        manifest_games.append(
            {
                "game_id": game_id,
                "index": game["index"],
                "seed": game["seed"],
                "split": game["split"],
                "path": game["path"],
                "selected_plies": [item.ply for item in items],
                "selected_positions": len(items),
                "selected": [
                    {
                        "ply": row["item"].ply,
                        "piece_count": row["piece_count"],
                        "king_count": row["king_count"],
                        "capture_available": row["capture_available"],
                    }
                    for row in game_rows_selected
                ],
            }
        )
    manifest = {
        "format": FORMAT,
        "kind": "early-phase-supplement-manifest",
        "target_positions": target_positions,
        "selected_positions": len(selected),
        "train_positions": train_target,
        "holdout_positions": holdout_target,
        "cross_split_duplicate_candidates_dropped": cross_split_dropped,
        "within_split_duplicate_candidates_dropped": within_split_dropped,
        "main_manifest_canonical_payload_sha256": hashlib.sha256(
            json.dumps(main_manifest, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "games": manifest_games,
    }
    return manifest, selected_by_game


def evaluation_trace_payload(state, perspective: int) -> dict:
    trace = trace_evaluation(state, perspective)
    return {
        "score": trace.score,
        "relative_terms": trace.relative_terms,
        "red": asdict(trace.red),
        "black": asdict(trace.black),
        "terminal_score": trace.terminal_score,
    }


def teacher_classification(searches: Sequence[dict]) -> str:
    moves = [search["move"] for search in searches]
    if len(set(moves)) == 1:
        return "stable"
    if len(moves) >= 3 and moves[-2] == moves[-1]:
        return "short-search-divergence"
    return "long-horizon-divergence"


def analyze_game_positions(
    game_path: Path,
    selected_plies: set[int],
    *,
    searcher: NativeSearch,
    library: Path,
    library_sha256: str,
    budgets_ms: Sequence[int],
    hash_mb: int,
) -> dict:
    record = load_game_record(game_path)
    replayed = replay_game(record, rules=DEFAULT_RULES)
    selected = [item for item in replayed.plies if item.ply in selected_plies]
    if len(selected) != len(selected_plies):
        raise RuntimeError(f"selected ply vanished from {game_path}")
    positions: list[dict] = []
    for item in selected:
        legal = legal_moves(item.state)
        child_traces = {
            move.notation: evaluation_trace_payload(
                apply_move(item.state, move, validate=False),
                item.player,
            )
            for move in legal
        }
        searches: list[dict] = []
        for budget_ms in budgets_ms:
            searcher.clear()
            result = searcher.search(
                item.state,
                depth=94,
                time_ms=budget_ms,
                no_progress_plies=DEFAULT_RULES.no_progress_plies,
                repetition_limit=DEFAULT_RULES.repetition_limit,
                history=item.history,
            )
            searches.append(
                {
                    "budget_ms": budget_ms,
                    "move": result.move.notation,
                    "score": result.score,
                    "depth": result.depth,
                    "nodes": result.nodes,
                    "elapsed_ms": result.elapsed_ms,
                    "pv": [move.notation for move in result.pv],
                }
            )
        longest = searches[-1]
        played_trace = child_traces[item.notation]
        long_trace = child_traces[longest["move"]]
        positions.append(
            {
                "ply": item.ply,
                "player": player_name(item.player),
                "position": format_position(item.state),
                "reversible_plies": item.state.reversible_plies,
                "legal_moves": len(legal),
                "played_move": item.notation,
                "recorded_actor": item.actor,
                "classification": teacher_classification(searches),
                "root_static": evaluation_trace_payload(item.state, item.player),
                "played_child_static": played_trace,
                "candidate_child_static": child_traces,
                "long_vs_played_static_term_delta": {
                    term: long_trace["relative_terms"][term]
                    - played_trace["relative_terms"][term]
                    for term in played_trace["relative_terms"]
                },
                "searches": searches,
            }
        )
    return {
        "format": GAME_ANALYSIS_FORMAT,
        "game_id": record.game_id,
        "source_game": str(game_path.resolve()),
        "library": str(library.resolve()),
        "library_sha256": library_sha256,
        "native_search_abi": searcher.abi_version,
        "threads": 1,
        "hash_mb": hash_mb,
        "depth_limit": 94,
        "rules_profile": "project",
        "repetition_limit": DEFAULT_RULES.repetition_limit,
        "no_progress_plies": DEFAULT_RULES.no_progress_plies,
        "budgets_ms": list(budgets_ms),
        "label_semantics": (
            "accepted single-thread self-search stability; not a proven best move"
        ),
        "positions": positions,
    }


def read_corpus_samples(path: Path) -> tuple[dict, list[dict]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    metadata = next(row for row in rows if row.get("kind") == "metadata")
    return metadata, [row for row in rows if row.get("kind") == "sample"]


def corpus_summary(
    corpus: Path,
    manifest: dict,
    *,
    library: Path,
    library_sha256: str,
    budgets_ms: Sequence[int],
) -> dict:
    metadata, samples = read_corpus_samples(corpus)
    split_by_game = {
        game["game_id"]: game["split"] for game in manifest["games"]
    }
    classifications = Counter(
        sample["label"]["classification"] for sample in samples
    )
    strict = [
        sample
        for sample in samples
        if sample["label"].get("stable_move") is not None
        and sample["label"]["classification"] in STRICT_CLASSES
    ]
    piece_counts = Counter(sample["piece_count"] for sample in samples)
    bands = Counter(phase_band(sample["piece_count"]) for sample in samples)
    mixed_kings = 0
    strict_by_split = Counter()
    samples_by_split = Counter()
    strict_ids = {sample["id"] for sample in strict}
    for sample in samples:
        split = split_by_game[sample["source"]["game_id"]]
        samples_by_split[split] += 1
        if sample["id"] in strict_ids:
            strict_by_split[split] += 1
        # Parsing only to count kings keeps the corpus itself free of derived state.
        replay_state = parse_position(
            sample["position"],
            reversible_plies=sample["reversible_plies"],
        )
        mixed_kings += any(
            piece in (BLACK_KING, RED_KING) for piece in replay_state.board
        )
    return {
        "format": FORMAT,
        "kind": "corpus-summary",
        "corpus": str(corpus.resolve()),
        "corpus_sha256": sha256(corpus),
        "metadata": metadata,
        "library": str(library.resolve()),
        "library_sha256": library_sha256,
        "budgets_ms": list(budgets_ms),
        "samples": len(samples),
        "source_games": len({sample["source"]["game_id"] for sample in samples}),
        "samples_by_split": dict(sorted(samples_by_split.items())),
        "strict_positions": len(strict),
        "strict_games": len({sample["source"]["game_id"] for sample in strict}),
        "strict_by_split": dict(sorted(strict_by_split.items())),
        "classifications": dict(sorted(classifications.items())),
        "piece_counts": dict(sorted(piece_counts.items())),
        "phase_bands": dict(sorted((str(key), value) for key, value in bands.items())),
        "mixed_king_positions": mixed_kings,
        "cross_split_duplicate_positions_dropped": manifest[
            "cross_split_duplicate_positions_dropped"
        ],
        "within_split_duplicate_positions_dropped": manifest[
            "within_split_duplicate_positions_dropped"
        ],
        "label_caveat": "search-stability observations only; no ground-truth claim",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--library",
        type=Path,
        default=ROOT / "build" / "makhos_native_accepted.dll",
    )
    parser.add_argument(
        "--expected-library-sha256",
        default=EXPECTED_ACCEPTED_SHA256,
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "build" / "middlegame_v5",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "corpora" / "middlegame_search_v5.jsonl",
    )
    parser.add_argument("--games", type=int, default=64)
    parser.add_argument("--seed-start", type=int, default=20262001)
    parser.add_argument("--generation-depth", type=int, default=10)
    parser.add_argument("--max-game-plies", type=int, default=120)
    parser.add_argument("--samples-per-game", type=int, default=16)
    parser.add_argument("--budget-ms", type=int, action="append", default=None)
    parser.add_argument("--hash-mb", type=int, default=128)
    parser.add_argument("--generation-only", action="store_true")
    parser.add_argument(
        "--early-supplement",
        type=int,
        help=(
            "add this many locked 13-16-piece positions from existing games; "
            "an existing supplement manifest is resumed automatically"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    budgets_ms = tuple(args.budget_ms or (100, 500, 2000))
    if args.games < 2:
        raise ValueError("--games must be at least two")
    if not 1 <= args.generation_depth <= 30:
        raise ValueError("--generation-depth must be in 1..30")
    if args.max_game_plies < 20:
        raise ValueError("--max-game-plies must be at least 20")
    if not 1 <= args.samples_per_game <= sum(PHASE_QUOTAS.values()):
        raise ValueError("--samples-per-game is outside the phase quota cap")
    if budgets_ms != tuple(sorted(set(budgets_ms))) or len(budgets_ms) < 3:
        raise ValueError("provide at least three strictly increasing budgets")
    if not 4 <= args.hash_mb <= 1024:
        raise ValueError("--hash-mb must be in 4..1024")

    library = args.library.resolve()
    library_sha256 = sha256(library)
    if library_sha256.lower() != args.expected_library_sha256.lower():
        raise RuntimeError(
            "teacher DLL identity mismatch: "
            f"expected {args.expected_library_sha256}, got {library_sha256}"
        )
    work_dir = args.work_dir.resolve()
    games_dir = work_dir / "games"
    analyses_dir = work_dir / "analyses"
    schedules = [
        game_schedule(index, args.seed_start, args.games)
        for index in range(1, args.games + 1)
    ]
    config = {
        "format": FORMAT,
        "kind": "locked-config",
        "library": str(library),
        "library_sha256": library_sha256,
        "games": args.games,
        "seed_start": args.seed_start,
        "generation_depth": args.generation_depth,
        "max_game_plies": args.max_game_plies,
        "samples_per_game": args.samples_per_game,
        "phase_quotas": PHASE_QUOTAS,
        "budgets_ms": list(budgets_ms),
        "threads": 1,
        "hash_mb": args.hash_mb,
        "rules_profile": "project",
        "label_semantics": "search-stability observations; not proven best moves",
        "schedules": schedules,
    }
    write_locked_json(work_dir / "config.json", config)

    game_rows: list[dict] = []
    with NativeSearch(library, hash_power=17, persistent=True) as searcher:
        for schedule in schedules:
            game_path = games_dir / (
                f"game_{schedule['index']:03d}_seed_{schedule['seed']}.json"
            )
            if not game_path.exists():
                payload = generate_game(
                    schedule,
                    searcher=searcher,
                    library=library,
                    library_sha256=library_sha256,
                    generation_depth=args.generation_depth,
                    max_game_plies=args.max_game_plies,
                )
                write_json(game_path, payload)
                print(
                    json.dumps(
                        {
                            "stage": "generated",
                            "game": schedule["index"],
                            "plies": len(payload["moves"]),
                            "split": schedule["split"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            game_rows.append(
                {"schedule": schedule, "path": game_path.resolve()}
            )

    manifest, selected_by_game = build_selection_manifest(
        game_rows,
        samples_per_game=args.samples_per_game,
    )
    write_locked_json(work_dir / "selection_manifest.json", manifest)
    selection_brief = {
        "stage": "selection",
        "games": len(manifest["games"]),
        "positions": sum(game["selected_positions"] for game in manifest["games"]),
        "cross_split_duplicates_dropped": manifest[
            "cross_split_duplicate_positions_dropped"
        ],
        "within_split_duplicates_dropped": manifest[
            "within_split_duplicate_positions_dropped"
        ],
        "phase_bands": manifest["selected_phase_bands"],
        "mixed_king_positions": manifest["selected_mixed_king_positions"],
    }
    print(json.dumps(selection_brief, sort_keys=True), flush=True)
    if args.generation_only:
        return

    analysis_paths: list[Path] = []
    teacher_hash_power = hash_power_for_megabytes(
        args.hash_mb,
        entry_bytes=native_tt_entry_bytes(library),
    )
    with NativeSearch(
        library,
        hash_power=teacher_hash_power,
        persistent=True,
    ) as teacher:
        for game in manifest["games"]:
            analysis_path = analyses_dir / (
                f"game_{game['index']:03d}_seed_{game['seed']}.analysis.json"
            )
            if not analysis_path.exists():
                game_path = Path(game["path"])
                report = analyze_game_positions(
                    game_path,
                    set(game["selected_plies"]),
                    searcher=teacher,
                    library=library,
                    library_sha256=library_sha256,
                    budgets_ms=budgets_ms,
                    hash_mb=args.hash_mb,
                )
                write_json(analysis_path, report)
                classifications = Counter(
                    position["classification"] for position in report["positions"]
                )
                print(
                    json.dumps(
                        {
                            "stage": "analyzed",
                            "game": game["index"],
                            "positions": len(report["positions"]),
                            "classifications": dict(sorted(classifications.items())),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            analysis_paths.append(analysis_path)

    supplement_manifest_path = work_dir / "early_supplement_manifest.json"
    if supplement_manifest_path.exists():
        existing_supplement = json.loads(
            supplement_manifest_path.read_text(encoding="utf-8")
        )
        existing_target = int(existing_supplement["target_positions"])
        if (
            args.early_supplement is not None
            and args.early_supplement != existing_target
        ):
            raise RuntimeError(
                "requested early supplement differs from locked manifest"
            )
        supplement_target = existing_target
    else:
        supplement_target = args.early_supplement or 0

    supplement_manifest = None
    if supplement_target:
        supplement_manifest, _supplement_by_game = build_early_supplement_manifest(
            game_rows,
            manifest,
            target_positions=supplement_target,
        )
        write_locked_json(supplement_manifest_path, supplement_manifest)
        supplement_dir = work_dir / "early_supplement_analyses"
        with NativeSearch(
            library,
            hash_power=teacher_hash_power,
            persistent=True,
        ) as teacher:
            for game in supplement_manifest["games"]:
                analysis_path = supplement_dir / (
                    f"game_{game['index']:03d}_seed_{game['seed']}.supplement.analysis.json"
                )
                if not analysis_path.exists():
                    report = analyze_game_positions(
                        Path(game["path"]),
                        set(game["selected_plies"]),
                        searcher=teacher,
                        library=library,
                        library_sha256=library_sha256,
                        budgets_ms=budgets_ms,
                        hash_mb=args.hash_mb,
                    )
                    write_json(analysis_path, report)
                    classifications = Counter(
                        position["classification"]
                        for position in report["positions"]
                    )
                    print(
                        json.dumps(
                            {
                                "stage": "analyzed-early-supplement",
                                "game": game["index"],
                                "positions": len(report["positions"]),
                                "classifications": dict(
                                    sorted(classifications.items())
                                ),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                analysis_paths.append(analysis_path)

    build_middlegame_corpus(
        analysis_paths,
        args.corpus,
        min_pieces=5,
        max_pieces=16,
        stable_only=False,
    )
    summary = corpus_summary(
        args.corpus,
        manifest,
        library=library,
        library_sha256=library_sha256,
        budgets_ms=budgets_ms,
    )
    summary["early_supplement"] = (
        None
        if supplement_manifest is None
        else {
            "manifest": str(supplement_manifest_path.resolve()),
            "manifest_sha256": sha256(supplement_manifest_path),
            "selected_positions": supplement_manifest["selected_positions"],
            "train_positions": supplement_manifest["train_positions"],
            "holdout_positions": supplement_manifest["holdout_positions"],
        }
    )
    write_json(work_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
