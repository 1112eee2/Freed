"""Size the next NNUE corpus from conservative whole-game yield evidence.

The audit reads only the development splits of the completed v4 pilot.  It
does not read test analysis files, train a model, or change playing code.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scratch.nnue_quiet_leaf_acquire import (  # noqa: E402
    validate_existing_analysis,
    validate_selection_manifest,
)


FORMAT = "thai-makhos-nnue-scaling-capacity-audit-v1"
DEFAULT_WORK_DIR = ROOT / "build" / "nnue_quiet_leaf_pilot_v4"
DEFAULT_OUTPUT = ROOT / "build" / "nnue_scaling_capacity_audit_v1.json"
METRICS = (
    "total",
    "with_kings",
    "phase_13_to_16",
    "phase_9_to_12",
    "phase_5_to_8",
    "turn_black",
    "turn_red",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("percentile fraction must be in 0..1")
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def wilson_lower_bound(successes: int, trials: int, z: float) -> float:
    if not 0 <= successes <= trials or trials < 1 or z <= 0.0:
        raise ValueError("invalid Wilson interval inputs")
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = proportion + z * z / (2.0 * trials)
    radius = z * math.sqrt(
        proportion * (1.0 - proportion) / trials
        + z * z / (4.0 * trials * trials)
    )
    return max(0.0, (center - radius) / denominator)


def bootstrap_mean_lower_bounds(
    rows: list[dict[str, int]],
    *,
    repetitions: int,
    seed: int,
    lower_fraction: float,
) -> dict[str, float]:
    if not rows or repetitions < 100:
        raise ValueError("bootstrap needs rows and at least 100 repetitions")
    if not 0.0 < lower_fraction < 0.5:
        raise ValueError("bootstrap lower fraction must be in 0..0.5")
    rng = random.Random(seed)
    size = len(rows)
    distributions = {metric: [] for metric in METRICS}
    for _ in range(repetitions):
        totals = {metric: 0 for metric in METRICS}
        for _sample in range(size):
            row = rows[rng.randrange(size)]
            for metric in METRICS:
                totals[metric] += row[metric]
        for metric in METRICS:
            distributions[metric].append(totals[metric] / size)
    return {
        metric: percentile(distributions[metric], lower_fraction)
        for metric in METRICS
    }


def required_source_files(
    *,
    per_unique_game_lcb: dict[str, float],
    unique_trajectory_rate_lcb: float,
    train_fraction: float,
    validation_fraction: float,
    test_fraction: float,
    requirements: dict[str, float],
    round_to: int,
) -> tuple[int, dict[str, int]]:
    if round_to < 1:
        raise ValueError("round-to must be positive")
    if min(unique_trajectory_rate_lcb, train_fraction, validation_fraction, test_fraction) <= 0:
        raise ValueError("rates and split fractions must be positive")
    source_files: dict[str, int] = {}
    for metric, required in requirements.items():
        if metric == "validation_total":
            rate = validation_fraction * per_unique_game_lcb["total"]
        elif metric == "sealed_test_total":
            rate = test_fraction * per_unique_game_lcb["total"]
        else:
            rate = train_fraction * per_unique_game_lcb[metric]
        rate *= unique_trajectory_rate_lcb
        if rate <= 0.0:
            raise RuntimeError(f"non-positive conservative yield for {metric}")
        source_files[metric] = math.ceil(required / rate)
    raw = max(source_files.values())
    rounded = math.ceil(raw / round_to) * round_to
    return rounded, source_files


def load_development_game_yields(work_dir: Path) -> tuple[list[dict], dict]:
    config_path = work_dir / "config.json"
    manifest_path = work_dir / "selection_manifest.json"
    analyses_dir = work_dir / "analyses"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_selection_manifest(manifest)
    rows = []
    analysis_hash_rows = []
    skipped_test_games = 0
    for game in manifest["games"]:
        if game["split"] == "test":
            skipped_test_games += 1
            continue
        path = analyses_dir / f"{game['game_id']}.analysis.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_existing_analysis(
            payload,
            game=game,
            library_sha256=config["accepted_library_sha256"],
            budgets_ms=config["budgets_ms"],
        )
        row = {metric: 0 for metric in METRICS}
        row["game_id"] = game["game_id"]
        row["split"] = game["split"]
        for position in payload["positions"]:
            if not position["eligible"]:
                continue
            row["total"] += 1
            row["with_kings"] += int(position["king_count"] > 0)
            row[f"phase_{position['phase_band']}"] += 1
            row[f"turn_{position['turn']}"] += 1
        rows.append(row)
        analysis_hash_rows.append(f"{game['game_id']}:{sha256(path)}")
    if not rows or skipped_test_games < 1:
        raise RuntimeError("development-only audit needs development and test games")
    evidence = {
        "config_sha256": sha256(config_path),
        "selection_manifest_sha256": sha256(manifest_path),
        "accepted_library_sha256": config["accepted_library_sha256"],
        "development_games_read": len(rows),
        "development_games_by_split": {
            split: sum(row["split"] == split for row in rows)
            for split in ("train", "validation")
        },
        "test_games_in_manifest": skipped_test_games,
        "test_analysis_files_read": 0,
        "development_analysis_set_sha256": hashlib.sha256(
            ("\n".join(analysis_hash_rows) + "\n").encode("ascii")
        ).hexdigest().upper(),
    }
    return rows, evidence


def measured_runtime_and_storage(work_dir: Path, run_manifest: dict) -> dict:
    resume = run_manifest.get("resume_history", [])[-1]
    started = datetime.fromisoformat(resume["started_local"])
    status_path = work_dir / "finalizer_status.json"
    ended = datetime.fromtimestamp(status_path.stat().st_mtime).astimezone()
    elapsed_seconds = max(0.0, (ended - started).total_seconds())
    initial = int(resume["initial_completed_analyses"])
    required = int(resume["required_analyses"])
    new_analyses = required - initial
    workers = len(resume["workers"])
    worker_seconds_per_analysis = (
        elapsed_seconds * workers / new_analyses if new_analyses > 0 else None
    )
    games_dir = work_dir / "games"
    analyses_dir = work_dir / "analyses"
    game_paths = list(games_dir.glob("*.json"))
    analysis_paths = list(analyses_dir.glob("*.analysis.json"))
    return {
        "resume_started_local": resume["started_local"],
        "finalizer_status_mtime_local": ended.isoformat(timespec="seconds"),
        "elapsed_seconds_including_finalization": elapsed_seconds,
        "new_analyses": new_analyses,
        "workers": workers,
        "worker_seconds_per_new_analysis": worker_seconds_per_analysis,
        "source_game_files": len(game_paths),
        "source_game_bytes": sum(path.stat().st_size for path in game_paths),
        "analysis_files": len(analysis_paths),
        "analysis_bytes": sum(path.stat().st_size for path in analysis_paths),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-repetitions", type=int, default=20_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20260825)
    parser.add_argument("--bootstrap-lower-fraction", type=float, default=0.01)
    parser.add_argument("--wilson-z", type=float, default=2.5758293035489004)
    parser.add_argument("--target-train-samples", type=int, default=100_000)
    parser.add_argument("--safety-margin", type=float, default=1.25)
    parser.add_argument("--train-fraction", type=float, default=0.8)
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument("--test-fraction", type=float, default=0.1)
    parser.add_argument("--minimum-validation-labels", type=int, default=10_000)
    parser.add_argument("--minimum-sealed-test-labels", type=int, default=10_000)
    parser.add_argument("--round-source-files", type=int, default=1024)
    parser.add_argument("--future-workers", type=int, default=6)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.bootstrap_repetitions < 100 or args.target_train_samples < 1:
        raise ValueError("bootstrap repetitions and target samples must be positive")
    if not math.isclose(
        args.train_fraction + args.validation_fraction + args.test_fraction,
        1.0,
        abs_tol=1e-12,
    ):
        raise ValueError("split fractions must sum to one")
    if args.safety_margin < 1.0 or args.future_workers < 1:
        raise ValueError("safety margin and future workers are invalid")

    work_dir = args.work_dir.resolve()
    output = args.output.resolve()
    rows, evidence = load_development_game_yields(work_dir)
    means = {
        metric: statistics.fmean(row[metric] for row in rows)
        for metric in METRICS
    }
    lower_bounds = bootstrap_mean_lower_bounds(
        rows,
        repetitions=args.bootstrap_repetitions,
        seed=args.bootstrap_seed,
        lower_fraction=args.bootstrap_lower_fraction,
    )
    summary = json.loads((work_dir / "summary.json").read_text(encoding="utf-8"))
    source_files = int(summary["games"]["count"])
    unique_trajectories = int(summary["games"]["unique_trajectories"])
    unique_rate_lcb = wilson_lower_bound(
        unique_trajectories,
        source_files,
        args.wilson_z,
    )
    target = args.target_train_samples
    margin = args.safety_margin
    requirements = {
        "total": target * margin,
        "with_kings": target * 0.30 * margin,
        "phase_13_to_16": target * 0.20 * margin,
        "phase_9_to_12": target * 0.20 * margin,
        "phase_5_to_8": target * 0.20 * margin,
        "turn_black": target * 0.45 * margin,
        "turn_red": target * 0.45 * margin,
        "validation_total": float(args.minimum_validation_labels),
        "sealed_test_total": float(args.minimum_sealed_test_labels),
    }
    recommended, by_requirement = required_source_files(
        per_unique_game_lcb=lower_bounds,
        unique_trajectory_rate_lcb=unique_rate_lcb,
        train_fraction=args.train_fraction,
        validation_fraction=args.validation_fraction,
        test_fraction=args.test_fraction,
        requirements=requirements,
        round_to=args.round_source_files,
    )
    projected_unique = recommended * unique_rate_lcb
    conservative_pools = {
        "train": {
            metric: projected_unique * args.train_fraction * lower_bounds[metric]
            for metric in METRICS
        },
        "validation_total": projected_unique
        * args.validation_fraction
        * lower_bounds["total"],
        "sealed_test_total": projected_unique
        * args.test_fraction
        * lower_bounds["total"],
    }
    run_manifest = json.loads(
        (work_dir / "acquisition_run_manifest.json").read_text(encoding="utf-8")
    )
    measured = measured_runtime_and_storage(work_dir, run_manifest)
    worker_seconds = measured["worker_seconds_per_new_analysis"]
    projected_teacher_hours = (
        projected_unique * worker_seconds / args.future_workers / 3600.0
        if worker_seconds is not None
        else None
    )
    projected_storage = {
        "source_game_bytes": recommended
        * measured["source_game_bytes"]
        / measured["source_game_files"],
        "analysis_bytes": projected_unique
        * measured["analysis_bytes"]
        / measured["analysis_files"],
    }
    report = {
        "format": FORMAT,
        "kind": "measurement-only-whole-game-scaling-capacity",
        "verdict": "SCALING_SIZE_READY_FOR_HARNESS_PREFLIGHT",
        "playing_code_changed": False,
        "model_trained": False,
        "test_policy": {
            "future_test_split": "fresh sealed whole-game manifest",
            "future_test_rows_may_select_model": False,
            "current_v4_test_analysis_files_read": 0,
        },
        "inputs": {
            **evidence,
            "audit_script": str(Path(__file__).resolve()),
            "audit_script_sha256": sha256(Path(__file__).resolve()),
        },
        "bootstrap": {
            "unit": "source game",
            "repetitions": args.bootstrap_repetitions,
            "seed": args.bootstrap_seed,
            "lower_fraction": args.bootstrap_lower_fraction,
            "observed_mean_eligible_per_unique_game": means,
            "lower_bound_eligible_per_unique_game": lower_bounds,
        },
        "deduplication": {
            "observed_source_files": source_files,
            "observed_unique_trajectories": unique_trajectories,
            "observed_unique_rate": unique_trajectories / source_files,
            "wilson_z": args.wilson_z,
            "unique_rate_lower_bound": unique_rate_lcb,
        },
        "sizing_contract": {
            "split_fractions": {
                "train": args.train_fraction,
                "validation": args.validation_fraction,
                "test": args.test_fraction,
            },
            "target_train_samples": target,
            "safety_margin": margin,
            "requirements": requirements,
            "source_files_required_by_requirement": by_requirement,
            "round_source_files_to": args.round_source_files,
            "recommended_fresh_source_files": recommended,
            "conservative_projected_pools": conservative_pools,
        },
        "resource_projection": {
            "measurement": measured,
            "future_whole_game_workers": args.future_workers,
            "teacher_acquisition_wall_hours_including_observed_finalization_overhead": projected_teacher_hours,
            "generation_runtime_is_not_measured_by_this_artifact": True,
            "projected_storage_bytes": projected_storage,
        },
        "next_gate": (
            "build and test a generation-sharded, analysis-sharded acquisition "
            "harness with a sealed fresh test manifest; run a bounded fresh-seed "
            "throughput/capacity preflight before full generation"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    output.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "sha256": sha256(output),
                "development_games": len(rows),
                "test_analysis_files_read": 0,
                "recommended_fresh_source_files": recommended,
                "verdict": report["verdict"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
