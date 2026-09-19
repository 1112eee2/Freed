"""Bounded GitHub-hosted, single-thread seed diagnostic; not a TSan gate."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = "117c22aa3cf47d1175e1758c70f9af1ab8daa709"
PROBES = {
    "r3": ("handoffs/lazy-smp-g2-r3", "67f8b7cf54e25e385a314bfa02b3bd71a153a98ec21e7b3218393e120194a19b"),
    "r4": ("handoffs/lazy-smp-g2-r4", "2c1c6fa494941bb8b2411cd4c41d3ca5160a382013d3fa32d78c9dadd6db3be9"),
}
run_id = os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]
OUT = HERE / "results" / run_id
OUT.mkdir(parents=True, exist_ok=False)
BUILD = ROOT / "build" / ("seed-diagnostic-" + run_id)
BUILD.mkdir(parents=True, exist_ok=False)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
commands = []
cases = []
result = {
    "status": "NOT_RUN", "scope": "deterministic harness-initialization diagnosis only",
    "base_commit": BASE, "source_commit": os.environ["GITHUB_SHA"],
    "workflow_url": "https://github.com/1112eee2/ThaiMakhosEngine/actions/runs/" + os.environ["GITHUB_RUN_ID"],
    "sanitizer": None, "tsan_gate_run": False, "g2": "NOT_PASSED",
    "candidate": "REJECT_FOR_PERFORMANCE / NOT_PROMOTED (user-directed retained status)",
    "threads_created_by_diagnostic": 0,
    "planned_matrix": "r3/r4 x clang/gcc x snapshot/assert-reader/valid-control = 12 processes",
    "cases": cases,
}

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

def run(label, argv, timeout=30, cwd=ROOT):
    begin = time.monotonic()
    entry = {"label": label, "argv": [str(a) for a in argv], "cwd": str(cwd),
             "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
             "timeout_seconds": timeout, "timed_out": False}
    try:
        p = subprocess.run(entry["argv"], cwd=cwd, capture_output=True, timeout=timeout, check=False)
        stdout, stderr = p.stdout, p.stderr
        entry["exit_code"] = p.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        entry.update(exit_code=None, timed_out=True)
    except OSError as exc:
        stdout, stderr = b"", (repr(exc) + "\n").encode()
        entry.update(exit_code=None, launch_error=repr(exc))
    entry["elapsed_seconds"] = time.monotonic() - begin
    for kind, raw in (("stdout", stdout), ("stderr", stderr)):
        filename = label + "." + kind + ".log"
        (OUT / filename).write_bytes(raw)
        entry[kind] = filename
        entry[kind + "_sha256"] = hashlib.sha256(raw).hexdigest()
    commands.append(entry)
    write_json("commands.json", commands)
    return entry

def require_zero(entry):
    if entry["exit_code"] != 0 or entry["timed_out"]:
        raise RuntimeError("prerequisite failed: " + entry["label"])

def protected_inventory():
    paths = subprocess.check_output(["git", "ls-files", "-z", "handoffs/lazy-smp-g2-r3",
        "handoffs/lazy-smp-g2-r4", "RULESET.json", "makhos/core.py", "config/gui_release.json",
        "releases/nnue-v1-20260908", "build/makhos_native_accepted.dll"], cwd=ROOT)
    return {s: digest(ROOT / s) for s in paths.decode().split("\0") if s}

before = None
try:
    require_zero(run("git_head", ["git", "rev-parse", "HEAD"]))
    require_zero(run("base_is_ancestor", ["git", "merge-base", "--is-ancestor", BASE, "HEAD"]))
    before = protected_inventory()
    write_json("protected_before.json", before)
    for label, argv in (
        ("uname", ["uname", "-a"]), ("os_release", ["cat", "/etc/os-release"]),
        ("python", [sys.executable, "--version"]), ("libc", ["ldd", "--version"]),
        ("clang_version", ["clang", "--version"]), ("gcc_version", ["gcc", "--version"]),
        ("cpu", ["lscpu"]), ("processes_before", ["ps", "-eo", "pid,comm"])):
        run(label, argv)
    source_hashes = {}
    setups = {}
    for rev, (folder, expected) in PROBES.items():
        frozen = ROOT / folder
        require_zero(run(rev + "_verify_before", [sys.executable, "-B", "verify_snapshot.py"], cwd=frozen))
        probe = frozen / "probe.c"
        if digest(probe) != expected:
            raise RuntimeError("probe hash mismatch " + rev)
        text = probe.read_text()
        main = text.split("int main(void) {", 1)[1]
        start = main.index("    NativeCompactMove move = {1, 2, 3, 4};")
        stop = main.index("    " + ("thrd_t" if rev == "r3" else "pthread_t") + " workers[12];")
        setup = main[start:stop]
        if not setup.endswith("    atomic_store(&slot.sequence, 0);\n"):
            raise RuntimeError("unexpected frozen setup boundary")
        setups[rev] = setup
        source_hashes[folder + "/probe.c"] = expected
    if setups["r3"] != setups["r4"]:
        raise RuntimeError("r3/r4 pre-thread setup differs")
    setup_path = BUILD / "seed_setup.inc"
    setup_path.write_text(setups["r4"], encoding="utf-8")
    (OUT / "seed_setup.inc").write_bytes(setup_path.read_bytes())
    source_hashes["generated/seed_setup.inc"] = digest(setup_path)
    for p in (HERE / "reproduce.c", HERE / "collect.py", ROOT / ".github/workflows/lazy-smp-seed-diagnostic.yml"):
        source_hashes[str(p.relative_to(ROOT))] = digest(p)
    result["source_sha256"] = source_hashes
    result["setup_is_verbatim_and_equal_r3_r4"] = True
    for rev, (folder, _) in PROBES.items():
        for cc in ("clang", "gcc"):
            label = rev + "_" + cc
            binary = BUILD / label
            compiled = run(label + "_compile", [cc, "-std=c17", "-O1", "-g", "-pthread",
                "-I", str(ROOT), "-I", str(BUILD), '-DFROZEN_PROBE="' + folder + '/probe.c"',
                str(HERE / "reproduce.c"), "-o", str(binary)], timeout=60)
            if compiled["exit_code"] != 0:
                cases.append({"revision": rev, "compiler": cc, "status": "NOT_RUN",
                              "reason": "compile failed", "command": compiled["label"]})
                continue
            binary_hash = digest(binary)
            run(label + "_linkage", ["ldd", str(binary)])
            for mode in ("snapshot", "assert-reader", "valid-control"):
                observed = run(label + "_" + mode, [str(binary), mode], timeout=10)
                stdout = (OUT / observed["stdout"]).read_text(errors="replace")
                stderr = (OUT / observed["stderr"]).read_text(errors="replace")
                records = []
                parse_error = None
                try:
                    records = [json.loads(line) for line in stdout.splitlines() if line.strip()]
                except ValueError as exc:
                    parse_error = str(exc)
                seed = records[0] if records else {}
                seed_ok = (seed.get("hit") is True and seed.get("threads_created") == 0
                    and seed.get("sequence_before") == seed.get("sequence_after") == "0000000000000000"
                    and seed.get("key") == "000000000000007b" and seed.get("epoch") == 7
                    and seed.get("data") == "0000000700000000"
                    and seed.get("w0") == "0000000000000001"
                    and seed.get("w1") == "0000000000000002"
                    and seed.get("w2") == "0000000400000003" and seed.get("depth") == 0
                    and all(seed.get(k) is False for k in ("low_ok", "high_ok", "captured_high_ok", "depth_ok")))
                if mode == "assert-reader":
                    expected_ok = (observed["exit_code"] == -signal.SIGABRT
                        and "move.captured_low == ~move.path_low" in stderr)
                else:
                    expected_ok = observed["exit_code"] == 0 and not stderr
                    if mode == "valid-control":
                        expected_ok &= bool(records and records[-1].get("accepted") == 100000)
                cases.append({"revision": rev, "compiler": cc, "mode": mode,
                    "command": observed["label"], "binary_sha256": binary_hash,
                    "expected_exit": -signal.SIGABRT if mode == "assert-reader" else 0,
                    "actual_exit": observed["exit_code"], "parse_error": parse_error,
                    "seed_snapshot_matches": seed_ok, "observations": records,
                    "status": "EXPECTED_OBSERVATION" if seed_ok and expected_ok and not parse_error
                              and not observed["timed_out"] else "UNEXPECTED_RESULT"})
    for rev, (folder, _) in PROBES.items():
        require_zero(run(rev + "_verify_after", [sys.executable, "-B", "verify_snapshot.py"], cwd=ROOT/folder))
    result["status"] = ("CONFIRMED_HARNESS_INITIALIZATION_DEFECT"
        if len(cases) == 12 and all(c["status"] == "EXPECTED_OBSERVATION" for c in cases)
        else "INCOMPLETE_OR_UNEXPECTED")
except Exception:
    result["error"] = traceback.format_exc()
finally:
    try:
        after = protected_inventory()
        write_json("protected_after.json", after)
        result["protected_inputs_unchanged"] = before is not None and before == after
        diff = run("tracked_worktree_diff", ["git", "diff", "--exit-code"])
        result["tracked_worktree_unchanged"] = diff["exit_code"] == 0
        if not result["protected_inputs_unchanged"] or not result["tracked_worktree_unchanged"]:
            result["status"] = "INPUT_DRIFT"
    except Exception:
        result["preservation_error"] = traceback.format_exc()
        result["status"] = "INPUT_VERIFICATION_FAILED"
    result["confirmed_scope"] = "This run only; original failures are not individually attributed."
    result["unknown"] = ["Cause of each historical concurrent failure", "General publication safety",
                         "Concurrent liveness guarantee", "Windows G2-G6 acceptance"]
    write_json("result.json", result)
    write_json("commands.json", commands)
    hashes = {p.name: digest(p) for p in sorted(OUT.iterdir()) if p.is_file()}
    write_json("evidence_sha256.json", hashes)
    # Text-only GitHub job-log transport, one JSON object per file. No binaries.
    for p in sorted(OUT.iterdir()):
        if p.is_file():
            print("SEED_EVIDENCE_FILE " + json.dumps({"path": p.name, "content": p.read_text()}), flush=True)
    print("SEED_DIAGNOSTIC_STATUS " + result["status"], flush=True)
sys.exit(0 if result["status"] == "CONFIRMED_HARNESS_INITIALIZATION_DEFECT" else 1)
