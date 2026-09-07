"""Fit HCE move-ranking weights without changing the playing engine.

Regularisation is selected only inside the locked training games.  The holdout
is opened once after the one-standard-error choice is fixed.  Search-stability
labels remain observational; this script can justify a candidate experiment,
not a strength promotion.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from typing import Iterable, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRATCH))

from hce_tuning_readiness_audit import (  # noqa: E402
    CURRENT_WEIGHTS,
    FEATURE_NAMES,
    HUMAN_DIVERGENCES,
    PAIRWISE_FEATURE_NAMES,
    build_measurements,
    child_feature_vectors,
    load_corpus,
    locked_game_split,
)
from makhos.core import parse_position  # noqa: E402


FORMAT = "thai-makhos-hce-pairwise-fit-audit-v1"
CV_SALT = "thai-makhos-hce-pairwise-cv-v1"
TEMPERATURE_CP = 64.0
RIDGE_GRID = (
    0.0001,
    0.0003,
    0.001,
    0.003,
    0.01,
    0.03,
    0.1,
    0.3,
    1.0,
    3.0,
    10.0,
)
CV_FOLDS = 6
PAIRWISE_INDICES = np.asarray(
    [FEATURE_NAMES.index(name) for name in PAIRWISE_FEATURE_NAMES],
    dtype=int,
)
CURRENT_PAIRWISE_WEIGHTS = CURRENT_WEIGHTS[PAIRWISE_INDICES]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def as_matrix(rows: Sequence[dict]) -> np.ndarray:
    return np.vstack([row["vector"][PAIRWISE_INDICES] for row in rows])


def game_position_pair_weights(rows: Sequence[dict]) -> np.ndarray:
    positions_by_game: dict[str, set[str]] = defaultdict(set)
    pairs_by_position: dict[str, int] = defaultdict(int)
    for row in rows:
        positions_by_game[row["game_id"]].add(row["id"])
        pairs_by_position[row["id"]] += 1
    games = len(positions_by_game)
    if not games:
        raise ValueError("pair rows contain no games")
    weights = np.asarray(
        [
            1.0
            / games
            / len(positions_by_game[row["game_id"]])
            / pairs_by_position[row["id"]]
            for row in rows
        ],
        dtype=np.float64,
    )
    weights /= np.sum(weights)
    return weights


def sigmoid_negative(value: np.ndarray) -> np.ndarray:
    return np.exp(-np.logaddexp(0.0, value))


def fit_pairwise(
    rows: Sequence[dict],
    *,
    ridge: float,
    maximum_iterations: int = 80,
) -> dict:
    matrix = as_matrix(rows)
    row_weights = game_position_pair_weights(rows)
    rms = np.sqrt(np.sum(row_weights[:, None] * np.square(matrix), axis=0))
    safe_rms = np.where(rms > 1e-12, rms, 1.0)
    scaled = matrix / safe_rms
    theta0 = CURRENT_PAIRWISE_WEIGHTS * safe_rms / TEMPERATURE_CP
    theta = theta0.copy()

    def objective(candidate: np.ndarray) -> float:
        margins = scaled @ candidate
        data_loss = float(np.sum(row_weights * np.logaddexp(0.0, -margins)))
        delta = candidate - theta0
        return data_loss + 0.5 * ridge * float(delta @ delta)

    converged = False
    iterations = 0
    for iteration in range(1, maximum_iterations + 1):
        iterations = iteration
        margins = scaled @ theta
        negative_probability = sigmoid_negative(margins)
        delta = theta - theta0
        gradient = -scaled.T @ (row_weights * negative_probability) + ridge * delta
        curvature = row_weights * negative_probability * (1.0 - negative_probability)
        hessian = scaled.T @ (curvature[:, None] * scaled)
        hessian += ridge * np.eye(len(theta), dtype=np.float64)
        try:
            direction = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            direction = np.linalg.lstsq(hessian, gradient, rcond=None)[0]
        if float(np.max(np.abs(gradient))) < 1e-10:
            converged = True
            break
        current_objective = objective(theta)
        directional = float(gradient @ direction)
        step = 1.0
        while step >= 2.0 ** -24:
            candidate = theta - step * direction
            if objective(candidate) <= current_objective - 1e-4 * step * directional:
                theta = candidate
                break
            step *= 0.5
        else:
            break
        if float(np.max(np.abs(step * direction))) < 1e-10:
            converged = True
            break

    fitted = theta * TEMPERATURE_CP / safe_rms
    return {
        "weights": fitted,
        "ridge": ridge,
        "iterations": iterations,
        "converged": converged,
        "objective": objective(theta),
        "feature_rms": rms,
    }


def margins(rows: Sequence[dict], weights: np.ndarray) -> np.ndarray:
    return as_matrix(rows) @ weights


def weighted_logistic_loss(rows: Sequence[dict], weights: np.ndarray) -> float:
    row_weights = game_position_pair_weights(rows)
    scaled_margins = margins(rows, weights) / TEMPERATURE_CP
    return float(np.sum(row_weights * np.logaddexp(0.0, -scaled_margins)))


def position_rows(rows: Sequence[dict], weights: np.ndarray) -> list[dict]:
    by_position: dict[str, list[tuple[dict, float]]] = defaultdict(list)
    for row, margin in zip(rows, margins(rows, weights), strict=True):
        by_position[row["id"]].append((row, float(margin)))
    output: list[dict] = []
    for position_id, entries in by_position.items():
        sample = entries[0][0]
        values = [value for _row, value in entries]
        output.append(
            {
                "id": position_id,
                "game_id": sample["game_id"],
                "classification": sample["classification"],
                "piece_count": sample["piece_count"],
                "pairs": len(values),
                "in_best_tie": all(value >= 0.0 for value in values),
                "unique_best": all(value > 0.0 for value in values),
                "rank": 1 + sum(value < 0.0 for value in values),
                "positive_pairs": sum(value > 0.0 for value in values),
                "zero_pairs": sum(value == 0.0 for value in values),
            }
        )
    return sorted(output, key=lambda row: row["id"])


def game_equal_average(rows: Sequence[dict], field: str) -> float:
    by_game: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_game[row["game_id"]].append(float(row[field]))
    return float(np.mean([np.mean(values) for values in by_game.values()]))


def metrics(rows: Sequence[dict], weights: np.ndarray) -> dict:
    pair_margins = margins(rows, weights)
    positions = position_rows(rows, weights)
    return {
        "games": len({row["game_id"] for row in rows}),
        "positions": len(positions),
        "pairs": len(rows),
        "game_position_equal_logistic_loss": weighted_logistic_loss(rows, weights),
        "pair_positive": int(np.count_nonzero(pair_margins > 0.0)),
        "pair_zero": int(np.count_nonzero(pair_margins == 0.0)),
        "pair_negative": int(np.count_nonzero(pair_margins < 0.0)),
        "pair_positive_rate": float(np.mean(pair_margins > 0.0)),
        "in_best_tie": sum(row["in_best_tie"] for row in positions),
        "in_best_tie_rate": float(np.mean([row["in_best_tie"] for row in positions])),
        "game_equal_in_best_tie_rate": game_equal_average(positions, "in_best_tie"),
        "unique_best": sum(row["unique_best"] for row in positions),
        "unique_best_rate": float(np.mean([row["unique_best"] for row in positions])),
        "game_equal_unique_best_rate": game_equal_average(positions, "unique_best"),
        "mean_reciprocal_rank": float(np.mean([1.0 / row["rank"] for row in positions])),
        "game_equal_mean_reciprocal_rank": game_equal_average(
            [{**row, "reciprocal_rank": 1.0 / row["rank"]} for row in positions],
            "reciprocal_rank",
        ),
    }


def phase_band(piece_count: int) -> str:
    if piece_count >= 13:
        return "13_to_16"
    if piece_count >= 9:
        return "9_to_12"
    return "5_to_8"


def breakdown_metrics(rows: Sequence[dict], weights: np.ndarray) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[f"phase:{phase_band(row['piece_count'])}"].append(row)
        groups[f"class:{row['classification']}"].append(row)
    return {
        name: metrics(group, weights)
        for name, group in sorted(groups.items())
        if group
    }


def cv_manifest(train_games: set[str]) -> list[dict]:
    ranked = sorted(
        train_games,
        key=lambda game_id: hashlib.sha256(
            f"{CV_SALT}|{game_id}".encode("utf-8")
        ).hexdigest(),
    )
    return [
        {"game_id": game_id, "fold": index % CV_FOLDS}
        for index, game_id in enumerate(ranked)
    ]


def cross_validate(train_rows: Sequence[dict], train_games: set[str]) -> dict:
    manifest = cv_manifest(train_games)
    fold_by_game = {row["game_id"]: row["fold"] for row in manifest}
    grid: list[dict] = []
    for ridge in RIDGE_GRID:
        folds: list[dict] = []
        for fold in range(CV_FOLDS):
            fit_rows = [
                row for row in train_rows if fold_by_game[row["game_id"]] != fold
            ]
            validation_rows = [
                row for row in train_rows if fold_by_game[row["game_id"]] == fold
            ]
            fitted = fit_pairwise(fit_rows, ridge=ridge)
            candidate_metrics = metrics(validation_rows, fitted["weights"])
            rounded_metrics = metrics(
                validation_rows,
                np.asarray([round(value) for value in fitted["weights"]], dtype=float),
            )
            current_metrics = metrics(validation_rows, CURRENT_PAIRWISE_WEIGHTS)
            folds.append(
                {
                    "fold": fold,
                    "train_games": len({row["game_id"] for row in fit_rows}),
                    "validation_games": len(
                        {row["game_id"] for row in validation_rows}
                    ),
                    "converged": fitted["converged"],
                    "iterations": fitted["iterations"],
                    "weights": {
                        name: float(value)
                        for name, value in zip(
                            PAIRWISE_FEATURE_NAMES,
                            fitted["weights"],
                            strict=True,
                        )
                    },
                    "current": current_metrics,
                    "candidate": candidate_metrics,
                    "candidate_rounded": rounded_metrics,
                    "loss_improvement": (
                        current_metrics["game_position_equal_logistic_loss"]
                        - candidate_metrics["game_position_equal_logistic_loss"]
                    ),
                    "rounded_loss_improvement": (
                        current_metrics["game_position_equal_logistic_loss"]
                        - rounded_metrics["game_position_equal_logistic_loss"]
                    ),
                }
            )
        losses = np.asarray(
            [fold["candidate"]["game_position_equal_logistic_loss"] for fold in folds],
            dtype=np.float64,
        )
        improvements = [fold["loss_improvement"] for fold in folds]
        rounded_improvements = [
            fold["rounded_loss_improvement"] for fold in folds
        ]
        grid.append(
            {
                "ridge": ridge,
                "mean_validation_loss": float(np.mean(losses)),
                "validation_loss_standard_error": float(
                    np.std(losses, ddof=1) / math.sqrt(len(losses))
                ),
                "mean_loss_improvement": float(np.mean(improvements)),
                "folds_improved": sum(value > 0.0 for value in improvements),
                "mean_rounded_loss_improvement": float(
                    np.mean(rounded_improvements)
                ),
                "rounded_folds_improved": sum(
                    value > 0.0 for value in rounded_improvements
                ),
                "folds": folds,
            }
        )
    best = min(grid, key=lambda row: (row["mean_validation_loss"], -row["ridge"]))
    threshold = (
        best["mean_validation_loss"] + best["validation_loss_standard_error"]
    )
    eligible = [row for row in grid if row["mean_validation_loss"] <= threshold]
    selected = max(eligible, key=lambda row: row["ridge"])
    return {
        "folds": CV_FOLDS,
        "salt": CV_SALT,
        "manifest": manifest,
        "grid": grid,
        "minimum_loss_ridge": best["ridge"],
        "minimum_mean_validation_loss": best["mean_validation_loss"],
        "one_standard_error_threshold": threshold,
        "selection_rule": "largest ridge within one standard error of minimum loss",
        "selected_ridge": selected["ridge"],
        "selected_grid_result": selected,
    }


def coefficient_stability(cv: dict) -> dict:
    folds = cv["selected_grid_result"]["folds"]
    result: dict[str, dict] = {}
    for name in PAIRWISE_FEATURE_NAMES:
        values = np.asarray([fold["weights"][name] for fold in folds], dtype=float)
        result[name] = {
            "mean": float(np.mean(values)),
            "standard_deviation": float(np.std(values, ddof=1)),
            "minimum": float(np.min(values)),
            "maximum": float(np.max(values)),
            "all_same_sign": bool(np.all(values > 0.0) or np.all(values < 0.0)),
        }
    return result


def pathology_checks(weights: np.ndarray) -> dict:
    active = dict(zip(PAIRWISE_FEATURE_NAMES, weights, strict=True))
    checks = {
        "all_finite": bool(np.all(np.isfinite(weights))),
        "men_positive": bool(active["men"] > 0.0),
        "king_more_than_man": bool(active["kings"] > active["men"]),
        "man_pst_nonnegative": bool(active["man_pst"] >= 0.0),
        "king_pst_nonnegative": bool(active["king_pst"] >= 0.0),
        "support_nonnegative": bool(active["support"] >= 0.0),
        "back_rank_nonnegative": bool(active["back_rank"] >= 0.0),
        "passed_men_nonnegative": bool(active["passed_men"] >= 0.0),
        "king_edge_nonpositive": bool(active["king_edge"] <= 0.0),
        "king_mobility_nonnegative": bool(active["king_mobility"] >= 0.0),
    }
    return {
        "checks": checks,
        "all_pass": all(checks.values()),
        "failed": [name for name, passed in checks.items() if not passed],
    }


def human_margins(weights: np.ndarray) -> list[dict]:
    output: list[dict] = []
    for item in HUMAN_DIVERGENCES:
        state = parse_position(
            item["position"],
            reversible_plies=item["reversible_plies"],
        )
        children = child_feature_vectors(state)
        played = children[item["played_move"]]
        if played is None:
            raise RuntimeError(f"human regression {item['id']} played move is terminal")
        comparisons = []
        for alternative_move in item["deeper_alternatives"]:
            alternative = children[alternative_move]
            if alternative is None:
                raise RuntimeError(
                    f"human regression {item['id']} alternative is terminal"
                )
            delta = (alternative - played)[PAIRWISE_INDICES]
            comparisons.append(
                {
                    "alternative_move": alternative_move,
                    "current_margin_cp": float(delta @ CURRENT_PAIRWISE_WEIGHTS),
                    "candidate_margin_cp": float(delta @ weights),
                }
            )
        output.append(
            {
                "id": item["id"],
                "played_move": item["played_move"],
                "evidence": item["evidence"],
                "comparisons": comparisons,
            }
        )
    return output


def game_bootstrap(
    rows: Sequence[dict],
    current_weights: np.ndarray,
    candidate_weights: np.ndarray,
    *,
    samples: int = 20_000,
    seed: int = 20262065,
) -> dict:
    games = sorted({row["game_id"] for row in rows})
    per_game = []
    for game_id in games:
        game_rows = [row for row in rows if row["game_id"] == game_id]
        current = metrics(game_rows, current_weights)
        candidate = metrics(game_rows, candidate_weights)
        per_game.append(
            {
                "game_id": game_id,
                "loss_delta_candidate_minus_current": (
                    candidate["game_position_equal_logistic_loss"]
                    - current["game_position_equal_logistic_loss"]
                ),
                "top_tie_delta_candidate_minus_current": (
                    candidate["in_best_tie_rate"] - current["in_best_tie_rate"]
                ),
            }
        )
    rng = random.Random(seed)
    loss_samples: list[float] = []
    top_samples: list[float] = []
    for _ in range(samples):
        selected = [per_game[rng.randrange(len(per_game))] for _game in games]
        loss_samples.append(float(np.mean([
            row["loss_delta_candidate_minus_current"] for row in selected
        ])))
        top_samples.append(float(np.mean([
            row["top_tie_delta_candidate_minus_current"] for row in selected
        ])))
    return {
        "unit": "source game",
        "games": len(games),
        "samples": samples,
        "seed": seed,
        "per_game": per_game,
        "loss_delta_mean": float(np.mean(loss_samples)),
        "loss_delta_95pct": [
            float(np.percentile(loss_samples, 2.5)),
            float(np.percentile(loss_samples, 97.5)),
        ],
        "top_tie_delta_mean": float(np.mean(top_samples)),
        "top_tie_delta_95pct": [
            float(np.percentile(top_samples, 2.5)),
            float(np.percentile(top_samples, 97.5)),
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "corpora" / "middlegame_search_v5.jsonl",
    )
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=ROOT / "build" / "middlegame_v5" / "selection_manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "middlegame_v5" / "hce_pairwise_fit.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    corpus = args.corpus.resolve()
    split_manifest = args.split_manifest.resolve()
    _metadata, samples = load_corpus(corpus)
    train_games, holdout_games, split_rows, split_provenance = locked_game_split(
        samples,
        split_manifest,
    )
    _roots, _rankings, pairs, terminal_exclusions = build_measurements(
        samples,
        train_games,
    )
    train_rows = [row for row in pairs if row["split"] == "train"]
    holdout_rows = [row for row in pairs if row["split"] == "holdout"]

    cv = cross_validate(train_rows, train_games)
    final_fit = fit_pairwise(train_rows, ridge=cv["selected_ridge"])
    candidate = final_fit["weights"]
    rounded = np.asarray([round(value) for value in candidate], dtype=np.float64)
    train_current = metrics(train_rows, CURRENT_PAIRWISE_WEIGHTS)
    train_candidate = metrics(train_rows, candidate)
    train_rounded = metrics(train_rows, rounded)

    # Locked holdout is evaluated only after the CV choice and final fit exist.
    holdout_current = metrics(holdout_rows, CURRENT_PAIRWISE_WEIGHTS)
    holdout_candidate = metrics(holdout_rows, candidate)
    holdout_rounded = metrics(holdout_rows, rounded)
    pathology = pathology_checks(candidate)
    rounded_pathology = pathology_checks(rounded)
    cv_selected = cv["selected_grid_result"]
    candidate_build_justified = (
        cv_selected["rounded_folds_improved"] >= 5
        and cv_selected["mean_rounded_loss_improvement"] > 0.0
        and holdout_rounded["game_position_equal_logistic_loss"]
        < holdout_current["game_position_equal_logistic_loss"]
        and holdout_rounded["game_equal_in_best_tie_rate"]
        > holdout_current["game_equal_in_best_tie_rate"]
        and rounded_pathology["all_pass"]
    )
    payload = {
        "format": FORMAT,
        "purpose": (
            "measurement-only grouped pairwise HCE fit; no playing weights changed"
        ),
        "corpus": str(corpus),
        "corpus_sha256": sha256(corpus),
        "split_manifest": str(split_manifest),
        "split_manifest_sha256": sha256(split_manifest),
        "split_provenance": split_provenance,
        "split": split_rows,
        "train_games": len(train_games),
        "holdout_games": len(holdout_games),
        "train_positions": len({row["id"] for row in train_rows}),
        "holdout_positions": len({row["id"] for row in holdout_rows}),
        "terminal_child_exclusions": terminal_exclusions,
        "label_caveat": (
            "accepted self-search stability labels are observational, not ground truth"
        ),
        "features": list(PAIRWISE_FEATURE_NAMES),
        "fixed_weight": {"simplification": 6.0},
        "temperature_cp": TEMPERATURE_CP,
        "weighting": (
            "each source game equal, each position within game equal, each alternative within position equal"
        ),
        "current_weights": {
            name: float(value)
            for name, value in zip(
                PAIRWISE_FEATURE_NAMES,
                CURRENT_PAIRWISE_WEIGHTS,
                strict=True,
            )
        },
        "ridge_grid": list(RIDGE_GRID),
        "cross_validation": cv,
        "coefficient_stability_at_selected_ridge": coefficient_stability(cv),
        "final_fit": {
            "ridge": final_fit["ridge"],
            "iterations": final_fit["iterations"],
            "converged": final_fit["converged"],
            "objective": final_fit["objective"],
            "candidate_weights_float": {
                name: float(value)
                for name, value in zip(
                    PAIRWISE_FEATURE_NAMES,
                    candidate,
                    strict=True,
                )
            },
            "candidate_weights_rounded": {
                name: int(value)
                for name, value in zip(
                    PAIRWISE_FEATURE_NAMES,
                    rounded,
                    strict=True,
                )
            },
            "pathology_checks_float": pathology,
            "pathology_checks_rounded": rounded_pathology,
        },
        "train_metrics": {
            "current": train_current,
            "candidate_float": train_candidate,
            "candidate_rounded": train_rounded,
            "current_breakdown": breakdown_metrics(
                train_rows, CURRENT_PAIRWISE_WEIGHTS
            ),
            "candidate_rounded_breakdown": breakdown_metrics(train_rows, rounded),
        },
        "locked_holdout_metrics": {
            "current": holdout_current,
            "candidate_float": holdout_candidate,
            "candidate_rounded": holdout_rounded,
            "current_breakdown": breakdown_metrics(
                holdout_rows, CURRENT_PAIRWISE_WEIGHTS
            ),
            "candidate_rounded_breakdown": breakdown_metrics(
                holdout_rows, rounded
            ),
        },
        "locked_holdout_game_bootstrap_rounded": game_bootstrap(
            holdout_rows,
            CURRENT_PAIRWISE_WEIGHTS,
            rounded,
        ),
        "human_regression_margins_float": human_margins(candidate),
        "human_regression_margins_rounded": human_margins(rounded),
        "conclusion": {
            "candidate_build_justified": candidate_build_justified,
            "strength_promotion_justified": False,
            "reason": (
                "build one opt-in rounded-weight candidate for correctness and "
                "paired strength testing"
                if candidate_build_justified
                else "measurement fit failed CV/holdout/sign gates; do not build"
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    brief = {
        "output": str(args.output.resolve()),
        "selected_ridge": cv["selected_ridge"],
        "cv_selected": {
            key: cv_selected[key]
            for key in (
                "mean_validation_loss",
                "validation_loss_standard_error",
                "mean_loss_improvement",
                "folds_improved",
                "mean_rounded_loss_improvement",
                "rounded_folds_improved",
            )
        },
        "weights_float": payload["final_fit"]["candidate_weights_float"],
        "weights_rounded": payload["final_fit"]["candidate_weights_rounded"],
        "pathology": pathology,
        "train": {
            "current": train_current,
            "candidate_rounded": train_rounded,
        },
        "holdout": {
            "current": holdout_current,
            "candidate_rounded": holdout_rounded,
        },
        "bootstrap": payload["locked_holdout_game_bootstrap_rounded"],
        "human": payload["human_regression_margins_rounded"],
        "conclusion": payload["conclusion"],
    }
    print(json.dumps(brief, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
