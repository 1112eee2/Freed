"""Part 1 of NNUE2_LABEL_PILOT_01: apply the declared depth-choice rule."""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

DEPTHS = (8, 10, 12, 14)
PHASES = ("13_to_16", "9_to_12", "5_to_8")


def target(cp: int) -> float:
    return math.tanh(max(-2000, min(2000, cp)) / 600)


def outcome_value(value):
    return {"loss": -1.0, "draw": 0.0, "win": 1.0}.get(value)


def read_labels(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        lines = [json.loads(line) for line in stream if line.strip()]
    return lines[0], {line["canonical_position_id"]: line for line in lines[1:]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--depths", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    depth_header, depth_labels = read_labels(args.depths)
    reference_header, reference = read_labels(args.reference)
    with gzip.open(args.rows, "rt", encoding="utf-8") as stream:
        rows = {
            row["canonical_position_id"]: row
            for row in map(json.loads, stream)
            if row["canonical_position_id"] in reference
        }
    ids = sorted(set(rows) & set(depth_labels) & set(reference))
    if len(ids) != depth_header["selected_rows"] or len(ids) != reference_header["selected_rows"]:
        raise SystemExit("label files are incomplete")

    sources = {"hce2000": lambda i: rows[i]["teacher_score"]}
    for depth in DEPTHS:
        sources[f"nnue_d{depth}"] = lambda i, d=depth: depth_labels[i][f"d{d}"]["score"]
    strata = {"all": lambda row: True}
    for phase in PHASES:
        strata[phase] = lambda row, p=phase: row["phase_band"] == p
    strata["kings"] = lambda row: row["king_count"] > 0
    strata["no_kings"] = lambda row: row["king_count"] == 0

    report = {"format": "thai-makhos-nnue2-pilot-part1-v1", "rows": len(ids), "strata": {}}
    for name, keep in strata.items():
        chosen = [i for i in ids if keep(rows[i])]
        entry = {"count": len(chosen)}
        for source, label in sources.items():
            errors = [abs(target(label(i)) - target(reference[i]["t8000"]["score"])) for i in chosen]
            outcome_pairs = [
                (target(label(i)), outcome_value(rows[i]["game_outcome_from_side_to_move"]))
                for i in chosen
                if outcome_value(rows[i]["game_outcome_from_side_to_move"]) is not None
            ]
            wdl_pairs = [
                (target(label(i)), outcome_value(rows[i]["exact_wdl"]))
                for i in chosen
                if outcome_value(rows[i]["exact_wdl"]) is not None
            ]
            entry[source] = {
                "mae_to_reference": sum(errors) / len(errors),
                "outcome_mae": (
                    sum(abs(a - b) for a, b in outcome_pairs) / len(outcome_pairs)
                    if outcome_pairs else None
                ),
                "outcome_rows": len(outcome_pairs),
                "exact_wdl_mae": (
                    sum(abs(a - b) for a, b in wdl_pairs) / len(wdl_pairs)
                    if wdl_pairs else None
                ),
                "exact_wdl_rows": len(wdl_pairs),
            }
        report["strata"][name] = entry

    decisive = (*PHASES, "kings", "no_kings")
    qualifying = [
        depth for depth in DEPTHS
        if all(
            report["strata"][name][f"nnue_d{depth}"]["mae_to_reference"]
            <= report["strata"][name]["hce2000"]["mae_to_reference"]
            for name in decisive
        )
    ]
    report["qualifying_depths"] = qualifying
    report["chosen_depth"] = qualifying[0] if qualifying else 14
    report["rule"] = (
        "smallest depth whose MAE to the 8,000 ms reference is at most the HCE "
        "2000 ms label's in every phase band and in the king and no-king strata; "
        "14 if none qualifies"
    )
    report["mean_ms"] = {
        f"d{depth}": sum(depth_labels[i][f"d{depth}"]["ms"] for i in ids) / len(ids)
        for depth in DEPTHS
    }
    report["reference_mean_depth"] = sum(reference[i]["t8000"]["depth"] for i in ids) / len(ids)
    args.output.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("qualifying_depths", "chosen_depth", "mean_ms")}))
    for name in strata:
        cells = report["strata"][name]
        print(name, cells["count"], " ".join(
            f"{source}={cells[source]['mae_to_reference']:.4f}" for source in sources
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
