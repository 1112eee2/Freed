"""Held-out Texel-style tuning for the linear handcrafted evaluator."""

from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .eval import CURRENT_EVALUATION_WEIGHTS, EvaluationFeatures
from .eval_corpus import load_exact_wdl_corpus


FEATURE_NAMES = tuple(EvaluationFeatures.__dataclass_fields__)
OUTCOME_TARGET = {"loss": 0.0, "draw": 0.5, "win": 1.0}


def _arrays(samples: Sequence[Mapping]) -> tuple[np.ndarray, np.ndarray]:
    features = np.asarray([
        [float(sample["features"][name]) for name in FEATURE_NAMES]
        for sample in samples
    ], dtype=np.float64)
    targets = np.asarray([
        OUTCOME_TARGET[sample["outcome"]]
        for sample in samples
    ], dtype=np.float64)
    return features, targets


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    clipped = np.clip(logits, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _metrics(
    features: np.ndarray,
    targets: np.ndarray,
    beta: np.ndarray,
) -> dict[str, float]:
    probabilities = _sigmoid(features @ beta)
    epsilon = 1e-15
    cross_entropy = -np.mean(
        targets * np.log(np.clip(probabilities, epsilon, 1.0))
        + (1.0 - targets)
        * np.log(np.clip(1.0 - probabilities, epsilon, 1.0))
    )
    brier = np.mean((probabilities - targets) ** 2)
    decisive = targets != 0.5
    decisive_accuracy = np.mean(
        (probabilities[decisive] >= 0.5) == (targets[decisive] == 1.0)
    )
    return {
        "cross_entropy": float(cross_entropy),
        "brier": float(brier),
        "decisive_accuracy": float(decisive_accuracy),
    }


def _optimize_scale(
    features: np.ndarray,
    targets: np.ndarray,
    weights: np.ndarray,
) -> float:
    """Fit only sigmoid scale, leaving playing weights unchanged."""

    def loss(log_scale: float) -> float:
        scale = math.exp(log_scale)
        return _metrics(features, targets, weights / scale)["cross_entropy"]

    left, right = math.log(1.0), math.log(5000.0)
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    x1 = right - ratio * (right - left)
    x2 = left + ratio * (right - left)
    f1, f2 = loss(x1), loss(x2)
    for _ in range(80):
        if f1 > f2:
            left, x1, f1 = x1, x2, f2
            x2 = left + ratio * (right - left)
            f2 = loss(x2)
        else:
            right, x2, f2 = x2, x1, f1
            x1 = right - ratio * (right - left)
            f1 = loss(x1)
    return math.exp((left + right) / 2.0)


def fit_logistic_weights(
    features: np.ndarray,
    targets: np.ndarray,
    initial_beta: np.ndarray,
    *,
    ridge: float = 1.0,
    maximum_iterations: int = 100,
) -> tuple[np.ndarray, int]:
    """Fit soft W/D/L targets with Newton/IRLS and a weak prior."""

    if ridge < 0:
        raise ValueError("ridge must be non-negative")
    beta = initial_beta.copy()
    prior = initial_beta.copy()
    identity = np.eye(features.shape[1], dtype=np.float64)
    for iteration in range(1, maximum_iterations + 1):
        probabilities = _sigmoid(features @ beta)
        gradient = features.T @ (probabilities - targets)
        gradient += ridge * (beta - prior)
        variance = np.maximum(probabilities * (1.0 - probabilities), 1e-8)
        hessian = features.T @ (features * variance[:, None])
        hessian += ridge * identity
        step = np.linalg.solve(hessian, gradient)
        beta -= step
        if float(np.max(np.abs(step))) < 1e-9:
            return beta, iteration
    return beta, maximum_iterations


def audit_and_fit_corpus(
    corpus_path: str | Path,
    output_path: str | Path | None = None,
    *,
    ridge: float = 1.0,
) -> dict:
    metadata, samples = load_exact_wdl_corpus(corpus_path)
    train = tuple(sample for sample in samples if sample["split"] == "train")
    validation = tuple(
        sample for sample in samples if sample["split"] == "validation"
    )
    if not train or not validation:
        raise ValueError("corpus must contain train and validation samples")
    train_x, train_y = _arrays(train)
    validation_x, validation_y = _arrays(validation)
    current_weights = np.asarray(
        [CURRENT_EVALUATION_WEIGHTS[name] for name in FEATURE_NAMES],
        dtype=np.float64,
    )
    current_scale = _optimize_scale(train_x, train_y, current_weights)
    current_beta = current_weights / current_scale
    fitted_beta, iterations = fit_logistic_weights(
        train_x,
        train_y,
        current_beta,
        ridge=ridge,
    )
    man_index = FEATURE_NAMES.index("men")
    if fitted_beta[man_index] <= 0:
        raise RuntimeError("fitted man coefficient is not positive")
    candidate_scale = 100.0 / fitted_beta[man_index]
    candidate_weights = fitted_beta * candidate_scale
    current_train = _metrics(train_x, train_y, current_beta)
    current_validation = _metrics(validation_x, validation_y, current_beta)
    candidate_train = _metrics(train_x, train_y, fitted_beta)
    candidate_validation = _metrics(validation_x, validation_y, fitted_beta)
    current_losses = -(
        validation_y * np.log(np.clip(_sigmoid(validation_x @ current_beta), 1e-15, 1.0))
        + (1.0 - validation_y)
        * np.log(np.clip(1.0 - _sigmoid(validation_x @ current_beta), 1e-15, 1.0))
    )
    candidate_losses = -(
        validation_y * np.log(np.clip(_sigmoid(validation_x @ fitted_beta), 1e-15, 1.0))
        + (1.0 - validation_y)
        * np.log(np.clip(1.0 - _sigmoid(validation_x @ fitted_beta), 1e-15, 1.0))
    )
    deltas = current_losses - candidate_losses
    delta_error = float(np.std(deltas, ddof=1) / math.sqrt(len(deltas)))
    by_piece: dict[str, dict] = {}
    for piece_count in sorted({sample["piece_count"] for sample in validation}):
        indexes = np.asarray([
            index
            for index, sample in enumerate(validation)
            if sample["piece_count"] == piece_count
        ])
        by_piece[str(piece_count)] = {
            "samples": int(len(indexes)),
            "current": _metrics(
                validation_x[indexes], validation_y[indexes], current_beta
            ),
            "candidate": _metrics(
                validation_x[indexes], validation_y[indexes], fitted_beta
            ),
        }
    all_x, all_y = _arrays(samples)
    group_folds = np.asarray([
        int.from_bytes(
            hashlib.sha256(
                (
                    str(sample["piece_count"])
                    + ":"
                    + ",".join(str(value) for value in sample["signature"])
                ).encode("ascii")
            ).digest()[:4],
            "big",
        ) % 5
        for sample in samples
    ])
    cv_deltas: list[np.ndarray] = []
    cv_weights: list[np.ndarray] = []
    cv_folds: list[dict] = []
    for fold in range(5):
        test_mask = group_folds == fold
        train_mask = ~test_mask
        if not np.any(test_mask) or not np.any(train_mask):
            raise RuntimeError("signature-grouped cross-validation fold is empty")
        fold_scale = _optimize_scale(
            all_x[train_mask], all_y[train_mask], current_weights
        )
        fold_current_beta = current_weights / fold_scale
        fold_beta, fold_iterations = fit_logistic_weights(
            all_x[train_mask],
            all_y[train_mask],
            fold_current_beta,
            ridge=ridge,
        )
        current_probability = _sigmoid(all_x[test_mask] @ fold_current_beta)
        candidate_probability = _sigmoid(all_x[test_mask] @ fold_beta)
        fold_targets = all_y[test_mask]
        fold_current_loss = -(
            fold_targets * np.log(np.clip(current_probability, 1e-15, 1.0))
            + (1.0 - fold_targets)
            * np.log(np.clip(1.0 - current_probability, 1e-15, 1.0))
        )
        fold_candidate_loss = -(
            fold_targets * np.log(np.clip(candidate_probability, 1e-15, 1.0))
            + (1.0 - fold_targets)
            * np.log(np.clip(1.0 - candidate_probability, 1e-15, 1.0))
        )
        fold_delta = fold_current_loss - fold_candidate_loss
        cv_deltas.append(fold_delta)
        fold_scale_to_man = 100.0 / fold_beta[man_index]
        cv_weights.append(fold_beta * fold_scale_to_man)
        cv_folds.append({
            "fold": fold,
            "held_out_samples": int(np.sum(test_mask)),
            "held_out_signatures": len({
                (
                    sample["piece_count"],
                    tuple(sample["signature"]),
                )
                for index, sample in enumerate(samples)
                if test_mask[index]
            }),
            "iterations": fold_iterations,
            "cross_entropy_improvement": float(np.mean(fold_delta)),
        })
    cv_delta = np.concatenate(cv_deltas)
    cv_weight_array = np.asarray(cv_weights)
    cv_error = float(np.std(cv_delta, ddof=1) / math.sqrt(len(cv_delta)))
    report = {
        "format": "thai-makhos-eval-fit-v1",
        "corpus": str(Path(corpus_path).resolve()),
        "corpus_format": metadata["format"],
        "train_samples": len(train),
        "validation_samples": len(validation),
        "feature_names": list(FEATURE_NAMES),
        "ridge": ridge,
        "iterations": iterations,
        "current": {
            "weights": dict(zip(FEATURE_NAMES, current_weights.tolist())),
            "sigmoid_scale": current_scale,
            "train": current_train,
            "validation": current_validation,
        },
        "candidate": {
            "weights_man_anchored_100": dict(
                zip(FEATURE_NAMES, candidate_weights.tolist())
            ),
            "sigmoid_scale": candidate_scale,
            "train": candidate_train,
            "validation": candidate_validation,
        },
        "held_out_cross_entropy_improvement": float(np.mean(deltas)),
        "held_out_improvement_standard_error": delta_error,
        "held_out_improvement_z": (
            float(np.mean(deltas)) / delta_error if delta_error > 0 else None
        ),
        "validation_by_piece_count": by_piece,
        "signature_grouped_5fold": {
            "folds": cv_folds,
            "cross_entropy_improvement": float(np.mean(cv_delta)),
            "improvement_standard_error": cv_error,
            "improvement_z": (
                float(np.mean(cv_delta)) / cv_error if cv_error > 0 else None
            ),
            "weight_mean_man_anchored_100": dict(
                zip(FEATURE_NAMES, np.mean(cv_weight_array, axis=0).tolist())
            ),
            "weight_standard_deviation": dict(
                zip(FEATURE_NAMES, np.std(cv_weight_array, axis=0).tolist())
            ),
        },
    }
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return report
