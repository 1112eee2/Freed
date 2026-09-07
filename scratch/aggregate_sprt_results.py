"""Aggregate compatible machine-readable paired SPRT result artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from makhos.sprt import calculate_pentanomial_sprt  # noqa: E402


INPUT_FORMAT = "thai-makhos-sprt-result-v1"
OUTPUT_FORMAT = "thai-makhos-sprt-aggregate-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def comparable_config(config: dict) -> dict:
    result = dict(config)
    result.pop("seed", None)
    return result


def aggregate(paths: list[Path]) -> dict:
    if len(paths) < 2:
        raise ValueError("aggregate requires at least two result artifacts")
    payloads = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("format") != INPUT_FORMAT:
            raise ValueError(f"unsupported SPRT artifact format: {path}")
        result = payload.get("result", {})
        pentanomial = result.get("pentanomial")
        if not isinstance(pentanomial, list) or len(pentanomial) != 5:
            raise ValueError(f"invalid pentanomial result: {path}")
        if sum(pentanomial) != result.get("pairs"):
            raise ValueError(f"pair count does not match pentanomial: {path}")
        if result.get("games") != 2 * result.get("pairs"):
            raise ValueError(f"game count does not match paired result: {path}")
        payloads.append(payload)

    reference = comparable_config(payloads[0]["config"])
    for path, payload in zip(paths[1:], payloads[1:], strict=True):
        if comparable_config(payload["config"]) != reference:
            raise ValueError(f"SPRT configurations are incompatible: {path}")

    pentanomial = tuple(
        sum(payload["result"]["pentanomial"][index] for payload in payloads)
        for index in range(5)
    )
    elo0 = float(reference["elo0"])
    elo1 = float(reference["elo1"])
    status, llr, elo, elo_error = calculate_pentanomial_sprt(
        pentanomial,
        elo0=elo0,
        elo1=elo1,
    )
    wins = sum(payload["result"]["wins"] for payload in payloads)
    draws = sum(payload["result"]["draws"] for payload in payloads)
    losses = sum(payload["result"]["losses"] for payload in payloads)
    pairs = sum(pentanomial)
    games = wins + draws + losses
    if games != 2 * pairs:
        raise ValueError("aggregate W/D/L does not match paired count")

    return {
        "format": OUTPUT_FORMAT,
        "sources": [
            {
                "path": str(path.resolve()),
                "sha256": sha256(path),
                "seed": payload["config"].get("seed"),
                "pairs": payload["result"]["pairs"],
                "pentanomial": payload["result"]["pentanomial"],
            }
            for path, payload in zip(paths, payloads, strict=True)
        ],
        "shared_config": reference,
        "result": {
            "status": status,
            "llr": llr,
            "elo": elo,
            "elo_95_error": elo_error,
            "pairs": pairs,
            "games": games,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "pentanomial": pentanomial,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [path.resolve() for path in args.input]
    report = aggregate(paths)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print(
        "SPRT_AGGREGATE "
        + json.dumps(
            {
                "output": str(output),
                "sha256": sha256(output),
                "result": report["result"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
