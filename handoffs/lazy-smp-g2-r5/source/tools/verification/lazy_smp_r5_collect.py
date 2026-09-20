"""Collect frozen Lazy SMP G2 r5 Windows readiness or Linux TSan evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time


EXIT_STATUS = {0: "PASS", 2: "FAIL", 3: "INCOMPLETE_COVERAGE", 4: "NOT_RUN"}
STATUS_ORDER = {"PASS": 0, "INCOMPLETE_COVERAGE": 1, "NOT_RUN": 2, "FAIL": 3}
RACE_TEXT = "ThreadSanitizer: data race"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Collector:
    def __init__(self, root: Path, result_id: str, lane: str, compiler: str | None):
        self.root = root.resolve()
        self.manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.matrix = self.manifest["run_matrix"]
        self.lane = lane
        self.compiler_override = compiler
        self.out = self.root / "results" / result_id
        self.out.mkdir(parents=True, exist_ok=False)
        self.commands: list[dict] = []
        self.observations: list[dict] = []
        self.temp = tempfile.TemporaryDirectory(prefix="makhos-r5-")
        self.bin_dir = Path(self.temp.name)
        self.base_env_extra: dict[str, str] = {}
        self.snapshot_before = None
        self.snapshot_after = None

    def close(self) -> None:
        self.temp.cleanup()

    def write_json(self, name: str, value: object) -> None:
        (self.out / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def run(self, name: str, argv: list[str], timeout: int, env: dict[str, str] | None = None) -> dict:
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        before = time.monotonic()
        merged_env = os.environ.copy()
        merged_env.update(self.base_env_extra)
        if env:
            merged_env.update(env)
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)
        timed_out = False
        launch_error = None
        stdout = b""
        stderr = b""
        returncode = None
        try:
            process = subprocess.Popen(
                argv,
                cwd=self.root,
                env=merged_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                start_new_session=(os.name != "nt"),
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                stdout, stderr = process.communicate()
            returncode = process.returncode
        except OSError as exc:
            launch_error = f"{type(exc).__name__}: {exc}"
        elapsed = time.monotonic() - before
        stdout_name = f"{name}.stdout.log"
        stderr_name = f"{name}.stderr.log"
        (self.out / stdout_name).write_bytes(stdout)
        (self.out / stderr_name).write_bytes(stderr)
        record = {
            "name": name,
            "argv": argv,
            "cwd": str(self.root),
            "started_utc": started,
            "timeout_seconds": timeout,
            "elapsed_seconds": elapsed,
            "exit_code": returncode,
            "timed_out": timed_out,
            "launch_error": launch_error,
            "stdout": stdout_name,
            "stderr": stderr_name,
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        }
        self.commands.append(record)
        self.write_json("commands.json", self.commands)
        return record

    def text(self, record: dict) -> str:
        return (self.out / record["stdout"]).read_text(encoding="utf-8", errors="replace") + "\n" + (
            self.out / record["stderr"]
        ).read_text(encoding="utf-8", errors="replace")

    def verify(self, suffix: str) -> dict:
        item = self.run(f"verify_{suffix}", [sys.executable, "verify_snapshot.py"], 30)
        return {
            "status": "PASS" if item["exit_code"] == 0 and not item["timed_out"] else "NOT_RUN",
            "command": item["name"],
        }

    def environment(self) -> dict:
        value = {
            "captured_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": sys.version,
            "python_executable": sys.executable,
            "cpu_count": os.cpu_count(),
            "lane": self.lane,
        }
        self.write_json("environment.json", value)
        return value

    @staticmethod
    def aggregate(statuses: list[str]) -> str:
        return max(statuses, key=lambda item: STATUS_ORDER[item]) if statuses else "NOT_RUN"

    def parse_process(self, record: dict, *, executing_protocol: bool) -> tuple[str, dict | None, str]:
        if record["launch_error"]:
            return "NOT_RUN", None, "process launch failed"
        if record["timed_out"]:
            return ("FAIL" if executing_protocol else "NOT_RUN"), None, "process timeout"
        parsed = None
        for line in (self.out / record["stdout"]).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if candidate.get("schema") == self.manifest["process_json_schema"]:
                parsed = candidate
        expected = EXIT_STATUS.get(record["exit_code"])
        if parsed is None:
            return ("FAIL" if executing_protocol else "NOT_RUN"), None, "canonical process JSON missing"
        if expected is None or parsed.get("status") != expected:
            return "FAIL", parsed, "exit mapping and JSON status disagree"
        return expected, parsed, "harness classification"

    def compiler_exists(self, executable: str) -> bool:
        path = Path(executable)
        return path.exists() if (path.is_absolute() or path.parent != Path(".")) else shutil.which(executable) is not None

    def compile(self, label: str, compiler: str, source: str, binary: Path, tsan: bool) -> tuple[str, dict]:
        argv = [compiler, "-std=c17", "-O1", "-g"]
        if tsan:
            argv.append("-fsanitize=thread")
        argv.extend(["-pthread", source, "-o", str(binary)])
        item = self.run(label, argv, 120)
        if item["launch_error"]:
            return "NOT_RUN", item
        if item["timed_out"]:
            return "FAIL", item
        if item["exit_code"] == 0:
            item["binary_sha256"] = digest(binary)
            self.write_json("commands.json", self.commands)
            return "PASS", item
        text = self.text(item).lower()
        unavailable_markers = (
            "cannot find -ltsan",
            "unrecognized argument to '-fsanitize=' option: 'thread'",
            "unsupported option '-fsanitize=thread'",
            "unable to find library -ltsan",
        )
        return ("NOT_RUN" if any(marker in text for marker in unavailable_markers) else "FAIL"), item

    def missing_slots(self, prefix: str, count: int, reason: str) -> list[dict]:
        return [
            {"slot": f"{prefix}_{index:02d}", "status": "NOT_RUN", "reason": reason}
            for index in range(1, count + 1)
        ]

    def windows(self) -> dict:
        config = self.matrix["windows_plain"]
        compiler = self.compiler_override or os.environ.get("CC") or "gcc"
        planned = 1 + config["protocol_processes"]
        if not self.compiler_exists(compiler):
            slots = self.missing_slots("windows_process", planned, "required compiler missing")
            return {
                "compiler": compiler,
                "build_status": "NOT_RUN",
                "correctness_liveness_status": "NOT_RUN",
                "slots": slots,
            }
        compiler_path = Path(compiler)
        if compiler_path.is_absolute():
            self.base_env_extra["PATH"] = str(compiler_path.parent) + os.pathsep + os.environ.get("PATH", "")
        version = self.run("windows_compiler_version", [compiler, "--version"], 30)
        binary = self.bin_dir / "probe.exe"
        build_status, build = self.compile("windows_probe_compile", compiler, "probe.c", binary, False)
        slots: list[dict] = []
        statuses: list[str] = [build_status] if build_status == "FAIL" else []
        if build_status != "PASS":
            slots.extend(self.missing_slots("windows_process", planned, f"probe build {build_status.lower()}"))
        else:
            directed = self.run("windows_directed_01", [str(binary), "directed"], 30)
            status, payload, reason = self.parse_process(directed, executing_protocol=True)
            slots.append({"slot": "directed_01", "status": status, "reason": reason, "payload": payload, "command": directed["name"]})
            statuses.append(status)
            for index in range(1, config["protocol_processes"] + 1):
                item = self.run(
                    f"windows_protocol_{index:02d}",
                    [str(binary), "protocol"],
                    config["protocol_timeout_seconds"],
                )
                status, payload, reason = self.parse_process(item, executing_protocol=True)
                slots.append({"slot": f"protocol_{index:02d}", "status": status, "reason": reason, "payload": payload, "command": item["name"]})
                statuses.append(status)
        return {
            "compiler": compiler,
            "compiler_version_command": version["name"],
            "build_status": build_status,
            "binary_sha256": digest(binary) if binary.exists() else None,
            "correctness_liveness_status": self.aggregate(statuses or ["NOT_RUN"]),
            "tsan_calibration_status": "NOT_RUN",
            "slots": slots,
        }

    def linux_compiler(self, compiler: str, label: str) -> dict:
        config = self.matrix["linux_tsan"]["per_compiler"]
        protocol_count = config["protocol_processes"]
        if not self.compiler_exists(compiler):
            return {
                "compiler": compiler,
                "correctness_liveness_status": "NOT_RUN",
                "tsan_calibration_status": "NOT_RUN",
                "smoke": {"status": "NOT_RUN", "reason": "compiler missing"},
                "negative": {"status": "NOT_RUN", "reason": "compiler missing"},
                "protocol": self.missing_slots(f"{label}_protocol", protocol_count, "compiler missing"),
            }
        version = self.run(f"{label}_version", [compiler, "--version"], 30)
        binaries = {
            "smoke": self.bin_dir / f"{label}_smoke",
            "negative": self.bin_dir / f"{label}_negative",
            "probe": self.bin_dir / f"{label}_probe",
        }
        sources = {"smoke": "smoke_pthread.c", "negative": "negative_pthread.c", "probe": "probe.c"}
        builds = {}
        build_statuses = []
        for name in ("smoke", "negative", "probe"):
            status, command = self.compile(f"{label}_{name}_compile", compiler, sources[name], binaries[name], True)
            builds[name] = {"status": status, "command": command["name"], "binary_sha256": digest(binaries[name]) if binaries[name].exists() else None}
            build_statuses.append(status)
        if any(status != "PASS" for status in build_statuses):
            lane_build = self.aggregate(build_statuses)
            reason = f"TSan build prerequisite {lane_build.lower()}"
            return {
                "compiler": compiler,
                "compiler_version_command": version["name"],
                "builds": builds,
                "correctness_liveness_status": "FAIL" if lane_build == "FAIL" else "NOT_RUN",
                "tsan_calibration_status": "NOT_RUN",
                "smoke": {"status": "NOT_RUN", "reason": reason},
                "negative": {"status": "NOT_RUN", "reason": reason},
                "protocol": self.missing_slots(f"{label}_protocol", protocol_count, reason),
            }

        env = {"TSAN_OPTIONS": "halt_on_error=1"}
        smoke_run = self.run(f"{label}_smoke_run_01", [str(binaries["smoke"])], config["smoke_timeout_seconds"], env)
        smoke_text = self.text(smoke_run)
        smoke_pass = smoke_run["exit_code"] == 0 and not smoke_run["timed_out"] and "pthread_create/join smoke PASS" in smoke_text and "ThreadSanitizer:" not in smoke_text
        smoke = {"status": "PASS" if smoke_pass else "NOT_RUN", "command": smoke_run["name"], "reason": "clean smoke reached body" if smoke_pass else "sanitizer smoke did not complete cleanly"}

        negative_run = self.run(f"{label}_negative_run_01", [str(binaries["negative"])], config["negative_timeout_seconds"], env)
        negative_race = RACE_TEXT in self.text(negative_run)
        negative = {"status": "PASS" if negative_race else "NOT_RUN", "command": negative_run["name"], "reason": "genuine TSan data-race report" if negative_race else "negative control did not report a TSan data race"}
        calibrated = smoke_pass and negative_race
        protocols: list[dict] = []
        statuses: list[str] = []
        if not calibrated:
            protocols.extend(self.missing_slots(f"{label}_protocol", protocol_count, "TSan calibration unavailable"))
        else:
            for index in range(1, protocol_count + 1):
                item = self.run(
                    f"{label}_protocol_{index:02d}",
                    [str(binaries["probe"]), "protocol"],
                    config["protocol_timeout_seconds"],
                    env,
                )
                race = RACE_TEXT in self.text(item)
                if race:
                    status, payload, reason = "FAIL", None, "calibrated TSan data-race report"
                else:
                    status, payload, reason = self.parse_process(item, executing_protocol=True)
                protocols.append({"slot": f"{label}_protocol_{index:02d}", "status": status, "reason": reason, "payload": payload, "command": item["name"], "tsan_data_race": race})
                statuses.append(status)
        correctness = self.aggregate(statuses) if calibrated else "NOT_RUN"
        return {
            "compiler": compiler,
            "compiler_version_command": version["name"],
            "builds": builds,
            "correctness_liveness_status": correctness,
            "tsan_calibration_status": "PASS" if calibrated else "NOT_RUN",
            "smoke": smoke,
            "negative": negative,
            "protocol": protocols,
        }

    def linux(self) -> dict:
        configured = self.matrix["linux_tsan"]["compilers"]
        lanes = {}
        for item in configured:
            lanes[item["id"]] = self.linux_compiler(item["executable"], item["id"])
        statuses = [lane["correctness_liveness_status"] for lane in lanes.values()]
        calibrations = [lane["tsan_calibration_status"] for lane in lanes.values()]
        if any(status == "FAIL" for status in statuses):
            overall = "FAIL"
        elif any(status == "NOT_RUN" for status in statuses) or any(status != "PASS" for status in calibrations):
            overall = "NOT_RUN"
        elif any(status == "INCOMPLETE_COVERAGE" for status in statuses):
            overall = "INCOMPLETE_COVERAGE"
        else:
            overall = "PASS"
        return {"compilers": lanes, "correctness_liveness_status": self.aggregate(statuses), "overall_status": overall}

    def collect(self) -> dict:
        environment = self.environment()
        self.snapshot_before = self.verify("before")
        if self.snapshot_before["status"] != "PASS":
            if self.lane == "windows":
                lane_result = {
                    "correctness_liveness_status": "NOT_RUN",
                    "tsan_calibration_status": "NOT_RUN",
                    "slots": self.missing_slots("windows_process", 6, "snapshot verification failed"),
                }
            else:
                lane_result = {"correctness_liveness_status": "NOT_RUN", "overall_status": "NOT_RUN", "reason": "snapshot verification failed"}
        else:
            lane_result = self.windows() if self.lane == "windows" else self.linux()
        self.snapshot_after = self.verify("after")
        observed = lane_result.get("overall_status", lane_result.get("correctness_liveness_status", "NOT_RUN"))
        final_status = observed
        if self.snapshot_before["status"] != "PASS" or self.snapshot_after["status"] != "PASS":
            final_status = "FAIL" if observed == "FAIL" else "NOT_RUN"
        result = {
            "format": "thai-makhos-lazy-smp-g2-r5-result-v1",
            "handoff": self.manifest["handoff"],
            "lane": self.lane,
            "status": final_status,
            "gate_effect": "readiness/evidence only; G2 remains NOT_PASSED until reviewed full matrix PASS",
            "environment": environment,
            "snapshot_before": self.snapshot_before,
            "snapshot_after": self.snapshot_after,
            "manifest_sha256": digest(self.root / "manifest.json"),
            "lane_result": lane_result,
            "commands_file": "commands.json",
            "compiled_binaries_committed": False,
            "no_retry_or_replacement": True,
        }
        self.write_json("result.json", result)
        evidence = {
            str(path.relative_to(self.out)): digest(path)
            for path in sorted(self.out.rglob("*"))
            if path.is_file() and path.name != "evidence_sha256.json"
        }
        self.write_json("evidence_sha256.json", evidence)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_id")
    parser.add_argument("--lane", choices=("windows", "linux-tsan"), required=True)
    parser.add_argument("--compiler", help="Windows compiler executable; defaults to CC or gcc")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    collector = Collector(root, args.result_id, args.lane, args.compiler)
    try:
        result = collector.collect()
    finally:
        collector.close()
    print(json.dumps({"result": str(collector.out), "status": result["status"]}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
