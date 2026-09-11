"""Locked Gate C launch/verification and read-only, manifest-bound status.

This tooling is outside the frozen playing-source inventory. It never changes
the contract, promotes an engine, or automatically restarts an unknown failure.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CONTRACT = "build/nnue_gate_c_contract_v1.json"
CONTRACT_SHA = "5B727707FBED8D5E9D79AE89159D9DF1EAF5C74D8AFE31A654F3CDC191F6A3F7"
FIRST_PASS_SHA = "41E78EF359BB9BA6E1CDF189FCD15B56D1D9ED36E2CCD684D4F96D0C8AFE94D8"
ACTIVE = "build/runtime/nnue_gate_c_active_run.json"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def read_json(path):
    """Read only immutable/stopped JSON or the retry-published run pointer.

    Release the Windows file handle before parsing; live arena checkpoints are
    excluded entirely by snapshot(), since sharing flags alone did not protect
    an open destination from os.replace on this host.
    """
    if os.name != "nt":
        encoded = Path(path).read_text(encoding="utf-8")
    else:
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
            wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
            wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            encoded = stream.read()
    return json.load(io.StringIO(encoded))


def contract_at(root=ROOT):
    if sha(root / CONTRACT) != CONTRACT_SHA:
        raise ValueError("Frozen Gate C contract hash mismatch")
    return read_json(root / CONTRACT)


def checked_pair_counts(result, max_pairs):
    buckets = result["pentanomial"]
    if len(buckets) != 5:
        raise ValueError("Expected five pentanomial buckets")
    counts = [result[key] for key in ("pairs", "games", "wins", "draws", "losses")]
    if any(type(n) is not int or n < 0 for n in [*counts, *buckets]):
        raise ValueError("Invalid result counts")
    pairs, games, wins, draws, losses = counts
    if (pairs != sum(buckets) or games != 2 * pairs or games != wins + draws + losses
            or 2 * wins + draws != sum(i * n for i, n in enumerate(buckets))
            or pairs > max_pairs):
        raise ValueError("Inconsistent completed-pair counts")
    # The middle bucket may contain either WL/LW or DD. Score mass alone
    # cannot distinguish them (and would accept four draws for LL + WW).
    split_pairs = wins - buckets[3] - 2 * buckets[4]
    if (not 0 <= split_pairs <= buckets[2]
            or losses != 2 * buckets[0] + buckets[1] + split_pairs
            or draws != buckets[1] + buckets[3] + 2 * (buckets[2] - split_pairs)):
        raise ValueError("W/D/L cannot be realized by the pentanomial buckets")


def checked_result(payload, expected_config):
    from makhos.sprt import calculate_pentanomial_sprt
    if payload.get("format") != "thai-makhos-sprt-result-v2":
        raise ValueError("Unsupported checkpoint format")
    if payload.get("config") != expected_config:
        raise ValueError("Checkpoint configuration mismatch")
    if type(payload.get("complete")) is not bool:
        raise ValueError("Invalid completion flag")
    result = payload["result"]
    checked_pair_counts(result, expected_config["max_pairs"])
    buckets = result["pentanomial"]
    status, llr, elo, error = calculate_pentanomial_sprt(
        tuple(buckets), expected_config["elo0"], expected_config["elo1"])
    if result["status"] != status:
        raise ValueError("SPRT status does not reproduce")
    for key, value in (("llr", llr), ("elo", elo), ("elo_95_error", error)):
        if not math.isclose(result[key], value, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"SPRT {key} does not reproduce")
    if payload["complete"] and status == "INCONCLUSIVE" and result["pairs"] < expected_config["max_pairs"]:
        raise ValueError("Premature finalization before the declared cap")
    return result


def require_resumable_result(payload, expected_config):
    result = checked_result(payload, expected_config)
    if (payload["complete"] or result["status"] != "INCONCLUSIVE"
            or result["pairs"] >= expected_config["max_pairs"]):
        raise RuntimeError("2000ms match reached a stop condition; do not restart")


def expected_configs(contract, root=ROOT):
    first_path = root / contract["matches"][0]["output"]
    if sha(first_path) != FIRST_PASS_SHA:
        raise ValueError("Completed 1000ms result changed")
    first = read_json(first_path)
    checked_result(first, first["config"])
    if not first["complete"] or first["result"]["status"] != "PASS":
        raise ValueError("1000ms predecessor is not complete PASS")
    configs = []
    for match in contract["matches"]:
        config = copy.deepcopy(first["config"])
        config["fixed_move_time_ms"] = match["fixed_move_time_ms"]
        config["seed"] = match["seed"]
        configs.append(config)
    return configs


def verify_bindings(contract, root=ROOT):
    from scratch.nnue_full_suite_attestation import (
        inventory_sha256, source_inventory_paths, test_inventory_paths)
    for section in ("artifact_sha256", "evidence_sha256"):
        for name, expected in contract[section].items():
            if sha(root / name) != expected:
                raise ValueError(f"Bound file changed: {name}")
    for key, paths in (("source_inventory_sha256", source_inventory_paths(root)),
                       ("test_inventory_sha256", test_inventory_paths(root))):
        if inventory_sha256(paths, root=root) != contract[key]:
            raise ValueError(f"Frozen {key} changed")
    if sys.version.split()[0] != contract["python_version"]:
        raise ValueError("Python version changed")
    if Path(sys.executable).resolve() != Path(contract["python_executable"]).resolve():
        raise ValueError("Python executable changed")
    return expected_configs(contract, root)


def repository_preflight(root=ROOT):
    """Cheap local prerequisites only; never inspect results or start work.

    A Git clone cannot establish the state of the original Windows arena.
    Large tablebases receive existence checks only to avoid competing for I/O.
    Full binding/process verification remains the host lifecycle's job.
    """
    root = Path(root).resolve()
    blockers, files = [], []
    report = {"format": "thai-makhos-gate-c-preflight-v1",
              "scope": "local_prerequisites_only", "root": str(root),
              "runtime_state": "UNKNOWN_NOT_INSPECTED",
              "result_payload_reads": 0, "native_search_authorized": False,
              "production_promoted": False, "files": files, "blockers": blockers,
              "verification_pending": ["full artifact and source/test inventory hashes",
                  "original Windows host process creation identity and GUI/workload state",
                  "manifest-bound live logs or stopped results; independent Gate C verdicts",
                  "production smoke and reversible promotion review after both controls PASS"]}
    try:
        contract = contract_at(root)
    except (OSError, ValueError) as error:
        blockers.append({"kind": "contract", "detail": str(error)})
        # Git's LF checkout of the Windows-frozen CRLF contract is a useful
        # diagnosis, never a replacement identity or launch authorization.
        try:
            raw = (root / CONTRACT).read_bytes()
            crlf = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            if hashlib.sha256(crlf).hexdigest().upper() != CONTRACT_SHA:
                report["status"] = "BLOCKED_LOCAL_PREREQUISITES"
                return report
            report["contract_checkout"] = {
                "actual_sha256": hashlib.sha256(raw).hexdigest().upper(),
                "required_sha256": CONTRACT_SHA,
                "diagnosis": "CRLF reconstruction matches frozen identity; checkout still rejected"}
            contract = json.loads(crlf)
        except (OSError, ValueError):
            report["status"] = "BLOCKED_LOCAL_PREREQUISITES"
            return report
    # Even if a future contract references a checkpoint as evidence, do not
    # open it here. Only the live/stopped manifest-bound monitor may do that.
    result_paths = {(root / m["output"]).resolve() for m in contract["matches"]}
    for section in ("artifact_sha256", "evidence_sha256"):
        for name, expected in contract[section].items():
            path = root / name
            row = {"path": name, "section": section, "expected_sha256": expected}
            try:
                path.resolve().relative_to(root)
                if not path.is_file():
                    row["check"] = "MISSING"
                    blockers.append({"kind": "missing_file", "path": name})
                elif path.resolve() in result_paths or path.stat().st_size > 1024 * 1024:
                    row["check"] = "PRESENT_NOT_HASHED"
                else:
                    row["actual_sha256"] = sha(path)
                    row["check"] = "MATCH" if row["actual_sha256"] == expected else "HASH_MISMATCH"
                    if row["check"] == "HASH_MISMATCH":
                        blockers.append({"kind": "hash_mismatch", "path": name})
            except (OSError, ValueError) as error:
                row["check"] = "UNREADABLE"
                blockers.append({"kind": "file_error", "path": name, "detail": str(error)})
            files.append(row)
    for name in [ACTIVE, *(match["output"] for match in contract["matches"])]:
        present = (root / name).is_file()
        files.append({"path": name, "section": "runtime_evidence",
                      "check": "PRESENT_NOT_READ" if present else "MISSING"})
        if not present:
            blockers.append({"kind": "missing_runtime_evidence", "path": name})
    if os.name != "nt":
        blockers.append({"kind": "host_platform", "required": "Windows", "actual": os.name})
    if sys.version.split()[0] != contract["python_version"]:
        blockers.append({"kind": "python_version", "required": contract["python_version"],
                         "actual": sys.version.split()[0]})
    if Path(sys.executable).resolve() != Path(contract["python_executable"]).resolve():
        blockers.append({"kind": "python_executable", "required": contract["python_executable"],
                         "actual": sys.executable})
    report["status"] = ("BLOCKED_LOCAL_PREREQUISITES" if blockers else
                        "LOCAL_PREREQUISITES_PRESENT_HOST_VERIFICATION_REQUIRED")
    return report


def process_identity(pid):
    """Creation ticks reject PID reuse; None means the process no longer exists."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:
            return None
        raise ctypes.WinError(error)
    try:
        created, exited, kernel_time, user_time = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *map(ctypes.byref, (created, exited, kernel_time, user_time))):
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"pid": pid, "creation_ticks": (created.dwHighDateTime << 32) | created.dwLowDateTime,
                "live": code.value == 259, "exit_code": code.value}
    finally:
        kernel.CloseHandle(handle)


def same_live_process(recorded, observed):
    return bool(recorded and observed and observed["live"]
                and recorded["pid"] == observed["pid"]
                and recorded["creation_ticks"] == observed["creation_ticks"])


def run_state(payload, live, stderr_bytes, gui_active):
    if stderr_bytes > 0:
        return "PAUSED_FOR_GUI_REVIEW_LOG" if gui_active else "ERROR_REVIEW_LOG"
    if payload and payload["complete"]:
        return "FINISHED_" + payload["result"]["status"]
    if live:
        return "YIELDING_TO_GUI" if gui_active else "RUNNING"
    if gui_active:
        return "PAUSED_FOR_GUI"
    return "STOPPED_REQUIRES_VERIFIED_RESUME" if payload else "NOT_STARTED"


def active_manifest(root=ROOT):
    pointer_path = root / ACTIVE
    if not pointer_path.exists():
        return None
    pointer = read_json(pointer_path)
    manifest_path = Path(pointer["manifest"]).resolve()
    manifest_path.relative_to((root / "build").resolve())
    if sha(manifest_path) != pointer["sha256"]:
        raise ValueError("Active run manifest changed")
    manifest = read_json(manifest_path)
    if manifest["contract_sha256"] != CONTRACT_SHA:
        raise ValueError("Active run belongs to another contract")
    return manifest


PAIR_LINE = re.compile(
    r"Pair\s+(\d+)\s+\(\s*(\d+) games\)\s+\|\s+W:\s*(\d+)\s+D:\s*(\d+)\s+L:\s*(\d+)"
    r"\s+\|\s+Ptnml:\s*(\d+)/(\d+)/(\d+)/(\d+)/(\d+)\s+\|.*\|\s+Status:\s*(PASS|FAIL|INCONCLUSIVE)"
)


def read_live_result(log_path, expected_config):
    """Read append-only stdout, never the active writer's checkpoint path."""
    from makhos.sprt import calculate_pentanomial_sprt
    with Path(log_path).open("rb") as stream:
        head = stream.readline(65536)
        stream.seek(0, os.SEEK_END)
        length = stream.tell()
        offset = max(0, length - 65536)
        stream.seek(offset)
        if offset:
            # Discard only a clipped first line, preserving a line that starts
            # exactly at the bounded tail window.
            stream.seek(offset - 1)
            if stream.read(1) != b"\n":
                stream.readline()
        tail = stream.read()
    if not head.endswith(b"\n"):
        return None
    prefix = b"SPRT_CONFIG "
    if not head.startswith(prefix) or json.loads(head[len(prefix):]) != expected_config:
        raise ValueError("Live log configuration mismatch")
    pairs = []
    for encoded in tail.splitlines(keepends=True):
        if not encoded.endswith(b"\n"):
            continue
        line = encoded.decode("utf-8").strip()
        if not line.startswith("Pair "):
            continue
        match = PAIR_LINE.fullmatch(line)
        if not match:
            raise ValueError("Malformed complete pair log line")
        numbers = list(map(int, match.groups()[:10]))
        count, games, wins, draws, losses, *buckets = numbers
        status, llr, elo, error = calculate_pentanomial_sprt(
            tuple(buckets), expected_config["elo0"], expected_config["elo1"])
        if match.group(11) != status:
            raise ValueError("Live log verdict does not reproduce")
        payload = {"format": "thai-makhos-sprt-result-v2", "complete": False,
            "config": expected_config, "result": {"pairs": count, "games": games,
                "wins": wins, "draws": draws, "losses": losses, "pentanomial": buckets,
                "status": status, "llr": llr, "elo": elo, "elo_95_error": error}}
        checked_result(payload, expected_config)
        if pairs:
            previous = pairs[-1]["result"]
            if (previous["status"] != "INCONCLUSIVE"
                    or count != previous["pairs"] + 1):
                raise ValueError("Live pair sequence duplicated, missing, or past a stop condition")
            # Validate the delta as one actual color-swapped pair. Independently
            # valid cumulative totals must not rewrite earlier game outcomes.
            delta = {key: payload["result"][key] - previous[key]
                     for key in ("pairs", "games", "wins", "draws", "losses")}
            delta["pentanomial"] = [n - old for n, old in
                                     zip(buckets, previous["pentanomial"])]
            checked_pair_counts(delta, 1)
        pairs.append(payload)
    return pairs[-1] if pairs else None


def publish_pointer(temporary, pointer):
    # Only our metadata publisher retries. The frozen arena writer is unchanged.
    for attempt in range(50):
        try:
            os.replace(temporary, pointer)
            return
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.02)


def snapshot(root=ROOT):
    from makhos.workload_isolation import interactive_session_active
    contract = contract_at(root)
    configs = expected_configs(contract, root)
    manifest = active_manifest(root)
    gui = interactive_session_active()
    rows = []
    for match, config in zip(contract["matches"], configs):
        path = root / match["output"]
        current = manifest if manifest and manifest["output"] == match["output"] else None
        observed = process_identity(current["process"]["pid"]) if current else None
        live = same_live_process(current["process"], observed) if current else False
        if live:
            payload = read_live_result(current["stdout"], config)
            progress_path = Path(current["stdout"])
        else:
            payload = read_json(path) if path.exists() else None
            progress_path = path
        if payload:
            checked_result(payload, config)
        error_path = Path(current["stderr"]) if current else None
        stderr_bytes = error_path.stat().st_size if error_path and error_path.exists() else 0
        rows.append({"budget_ms": match["fixed_move_time_ms"], "output": str(path),
                     "state": run_state(payload, live, stderr_bytes, gui),
                     "result": payload["result"] if payload else None,
                     "result_source": "append_only_stdout" if live else "stopped_checkpoint",
                     "last_pair_at": datetime.fromtimestamp(progress_path.stat().st_mtime, timezone.utc).isoformat() if payload else None,
                     "last_pair_unix": int(progress_path.stat().st_mtime) if payload else None,
                     "process": observed, "identity_confirmed": live,
                     "stderr_bytes": stderr_bytes, "stderr": str(error_path) if error_path else None})
    return {"format": "thai-makhos-gate-c-status-v1", "updated_at": datetime.now(timezone.utc).isoformat(),
            "gui_active": gui, "matches": rows, "llr_bound": math.log(19),
            "promotion": "NOT_PROMOTED", "eta": None}


def launch(root=ROOT):
    from scratch.nnue_full_suite_attestation import ExclusiveSuiteLease
    from scratch.nnue_quiet_leaf_acquire import write_locked_json
    from makhos.workload_isolation import _RangeLock, ensure_interactive_session_inactive
    lock = _RangeLock(root / "build/runtime/nnue_gate_c_launch.lock")
    if not lock.try_lock(0, 1):
        raise RuntimeError("Another Gate C launcher owns the launch lock")
    try:
        with ExclusiveSuiteLease(root):
            contract = contract_at(root)
            configs = verify_bindings(contract, root)
            # Refuse untracked Python batch work as well as a duplicate arena.
            inventory = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command",
                "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Select-Object ProcessId,CommandLine) | ConvertTo-Json -Compress"], text=True)
            processes = json.loads(inventory or "[]")
            if isinstance(processes, dict):
                processes = [processes]
            if any(p["ProcessId"] != os.getpid() for p in processes):
                raise RuntimeError("Other Python workload detected; inspect before launch")
            match = contract["matches"][1]
            result_path = root / match["output"]
            if result_path.exists():
                payload = read_json(result_path)
                require_resumable_result(payload, configs[1])
            previous = active_manifest(root)
            if previous:
                observed = process_identity(previous["process"]["pid"])
                if same_live_process(previous["process"], observed):
                    raise RuntimeError("Previous arena is still alive")
                if Path(previous["stderr"]).stat().st_size:
                    raise RuntimeError("Previous stderr needs an explicit incident review before resume")
            run_dir = root / "build" / ("nnue_gate_c_2000ms_run_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6])
            run_dir.mkdir()
            if result_path.exists():
                # Preserve original checkpoint bytes; do not rewrite its contents.
                import shutil
                shutil.copyfile(result_path, run_dir / "checkpoint_before_resume.json")
            command = [contract["python_executable"], *match["argv"]]
            write_locked_json(run_dir / "launch_intent.json", {
                "command": command, "cwd": str(root), "contract_sha256": CONTRACT_SHA,
                "source_inventory_sha256": contract["source_inventory_sha256"],
                "test_inventory_sha256": contract["test_inventory_sha256"],
                "predecessor_result_sha256": FIRST_PASS_SHA, "tool_sha256": sha(__file__)})
        ensure_interactive_session_inactive("Gate C 2000ms launch")
        stdout, stderr = run_dir / "stdout.log", run_dir / "stderr.log"
        with stdout.open("xb") as out, stderr.open("xb") as err:
            child = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                close_fds=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        try:
            identity = process_identity(child.pid)
            if not identity or not identity["live"]:
                raise RuntimeError("Arena exited at startup; inspect preserved logs")
            manifest_path = run_dir / "run.json"
            write_locked_json(manifest_path, {"format": "thai-makhos-gate-c-run-v1",
                "contract_sha256": CONTRACT_SHA, "output": match["output"], "command": command,
                "cwd": str(root), "process": identity, "started_at": datetime.now(timezone.utc).isoformat(),
                "stdout": str(stdout), "stderr": str(stderr), "automatic_restart": False})
            pointer = root / ACTIVE
            temporary = pointer.with_name(pointer.name + "." + uuid.uuid4().hex + ".tmp")
            write_locked_json(temporary, {"manifest": str(manifest_path), "sha256": sha(manifest_path)})
            publish_pointer(temporary, pointer)
            return {"started": True, "manifest": str(manifest_path), "process": identity}
        except BaseException:
            # Only the child created by this failed launch is eligible for cleanup.
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            raise
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "status", "verify", "launch"))
    args = parser.parse_args()
    if args.action == "preflight":
        result = repository_preflight()
    elif args.action == "status":
        result = snapshot()
    elif args.action == "verify":
        verify_bindings(contract_at())
        result = {"verified": True, "next": "2000ms", "promotion": False}
    else:
        result = launch()
    print(json.dumps(result, sort_keys=True), flush=True)
    if args.action == "preflight" and result["blockers"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
