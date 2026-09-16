#!/usr/bin/env python3
"""Deterministic stand-in for the coding agent, used to test the self-drive loop.

It implements exactly the contract `self_drive.py` expects: read the prompt from
its last argument, honour the required report path and round number, write a
valid round report, and print a CLI-shaped JSON envelope on stdout. It never
touches the repository.

Use it to exercise the loop without spending tokens or invoking a real agent::

    python -B tools/automation/self_drive.py --rounds 6 \\
        --agent-cmd "python -B tools/automation/stub_agent.py" --cooldown-seconds 0

Behaviour is driven by environment variables so a single command can reproduce a
scenario:

    STUB_PLAN      comma list of outcomes cycled by round, e.g. "progress,no-op"
                   (default "progress,progress,no-op,blocked,done")
    STUB_EXIT      exit code to return (default 0)
    STUB_SLEEP     seconds to sleep before writing anything (default 0)
    STUB_NO_REPORT set to 1 to skip writing the report (simulates a broken round)
    STUB_BAD_REPORT set to 1 to write malformed JSON
    STUB_BAD_EVIDENCE set to 1 to reference an evidence path that does not exist
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

DEFAULT_PLAN = "progress,progress,no-op,blocked,done"


def parse_prompt(prompt: str) -> tuple[int, Path | None]:
    round_match = re.search(r"Round number for the report:\s*(\d+)", prompt)
    round_number = int(round_match.group(1)) if round_match else 0
    path_match = re.search(r"`([^`]*round-\d+\.agent\.json)`", prompt)
    report_path = Path(path_match.group(1)) if path_match else None
    return round_number, report_path


def main() -> int:
    prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
    round_number, report_path = parse_prompt(prompt)
    plan = [item.strip() for item in os.environ.get("STUB_PLAN", DEFAULT_PLAN).split(",") if item.strip()]
    outcome = plan[(round_number - 1) % len(plan)] if plan else "progress"

    sleep_for = float(os.environ.get("STUB_SLEEP", "0") or 0)
    if sleep_for:
        time.sleep(sleep_for)

    print(f"stub agent: round {round_number} -> {outcome}", flush=True)

    if report_path is not None and os.environ.get("STUB_NO_REPORT") != "1":
        if os.environ.get("STUB_BAD_REPORT") == "1":
            report_path.write_text("{ not json", encoding="utf-8")
        else:
            evidence = [{"path": "tools/automation/self_drive.py", "sha256": None}]
            if os.environ.get("STUB_BAD_EVIDENCE") == "1":
                evidence.append({"path": "build/does-not-exist/evidence.json", "sha256": None})
            report = {
                "round": round_number,
                "outcome": outcome,
                "goal": f"stub round {round_number}: exercise the {outcome} path",
                "hypothesis": "the driver handles this outcome correctly",
                "actions": [f"emitted a {outcome} report", "touched nothing in the repository"],
                "evidence": evidence,
                "result": "N/A",
                "files_changed": [],
                "blockers": ["stub blocker: nothing real is blocked"] if outcome == "blocked" else [],
                "next_round_suggestion": "run the real agent instead of the stub",
            }
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    envelope = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": f"stub completed round {round_number} with outcome {outcome}",
        "session_id": f"stub-{round_number}",
        "num_turns": 1,
        "total_cost_usd": 0.0,
        "duration_ms": int(sleep_for * 1000),
        "finished_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    print(json.dumps(envelope), flush=True)
    return int(os.environ.get("STUB_EXIT", "0") or 0)


if __name__ == "__main__":
    raise SystemExit(main())
