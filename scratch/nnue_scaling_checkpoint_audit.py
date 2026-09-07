"""Create a reproducible development-only checkpoint during NNUE acquisition.

The first invocation locks the exact completed analysis-file set.  Later
invocations ignore newly completed files and reproduce the same checkpoint.
The sealed test manifest and test analyses are never opened.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scratch.nnue_quiet_leaf_acquire import (  # noqa: E402
    EXPECTED_ACCEPTED_SHA256,
    FORMAT as ACQUISITION_FORMAT,
    TEACHER_MAX_DEPTH,
    sha256,
    write_locked_json,
)


FORMAT = "thai-makhos-nnue-scaling-checkpoint-v1"
EXPECTED_CONFIG_SHA256 = (
    "B42B9369ED6CD40C7D19843674F191CCEE4E22BC137FD28F94C99B57177FA8A4"
)
DEFAULT_WORK_DIR = ROOT / "build" / "nnue_scaling_full_v1"
DEFAULT_OUTPUT = DEFAULT_WORK_DIR / "checkpoint_early_development.json"


def validate_analysis_payload(payload: dict, *, expected_name: str) -> None:
    expected = {
        "format": ACQUISITION_FORMAT,
        "kind": "game-analysis",
        "accepted_library_sha256": EXPECTED_ACCEPTED_SHA256,
        "threads": 1,
        "persistent_search": True,
        "budgets_ms": [100, 500, 2000],
        "teacher_max_depth": TEACHER_MAX_DEPTH,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(f"checkpoint analysis has stale {key}: {expected_name}")
    game_id = expected_name.removesuffix(".analysis.json")
    if payload.get("game_id") != game_id:
        raise RuntimeError(f"analysis filename/game id differs: {expected_name}")
    if payload.get("split") not in {"train", "validation"}:
        raise RuntimeError(f"test/unknown split entered checkpoint: {expected_name}")
    if not payload.get("selection_sha256"):
        raise RuntimeError(f"analysis lacks selection binding: {expected_name}")
    for row in payload.get("positions", []):
        if row.get("split") != payload["split"]:
            raise RuntimeError(f"position split differs: {expected_name}")
        searches = row.get("searches", [])
        if [search.get("budget_ms") for search in searches] != [100, 500, 2000]:
            raise RuntimeError(f"position teacher budgets differ: {expected_name}")
        if any(
            search.get("native_library_sha256") != EXPECTED_ACCEPTED_SHA256
            for search in searches
        ):
            raise RuntimeError(f"position teacher DLL differs: {expected_name}")


def summarize_payloads(payloads: list[dict]) -> dict:
    counts = Counter()
    elapsed_ms = 0.0
    for payload in payloads:
        counts[f"split_{payload['split']}"] += 1
        for row in payload["positions"]:
            counts["positions"] += 1
            searches = row["searches"]
            elapsed_ms += sum(float(search["elapsed_ms"]) for search in searches)
            if row["eligible"]:
                counts["eligible"] += 1
                counts[f"phase_{row['phase_band']}"] += 1
                counts[f"turn_{row['turn']}"] += 1
                counts["with_kings"] += int(row["king_count"] > 0)
                counts["with_exact_wdl"] += int(row.get("exact_wdl") is not None)
            else:
                counts[f"rejected_{row['gate_reason']}"] += 1
    games = len(payloads)
    positions = counts["positions"]
    eligible = counts["eligible"]
    return {
        "games": games,
        "positions": positions,
        "eligible": eligible,
        "eligible_percent": round(100.0 * eligible / positions, 6)
        if positions
        else 0.0,
        "eligible_per_game": round(eligible / games, 6) if games else 0.0,
        "with_kings": counts["with_kings"],
        "kings_per_game": round(counts["with_kings"] / games, 6)
        if games
        else 0.0,
        "phases": {
            phase: counts[f"phase_{phase}"]
            for phase in ("13_to_16", "9_to_12", "5_to_8")
        },
        "turns": {
            turn: counts[f"turn_{turn}"] for turn in ("black", "red")
        },
        "splits": {
            split: counts[f"split_{split}"] for split in ("train", "validation")
        },
        "rejections": {
            reason: value
            for key, value in sorted(counts.items())
            if key.startswith("rejected_")
            for reason in (key.removeprefix("rejected_"),)
        },
        "with_exact_wdl": counts["with_exact_wdl"],
        "teacher_elapsed_ms": round(elapsed_ms, 3),
    }


def build_checkpoint(
    work_dir: Path,
    *,
    output: Path,
    minimum_analyses: int,
) -> dict:
    work_dir = work_dir.resolve()
    output = output.resolve()
    analyses_dir = work_dir / "analyses"
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        names = [row["name"] for row in existing["analysis_files"]]
    else:
        paths = sorted(analyses_dir.glob("*.analysis.json"))
        if len(paths) < minimum_analyses:
            raise RuntimeError(
                f"checkpoint needs {minimum_analyses} analyses; found {len(paths)}"
            )
        names = [path.name for path in paths]
    if len(names) < minimum_analyses or len(set(names)) != len(names):
        raise RuntimeError("checkpoint analysis file set is too small or duplicated")

    config_path = work_dir / "config.json"
    commitment_path = work_dir / "selection_partition_commitment.json"
    full_manifest_path = work_dir / "full_run_manifest.json"
    if sha256(config_path) != EXPECTED_CONFIG_SHA256:
        raise RuntimeError("full-run config identity changed")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    accepted_path = Path(config["accepted_library"])
    if sha256(accepted_path) != EXPECTED_ACCEPTED_SHA256:
        raise RuntimeError("accepted DLL identity changed")
    commitment = json.loads(commitment_path.read_text(encoding="utf-8"))
    if commitment.get("test_analysis_files_may_be_read") is not False:
        raise RuntimeError("sealed-test read policy changed")

    payloads = []
    analysis_rows = []
    for name in names:
        path = analyses_dir / name
        if not path.exists():
            raise RuntimeError(f"captured analysis disappeared: {name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_analysis_payload(payload, expected_name=name)
        payloads.append(payload)
        analysis_rows.append({"name": name, "sha256": sha256(path)})
    stderr_bytes = sum(
        path.stat().st_size for path in work_dir.rglob("*.stderr.log")
    )
    temporary_files = sorted(str(path) for path in work_dir.rglob("*.tmp"))
    summary = summarize_payloads(payloads)
    checkpoint = {
        "format": FORMAT,
        "kind": "development-analysis-checkpoint",
        "playing_code_changed": False,
        "model_trained": False,
        "sealed_test_manifest_read": False,
        "test_analysis_files_read": 0,
        "accepted_library_sha256": EXPECTED_ACCEPTED_SHA256,
        "config_sha256": sha256(config_path),
        "commitment_sha256": sha256(commitment_path),
        "full_run_manifest_sha256": sha256(full_manifest_path),
        "development_manifest_sha256": commitment[
            "development_manifest_sha256"
        ],
        "sealed_test_manifest_sha256": commitment[
            "sealed_test_manifest_sha256"
        ],
        "audit_script_sha256": sha256(Path(__file__).resolve()),
        "analysis_files": analysis_rows,
        "summary": summary,
        "stderr_bytes": stderr_bytes,
        "temporary_files": temporary_files,
        "gates": {
            "minimum_analyses": len(analysis_rows) >= minimum_analyses,
            "accepted_only": True,
            "development_splits_only": True,
            "test_analysis_files_read_zero": True,
            "stderr_empty": stderr_bytes == 0,
            "temporary_files_empty": not temporary_files,
            "no_incomplete_search_labels": summary["rejections"].get(
                "incomplete_search", 0
            )
            == 0,
        },
    }
    if not all(checkpoint["gates"].values()):
        raise RuntimeError(f"checkpoint gate failed: {checkpoint['gates']}")
    return checkpoint


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--minimum-analyses", type=int, default=50)
    args = parser.parse_args()
    if args.minimum_analyses < 1:
        parser.error("minimum-analyses must be positive")
    checkpoint = build_checkpoint(
        args.work_dir,
        output=args.output,
        minimum_analyses=args.minimum_analyses,
    )
    write_locked_json(args.output.resolve(), checkpoint)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": sha256(args.output.resolve()),
                "games": checkpoint["summary"]["games"],
                "eligible": checkpoint["summary"]["eligible"],
                "test_analysis_files_read": 0,
                "verdict": "PASS",
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
