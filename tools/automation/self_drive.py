#!/usr/bin/env python3
"""Self-driving development loop for ThaiMakhosEngine.

Runs the coding agent headlessly, round after round, without asking the user
anything between rounds. Each round the agent is launched as a fresh session,
told to read the project's own authority chain, pick exactly ONE highest-value
next action, execute it, leave evidence, and write a machine-readable round
report. The driver reads that report, appends progress, checks the stop
conditions, and starts the next round.

Typical use::

    python -B tools/automation/self_drive.py --rounds 5
    python -B tools/automation/self_drive.py --duration-minutes 120 --max-failures 2
    python -B tools/automation/self_drive.py --rounds 2 --dry-run
    python -B tools/automation/self_drive.py --rounds 3 --agent-cmd "python -B tools/automation/stub_agent.py"

State, prompts, raw agent logs and per-round reports all land under
``.workbuddy-ai/self_drive/<run-id>/`` so a run can be inspected or resumed.

Stop the loop at any time with Ctrl+C, or by creating ``<state-dir>/STOP``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_ROOT = REPO_ROOT / ".workbuddy-ai" / "self_drive"

# Exit codes: 0 goal reached or rounds exhausted, 2 budget exhausted,
# 3 failure limit, 4 no-progress limit, 5 blocked, 130 interrupted.
EXIT_OK, EXIT_BUDGET, EXIT_FAILURES, EXIT_NO_PROGRESS, EXIT_BLOCKED, EXIT_INTERRUPT = 0, 2, 3, 4, 5, 130

OUTCOMES = ("progress", "no-op", "blocked", "done")
REQUIRED_REPORT_KEYS = ("round", "outcome", "goal")

# Process patterns that mean a user-facing workload owns the machine. The project
# gives the GUI absolute priority, so a round waits instead of competing with it.
DEFAULT_BUSY_PATTERN = r"makhos_native.*\.exe|server\.py|run_gui\.ps1|makhos_tb[456]\.exe"

MISSION = """\
Continue development of the ThaiMakhosEngine repository at {root}.

Authority order, highest first:
  1. the user's latest request and the active goal recorded below;
  2. .agents/skills/thai-makhos-engine/SKILL.md and its
     references/current-state.md (the single current-state record);
  3. DEVELOPMENT_PLAN_TH.md;
  4. NNUE_ROADMAP.md for NNUE detail;
  5. references/experiment-evidence-ledger.md;
  6. deferred proof/architecture roadmaps.

Read those files before deciding anything. Do not infer current experiment
state from filenames, old prose, or test counts. Re-measure cheap, drift-prone
facts instead of trusting a cached number.
"""

HARD_INVARIANTS = """\
- Never edit RULESET.json or makhos/core.py; they are the verified references.
- Preserve mandatory capture, Thai king-halt landing, immediate captured-piece
  removal, end-of-turn promotion, threefold repetition and 80 reversible plies.
- Proof/tablebase/terminal results stay authoritative over HCE and NNUE.
- The GUI has absolute priority. Do not start resource-heavy work while a
  user-facing workload is running.
- One experiment at a time, one concept changed per experiment, evidence first.
  End every experiment with PROMOTE / KEEP / REJECT / INCONCLUSIVE.
- Do not resume a stopped or completed run, and do not launch an SPRT or promote
  anything unless the plan's gates for it have actually passed.
- Do not delete, move or rewrite proof/DFPN/tablebase artifacts, frozen
  manifests, or another run's evidence.
- Never `git add -A`, `git reset`, `git clean`, or otherwise disturb work in
  progress that you did not create. Stage only the paths you own.
- Do not modify .agents/skills/thai-makhos-engine/references/current-state.md
  unless the change is part of the action you are taking this round.
- Never weaken an assertion, test, tolerance or detector to manufacture a pass.
"""

ROUND_CONTRACT = """\
### What this round must produce

1. Re-read the authority chain and re-measure anything cheap that may have drifted.
2. Choose exactly ONE highest-value next action that is (a) not blocked and
   (b) does not require a gate the project has not passed. Prefer the action the
   project's own documents already name as next.
3. Carry it to a real, verifiable result. Do not stop at a plan or a summary.
4. Leave the evidence on disk at a stable path, and record the path.
5. Write the round report described below. This file is how the loop learns what
   happened; a missing or malformed report counts as a failed round.

Do not ask the user anything and do not wait for confirmation. If the chosen
action turns out to be blocked, record the blocker, stop working on it, and
write outcome "blocked" rather than improvising around it.
"""

REPORT_SHAPE = """\
{
  "round": <integer, the round number you were given>,
  "outcome": "progress" | "no-op" | "blocked" | "done",
  "goal": "<one line: what this round set out to do>",
  "hypothesis": "<the falsifiable claim, or null>",
  "actions": ["<what you actually did>"],
  "evidence": [{"path": "<repo-relative path>", "sha256": "<hex or null>"}],
  "result": "PROMOTE" | "KEEP" | "REJECT" | "INCONCLUSIVE" | "N/A",
  "files_changed": ["<repo-relative path>"],
  "blockers": ["<what stopped you, or empty>"],
  "next_round_suggestion": "<the single highest-value next action you would take>"
}

Use "done" only when the active goal above is genuinely achieved with evidence.
Use "no-op" when nothing of value could be advanced this round. Use "progress"
for any real, evidenced advance.
"""


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class Driver:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.root = Path(args.repo_root).resolve()
        self.started = time.monotonic()
        self.started_at = now_utc()
        self.interrupted = False
        self.stop_reason: str | None = None
        self.exit_code = EXIT_OK
        self.run_id = args.run_id or dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        base = Path(args.state_dir) if args.state_dir else DEFAULT_STATE_ROOT
        self.state_dir = (base / self.run_id).resolve()
        self.rounds_dir = self.state_dir / "rounds"
        self.logs_dir = self.state_dir / "logs"
        self.prompts_dir = self.state_dir / "prompts"
        self.driver_log = self.state_dir / "driver.log"
        self.progress_file = self.state_dir / "progress.md"
        self.state_file = self.state_dir / "state.json"
        self.stop_file = self.state_dir / "STOP"
        self.lock_file = base / ".lock"
        self.history: list[dict] = []
        self.consecutive_failures = 0
        self.consecutive_no_progress = 0
        self.rounds_completed = 0
        self.next_round = 1

    # ---------------------------------------------------------------- plumbing

    def log(self, message: str, level: str = "INFO") -> None:
        line = f"[{now_utc()}] {level:<5} {message}"
        print(line, flush=True)
        try:
            with self.driver_log.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass

    def prepare_dirs(self) -> None:
        for directory in (self.rounds_dir, self.logs_dir, self.prompts_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def acquire_lock(self) -> None:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_file.exists():
            try:
                holder = json.loads(self.lock_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                holder = {"pid": "unknown", "run_id": "unknown"}
            if not self.args.force and self._pid_alive(holder.get("pid")):
                raise SystemExit(
                    f"another self-drive run is active (pid {holder.get('pid')}, "
                    f"run {holder.get('run_id')}); pass --force to override"
                )
        self.lock_file.write_text(
            json.dumps({"pid": os.getpid(), "run_id": self.run_id, "started_at": now_utc()}),
            encoding="utf-8",
        )

    def release_lock(self) -> None:
        try:
            if self.lock_file.exists():
                holder = json.loads(self.lock_file.read_text(encoding="utf-8"))
                if holder.get("pid") == os.getpid():
                    self.lock_file.unlink()
        except (OSError, ValueError):
            pass

    @staticmethod
    def _pid_alive(pid) -> bool:
        """Probe liveness without touching the process.

        Never use os.kill(pid, 0) on Windows: any signal other than
        CTRL_C_EVENT/CTRL_BREAK_EVENT terminates the target process, so the probe
        would kill the very process it is testing.
        """
        if not isinstance(pid, int) or pid <= 0:
            return False
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return True  # could not read the code: assume alive
                return code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    # ------------------------------------------------------------------- state

    def load_state(self) -> None:
        if not (self.args.resume and self.state_file.exists()):
            return
        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.history = state.get("rounds", [])
        self.rounds_completed = state.get("rounds_completed", 0)
        self.next_round = self.rounds_completed + 1
        self.consecutive_failures = state.get("consecutive_failures", 0)
        self.consecutive_no_progress = state.get("consecutive_no_progress", 0)
        self.log(f"resumed at round {self.next_round} from {self.state_file}")

    def write_state(self) -> None:
        state = {
            "run_id": self.run_id,
            "repo_root": str(self.root),
            "started_at": self.started_at,
            "updated_at": now_utc(),
            "rounds_completed": self.rounds_completed,
            "next_round": self.next_round,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_no_progress": self.consecutive_no_progress,
            "last_outcome": self.history[-1]["outcome"] if self.history else None,
            "elapsed_seconds": round(time.monotonic() - self.started, 1),
            "stop_reason": self.stop_reason,
            "rounds": self.history,
        }
        self.state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def append_progress(self, record: dict) -> None:
        report = record.get("report") or {}
        lines = [
            "",
            f"## Round {record['round']:03d} — {record['finished_at']} — {record['outcome']}",
            "",
            f"- **goal**: {report.get('goal', '(not reported)')}",
            f"- **result**: {report.get('result', 'N/A')}",
            f"- **exit**: {record['exit_code']} · **elapsed**: {record['elapsed_seconds']}s"
            f" · **turns**: {record.get('num_turns', '?')}"
            f" · **cost_usd**: {record.get('cost_usd', '?')}",
        ]
        if report.get("hypothesis"):
            lines.append(f"- **hypothesis**: {report['hypothesis']}")
        for action in report.get("actions") or []:
            lines.append(f"- **did**: {action}")
        for item in report.get("evidence") or []:
            digest = (item.get("sha256") or "?")[:12]
            lines.append(f"- **evidence**: `{item.get('path')}` ({digest})")
        if report.get("files_changed"):
            lines.append(f"- **files**: {', '.join(report['files_changed'])}")
        for blocker in report.get("blockers") or []:
            lines.append(f"- **blocker**: {blocker}")
        if report.get("next_round_suggestion"):
            lines.append(f"- **next**: {report['next_round_suggestion']}")
        if record.get("error"):
            lines.append(f"- **error**: {record['error']}")
        with self.progress_file.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    # ------------------------------------------------------------------ prompt

    def build_prompt(self, round_number: int) -> str:
        report_path = self.rounds_dir / f"round-{round_number:03d}.agent.json"
        history = self.render_history()
        return "\n".join(
            part
            for part in (
                MISSION.format(root=self.root),
                "\n## Active goal\n\n" + self.active_goal() + "\n",
                f"\n## Round {round_number} of a self-driving loop\n",
                ROUND_CONTRACT,
                "\n### Hard invariants\n\n" + HARD_INVARIANTS,
                history,
                "\n### Round report (required)\n\n"
                f"Write exactly this JSON object to `{report_path}` before you finish:\n\n"
                "```json\n" + REPORT_SHAPE + "```\n",
                f"\nRound number for the report: {round_number}\n",
            )
            if part
        )

    def active_goal(self) -> str:
        if self.args.goal_file:
            text = Path(self.args.goal_file).read_text(encoding="utf-8").strip()
            if text:
                return text
        return (
            "Advance ThaiMakhosEngine along its own recorded plan: close the next "
            "unblocked gate, or produce the next piece of missing evidence, without "
            "weakening any existing correctness or promotion guarantee."
        )

    def render_history(self) -> str:
        if not self.history:
            return "\n### History from previous rounds\n\nThis is round 1; there is no history yet.\n"
        lines = ["\n### History from previous rounds\n"]
        if self.consecutive_failures:
            lines.append(
                f"The last {self.consecutive_failures} round(s) failed. Do not repeat the "
                "same failing action; change approach or report a blocker.\n"
            )
        if self.consecutive_no_progress:
            lines.append(
                f"The last {self.consecutive_no_progress} round(s) produced no progress. "
                "Choose a materially different action this round.\n"
            )
        for record in self.history[-self.args.history_rounds:]:
            report = record.get("report") or {}
            lines.append(
                f"- round {record['round']} [{record['outcome']}]: "
                f"{report.get('goal', '(no report)')} "
                f"→ {report.get('result', 'N/A')}"
            )
            if report.get("next_round_suggestion"):
                lines.append(f"  suggested next: {report['next_round_suggestion']}")
            for blocker in report.get("blockers") or []:
                lines.append(f"  blocker: {blocker}")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ agent

    def resolve_agent_command(self, prompt: str) -> list[str]:
        if self.args.agent_cmd:
            return [*self.args.agent_cmd, prompt]
        command = [
            self.args.cli_path,
            "-p",
            "--output-format",
            "json",
            "--max-turns",
            str(self.args.max_turns),
        ]
        if self.args.permission_mode == "bypassPermissions":
            # --permission-mode is documented for TUI/--serve/ACP; -y is the
            # headless "bypass all permission checks" flag.
            command.append("-y")
        else:
            command += ["--permission-mode", self.args.permission_mode]
        if self.args.model:
            command += ["--model", self.args.model]
        command.append(prompt)
        return command

    def busy_workloads(self) -> list[str]:
        if not self.args.respect_gui_priority:
            return []
        try:
            import psutil  # optional: GUI-priority pre-check degrades gracefully
        except ImportError:
            return []
        pattern = re.compile(self.args.busy_pattern, re.IGNORECASE)
        found = []
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = process.info["name"] or ""
                cmdline = " ".join(process.info["cmdline"] or [])
                if process.pid == os.getpid():
                    continue
                if pattern.search(name) or pattern.search(cmdline):
                    found.append(f"{process.pid}:{name}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found

    def wait_for_idle(self) -> bool:
        deadline = time.monotonic() + self.args.busy_wait_minutes * 60
        while True:
            busy = self.busy_workloads()
            if not busy:
                return True
            if time.monotonic() >= deadline:
                self.log(
                    f"user workload still active after {self.args.busy_wait_minutes} min "
                    f"({', '.join(busy[:3])}); stopping to protect it",
                    "WARN",
                )
                return False
            self.log(f"waiting: user workload active ({', '.join(busy[:3])})", "WARN")
            if self._sleep_interruptible(self.args.cooldown_seconds):
                return False

    def _sleep_interruptible(self, seconds: float) -> bool:
        """Sleep, returning True if interrupted."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.interrupted:
                return True
            time.sleep(min(0.5, max(0.0, end - time.monotonic())))
        return self.interrupted

    def invoke_agent(self, prompt: str, round_number: int) -> dict:
        if len(prompt) > self.args.max_prompt_chars:
            return {"command": [], "agent_log": "", "exit_code": -1, "timed_out": False,
                    "stdout_tail": "",
                    "error": (f"prompt is {len(prompt)} chars, above the "
                              f"{self.args.max_prompt_chars} limit; lower --history-rounds")}
        command = self.resolve_agent_command(prompt)
        agent_log = self.logs_dir / f"round-{round_number:03d}.agent.log"
        result = {"command": command[:2] + ["<prompt>"], "agent_log": str(agent_log),
                  "exit_code": None, "timed_out": False, "stdout_tail": "", "error": None}
        env = os.environ.copy()
        env["CODEBUDDY_SELF_DRIVE_ROUND"] = str(round_number)
        popen_kwargs: dict = {"cwd": str(self.root), "env": env}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        with agent_log.open("w", encoding="utf-8", errors="replace") as handle:
            handle.write(f"# command: {' '.join(command)}\n# prompt: {self.prompts_dir}\n\n")
            handle.flush()
            try:
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=handle,
                    stderr=subprocess.STDOUT, **popen_kwargs,
                )
            except OSError as exc:
                result["error"] = f"could not start agent: {exc}"
                result["exit_code"] = -1
                return result
            try:
                result["exit_code"] = process.wait(timeout=self.args.round_timeout_minutes * 60)
            except subprocess.TimeoutExpired:
                result["timed_out"] = True
                self._kill_tree(process)
                result["exit_code"] = process.wait()
                result["error"] = f"round exceeded {self.args.round_timeout_minutes} min"
        result["stdout_tail"] = self._read_tail(agent_log)
        return result

    @staticmethod
    def _kill_tree(process: subprocess.Popen) -> None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                               capture_output=True, check=False)
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            process.kill()
        except OSError:
            pass

    @staticmethod
    def _read_tail(path: Path, limit: int = 4000) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-limit:]

    def parse_agent_json(self, text: str) -> dict:
        """Pull the CLI's own result envelope out of the raw log, tolerantly."""
        for candidate in (text.strip(), *reversed([ln for ln in text.splitlines() if ln.strip()])):
            try:
                payload = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(payload, dict) and ("result" in payload or "type" in payload):
                return payload
        return {}

    # ------------------------------------------------------------------ report

    def read_round_report(self, round_number: int) -> tuple[dict | None, str | None]:
        path = self.rounds_dir / f"round-{round_number:03d}.agent.json"
        if not path.exists():
            return None, f"agent did not write {path.name}"
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            return None, f"{path.name} is not valid JSON: {exc}"
        if not isinstance(report, dict):
            return None, f"{path.name} is not a JSON object"
        missing = [key for key in REQUIRED_REPORT_KEYS if key not in report]
        if missing:
            return None, f"{path.name} is missing {', '.join(missing)}"
        if report.get("outcome") not in OUTCOMES:
            return None, f"{path.name} has an unknown outcome {report.get('outcome')!r}"
        return report, None

    def verify_evidence(self, report: dict) -> list[str]:
        problems = []
        for item in report.get("evidence") or []:
            if not isinstance(item, dict) or not item.get("path"):
                problems.append(f"malformed evidence entry: {item!r}")
                continue
            path = Path(item["path"])
            path = path if path.is_absolute() else self.root / path
            if not path.exists():
                problems.append(f"evidence path does not exist: {item['path']}")
        return problems

    # ------------------------------------------------------------------- round

    def run_round(self, round_number: int) -> dict:
        started = time.monotonic()
        record: dict = {"round": round_number, "started_at": now_utc(), "outcome": "error"}
        prompt = self.build_prompt(round_number)
        prompt_file = self.prompts_dir / f"round-{round_number:03d}.md"
        prompt_file.write_text(prompt, encoding="utf-8", newline="\n")

        if self.args.dry_run:
            self.log(f"round {round_number}: dry run, prompt written to {prompt_file}")
            record.update(outcome="no-op", finished_at=now_utc(), exit_code=None,
                          elapsed_seconds=0.0, report={"goal": "dry run", "result": "N/A"})
            return record

        self.log(f"round {round_number}: launching agent")
        invocation = self.invoke_agent(prompt, round_number)
        envelope = self.parse_agent_json(invocation["stdout_tail"])
        record.update(
            exit_code=invocation["exit_code"],
            error=invocation["error"],
            timed_out=invocation["timed_out"],
            agent_log=invocation["agent_log"],
            num_turns=envelope.get("num_turns"),
            cost_usd=envelope.get("total_cost_usd"),
            session_id=envelope.get("session_id"),
        )

        report, report_error = self.read_round_report(round_number)
        if report is None:
            record["outcome"] = "error"
            record["error"] = "; ".join(filter(None, [record.get("error"), report_error]))
            record["finished_at"] = now_utc()
            record["elapsed_seconds"] = round(time.monotonic() - started, 1)
            return record

        problems = self.verify_evidence(report)
        if problems:
            record["error"] = "; ".join(filter(None, [record.get("error"), *problems]))
            if report.get("outcome") == "progress":
                # Evidence-first: a claimed advance whose evidence cannot be found on
                # disk is recorded honestly, but it does not count as progress.
                report["outcome"] = "no-op"
                report.setdefault("blockers", []).append(
                    "claimed evidence was not found on disk"
                )
        if invocation["exit_code"] not in (0, None) and report.get("outcome") == "progress":
            # The agent claims progress but the process failed; do not trust it.
            report["outcome"] = "no-op"
            record["error"] = "; ".join(
                filter(None, [record.get("error"), f"agent exited {invocation['exit_code']}"])
            )
        record["report"] = report
        record["outcome"] = report["outcome"]
        record["finished_at"] = now_utc()
        record["elapsed_seconds"] = round(time.monotonic() - started, 1)
        return record

    def record_round(self, record: dict) -> None:
        merged = self.rounds_dir / f"round-{record['round']:03d}.json"
        merged.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        self.history.append(record)
        self.rounds_completed += 1
        self.next_round = record["round"] + 1
        self.append_progress(record)
        outcome = record["outcome"]
        if outcome == "error":
            self.consecutive_failures += 1
            self.consecutive_no_progress += 1
        else:
            self.consecutive_failures = 0
            self.consecutive_no_progress = 0 if outcome == "progress" else self.consecutive_no_progress + 1
        self.write_state()

    # -------------------------------------------------------------------- stop

    def check_stop(self) -> str | None:
        if self.interrupted:
            return "interrupted by the user"
        if self.stop_file.exists():
            return f"{self.stop_file.name} sentinel present"
        if self.history:
            last = self.history[-1]
            if last["outcome"] == "done":
                return "the agent reported the goal as done"
            if last["outcome"] == "blocked" and self.args.stop_on_blocked:
                return "the agent reported a blocker and --stop-on-blocked is set"
        if self.args.max_failures and self.consecutive_failures >= self.args.max_failures:
            self.exit_code = EXIT_FAILURES
            return f"{self.consecutive_failures} consecutive failed rounds"
        if self.args.max_no_progress and self.consecutive_no_progress >= self.args.max_no_progress:
            self.exit_code = EXIT_NO_PROGRESS
            return f"{self.consecutive_no_progress} consecutive rounds without progress"
        if self.rounds_completed >= self.args.rounds:
            return f"completed the requested {self.args.rounds} round(s)"
        if self.args.duration_minutes:
            remaining = self.args.duration_minutes * 60 - (time.monotonic() - self.started)
            if remaining <= 0:
                self.exit_code = EXIT_BUDGET
                return f"time budget of {self.args.duration_minutes} min exhausted"
            if remaining < self.args.min_round_seconds:
                self.exit_code = EXIT_BUDGET
                return (f"only {remaining:.0f}s left, less than the "
                        f"{self.args.min_round_seconds:.0f}s minimum round budget")
        return None

    # --------------------------------------------------------------------- run

    started_at = ""

    def run(self) -> int:
        self.started_at = now_utc()
        self.prepare_dirs()
        self.acquire_lock()
        try:
            self.load_state()
            self.log(
                f"self-drive run {self.run_id} starting: rounds={self.args.rounds} "
                f"duration_min={self.args.duration_minutes} state={self.state_dir}"
            )
            if not self.args.resume:
                self.progress_file.write_text(
                    f"# Self-drive progress — run {self.run_id}\n\n"
                    f"- started: {self.started_at}\n"
                    f"- repo: {self.root}\n"
                    f"- budget: {self.args.rounds} round(s), "
                    f"{self.args.duration_minutes} minute(s)\n",
                    encoding="utf-8",
                )
            while True:
                stop = self.check_stop()
                if stop:
                    self.stop_reason = stop
                    break
                if not self.wait_for_idle():
                    self.stop_reason = "user workload held priority"
                    self.exit_code = EXIT_BLOCKED
                    break
                record = self.run_round(self.next_round)
                self.record_round(record)
                self.log(
                    f"round {record['round']} finished: {record['outcome']} "
                    f"({record['elapsed_seconds']}s)"
                    + (f" — {record['error']}" if record.get("error") else "")
                )
                if self._sleep_interruptible(self.args.cooldown_seconds):
                    continue
            self.write_state()
            self.log(f"stopping: {self.stop_reason}")
            return self.exit_code
        finally:
            self.release_lock()

    def handle_interrupt(self, *_args) -> None:
        self.interrupted = True
        print("", flush=True)
        self.log("interrupt received; finishing the current round then stopping", "WARN")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="self_drive.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Run the coding agent headlessly, round after round, on ThaiMakhosEngine.",
        epilog=textwrap.dedent(
            """\
            examples:
              python -B tools/automation/self_drive.py --rounds 5
              python -B tools/automation/self_drive.py --duration-minutes 120 --max-failures 2
              python -B tools/automation/self_drive.py --rounds 3 --dry-run
              python -B tools/automation/self_drive.py --rounds 3 \\
                  --agent-cmd "python -B tools/automation/stub_agent.py"
              python -B tools/automation/self_drive.py --resume --rounds 10

            stop early with Ctrl+C, or:  type nul > .workbuddy-ai/self_drive/STOP
            inspect a run in:            .workbuddy-ai/self_drive/<run-id>/
            """
        ),
    )
    budget = parser.add_argument_group("budget and stop conditions")
    budget.add_argument("--rounds", type=int, default=None,
                        help="maximum rounds; default 3 when no time budget is given, "
                             "unlimited when --duration-minutes is set")
    budget.add_argument("--duration-minutes", type=float, default=0,
                        help="wall-clock budget in minutes; 0 disables it (default 0)")
    budget.add_argument("--min-round-seconds", type=float, default=120,
                        help="do not start a round with less than this much budget left (default 120)")
    budget.add_argument("--max-failures", type=int, default=3,
                        help="stop after this many consecutive failed rounds; 0 disables (default 3)")
    budget.add_argument("--max-no-progress", type=int, default=3,
                        help="stop after this many consecutive no-progress rounds; 0 disables (default 3)")
    budget.add_argument("--stop-on-blocked", action="store_true",
                        help="stop as soon as a round reports outcome 'blocked'")

    agent = parser.add_argument_group("agent invocation")
    agent.add_argument("--agent-cmd", nargs=argparse.REMAINDER, default=None,
                       help="override the whole agent command line (e.g. a stub for testing)")
    agent.add_argument("--cli-path", default=(
        r"C:\Program Files\WorkBuddyAI\resources\app.asar.unpacked\cli\bin\codebuddy"),
        help="path to the codebuddy CLI")
    agent.add_argument("--permission-mode", default="bypassPermissions",
                       choices=["acceptEdits", "bypassPermissions", "default", "plan",
                                "dontAsk", "auto"],
                       help="permission mode for the unattended agent; bypassPermissions "
                            "(the default) uses -y so the loop never prompts")
    agent.add_argument("--model", default=None,
                       help="model id for the agent, e.g. fast-model or primary-model "
                            "(default: the CLI's own default)")
    agent.add_argument("--max-turns", type=int, default=80,
                       help="agentic turn limit per round (default 80)")
    agent.add_argument("--round-timeout-minutes", type=float, default=45,
                       help="kill a round that runs longer than this (default 45)")
    agent.add_argument("--max-prompt-chars", type=int, default=24000,
                       help="refuse to launch a round whose prompt exceeds this (default 24000)")

    loop = parser.add_argument_group("loop behaviour")
    loop.add_argument("--cooldown-seconds", type=float, default=15,
                      help="pause between rounds (default 15)")
    loop.add_argument("--history-rounds", type=int, default=5,
                      help="how many previous rounds to summarise into the prompt (default 5)")
    loop.add_argument("--goal-file", type=Path, default=None,
                      help="file holding the standing goal; default is a built-in brief")
    loop.add_argument("--state-dir", type=Path, default=None,
                      help="parent directory for run state (default .workbuddy-ai/self_drive)")
    loop.add_argument("--run-id", default=None, help="name this run (default: UTC timestamp)")
    loop.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="repository root")
    loop.add_argument("--resume", action="store_true",
                      help="continue a run from its state.json (use with --run-id)")
    loop.add_argument("--force", action="store_true", help="ignore an existing lock file")
    loop.add_argument("--dry-run", action="store_true",
                      help="write prompts and state but never launch the agent")
    loop.add_argument("--respect-gui-priority", action="store_true", default=True,
                      help="wait while a user-facing workload is running (default on)")
    loop.add_argument("--no-respect-gui-priority", dest="respect_gui_priority",
                      action="store_false", help="disable the GUI-priority pre-check")
    loop.add_argument("--busy-pattern", default=DEFAULT_BUSY_PATTERN,
                      help="regex matching processes that own the machine")
    loop.add_argument("--busy-wait-minutes", type=float, default=30,
                      help="give up waiting for an idle machine after this long (default 30)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rounds is None:
        args.rounds = 3 if not args.duration_minutes else 10_000
    if args.rounds <= 0 and not args.duration_minutes:
        print("nothing to do: set --rounds > 0 or --duration-minutes > 0", file=sys.stderr)
        return 1
    if not args.agent_cmd and not Path(args.cli_path).exists():
        print(f"agent CLI not found at {args.cli_path}; pass --cli-path or --agent-cmd",
              file=sys.stderr)
        return 1
    driver = Driver(args)
    signal.signal(signal.SIGINT, driver.handle_interrupt)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, driver.handle_interrupt)
    code = driver.run()
    if driver.interrupted:
        code = EXIT_INTERRUPT
    print(f"\nstopped: {driver.stop_reason}")
    print(f"rounds completed: {driver.rounds_completed}")
    print(f"state: {driver.state_dir}")
    print(f"progress: {driver.progress_file}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
