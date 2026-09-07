"""Audit whether the middlegame corpus can support an HCE fit.

This is measurement-only.  It keeps source games intact across the
train/holdout boundary, treats long-search choices as observations rather than
ground truth, and never writes evaluator weights.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Iterable, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import (  # noqa: E402
    BLACK_KING,
    EMPTY,
    RED_KING,
    apply_move,
    legal_moves,
    parse_position,
)
from makhos.eval import (  # noqa: E402
    CURRENT_EVALUATION_WEIGHTS,
    EvaluationFeatures,
    evaluation_features,
)


FORMAT = "thai-makhos-hce-tuning-readiness-v1"
SPLIT_SALT = "thai-makhos-hce-audit-v1"
FEATURE_NAMES = tuple(EvaluationFeatures.__dataclass_fields__)
PAIRWISE_FEATURE_NAMES = tuple(
    name for name in FEATURE_NAMES if name != "simplification"
)
CURRENT_WEIGHTS = np.asarray(
    [CURRENT_EVALUATION_WEIGHTS[name] for name in FEATURE_NAMES],
    dtype=np.float64,
)
STRICT_LABEL_CLASSES = frozenset(("stable", "short-search-divergence"))
HUMAN_DIVERGENCES = (
    {
        "id": "human-loss-ply-13",
        "position": "B:BM20,22,23,25,27,28,29,31:RM2,3,5,7,8,9,11,15",
        "reversible_plies": 12,
        "played_move": "28-24",
        "deeper_alternatives": ("22-18", "23-19"),
        "evidence": (
            "played move is stable-worse; exact preferred PV remains horizon-sensitive"
        ),
    },
    {
        "id": "human-loss-ply-25",
        "position": "B:BM19,20,22,27,31:RM2,3,5,10,11",
        "reversible_plies": 3,
        "played_move": "27-23",
        "deeper_alternatives": ("31-26",),
        "evidence": "31-26 was preferred at both 20 s and 60 s",
    },
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_corpus(path: Path) -> tuple[dict, list[dict]]:
    metadata: dict | None = None
    samples: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            row = json.loads(line)
            if row.get("kind") == "metadata":
                if metadata is not None:
                    raise ValueError("corpus contains more than one metadata row")
                metadata = row
            elif row.get("kind") == "sample":
                samples.append(row)
            else:
                raise ValueError(f"unknown corpus row at line {line_number}")
    if metadata is None:
        raise ValueError("corpus has no metadata row")
    if metadata.get("sample_count") != len(samples):
        raise ValueError("corpus metadata sample count is stale")
    return metadata, samples


def source_game_id(sample: dict) -> str:
    game_id = sample.get("source", {}).get("game_id")
    if not isinstance(game_id, str) or not game_id:
        raise ValueError(f"sample {sample.get('id')} has no source game id")
    observation_games = {
        observation.get("source", {}).get("game_id")
        for observation in sample.get("observations", ())
    }
    observation_games.discard(None)
    if observation_games and game_id not in observation_games:
        raise ValueError(f"sample {sample.get('id')} primary source is inconsistent")
    return game_id


def deterministic_game_split(
    samples: Sequence[dict],
    *,
    holdout_fraction: float,
) -> tuple[set[str], set[str], list[dict]]:
    games = sorted({source_game_id(sample) for sample in samples})
    if len(games) < 2:
        raise ValueError("at least two source games are required")
    holdout_count = min(
        len(games) - 1,
        max(1, round(len(games) * holdout_fraction)),
    )
    ranked = sorted(
        games,
        key=lambda game_id: hashlib.sha256(
            f"{SPLIT_SALT}|{game_id}".encode("utf-8")
        ).hexdigest(),
    )
    holdout = set(ranked[:holdout_count])
    train = set(ranked[holdout_count:])
    manifest = [
        {
            "game_id": game_id,
            "split": "holdout" if game_id in holdout else "train",
            "split_hash": hashlib.sha256(
                f"{SPLIT_SALT}|{game_id}".encode("utf-8")
            ).hexdigest(),
        }
        for game_id in ranked
    ]
    return train, holdout, manifest


def locked_game_split(
    samples: Sequence[dict],
    manifest_path: Path,
) -> tuple[set[str], set[str], list[dict], dict]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_games = payload.get("games")
    if not isinstance(raw_games, list) or not raw_games:
        raise ValueError("split manifest has no games")
    split_by_game: dict[str, str] = {}
    manifest: list[dict] = []
    for index, row in enumerate(raw_games):
        if not isinstance(row, dict):
            raise ValueError(f"split manifest game {index} is not an object")
        game_id = row.get("game_id")
        split = row.get("split")
        if not isinstance(game_id, str) or not game_id:
            raise ValueError(f"split manifest game {index} has no game_id")
        if split not in ("train", "holdout"):
            raise ValueError(f"split manifest game {game_id} has invalid split")
        if game_id in split_by_game:
            raise ValueError(f"split manifest repeats game {game_id}")
        split_by_game[game_id] = split
        manifest.append({"game_id": game_id, "split": split})
    corpus_games = {source_game_id(sample) for sample in samples}
    missing = corpus_games - set(split_by_game)
    if missing:
        raise ValueError(
            "corpus games missing from split manifest: " + ", ".join(sorted(missing))
        )
    for sample in samples:
        observation_games = {
            observation.get("source", {}).get("game_id")
            for observation in sample.get("observations", ())
        }
        observation_games.discard(None)
        observation_splits = {
            split_by_game[game_id]
            for game_id in observation_games
            if game_id in split_by_game
        }
        if len(observation_splits) > 1:
            raise ValueError(f"sample {sample['id']} leaks across locked split")
    train = {
        game_id for game_id in corpus_games if split_by_game[game_id] == "train"
    }
    holdout = corpus_games - train
    if not train or not holdout:
        raise ValueError("locked split must contain corpus games on both sides")
    provenance = {
        "path": str(manifest_path.resolve()),
        "sha256": sha256(manifest_path),
        "declared_games": len(split_by_game),
        "corpus_games": len(corpus_games),
    }
    return train, holdout, manifest, provenance


def feature_vector(state, perspective: int) -> np.ndarray:
    features = evaluation_features(state, perspective)
    return np.asarray(
        [getattr(features, name) for name in FEATURE_NAMES],
        dtype=np.float64,
    )


def child_feature_vectors(state) -> dict[str, np.ndarray | None]:
    children: dict[str, np.ndarray | None] = {}
    for move in legal_moves(state):
        child = apply_move(state, move, validate=False)
        try:
            children[move.notation] = feature_vector(child, state.turn)
        except ValueError as error:
            if str(error) != "terminal material positions have no linear features":
                raise
            children[move.notation] = None
    return children


def split_name(game_id: str, train_games: set[str]) -> str:
    return "train" if game_id in train_games else "holdout"


def build_measurements(
    samples: Sequence[dict],
    train_games: set[str],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    roots: list[dict] = []
    rankings: list[dict] = []
    pairs: list[dict] = []
    terminal_child_exclusions: list[dict] = []
    for sample in samples:
        game_id = source_game_id(sample)
        state = parse_position(
            sample["position"],
            reversible_plies=int(sample.get("reversible_plies", 0)),
        )
        root = feature_vector(state, state.turn)
        king_count = sum(piece in (BLACK_KING, RED_KING) for piece in state.board)
        root_row = {
            "id": sample["id"],
            "game_id": game_id,
            "split": split_name(game_id, train_games),
            "classification": sample["label"]["classification"],
            "piece_count": int(sample["piece_count"]),
            "king_count": king_count,
            "ply": int(sample["source"]["ply"]),
            "vector": root,
        }
        roots.append(root_row)

        stable_move = sample["label"].get("stable_move")
        strict = (
            stable_move is not None
            and sample["label"]["classification"] in STRICT_LABEL_CLASSES
        )
        if not strict:
            continue
        children = child_feature_vectors(state)
        if set(children) != set(sample["legal_moves"]):
            raise ValueError(f"sample {sample['id']} legal move list drifted")
        if stable_move not in children:
            raise ValueError(f"sample {sample['id']} stable move is not legal")
        terminal_moves = sorted(
            move for move, vector in children.items() if vector is None
        )
        if terminal_moves:
            terminal_child_exclusions.append(
                {
                    "id": sample["id"],
                    "game_id": game_id,
                    "split": root_row["split"],
                    "classification": root_row["classification"],
                    "piece_count": root_row["piece_count"],
                    "stable_move": stable_move,
                    "stable_move_is_terminal": stable_move in terminal_moves,
                    "terminal_moves": terminal_moves,
                }
            )
            continue
        scores = {
            move: float(vector @ CURRENT_WEIGHTS)
            for move, vector in children.items()
        }
        chosen_score = scores[stable_move]
        best_score = max(scores.values())
        better_count = sum(score > chosen_score for score in scores.values())
        tied_count = sum(score == chosen_score for score in scores.values())
        ranking = {
            **{key: value for key, value in root_row.items() if key != "vector"},
            "stable_move": stable_move,
            "legal_move_count": len(children),
            "current_static_rank": better_count + 1,
            "current_static_tie_count": tied_count,
            "current_static_in_best_tie": chosen_score == best_score,
            "current_static_unique_best": (
                chosen_score == best_score
                and sum(score == best_score for score in scores.values()) == 1
            ),
            "current_static_score": chosen_score,
            "current_static_best_score": best_score,
        }
        rankings.append(ranking)
        chosen = children[stable_move]
        for other_move, other in children.items():
            if other_move == stable_move:
                continue
            pairs.append(
                {
                    "id": sample["id"],
                    "game_id": game_id,
                    "split": root_row["split"],
                    "classification": root_row["classification"],
                    "piece_count": root_row["piece_count"],
                    "chosen_move": stable_move,
                    "other_move": other_move,
                    "vector": chosen - other,
                }
            )
    return roots, rankings, pairs, terminal_child_exclusions


def as_matrix(rows: Sequence[dict]) -> np.ndarray:
    if not rows:
        return np.empty((0, len(FEATURE_NAMES)), dtype=np.float64)
    return np.vstack([row["vector"] for row in rows])


def finite_float(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def feature_inventory(rows: Sequence[dict]) -> dict:
    matrix = as_matrix(rows)
    result: dict[str, dict] = {}
    for column, name in enumerate(FEATURE_NAMES):
        values = matrix[:, column] if len(matrix) else np.asarray([], dtype=float)
        nonzero = np.abs(values) > 1e-12
        nonzero_games = {
            row["game_id"]
            for row, active in zip(rows, nonzero, strict=True)
            if active
        }
        result[name] = {
            "rows": len(values),
            "nonzero_rows": int(np.count_nonzero(nonzero)),
            "nonzero_games": len(nonzero_games),
            "unique_values": int(len(np.unique(values))) if len(values) else 0,
            "minimum": finite_float(np.min(values)) if len(values) else None,
            "maximum": finite_float(np.max(values)) if len(values) else None,
            "mean": finite_float(np.mean(values)) if len(values) else None,
            "standard_deviation": finite_float(np.std(values)) if len(values) else None,
        }
    return result


def matrix_diagnostics(rows: Sequence[dict]) -> dict:
    matrix = as_matrix(rows)
    if not len(matrix):
        return {
            "rows": 0,
            "positions": 0,
            "source_games": 0,
            "features": len(FEATURE_NAMES),
            "active_features": [],
            "zero_variance_features": list(FEATURE_NAMES),
            "rank": 0,
            "condition_number": None,
            "condition_status": "empty",
            "high_correlations": [],
        }
    rms = np.sqrt(np.mean(np.square(matrix), axis=0))
    active_indices = np.flatnonzero(rms > 1e-12)
    active_names = [FEATURE_NAMES[index] for index in active_indices]
    inactive_names = [
        name for index, name in enumerate(FEATURE_NAMES) if index not in active_indices
    ]
    scaled = matrix[:, active_indices] / rms[active_indices]
    singular = np.linalg.svd(scaled, compute_uv=False)
    rank = int(np.linalg.matrix_rank(scaled))
    full_rank = rank == len(active_indices)
    condition = (
        float(singular[0] / singular[-1])
        if full_rank and len(singular) and singular[-1] > 0
        else None
    )

    correlations: list[dict] = []
    standard_deviations = np.std(matrix, axis=0)
    varying = np.flatnonzero(standard_deviations > 1e-12)
    if len(varying) >= 2:
        correlation_matrix = np.corrcoef(matrix[:, varying], rowvar=False)
        for left_offset, left in enumerate(varying):
            for right_offset in range(left_offset + 1, len(varying)):
                right = varying[right_offset]
                correlation = float(correlation_matrix[left_offset, right_offset])
                if abs(correlation) >= 0.95:
                    correlations.append(
                        {
                            "left": FEATURE_NAMES[left],
                            "right": FEATURE_NAMES[right],
                            "correlation": correlation,
                        }
                    )
    correlations.sort(key=lambda item: (-abs(item["correlation"]), item["left"], item["right"]))
    return {
        "rows": len(rows),
        "positions": len({row["id"] for row in rows}),
        "source_games": len({row["game_id"] for row in rows}),
        "features": len(FEATURE_NAMES),
        "active_features": active_names,
        "zero_rms_features": inactive_names,
        "rank": rank,
        "full_current_basis_rank": rank == len(FEATURE_NAMES),
        "condition_number": finite_float(condition) if condition is not None else None,
        "condition_status": (
            "full-rank"
            if full_rank
            else "rank-deficient-among-active-features"
        ),
        "scaled_singular_values": [float(value) for value in singular],
        "high_correlations_abs_ge_0_95": correlations,
    }


def selected_basis_diagnostics(
    rows: Sequence[dict],
    feature_names: Sequence[str],
) -> dict:
    matrix = as_matrix(rows)
    indices = np.asarray(
        [FEATURE_NAMES.index(name) for name in feature_names],
        dtype=int,
    )
    selected = matrix[:, indices]
    rms = (
        np.sqrt(np.mean(np.square(selected), axis=0))
        if len(selected)
        else np.zeros(len(indices), dtype=float)
    )
    active = np.flatnonzero(rms > 1e-12)
    missing = [
        feature_names[index]
        for index in range(len(feature_names))
        if index not in active
    ]
    if not len(selected) or len(active) == 0:
        return {
            "feature_names": list(feature_names),
            "rows": len(rows),
            "rank": 0,
            "full_rank": False,
            "condition_number": None,
            "missing_features": missing,
        }
    scaled = selected[:, active] / rms[active]
    singular = np.linalg.svd(scaled, compute_uv=False)
    rank = int(np.linalg.matrix_rank(scaled))
    full_rank = rank == len(feature_names)
    condition = (
        float(singular[0] / singular[-1])
        if rank == len(active) and singular[-1] > 0
        else None
    )
    return {
        "feature_names": list(feature_names),
        "rows": len(rows),
        "rank": rank,
        "full_rank": full_rank,
        "condition_number": finite_float(condition) if condition is not None else None,
        "missing_features": missing,
        "scaled_singular_values": [float(value) for value in singular],
    }


def ranking_summary(rows: Sequence[dict]) -> dict:
    if not rows:
        return {
            "positions": 0,
            "source_games": 0,
            "in_best_tie": 0,
            "unique_best": 0,
            "mean_reciprocal_rank": None,
        }
    return {
        "positions": len(rows),
        "source_games": len({row["game_id"] for row in rows}),
        "in_best_tie": sum(row["current_static_in_best_tie"] for row in rows),
        "in_best_tie_rate": sum(
            row["current_static_in_best_tie"] for row in rows
        ) / len(rows),
        "unique_best": sum(row["current_static_unique_best"] for row in rows),
        "unique_best_rate": sum(
            row["current_static_unique_best"] for row in rows
        ) / len(rows),
        "mean_reciprocal_rank": sum(
            1.0 / row["current_static_rank"] for row in rows
        ) / len(rows),
        "mean_legal_moves": sum(row["legal_move_count"] for row in rows) / len(rows),
    }


def pair_margin_summary(rows: Sequence[dict]) -> dict:
    matrix = as_matrix(rows)
    margins = matrix @ CURRENT_WEIGHTS if len(matrix) else np.asarray([], dtype=float)
    return {
        "pairs": len(rows),
        "positive": int(np.count_nonzero(margins > 0)),
        "zero": int(np.count_nonzero(margins == 0)),
        "negative": int(np.count_nonzero(margins < 0)),
        "positive_rate": (
            float(np.count_nonzero(margins > 0) / len(margins))
            if len(margins)
            else None
        ),
        "median_margin": finite_float(np.median(margins)) if len(margins) else None,
    }


def count_by(rows: Iterable[dict], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[field]) for row in rows).items()))


def phase_inventory(rows: Sequence[dict]) -> dict:
    piece_counts = Counter(row["piece_count"] for row in rows)
    king_counts = Counter(row["king_count"] for row in rows)
    bands = {
        "13_to_16_pieces": sum(13 <= row["piece_count"] <= 16 for row in rows),
        "9_to_12_pieces": sum(9 <= row["piece_count"] <= 12 for row in rows),
        "5_to_8_pieces": sum(5 <= row["piece_count"] <= 8 for row in rows),
        "4_or_fewer_pieces": sum(row["piece_count"] <= 4 for row in rows),
        "mixed_king_positions": sum(row["king_count"] > 0 for row in rows),
        "men_only_positions": sum(row["king_count"] == 0 for row in rows),
    }
    return {
        "piece_counts": dict(sorted(piece_counts.items())),
        "king_counts": dict(sorted(king_counts.items())),
        "bands": bands,
        "ply_minimum": min((row["ply"] for row in rows), default=None),
        "ply_maximum": max((row["ply"] for row in rows), default=None),
    }


def human_coverage(
    train_roots: Sequence[dict],
    train_pairs: Sequence[dict],
) -> list[dict]:
    root_matrix = as_matrix(train_roots)
    pair_matrix = as_matrix(train_pairs)
    pair_minimum = np.min(pair_matrix, axis=0)
    pair_maximum = np.max(pair_matrix, axis=0)
    pair_mean = np.mean(pair_matrix, axis=0)
    pair_std = np.std(pair_matrix, axis=0)
    root_minimum = np.min(root_matrix, axis=0)
    root_maximum = np.max(root_matrix, axis=0)
    output: list[dict] = []
    for item in HUMAN_DIVERGENCES:
        state = parse_position(
            item["position"],
            reversible_plies=item["reversible_plies"],
        )
        root = feature_vector(state, state.turn)
        children = child_feature_vectors(state)
        played = children[item["played_move"]]
        if played is None:
            raise RuntimeError(f"human regression {item['id']} played move is terminal")
        root_outside = [
            FEATURE_NAMES[index]
            for index, value in enumerate(root)
            if value < root_minimum[index] or value > root_maximum[index]
        ]
        comparisons: list[dict] = []
        for alternative_move in item["deeper_alternatives"]:
            alternative = children[alternative_move]
            if alternative is None:
                raise RuntimeError(
                    f"human regression {item['id']} alternative is terminal"
                )
            delta = alternative - played
            unsupported = [
                FEATURE_NAMES[index]
                for index, value in enumerate(delta)
                if value != 0 and pair_minimum[index] == pair_maximum[index] == 0
            ]
            outside = [
                FEATURE_NAMES[index]
                for index, value in enumerate(delta)
                if value < pair_minimum[index] or value > pair_maximum[index]
            ]
            z_scores = {
                FEATURE_NAMES[index]: float(
                    (value - pair_mean[index]) / pair_std[index]
                )
                for index, value in enumerate(delta)
                if pair_std[index] > 1e-12
            }
            comparisons.append(
                {
                    "alternative_move": alternative_move,
                    "feature_delta_alternative_minus_played": {
                        name: int(delta[index])
                        for index, name in enumerate(FEATURE_NAMES)
                    },
                    "current_static_margin": float(delta @ CURRENT_WEIGHTS),
                    "unsupported_nonzero_features": unsupported,
                    "features_outside_train_pair_range": outside,
                    "maximum_absolute_train_z": (
                        max((abs(value) for value in z_scores.values()), default=None)
                    ),
                    "train_z_scores": z_scores,
                }
            )
        output.append(
            {
                **item,
                "deeper_alternatives": list(item["deeper_alternatives"]),
                "piece_count": sum(piece != EMPTY for piece in state.board),
                "king_count": sum(
                    piece in (BLACK_KING, RED_KING) for piece in state.board
                ),
                "root_features": {
                    name: int(root[index])
                    for index, name in enumerate(FEATURE_NAMES)
                },
                "root_features_outside_train_range": root_outside,
                "comparisons": comparisons,
            }
        )
    return output


def readiness_assessment(
    *,
    strict_rankings: Sequence[dict],
    train_rankings: Sequence[dict],
    holdout_rankings: Sequence[dict],
    train_pairs: Sequence[dict],
    holdout_pairs: Sequence[dict],
    train_roots: Sequence[dict],
) -> dict:
    train_pairwise_basis = selected_basis_diagnostics(
        train_pairs,
        PAIRWISE_FEATURE_NAMES,
    )
    holdout_pairwise_basis = selected_basis_diagnostics(
        holdout_pairs,
        PAIRWISE_FEATURE_NAMES,
    )
    train_feature_support = feature_inventory(train_pairs)
    phase = phase_inventory(train_roots)
    gates = {
        "at_least_256_strict_positions": len(strict_rankings) >= 256,
        "at_least_32_strict_source_games": len(
            {row["game_id"] for row in strict_rankings}
        ) >= 32,
        "at_least_64_holdout_positions": len(holdout_rankings) >= 64,
        "all_pairwise_features_nonzero_in_at_least_5_train_games": all(
            train_feature_support[name]["nonzero_games"] >= 5
            for name in PAIRWISE_FEATURE_NAMES
        ),
        "all_pairwise_features_present_in_holdout": not holdout_pairwise_basis[
            "missing_features"
        ],
        "full_rank_nine_feature_pairwise_basis_on_train": train_pairwise_basis[
            "full_rank"
        ],
        "pairwise_train_condition_number_at_most_100": (
            train_pairwise_basis["condition_number"] is not None
            and train_pairwise_basis["condition_number"] <= 100.0
        ),
        "coverage_at_13_to_16_pieces": phase["bands"]["13_to_16_pieces"] >= 64,
        "coverage_at_9_to_12_pieces": phase["bands"]["9_to_12_pieces"] >= 64,
        "coverage_at_5_to_8_pieces": phase["bands"]["5_to_8_pieces"] >= 32,
        "mixed_king_coverage": phase["bands"]["mixed_king_positions"] >= 64,
        "independent_non_self_search_label_source": False,
    }
    fit_gates = {
        key: value
        for key, value in gates.items()
        if key != "independent_non_self_search_label_source"
    }
    fit_ready = all(fit_gates.values())
    promotion_ready = fit_ready and gates["independent_non_self_search_label_source"]
    failed = [name for name, passed in gates.items() if not passed]
    return {
        "gate_policy": (
            "conservative pre-fit sufficiency gates for a nine-feature grouped "
            "move-ranking fit while simplification remains fixed for separate "
            "outcome/value identification; thresholds are audit criteria, not "
            "strength claims"
        ),
        "gates": gates,
        "fit_ready": fit_ready,
        "promotion_ready": promotion_ready,
        "failed_gates": failed,
        "verdict": (
            "sufficient-for-measurement-fit-only"
            if fit_ready and not promotion_ready
            else "sufficient-for-candidate-fit"
            if promotion_ready
            else "insufficient-do-not-fit-or-change-hce-weights"
        ),
        "note": (
            "The position-global simplification term is intentionally excluded "
            "from the nine-feature move-ranking basis and must remain fixed until "
            "outcome/value labels identify it. Ridge regularization cannot create "
            "missing evidence for either basis."
        ),
        "pairwise_basis_train": train_pairwise_basis,
        "pairwise_basis_holdout": holdout_pairwise_basis,
    }


def acquisition_plan(assessment: dict) -> dict:
    return {
        "name": "middlegame-search-corpus-v5",
        "purpose": (
            "repair measured coverage and independence gaps before any HCE coefficient experiment"
        ),
        "minimum_targets": {
            "source_games": 64,
            "strict_stability_positions": 512,
            "locked_game_split": {"train_games": 48, "holdout_games": 16},
            "piece_bands_each": {
                "13_to_16": 256,
                "9_to_12": 256,
                "5_to_8": 128,
            },
            "mixed_king_positions": 128,
        },
        "sampling": [
            "vary opening length and opening seed; do not reuse only six random plies",
            "sample at most twelve positions per game and keep every source game in one split",
            "stratify by piece count, king presence, side to move, capture availability, and legal-move count",
            "deduplicate by position plus reversible clock before analysis",
        ],
        "teacher_labels": [
            "use the byte-preserved accepted DLL as control identity",
            "prefer deterministic single-thread deeper searches because current root split is a measured weaker teacher",
            "retain at least three increasing budgets and require the last two completed searches to agree",
            "store all root scores/PVs/depth/nodes; never call the longest move proven best",
            "reserve provenance-complete human/external games as out-of-distribution regression only",
        ],
        "next_gate": (
            "rerun this audit; only a full-rank, supported game-held-out matrix may justify one HCE candidate"
        ),
        "current_failed_gates": assessment["failed_gates"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "corpora" / "middlegame_search_v4.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "hce_tuning_readiness_audit_20260823.json",
    )
    parser.add_argument("--holdout-fraction", type=float, default=0.25)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        help="locked acquisition manifest; overrides the salted fallback split",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0.1 <= args.holdout_fraction <= 0.5:
        raise ValueError("--holdout-fraction must be in [0.1, 0.5]")
    corpus = args.corpus.resolve()
    metadata, samples = load_corpus(corpus)
    split_provenance = None
    if args.split_manifest is not None:
        train_games, holdout_games, split_manifest, split_provenance = locked_game_split(
            samples,
            args.split_manifest.resolve(),
        )
        split_method = "locked acquisition manifest"
    else:
        train_games, holdout_games, split_manifest = deterministic_game_split(
            samples,
            holdout_fraction=args.holdout_fraction,
        )
        split_method = "whole source games ranked by salted SHA-256"
    roots, rankings, pairs, terminal_child_exclusions = build_measurements(
        samples,
        train_games,
    )
    train_roots = [row for row in roots if row["split"] == "train"]
    holdout_roots = [row for row in roots if row["split"] == "holdout"]
    train_rankings = [row for row in rankings if row["split"] == "train"]
    holdout_rankings = [row for row in rankings if row["split"] == "holdout"]
    train_pairs = [row for row in pairs if row["split"] == "train"]
    holdout_pairs = [row for row in pairs if row["split"] == "holdout"]
    assessment = readiness_assessment(
        strict_rankings=rankings,
        train_rankings=train_rankings,
        holdout_rankings=holdout_rankings,
        train_pairs=train_pairs,
        holdout_pairs=holdout_pairs,
        train_roots=train_roots,
    )

    classification_total = Counter(
        sample["label"]["classification"] for sample in samples
    )
    classification_stable = Counter(
        sample["label"]["classification"]
        for sample in samples
        if sample["label"].get("stable_move") is not None
    )
    declared_usable = [
        sample
        for sample in samples
        if sample["label"].get("usable_for_supervised_training")
    ]
    strict_label_samples = [
        sample
        for sample in samples
        if sample["label"].get("stable_move") is not None
        and sample["label"]["classification"] in STRICT_LABEL_CLASSES
    ]
    payload = {
        "format": FORMAT,
        "purpose": "measurement-only HCE tuning readiness; no weights are fitted or written",
        "corpus": str(corpus),
        "corpus_sha256": sha256(corpus),
        "corpus_metadata": metadata,
        "feature_names": list(FEATURE_NAMES),
        "pairwise_feature_names": list(PAIRWISE_FEATURE_NAMES),
        "non_pairwise_feature_note": (
            "simplification is position-global for ordinary sibling moves and "
            "requires outcome/value evidence rather than move-ranking labels"
        ),
        "current_weights": dict(CURRENT_EVALUATION_WEIGHTS),
        "label_caveat": (
            "all corpus labels are self-search stability observations, not proven best moves"
        ),
        "split": {
            "method": split_method,
            "salt": SPLIT_SALT,
            "holdout_fraction": args.holdout_fraction,
            "train_games": len(train_games),
            "holdout_games": len(holdout_games),
            "provenance": split_provenance,
            "manifest": split_manifest,
        },
        "labels": {
            "samples": len(samples),
            "source_games": len(train_games | holdout_games),
            "by_classification": dict(sorted(classification_total.items())),
            "stable_move_by_classification": dict(
                sorted(classification_stable.items())
            ),
            "declared_usable_positions": len(declared_usable),
            "strict_usable_definition": (
                "stable_move present and classification is stable or short-search-divergence"
            ),
            "strict_label_positions": len(strict_label_samples),
            "strict_label_games": len(
                {source_game_id(sample) for sample in strict_label_samples}
            ),
            "terminal_child_positions_excluded_from_linear_fit": len(
                terminal_child_exclusions
            ),
            "linear_pairwise_positions": len(rankings),
            "linear_pairwise_games": len({row["game_id"] for row in rankings}),
            "train_linear_pairwise_positions": len(train_rankings),
            "holdout_linear_pairwise_positions": len(holdout_rankings),
            "conflicting_source_labels": int(
                metadata.get("conflict_sample_count", 0)
            ),
        },
        "phase_coverage_all": phase_inventory(roots),
        "phase_coverage_train": phase_inventory(train_roots),
        "root_feature_inventory": {
            "all": feature_inventory(roots),
            "train": feature_inventory(train_roots),
            "holdout": feature_inventory(holdout_roots),
        },
        "pairwise_feature_inventory_strict": {
            "all": feature_inventory(pairs),
            "train": feature_inventory(train_pairs),
            "holdout": feature_inventory(holdout_pairs),
        },
        "pairwise_matrix_strict": {
            "all": matrix_diagnostics(pairs),
            "train": matrix_diagnostics(train_pairs),
            "holdout": matrix_diagnostics(holdout_pairs),
            "nine_feature_basis_all": selected_basis_diagnostics(
                pairs, PAIRWISE_FEATURE_NAMES
            ),
            "nine_feature_basis_train": selected_basis_diagnostics(
                train_pairs, PAIRWISE_FEATURE_NAMES
            ),
            "nine_feature_basis_holdout": selected_basis_diagnostics(
                holdout_pairs, PAIRWISE_FEATURE_NAMES
            ),
        },
        "current_static_ranking_against_stable_search": {
            "all": ranking_summary(rankings),
            "train": ranking_summary(train_rankings),
            "holdout": ranking_summary(holdout_rankings),
            "by_classification": {
                classification: ranking_summary(
                    [row for row in rankings if row["classification"] == classification]
                )
                for classification in sorted(STRICT_LABEL_CLASSES)
            },
            "pair_margins_all": pair_margin_summary(pairs),
            "pair_margins_train": pair_margin_summary(train_pairs),
            "pair_margins_holdout": pair_margin_summary(holdout_pairs),
        },
        "human_divergence_out_of_sample_coverage": human_coverage(
            train_roots,
            train_pairs,
        ),
        "terminal_child_exclusions": terminal_child_exclusions,
        "assessment": assessment,
        "recommended_next_experiment": acquisition_plan(assessment),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    brief = {
        "output": str(args.output.resolve()),
        "corpus_sha256": payload["corpus_sha256"],
        "labels": payload["labels"],
        "phase": payload["phase_coverage_all"],
        "train_matrix": payload["pairwise_matrix_strict"]["train"],
        "holdout_ranking": payload[
            "current_static_ranking_against_stable_search"
        ]["holdout"],
        "human": payload["human_divergence_out_of_sample_coverage"],
        "assessment": assessment,
    }
    print(json.dumps(brief, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
