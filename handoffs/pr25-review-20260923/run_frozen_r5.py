"""Run the frozen r5 collector once; archive every output without changing inputs."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "handoffs/lazy-smp-g2-r5"
BASE = "0ced9eb2759ccd0dbe2541b07b0609301c80e317"
PR25 = "7cca706377f5e963431fc0f251b91add8673a136"
RUN_ID = "linux-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]
OUT = BUNDLE / "results" / RUN_ID
EXTRA = ROOT / "handoffs/pr25-review-20260923/results" / RUN_ID
EXTRA.mkdir(parents=True, exist_ok=False)
COMMANDS = []

def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(name, data):
    (EXTRA / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def run(name, argv, timeout=30):
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    before = time.monotonic()
    timed_out = False
    error = None
    try:
        p = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=timeout)
        code, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = None, exc.stdout or b"", exc.stderr or b""
        timed_out = True
    except OSError as exc:
        code, stdout, stderr = None, b"", str(exc).encode()
        error = str(exc)
    for suffix, data in (("stdout", stdout), ("stderr", stderr)):
        (EXTRA / (name + "." + suffix + ".log")).write_bytes(data)
    item = dict(name=name, argv=argv, cwd=str(ROOT), started_utc=started,
                exit_code=code, timed_out=timed_out, launch_error=error,
                timeout_seconds=timeout, elapsed_seconds=time.monotonic()-before,
                stdout=name+".stdout.log", stderr=name+".stderr.log",
                stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                stderr_sha256=hashlib.sha256(stderr).hexdigest())
    COMMANDS.append(item)
    save("commands.json", COMMANDS)
    return item, stdout

def inventory():
    paths = subprocess.check_output(["git","ls-files","-z"], cwd=ROOT).decode().split("\0")
    return {p:hash_file(ROOT/p) for p in paths if p and (ROOT/p).is_file()}

before = inventory()
save("tracked_before.json", before)
for name, argv in (
    ("git_head", ["git","rev-parse","HEAD"]),
    ("base_ancestor", ["git","merge-base","--is-ancestor",BASE,"HEAD"]),
    ("uname", ["uname","-a"]),
    ("os_release", ["cat","/etc/os-release"]),
    ("cpu", ["lscpu"]),
    ("libc", ["ldd","--version"]),
    ("packages", ["dpkg-query","-W","clang-18","libclang-rt-18-dev","gcc-13","libtsan2","libc6"]),
    ("clang_runtime_path", ["clang-18","--print-runtime-dir"]),
    ("gcc_runtime_path", ["gcc-13","-print-file-name=libtsan.so"]),
    ("processes_before", ["ps","-eo","pid,comm"]),
):
    run(name, argv)
# Record runtime binary identities where the installed compiler exposes them.
runtime_files = {}
for label in ("clang_runtime_path", "gcc_runtime_path"):
    value=(EXTRA/(label+".stdout.log")).read_text(errors="replace").strip()
    p=Path(value)
    if value and p.is_absolute() and p.exists():
        candidates = list(p.glob("*tsan*")) if p.is_dir() else [p]
        for q in candidates:
            if q.is_file():
                runtime_files[str(q)] = hash_file(q)
save("runtime_sha256.json", runtime_files)
save("provenance.json", dict(
    frozen_r5_commit=BASE, reviewed_pr25_commit=PR25,
    execution_commit=os.environ.get("GITHUB_SHA"),
    workflow_run=os.environ["GITHUB_RUN_ID"], attempt=os.environ["GITHUB_RUN_ATTEMPT"],
    run_url="https://github.com/1112eee2/ThaiMakhosEngine/actions/runs/"+os.environ["GITHUB_RUN_ID"],
    runner_image=os.environ.get("ImageOS"), runner_image_version=os.environ.get("ImageVersion"),
    tsan_options="halt_on_error=1 (set by frozen collector)",
    inherited_tsan_options=os.environ.get("TSAN_OPTIONS"),
    repeated_gate_processes=False, suppression_added=False,
    note="Wrapper records environment and transports evidence. Frozen probe/collector/workflow are untouched."
))
try:
    run("frozen_collector", [sys.executable,"-B",str(BUNDLE/"collect.py"),RUN_ID,"--lane","linux-tsan"], 1500)
finally:
    after=inventory()
    save("tracked_after.json", after)
    save("integrity.json", dict(all_tracked_files_unchanged=before==after,
         changed=[p for p in set(before)|set(after) if before.get(p)!=after.get(p)]))
    workflow=ROOT/".github/workflows/astra-r5-review-run.yml"
    (EXTRA/"executed_workflow.yml").write_bytes(workflow.read_bytes())
    # Preserve the collector's own result/hash manifest exactly. Additional evidence has its own manifest.
    save("evidence_sha256.json", {
        str(p.relative_to(EXTRA)):hash_file(p) for p in sorted(EXTRA.rglob("*"))
        if p.is_file() and p.name!="evidence_sha256.json"
    })
    for directory in (OUT, EXTRA):
        if directory.is_dir():
            for p in sorted(directory.rglob("*")):
                if p.is_file():
                    raw=p.read_bytes()
                    # Logs are UTF-8 on this runner. Never silently replace or drop bytes.
                    content=raw.decode("utf-8", errors="strict")
                    print("R5_EVIDENCE_FILE "+json.dumps(dict(
                        path=str(p.relative_to(ROOT)),content=content,
                        sha256=hashlib.sha256(raw).hexdigest()
                    ),ensure_ascii=True), flush=True)
result_path=OUT/"result.json"
summary=json.loads(result_path.read_text()) if result_path.is_file() else {"status":"NOT_RUN"}
print("R5_COLLECTION_SUMMARY "+json.dumps(dict(
    status=summary.get("status"), original_result=str(result_path.relative_to(ROOT)),
    all_tracked_files_unchanged=before==after,
    g2="NOT_PASSED", candidate="REJECT_FOR_PERFORMANCE / NOT_PROMOTED"
)), flush=True)
raise SystemExit(0 if before==after and result_path.is_file() else 1)
