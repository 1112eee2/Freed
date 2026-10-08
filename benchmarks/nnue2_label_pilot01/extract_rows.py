"""Extract v1's eligible development rows for NNUE2_LABEL_PILOT_01.

Reads only the development analyses in build/nnue_scaling_full_v1/analyses
(train and validation games listed in the v1 development manifest).  The v1
sealed test under build/nnue_sealed_test_v1 is never opened.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "build" / "nnue_scaling_full_v1"
DEFAULT_OUTPUT = ROOT / "build" / "nnue2_pilot01" / "v1_rows.jsonl.gz"
FIELDS = (
    "canonical_position_id", "position", "reversible_plies", "ply", "turn",
    "piece_count", "king_count", "phase_band", "teacher_score",
    "game_outcome_from_side_to_move", "game_truncated",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1-dir", type=Path, default=V1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    v1 = args.v1_dir
    manifest = json.loads(
        (v1 / "development_selection_manifest.json").read_text(encoding="utf-8")
    )
    splits = {}
    for game in manifest["games"]:
        if game["split"] not in ("train", "validation"):
            raise SystemExit(f"unexpected split {game['split']}")
        splits[game["game_id"]] = game["split"]
    expected = manifest["games_by_split"]
    for split in ("train", "validation"):
        if sum(value == split for value in splits.values()) != expected[split]:
            raise SystemExit(f"{split} game count differs from the manifest")
    rows = []
    for game_id in sorted(splits):
        path = v1 / "analyses" / f"{game_id}.analysis.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("game_id") != game_id or payload.get("split") != splits[game_id]:
            raise SystemExit(f"analysis binding differs for {game_id}")
        for position in payload["positions"]:
            if not position.get("eligible"):
                continue
            exact = position.get("exact_wdl")
            row = {"game_id": game_id, "split": splits[game_id]}
            row.update({key: position.get(key) for key in FIELDS})
            row["exact_wdl"] = exact.get("outcome") if isinstance(exact, dict) else None
            rows.append(row)
    rows.sort(key=lambda row: (row["split"], row["canonical_position_id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(args.output)
    counts = {}
    for row in rows:
        counts[row["split"]] = counts.get(row["split"], 0) + 1
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(json.dumps({"output": str(args.output), "rows": counts, "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
