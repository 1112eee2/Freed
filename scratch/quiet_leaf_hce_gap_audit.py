"""Measure static-HCE gaps against quiet-leaf teacher scores.

This is a data-quality diagnostic, not a weight fitter.  It defaults to the
train split and deliberately refuses an incomplete acquisition unless the
caller records that choice with ``--allow-partial``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import parse_position
from makhos.eval import evaluate_handcrafted
from scratch.nnue_quiet_leaf_acquire import (
    validate_existing_analysis,
    validate_selection_manifest,
)


FORMAT = "thai-makhos-quiet-leaf-hce-gap-v1"
DEFAULT_WORK_DIR = ROOT / "build" / "nnue_quiet_leaf_pilot_v4"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def percentile(values: Iterable[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("percentile fraction must be in 0..1")
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def pair_metrics(rows: list[dict], target_key: str) -> dict:
    if not rows:
        return {"positions": 0}
    hce = [float(row["hce_score"]) for row in rows]
    target = [float(row[target_key]) for row in rows]
    residuals = [second - first for first, second in zip(hce, target)]
    absolute = [abs(value) for value in residuals]
    hce_mean = statistics.fmean(hce)
    target_mean = statistics.fmean(target)
    covariance = sum(
        (first - hce_mean) * (second - target_mean)
        for first, second in zip(hce, target)
    )
    hce_variance = sum((value - hce_mean) ** 2 for value in hce)
    target_variance = sum((value - target_mean) ** 2 for value in target)
    correlation = (
        covariance / math.sqrt(hce_variance * target_variance)
        if hce_variance and target_variance
        else None
    )
    sign_matches = sum(
        ((first > 0) - (first < 0)) == ((second > 0) - (second < 0))
        for first, second in zip(hce, target)
    )
    return {
        "positions": len(rows),
        "mean_hce": statistics.fmean(hce),
        "mean_target": statistics.fmean(target),
        "bias_target_minus_hce": statistics.fmean(residuals),
        "mae": statistics.fmean(absolute),
        "rmse": math.sqrt(statistics.fmean(value * value for value in residuals)),
        "absolute_residual_p50": percentile(absolute, 0.50),
        "absolute_residual_p90": percentile(absolute, 0.90),
        "absolute_residual_p95": percentile(absolute, 0.95),
        "pearson": correlation,
        "sign_agreement_percent": 100.0 * sign_matches / len(rows),
    }


def summarize_rows(rows: list[dict], budgets_ms: tuple[int, ...]) -> dict:
    groups = {
        "all": rows,
        "with_kings": [row for row in rows if row["king_count"] > 0],
        "without_kings": [row for row in rows if row["king_count"] == 0],
    }
    for phase in ("13_to_16", "9_to_12", "5_to_8"):
        groups[phase] = [row for row in rows if row["phase_band"] == phase]
    for turn in ("black", "red"):
        groups[f"turn_{turn}"] = [row for row in rows if row["turn"] == turn]

    summaries: dict[str, dict] = {}
    for name, group in groups.items():
        target_metrics = {
            str(budget): pair_metrics(group, f"score_{budget}ms")
            for budget in budgets_ms
        }
        ladder_delta: dict[str, dict] = {}
        for first, second in zip(budgets_ms, budgets_ms[1:]):
            differences = [
                abs(row[f"score_{second}ms"] - row[f"score_{first}ms"])
                for row in group
            ]
            ladder_delta[f"{first}_to_{second}ms"] = (
                {
                    "positions": len(differences),
                    "mean_absolute_delta": statistics.fmean(differences),
                    "p90_absolute_delta": percentile(differences, 0.90),
                }
                if differences
                else {"positions": 0}
            )
        summaries[name] = {
            "teacher": pair_metrics(group, "teacher_score"),
            "search_budgets": target_metrics,
            "search_ladder_delta": ladder_delta,
        }
    return summaries


def load_rows(
    work_dir: Path,
    *,
    split: str,
    allow_partial: bool,
) -> tuple[list[dict], dict]:
    config_path = work_dir / "config.json"
    manifest_path = work_dir / "selection_manifest.json"
    analyses_dir = work_dir / "analyses"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_selection_manifest(manifest)
    games = {game["game_id"]: game for game in manifest["games"]}
    analysis_paths = sorted(analyses_dir.glob("*.analysis.json"))
    if len(analysis_paths) != len(games) and not allow_partial:
        raise RuntimeError(
            f"acquisition is incomplete: {len(analysis_paths)}/{len(games)} analyses"
        )

    seen_games: set[str] = set()
    seen_positions: set[str] = set()
    teacher_hashes: set[str] = set()
    analysis_hash_rows: list[str] = []
    rows: list[dict] = []
    for path in analysis_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        game_id = payload.get("game_id")
        game = games.get(game_id)
        if game is None:
            raise RuntimeError(f"analysis references an unselected game: {path}")
        if game_id in seen_games:
            raise RuntimeError(f"duplicate game analysis: {game_id}")
        seen_games.add(game_id)
        validate_existing_analysis(
            payload,
            game=game,
            library_sha256=config["accepted_library_sha256"],
            budgets_ms=config["budgets_ms"],
        )
        expected_ids = {
            selected["canonical_position_id"] for selected in game["selected"]
        }
        actual_ids = {
            position["canonical_position_id"] for position in payload["positions"]
        }
        if expected_ids != actual_ids:
            raise RuntimeError(f"analysis selection differs from manifest: {game_id}")
        analysis_hash_rows.append(f"{game_id}:{sha256(path)}")

        for position in payload["positions"]:
            position_id = position["canonical_position_id"]
            if position_id in seen_positions:
                raise RuntimeError(f"duplicate canonical position: {position_id}")
            seen_positions.add(position_id)
            for search in position["searches"]:
                teacher_hashes.add(search["native_library_sha256"])
            if position["split"] != split or not position["eligible"]:
                continue
            state = parse_position(
                position["position"],
                reversible_plies=position["reversible_plies"],
            )
            row = {
                "phase_band": position["phase_band"],
                "king_count": position["king_count"],
                "turn": position["turn"],
                "hce_score": evaluate_handcrafted(state, state.turn),
                "teacher_score": position["teacher_score"],
            }
            for search in position["searches"]:
                row[f"score_{search['budget_ms']}ms"] = search["score"]
            rows.append(row)

    if teacher_hashes != {config["accepted_library_sha256"]}:
        raise RuntimeError(f"teacher DLL hashes differ from config: {teacher_hashes}")
    aggregate = hashlib.sha256(
        ("\n".join(analysis_hash_rows) + "\n").encode("ascii")
    ).hexdigest().upper()
    evidence = {
        "audit_script": str(Path(__file__).resolve()),
        "audit_script_sha256": sha256(Path(__file__).resolve()),
        "work_dir": str(work_dir),
        "config_sha256": sha256(config_path),
        "selection_manifest_sha256": sha256(manifest_path),
        "analysis_set_sha256": aggregate,
        "manifest_games": len(games),
        "analyses": len(analysis_paths),
        "partial": len(analysis_paths) != len(games),
        "unique_positions_validated": len(seen_positions),
        "teacher_library_sha256": config["accepted_library_sha256"],
        "ruleset_sha256": config["ruleset_sha256"],
        "budgets_ms": tuple(config["budgets_ms"]),
    }
    return rows, evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--split", choices=("train", "validation"), default="train")
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    work_dir = args.work_dir.resolve()
    output = (
        args.output.resolve()
        if args.output is not None
        else work_dir / "hce_gap_audit.json"
    )
    rows, evidence = load_rows(
        work_dir,
        split=args.split,
        allow_partial=args.allow_partial,
    )
    if not rows:
        raise RuntimeError(f"no eligible rows in split {args.split}")
    report = {
        "format": FORMAT,
        "kind": "measurement-only-static-hce-vs-quiet-leaf-teacher",
        "split": args.split,
        "model_selection_uses_test_split": False,
        "playing_code_changed": False,
        "inputs": evidence,
        "eligible_rows": len(rows),
        "groups": summarize_rows(rows, evidence["budgets_ms"]),
        "interpretation_guard": (
            "Teacher scores include search effects; aggregate gaps do not justify "
            "changing one HCE coefficient or promoting a playing candidate."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "QUIET_LEAF_HCE_GAP "
        + json.dumps(
            {
                "output": str(output),
                "sha256": sha256(output),
                "analyses": evidence["analyses"],
                "eligible_rows": len(rows),
                "partial": evidence["partial"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
