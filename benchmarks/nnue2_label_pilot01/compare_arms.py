"""Offline comparison of trained pilot arms on the validation split.

Reports each float model's MAE against every available reference: the HCE
2000 ms label, the NNUE d10 label, the 8 s reference (part 1 sample), exact
WDL and game outcome.  Context only: the paired match decides part 2.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

import numpy

OUTCOME = {"loss": -1.0, "draw": 0.0, "win": 1.0}


def target(cp: int) -> float:
    return math.tanh(max(-2000, min(2000, cp)) / 600)


def labels(path: Path, key: str) -> dict:
    with path.open(encoding="utf-8") as stream:
        lines = [json.loads(line) for line in stream if line.strip()]
    return {line["canonical_position_id"]: line[key]["score"] for line in lines[1:]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--d10", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with gzip.open(args.rows, "rt", encoding="utf-8") as stream:
        validation = [row for row in map(json.loads, stream) if row["split"] == "validation"]
    d10 = labels(args.d10, "d10")
    reference = labels(args.reference, "t8000")
    references = {
        "hce2000": [target(row["teacher_score"]) for row in validation],
        "nnue_d10": [target(d10[row["canonical_position_id"]]) for row in validation],
        "reference_8s": [
            target(reference[row["canonical_position_id"]])
            if row["canonical_position_id"] in reference else None
            for row in validation
        ],
        "exact_wdl": [OUTCOME.get(row["exact_wdl"]) for row in validation],
        "game_outcome": [
            None if row["game_truncated"] else OUTCOME.get(row["game_outcome_from_side_to_move"])
            for row in validation
        ],
    }
    strata = {
        "all": lambda row: True,
        "13_to_16": lambda row: row["phase_band"] == "13_to_16",
        "9_to_12": lambda row: row["phase_band"] == "9_to_12",
        "5_to_8": lambda row: row["phase_band"] == "5_to_8",
        "kings": lambda row: row["king_count"] > 0,
    }
    report = {"format": "thai-makhos-nnue2-pilot-arms-v1", "models": {}}
    for path in args.predictions:
        prediction = numpy.load(path)
        if len(prediction) != len(validation):
            raise SystemExit(f"{path.name} has the wrong length")
        entry = {}
        for stratum, keep in strata.items():
            cells = {}
            for name, values in references.items():
                errors = [
                    abs(float(prediction[index]) - value)
                    for index, (row, value) in enumerate(zip(validation, values))
                    if value is not None and keep(row)
                ]
                cells[name] = {"mae": sum(errors) / len(errors), "rows": len(errors)} if errors else None
            entry[stratum] = cells
        report["models"][path.name.removesuffix(".validation_prediction.npy")] = entry
    args.output.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for model, entry in report["models"].items():
        print(model, " ".join(
            f"{name}={cell['mae']:.4f}" for name, cell in entry["all"].items() if cell
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
