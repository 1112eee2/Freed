"""Reproducible, measurement-only audit for the first Thai Makhos NNUE phase.

This script does not train a model and does not alter engine behavior.  It
summarizes the locked classical control and the label coverage that actually
exists, then evaluates predeclared design/training-readiness gates.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
ACCEPTED_SHA256 = (
    "feedd39cf16e5f5abc236452be897abe1ecf26b8ba7adcda4a25022b868c3ddd"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_jsonl(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    if not rows or not isinstance(rows[0], dict) or rows[0].get("kind") != "metadata":
        raise ValueError(f"{path} must start with a metadata row")
    samples = rows[1:]
    if any(not isinstance(row, dict) or row.get("kind") != "sample" for row in samples):
        raise ValueError(f"{path} contains a non-sample data row")
    return rows[0], samples


def sorted_counts(values: Iterable[object]) -> dict[str, int]:
    counts = Counter(str(value) for value in values)
    return dict(sorted(counts.items()))


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index]


def exact_summary(path: Path) -> dict[str, Any]:
    metadata, samples = load_jsonl(path)
    if metadata.get("format") != "thai-makhos-exact-wdl-eval-v1":
        raise ValueError("unexpected exact-WDL corpus format")
    if metadata.get("sample_count") != len(samples):
        raise ValueError("exact-WDL metadata sample count does not match rows")
    unique_positions = {
        (row["position"], int(row.get("reversible_plies", 0))) for row in samples
    }
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "samples": len(samples),
        "unique_position_clocks": len(unique_positions),
        "piece_counts": sorted_counts(row["piece_count"] for row in samples),
        "outcomes": sorted_counts(row["outcome"] for row in samples),
        "splits": sorted_counts(row["split"] for row in samples),
        "turns": sorted_counts(row["turn"] for row in samples),
        "quiet_only": metadata.get("filters", {}).get("quiet_only") is True,
        "reversible_plies": sorted_counts(
            row.get("reversible_plies", 0) for row in samples
        ),
        "color_rotation_deduplicated": metadata.get("filters", {}).get(
            "color_rotation_deduplicated"
        )
        is True,
        "label_source": "exact ranked 4/5/6-piece WDL",
    }


def middlegame_summary(path: Path, summary_path: Path) -> dict[str, Any]:
    metadata, samples = load_jsonl(path)
    summary = load_json(summary_path)
    if metadata.get("format") != "thai-makhos-middlegame-search-v1":
        raise ValueError("unexpected middlegame corpus format")
    if metadata.get("sample_count") != len(samples):
        raise ValueError("middlegame metadata sample count does not match rows")
    if summary.get("corpus_sha256", "").lower() != sha256(path):
        raise ValueError("middlegame summary is bound to a different corpus")

    score_deltas: list[int] = []
    quiet = 0
    quiet_stable_delta50 = 0
    source_games: set[str] = set()
    source_libraries: set[str] = set()
    unique_positions: set[tuple[str, int]] = set()
    for row in samples:
        legal = row.get("legal_moves", [])
        is_quiet = not any("x" in move for move in legal)
        quiet += int(is_quiet)
        trace = row.get("search_trace", [])
        if len(trace) >= 2:
            delta = abs(int(trace[-1]["score"]) - int(trace[-2]["score"]))
            score_deltas.append(delta)
            if (
                is_quiet
                and row.get("label", {}).get("usable_for_supervised_training") is True
                and delta <= 50
            ):
                quiet_stable_delta50 += 1
        source = row.get("source", {})
        source_games.add(str(source.get("game_id")))
        source_libraries.add(str(source.get("library_sha256", "")).lower())
        unique_positions.add((row["position"], int(row.get("reversible_plies", 0))))

    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "summary_path": str(summary_path.resolve()),
        "summary_sha256": sha256(summary_path),
        "samples": len(samples),
        "unique_position_clocks": len(unique_positions),
        "source_games": len(source_games),
        "source_library_sha256": sorted(source_libraries),
        "samples_by_split": summary.get("samples_by_split"),
        "strict_by_split": summary.get("strict_by_split"),
        "classifications": sorted_counts(
            row.get("label", {}).get("classification") for row in samples
        ),
        "piece_counts": sorted_counts(row["piece_count"] for row in samples),
        "phase_bands": summary.get("phase_bands"),
        "turns": {
            "black": sum(row["position"].startswith("B:") for row in samples),
            "red": sum(row["position"].startswith("R:") for row in samples),
        },
        "mixed_king_positions": summary.get("mixed_king_positions"),
        "quiet_root_positions": quiet,
        "capture_root_positions": len(samples) - quiet,
        "reversible_clock": {
            "nonzero": sum(int(row.get("reversible_plies", 0)) > 0 for row in samples),
            "maximum": max(int(row.get("reversible_plies", 0)) for row in samples),
        },
        "last_two_score_delta_cp": {
            "median": percentile(score_deltas, 0.50),
            "p90": percentile(score_deltas, 0.90),
            "p95": percentile(score_deltas, 0.95),
            "at_most_25": sum(value <= 25 for value in score_deltas),
            "at_most_50": sum(value <= 50 for value in score_deltas),
            "at_most_100": sum(value <= 100 for value in score_deltas),
        },
        "quiet_strict_score_delta_at_most_50": quiet_stable_delta50,
        "has_game_outcome_labels": any("game_outcome" in row for row in samples),
        "label_source": "accepted-engine search stability, not ground truth",
    }


def external_summary(path: Path) -> dict[str, Any]:
    data = load_json(path)
    if data.get("format") != "thai-makhos-positional-regressions-v1":
        raise ValueError("unexpected positional-regression format")
    cases = data.get("cases", [])
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "cases": len(cases),
        "ids": [case.get("id") for case in cases],
        "evidence_kinds": sorted_counts(
            case.get("evidence", {}).get("kind") for case in cases
        ),
        "proven_best_move_labels": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exact",
        type=Path,
        default=ROOT / "corpora" / "exact_wdl_eval_v1.jsonl",
    )
    parser.add_argument(
        "--middlegame",
        type=Path,
        default=ROOT / "corpora" / "middlegame_search_v5.jsonl",
    )
    parser.add_argument(
        "--middlegame-summary",
        type=Path,
        default=ROOT / "build" / "middlegame_v5" / "summary.json",
    )
    parser.add_argument(
        "--external",
        type=Path,
        default=ROOT / "corpora" / "positional_regressions.json",
    )
    parser.add_argument(
        "--accepted-library",
        type=Path,
        default=ROOT / "build" / "makhos_native_accepted.dll",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "nnue_readiness_v1.json",
    )
    args = parser.parse_args()

    accepted_hash = sha256(args.accepted_library)
    exact = exact_summary(args.exact)
    middlegame = middlegame_summary(args.middlegame, args.middlegame_summary)
    external = external_summary(args.external)

    design_gates = {
        "accepted_control_locked": accepted_hash == ACCEPTED_SHA256,
        "exact_wdl_corpus_valid": exact["samples"] == 9000,
        "middlegame_game_split_present": set(middlegame["samples_by_split"] or {})
        == {"train", "holdout"},
        "middlegame_phase_coverage_present": set(middlegame["phase_bands"] or {})
        == {"13_to_16", "9_to_12", "5_to_8"},
        "external_regressions_present": external["cases"] >= 2,
    }
    training_gates = {
        "at_least_100000_broad_phase_quiet_scalar_labels": False,
        "broad_phase_independent_outcome_labels": False,
        "fresh_unopened_test_split": False,
        "quantized_python_native_parity": False,
        "incremental_native_inference_implemented": False,
    }
    report = {
        "format": "thai-makhos-nnue-readiness-v1",
        "accepted_control": {
            "path": str(args.accepted_library.resolve()),
            "sha256": accepted_hash,
            "expected_sha256": ACCEPTED_SHA256,
        },
        "corpora": {
            "exact_wdl": exact,
            "middlegame_search": middlegame,
            "external_regressions": external,
        },
        "gates": {
            "design": design_gates,
            "training": training_gates,
        },
        "design_ready": all(design_gates.values()),
        "training_ready": all(training_gates.values()),
        "verdict": "design-ready-data-not-training-ready",
        "highest_value_next_experiment": {
            "name": "quiet-leaf scalar-label acquisition pilot",
            "authorization_required": True,
            "playing_code_change": False,
            "model_training": False,
            "source_games": 256,
            "minimum_unique_quiet_positions": 8000,
            "split_before_sampling": "80/10/10 by source-game hash",
            "teacher": "byte-locked accepted DLL, one thread, persistent search",
            "budgets_ms": [100, 500, 2000],
            "sample_gate": "last-two score delta <= 50 cp and no mandatory capture",
            "required_checks": [
                "zero position or symmetry leakage across game splits",
                "all teacher DLL hashes equal the accepted control",
                "both turns each between 45 and 55 percent",
                "each 13-16, 9-12, and 5-8 piece band at least 20 percent",
                "at least 30 percent of positions contain a king",
                "record game outcome separately and never relabel truncations as draws",
            ],
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "sha256": sha256(args.output),
        "verdict": report["verdict"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
