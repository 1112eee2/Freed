"""Export verbatim production publication code for the r4 pthread race-detector run.

r4 revision of ``tools/verification/prepare_lazy_smp_race_probe.py``. The r3 exporter
and its frozen bundle stay byte-for-byte unchanged; this is a separate versioned
handoff. The only harness difference is the thread adapter layer: pthread instead of
C11 ``thrd_*``, because the unchanged r3 C11 probe and a publication-free C11 smoke
both abort inside the sanitizer's function-entry handling with a null thread state on
the tested Clang/GCC + glibc combinations, while pthread controls instrument correctly
on the same runners.

No replacement implementation and no playing binary changes. This only prepares an
evidence bundle; successful export, a Windows smoke, or an ASan run does not pass the
TSan gate. r4 results must never be transferred from r3.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.verification.run_tests import new_output_directory

HANDOFF_ID = "lazy-smp-g2-r4"
PROBE_SOURCES = (
    "native/makhos_native.c",
    "native/makhos_types.h",
    "tests/native_lazy_smp_portable_pthread.c",
    "tests/native_lazy_smp_smoke_pthread.c",
    "tests/native_lazy_smp_negative_pthread.c",
    "tools/verification/prepare_lazy_smp_race_probe_r4.py",
)
CONTROL_SOURCES = (
    "tests/native_lazy_smp_smoke_pthread.c",
    "tests/native_lazy_smp_negative_pthread.c",
)
CONTROL_OUTPUT = {
    "smoke_pthread.c": "tests/native_lazy_smp_smoke_pthread.c",
    "negative_pthread.c": "tests/native_lazy_smp_negative_pthread.c",
}
HARNESS = "tests/native_lazy_smp_portable_pthread.c"

LINUX_BUILD = "clang -std=c17 -O1 -g -fsanitize=thread -pthread probe.c -o probe"
LINUX_RUN = "TSAN_OPTIONS=halt_on_error=1 timeout 120s ./probe"
NEGATIVE_BUILD = (
    "clang -std=c17 -O1 -g -fsanitize=thread -pthread negative_pthread.c -o negative"
)
NEGATIVE_RUN = "TSAN_OPTIONS=halt_on_error=1 timeout 120s ./negative"
SMOKE_BUILD = "clang -std=c17 -O1 -g -fsanitize=thread -pthread smoke_pthread.c -o smoke"
SMOKE_RUN = "timeout 120s ./smoke"
GATE = (
    "require a genuine pthread data-race report from the negative control, then five "
    "clean protocol PASS runs with zero exit, zero detector reports, no assertion "
    "failure and no timeout; an unsupported sanitizer runtime is NOT_RUN"
)
VERIFY_SNAPSHOT = '''"""Fail closed on input drift or non-verbatim production extraction (r4)."""
from pathlib import Path
import hashlib
import json
import re

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text())
for name, expected in manifest["source_sha256"].items():
    actual = hashlib.sha256((root / "source" / name).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"source hash mismatch: {name}")
probe = root / "probe.c"
if hashlib.sha256(probe.read_bytes()).hexdigest() != manifest["probe_sha256"]:
    raise SystemExit("probe hash mismatch")


def extract(source, pattern):
    found = re.findall(pattern, source, flags=re.MULTILINE)
    if len(found) != 1:
        raise SystemExit("ambiguous production extraction")
    return found[0]


types = (root / "source/native/makhos_types.h").read_text()
source = (root / "source/native/makhos_native.c").read_text()
parts = [extract(types, rf"^typedef struct \\{{[^{{}}]*\\}} {name};")
         for name in ("NativeCompactMove", "SharedMoveHintEntry")]
parts += [extract(source, rf"^static inline bool {name}\\([\\s\\S]*?^\\}}")
          for name in ("shared_move_hint_write", "shared_move_hint_read")]
expected = "#include <stdint.h>\\n#include <stdbool.h>\\n#include <stddef.h>\\n"
expected += "#include <stdatomic.h>\\n"
expected += "\\n\\n".join(parts) + "\\n"
expected += (root / "source/tests/native_lazy_smp_portable_pthread.c").read_text()
if probe.read_text() != expected:
    raise SystemExit("probe is not the verbatim production extraction")
if "<threads.h>" in probe.read_text() or "thrd_" in probe.read_text():
    raise SystemExit("r4 probe still contains a C11 thread adapter")
print("PASS: source hashes, probe hash and exact production extraction (r4 pthread)")
'''


def extract(source: str, pattern: str) -> str:
    matches = re.findall(pattern, source, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"expected one production declaration, found {len(matches)}")
    return matches[0]


def build_probe(raw: dict) -> str:
    source = raw["native/makhos_native.c"].decode().replace("\r\n", "\n")
    types = raw["native/makhos_types.h"].decode().replace("\r\n", "\n")
    declarations = [extract(types, rf"^typedef struct \{{[^{{}}]*\}} {name};")
                    for name in ("NativeCompactMove", "SharedMoveHintEntry")]
    declarations += [extract(source, rf"^static inline bool {name}\([\s\S]*?^\}}")
                     for name in ("shared_move_hint_write", "shared_move_hint_read")]
    content = "#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\n#include <stdatomic.h>\n"
    content += "\n\n".join(declarations) + "\n"
    content += raw[HARNESS].decode().replace("\r\n", "\n")
    return content


def readme(manifest: dict) -> str:
    return f"""# Astra Web: Linux ThreadSanitizer handoff (r4 pthread)

This is a **separate versioned r4 handoff**. The r3 handoff (`handoffs/lazy-smp-g2-r3/`),
PR #18 and its NOT_RUN evidence directory remain byte-for-byte frozen and are **not**
superseded or reinterpreted by this bundle. Never transfer r3 results to r4.

Use **this directory's source snapshot**, not the checkout's top-level native sources.
The exact inputs are under `source/`, bound by `manifest.json`. This branch does not
promote or replace any engine DLL.

## Why r4 exists

The unchanged r3 C11 probe and a publication-free C11 smoke both abort in sanitizer
function-entry handling (`__tsan_func_entry`, null thread state) on the tested
Clang/GCC + glibc combinations, while pthread negative controls are correctly
instrumented on the same runners. r4 replaces **only** the thread launch/join/yield
adapters with pthread. Eight writers, four readers, 100000 iterations each, all payload
assertions, start synchronization, mismatch/paused-writer/wrap checks, all atomic types
and memory orders, and the at-least-one-accepted-read requirement are unchanged.

## Procedure

Preferred: `python3 collect.py <unique-run-id>` runs every step below for both Clang and
GCC, writes raw logs, `commands.json` and `result.json` under `results/<unique-run-id>/`,
and re-verifies the snapshot before and after. Raw status is `REVIEW_REQUIRED`; the
reviewed classification is decided by Windows Local, not by the collector.

Manual equivalent:

1. Run `python3 verify_snapshot.py` here. Record this branch commit,
   OS/kernel/architecture, and compiler and sanitizer runtime versions.
2. Compile and execute the **independent pthread negative control** and require a
   genuine ThreadSanitizer data-race report. A nonzero exit alone could be a runtime
   failure and is not accepted as calibration. `{NEGATIVE_BUILD}` then
   `{NEGATIVE_RUN}`.
3. Compile and run the **pthread smoke** (`{SMOKE_BUILD}` then `{SMOKE_RUN}`) to
   separate a sanitizer thread-entry failure from a publication failure.
4. Compile `{LINUX_BUILD}`.
5. Run `{LINUX_RUN}` five times in separate processes. Capture commands, stdout/stderr,
   exit codes, elapsed times and binary SHA-256.
6. PASS requires a working negative control plus five clean protocol PASS results with
   no sanitizer reports, assertion failures or timeouts. An unsupported runtime is
   NOT_RUN.

Do not change atomics, assertions, workload, implementation, or add suppressions to
obtain PASS. ASan and ordinary stress do not replace TSan. If blocked, return the exact
error and environment evidence. Do not alter rules, production binaries or checkpoints,
launch SPRT, merge, or promote this branch.

## Return through GitHub

Put `result.json`, environment, commands and raw logs under
`handoffs/{HANDOFF_ID}/results/<unique-run-id>/`. Do not commit compiled binaries;
record their hashes. Keep inputs unchanged. Report the PR URL and result.
Scope is the publication protocol only, not the Windows worker lifecycle or full
G2/G3 acceptance. Windows Local validates evidence before closing any gate.

## Frozen identities

- probe SHA-256 `{manifest['probe_sha256']}`
- gate: {manifest['gate']}
"""


COLLECT_PY = '''"""Run the frozen r4 pthread handoff under ThreadSanitizer; never alter inputs.

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
    (OUT / "commands.json").write_text(json.dumps(records, indent=2) + "\\n")
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
run("environment", "uname -a\\ncat /etc/os-release\\ngetconf GNU_LIBC_VERSION\\n"
    "python3 --version\\nclang --version\\ngcc --version\\ngdb --version\\ntimeout --version\\n"
    "dpkg-query -W clang libclang-rt-18-dev gcc libtsan2 libc6 gdb\\n"
    "cat /proc/sys/vm/mmap_rnd_bits\\nnproc\\nps -eo pid,comm --sort=pid")

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
                        f"-ex \\"set pagination off\\" -ex \\"set disable-randomization off\\" "
                        f"-ex \\"handle SIGSEGV stop print nopass\\" -ex run "
                        f"-ex \\"thread apply all bt\\" -ex \\"info sharedlibrary\\" "
                        f"-ex \\"info registers\\" --args {quote(binary)}")
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
(OUT / "result.json").write_text(json.dumps(result, indent=2) + "\\n")
print("REVIEW_REQUIRED", OUT)
'''


def write_tree(root: Path, raw: dict, probe: str, manifest: dict,
               windows_smoke: Path | None = None) -> None:
    for name, content in raw.items():
        target = root / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (root / "probe.c").write_text(probe, encoding="utf-8", newline="\n")
    for name, source in CONTROL_OUTPUT.items():
        (root / name).write_bytes(raw[source])
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (root / "verify_snapshot.py").write_text(VERIFY_SNAPSHOT, encoding="utf-8", newline="\n")
    (root / "collect.py").write_text(COLLECT_PY, encoding="utf-8", newline="\n")
    (root / "README.md").write_text(readme(manifest), encoding="utf-8", newline="\n")
    (root / ".gitattributes").write_text("* -text\n", encoding="utf-8", newline="\n")
    if windows_smoke is not None:
        (root / "windows_smoke.json").write_bytes(Path(windows_smoke).read_bytes())


def prepare(output: Path, handoff: Path | None = None,
            windows_smoke: Path | None = None) -> dict:
    raw = {name: (ROOT / name).read_bytes() for name in PROBE_SOURCES}
    probe = build_probe(raw)
    manifest = {
        "handoff": HANDOFF_ID,
        "status": "PREPARED_NOT_RUN",
        "supersedes": None,
        "revision_of": "handoffs/lazy-smp-g2-r3",
        "harness_change": (
            "thread launch/join/yield adapters only: pthread instead of C11 thrd_*; "
            "workload, assertions, atomic types and memory orders unchanged"
        ),
        "source_sha256": {name: hashlib.sha256(value).hexdigest()
                          for name, value in raw.items()},
        "probe_sha256": hashlib.sha256(probe.encode()).hexdigest(),
        "scope": "actual publication functions and types; not Windows worker lifecycle",
        "linux_build": LINUX_BUILD,
        "linux_run": LINUX_RUN,
        "negative_control_build": NEGATIVE_BUILD,
        "negative_control_run": NEGATIVE_RUN,
        "smoke_build": SMOKE_BUILD,
        "smoke_run": SMOKE_RUN,
        "gate": GATE,
    }
    output = new_output_directory(Path(output))
    write_tree(output, raw, probe, manifest, windows_smoke)
    if handoff is not None:
        handoff = Path(handoff).resolve()
        expected = (ROOT / "handoffs" / HANDOFF_ID).resolve()
        if handoff != expected:
            raise ValueError(f"--handoff must be exactly {expected}")
        if handoff.exists():
            shutil.rmtree(handoff)
        write_tree(handoff, raw, probe, manifest, windows_smoke)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--handoff", type=Path, default=None)
    parser.add_argument("--windows-smoke", type=Path, default=None,
                        help="windows_smoke.json to copy into the frozen tree")
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.handoff, args.windows_smoke), indent=2))
