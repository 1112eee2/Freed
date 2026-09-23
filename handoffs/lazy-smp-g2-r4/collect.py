"""Run the frozen r4 pthread handoff under ThreadSanitizer; never alter inputs.

Usage: python3 collect.py <result-dir-name>

Writes logs, commands.json and result.json under results/<result-dir-name>/.
Raw status is REVIEW_REQUIRED; the reviewed classification is decided by Windows Local.
r3 results are never read, reused or transferred here.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
OUT = HERE / "results" / sys.argv[1]
OUT.mkdir(parents=True, exist_ok=False)
BIN = OUT / "binaries"
BIN.mkdir()
os.chdir(HERE)
records = []


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quote(path):
    return shlex.quote(str(path))


def run(name, command):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clock = time.monotonic()
    env = os.environ.copy()
    env.pop("TSAN_OPTIONS", None)
    process = subprocess.Popen(["/bin/bash", "-c", command], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env, start_new_session=True)
    killed = False
    try:
        stdout, stderr = process.communicate(timeout=130)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        killed = True
    for suffix, content in (("stdout", stdout), ("stderr", stderr)):
        (OUT / f"{name}.{suffix}.log").write_bytes(content)
    item = dict(name=name, command=command, cwd=str(HERE), started_utc=started,
                exit_code=process.returncode, elapsed_seconds=time.monotonic() - clock,
                runner_killed=killed, stdout=f"{name}.stdout.log",
                stderr=f"{name}.stderr.log",
                stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                stderr_sha256=hashlib.sha256(stderr).hexdigest())
    records.append(item)
    (OUT / "commands.json").write_text(json.dumps(records, indent=2) + "\n")
    print(name, process.returncode, round(item["elapsed_seconds"], 3),
          stderr.decode(errors="replace")[:120], flush=True)
    return item


def has_race_report(item):
    text = (OUT / item["stderr"]).read_text(errors="replace")
    text += (OUT / item["stdout"]).read_text(errors="replace")
    return "WARNING: ThreadSanitizer: data race" in text


inputs = {str(path.relative_to(HERE)): digest(path) for path in HERE.rglob("*")
          if path.is_file() and path.relative_to(HERE).parts[0] != "results"}
assert run("verify_before", "python3 verify_snapshot.py")["exit_code"] == 0
run("environment", "uname -a\ncat /etc/os-release\ngetconf GNU_LIBC_VERSION\n"
    "python3 --version\nclang --version\ngcc --version\ngdb --version\ntimeout --version\n"
    "dpkg-query -W clang libclang-rt-18-dev gcc libtsan2 libc6 gdb\n"
    "cat /proc/sys/vm/mmap_rnd_bits\nnproc\nps -eo pid,comm --sort=pid")

results = {}
sources = {"smoke_pthread": HERE / "smoke_pthread.c",
           "negative_pthread": HERE / "negative_pthread.c",
           "probe": HERE / "probe.c"}
for compiler in ("clang", "gcc"):
    tests = {}
    for name, source in sources.items():
        for mode in ("plain", "tsan"):
            ident = f"{compiler}_{name}_{mode}"
            binary = BIN / ident
            flags = "-fsanitize=thread " if mode == "tsan" else ""
            built = run(ident + "_compile",
                        f"{compiler} -std=c17 -O1 -g {flags}-pthread "
                        f"{quote(source)} -o {quote(binary)}")
            entry = {"compile": built, "runs": []}
            tests[ident] = entry
            if built["exit_code"] != 0:
                entry["status"] = "NOT_RUN"
                continue
            entry["binary_sha256"] = digest(binary)
            entry["binary_path"] = str(binary.relative_to(HERE))
            if mode == "tsan":
                run(ident + "_linkage", f"ldd {quote(binary)}")
            repeats = 5 if (name == "probe" and mode == "tsan") else 1
            for index in range(repeats):
                prefix = "TSAN_OPTIONS=halt_on_error=1 " if mode == "tsan" else ""
                entry["runs"].append(
                    run(f"{ident}_run_{index + 1:02}", f"{prefix}timeout 120s {quote(binary)}"))
            if mode == "tsan":
                entry["reported_data_race"] = any(has_race_report(x) for x in entry["runs"])
                if any(x["exit_code"] for x in entry["runs"]):
                    run(ident + "_gdb",
                        f"TSAN_OPTIONS=halt_on_error=1 timeout 120s gdb -q -batch "
                        f"-ex \"set pagination off\" -ex \"set disable-randomization off\" "
                        f"-ex \"handle SIGSEGV stop print nopass\" -ex run "
                        f"-ex \"thread apply all bt\" -ex \"info sharedlibrary\" "
                        f"-ex \"info registers\" --args {quote(binary)}")
    results[compiler] = tests

assert run("verify_after", "python3 verify_snapshot.py")["exit_code"] == 0
assert all(digest(HERE / path) == value for path, value in inputs.items())
result = {"status": "REVIEW_REQUIRED",
          "handoff": "lazy-smp-g2-r4",
          "scope": "publication protocol only; not Windows worker lifecycle or full G2/G3",
          "prior_results": "r3 (PR #18 and the C11 follow-up) preserved, not reused",
          "input_sha256": inputs, "inputs_unchanged": True, "tests": results,
          "tsan_options": "halt_on_error=1", "suppressions": False, "aslr_modified": False,
          "review_note": "a TSan report, assertion failure or timeout is not PASS; "
                         "an unsupported sanitizer runtime is NOT_RUN"}
(OUT / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print("REVIEW_REQUIRED", OUT)
