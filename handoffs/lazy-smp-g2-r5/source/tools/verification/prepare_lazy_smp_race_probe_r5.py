"""Freeze the reviewed Lazy SMP G2 r5 pthread acceptance bundle.

The production types/functions and pthread controls come from the already frozen r4
snapshot.  Top-level native sources are intentionally not consulted.  r3/r4 and all
of their evidence remain byte-for-byte unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


ROOT = Path(__file__).resolve().parents[2]
R4 = ROOT / "handoffs" / "lazy-smp-g2-r4"
HANDOFF = ROOT / "handoffs" / "lazy-smp-g2-r5"
HARNESS = ROOT / "tests" / "native_lazy_smp_portable_pthread_r5.c"
COLLECTOR = ROOT / "tools" / "verification" / "lazy_smp_r5_collect.py"
GENERATOR = Path(__file__).resolve()
WORKFLOW = ROOT / ".github" / "workflows" / "lazy-smp-tsan-r5.yml"
FROZEN_R4 = {
    "native/makhos_native.c": "source/native/makhos_native.c",
    "native/makhos_types.h": "source/native/makhos_types.h",
    "tests/native_lazy_smp_smoke_pthread.c": "source/tests/native_lazy_smp_smoke_pthread.c",
    "tests/native_lazy_smp_negative_pthread.c": "source/tests/native_lazy_smp_negative_pthread.c",
}
PROCESS_SCHEMA = "thai-makhos-lazy-smp-g2-r5-process-v1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(data: bytes) -> str:
    return data.decode("utf-8").replace("\r\n", "\n")


def extract(source: str, pattern: str) -> str:
    matches = re.findall(pattern, source, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"expected one production declaration, found {len(matches)}")
    return matches[0]


def build_probe(raw: dict[str, bytes]) -> str:
    source = normalize(raw["native/makhos_native.c"])
    types = normalize(raw["native/makhos_types.h"])
    declarations = [
        extract(types, rf"^typedef struct \{{[^{{}}]*\}} {name};")
        for name in ("NativeCompactMove", "SharedMoveHintEntry")
    ]
    declarations += [
        extract(source, rf"^static inline bool {name}\([\s\S]*?^\}}")
        for name in ("shared_move_hint_write", "shared_move_hint_read")
    ]
    prefix = (
        "#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\n"
        "#include <stdatomic.h>\n"
    )
    return prefix + "\n\n".join(declarations) + "\n" + normalize(raw["tests/native_lazy_smp_portable_pthread_r5.c"])


VERIFY_SNAPSHOT = r'''"""Fail closed on r5 frozen-input drift or non-verbatim extraction."""
from pathlib import Path
import hashlib
import json
import re

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

for name, expected in manifest["source_sha256"].items():
    path = root / "source" / name
    if not path.is_file() or digest(path) != expected:
        raise SystemExit(f"source hash mismatch: {name}")
for name, expected in manifest["artifact_sha256"].items():
    path = root / name
    if not path.is_file() or digest(path) != expected:
        raise SystemExit(f"artifact hash mismatch: {name}")
repository = root.parents[1]
for name, expected in manifest["repository_sha256"].items():
    path = repository / name
    if not path.is_file() or digest(path) != expected:
        raise SystemExit(f"repository artifact hash mismatch: {name}")

def extract(source, pattern):
    found = re.findall(pattern, source, flags=re.MULTILINE)
    if len(found) != 1:
        raise SystemExit("ambiguous production extraction")
    return found[0]

types = (root / "source/native/makhos_types.h").read_text(encoding="utf-8")
source = (root / "source/native/makhos_native.c").read_text(encoding="utf-8")
parts = [extract(types, rf"^typedef struct \{{[^{{}}]*\}} {name};")
         for name in ("NativeCompactMove", "SharedMoveHintEntry")]
parts += [extract(source, rf"^static inline bool {name}\([\s\S]*?^\}}")
          for name in ("shared_move_hint_write", "shared_move_hint_read")]
expected = "#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\n#include <stdatomic.h>\n"
expected += "\n\n".join(parts) + "\n"
expected += (root / "source/tests/native_lazy_smp_portable_pthread_r5.c").read_text(encoding="utf-8")
if (root / "probe.c").read_text(encoding="utf-8") != expected:
    raise SystemExit("probe is not the exact production extraction plus frozen r5 body")
if "thrd_" in expected or "<threads.h>" in expected:
    raise SystemExit("r5 probe is not pthread-only")
print("PASS: r5 source hashes, artifact hashes, and exact production extraction")
'''


README = """# Lazy SMP G2 r5 frozen publication-protocol bundle

This bundle implements the reviewed r5 contract. It keeps the r3/r4 bundles and
evidence unchanged and reuses their frozen production `SharedMoveHintEntry`,
`NativeCompactMove`, `shared_move_hint_write`, and `shared_move_hint_read` verbatim.
It does not use top-level Local WIP native sources.

The harness separates three slots: deterministic preflight, bounded 256-publication
SPSC liveness, and 8-writer/4-reader concurrent safety/coverage. Production atomics
are not instrumented or altered. Per-participant counters are owner-only non-atomic
records aggregated after join.

## Verify and run

Always run `python3 verify_snapshot.py` before and after collection.

Windows readiness (GCC C17 pthread; not a TSan substitute):

```
python collect.py <unique-result-id> --lane windows --compiler <gcc-path>
```

Linux TSan acceptance matrix (Clang 18 and GCC 13, five fresh protocol processes
per compiler):

```
python3 collect.py <unique-result-id> --lane linux-tsan
```

The collector records every predeclared process slot. A failed or incomplete process
does not cause replacement/retry and does not remove later slots. A shared input or
runtime blocker produces explicit NOT_RUN entries for every remaining slot. Compile
errors on an otherwise supported toolchain are FAIL; missing compiler/sanitizer
runtime is NOT_RUN. A protocol timeout after launch is FAIL.

Do not commit binaries. Return raw logs, commands, environment, hashes, exit codes,
elapsed times, and result JSON under `results/<unique-result-id>/`. Windows evidence
is readiness only. G2 remains NOT_PASSED until the complete Linux matrix is reviewed.
No result from this bundle authorizes production changes, merge/promotion, or SPRT.
"""


RUN_MATRIX = {
    "windows_plain": {
        "compiler": "GCC C17 pthread",
        "directed_processes": 1,
        "protocol_processes": 5,
        "directed_timeout_seconds": 30,
        "protocol_timeout_seconds": 30,
        "role": "readiness only; not a TSan substitute",
    },
    "linux_tsan": {
        "runner": "ubuntu-24.04",
        "compilers": [
            {"id": "clang18", "display": "Clang 18", "executable": "clang-18"},
            {"id": "gcc13", "display": "GCC 13", "executable": "gcc-13"},
        ],
        "per_compiler": {
            "smoke_processes": 1,
            "negative_control_processes": 1,
            "protocol_processes": 5,
            "smoke_timeout_seconds": 30,
            "negative_timeout_seconds": 30,
            "protocol_timeout_seconds": 120,
        },
        "total_required_clean_protocol_processes": 10,
        "job_timeout_minutes": 30,
    },
}


def read_frozen_inputs() -> tuple[dict[str, bytes], dict]:
    r4_manifest = json.loads((R4 / "manifest.json").read_text(encoding="utf-8"))
    raw: dict[str, bytes] = {}
    for target, source in FROZEN_R4.items():
        data = (R4 / source).read_bytes()
        expected = r4_manifest["source_sha256"][target]
        if sha(data) != expected:
            raise ValueError(f"r4 frozen source drift: {source}")
        raw[target] = data
    raw["tests/native_lazy_smp_portable_pthread_r5.c"] = HARNESS.read_bytes()
    raw["tools/verification/lazy_smp_r5_collect.py"] = COLLECTOR.read_bytes()
    raw["tools/verification/prepare_lazy_smp_race_probe_r5.py"] = GENERATOR.read_bytes()
    return raw, r4_manifest


def write_bundle(destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError(f"refusing to replace existing frozen bundle: {destination}")
    raw, r4_manifest = read_frozen_inputs()
    probe = build_probe(raw)
    collector = normalize(raw["tools/verification/lazy_smp_r5_collect.py"])
    controls = {
        "smoke_pthread.c": raw["tests/native_lazy_smp_smoke_pthread.c"],
        "negative_pthread.c": raw["tests/native_lazy_smp_negative_pthread.c"],
    }
    artifacts: dict[str, bytes] = {
        "probe.c": probe.encode("utf-8"),
        "collect.py": collector.encode("utf-8"),
        "verify_snapshot.py": VERIFY_SNAPSHOT.encode("utf-8"),
        "README.md": README.encode("utf-8"),
        ".gitattributes": b"* -text\n",
        **controls,
    }
    manifest = {
        "format": "thai-makhos-lazy-smp-g2-r5-manifest-v1",
        "handoff": "lazy-smp-g2-r5",
        "status": "FROZEN_AWAITING_ACCEPTANCE",
        "design_commit": "8f575a568fd258aa98c9bf918528f75a2bd7753f",
        "diagnostic_head": "f5a2f3fee1b04c0af10f74f802095ee0ce66f807",
        "frozen_r4_probe_sha256": r4_manifest["probe_sha256"],
        "production_reuse": "verbatim types/functions from frozen r4 snapshot; top-level native source excluded",
        "source_sha256": {name: sha(data) for name, data in sorted(raw.items())},
        "artifact_sha256": {name: sha(data) for name, data in sorted(artifacts.items())},
        "repository_sha256": {
            ".github/workflows/lazy-smp-tsan-r5.yml": sha(WORKFLOW.read_bytes()),
        },
        "probe_sha256": sha(artifacts["probe.c"]),
        "process_json_schema": PROCESS_SCHEMA,
        "process_json_required_fields": ["schema", "mode", "status"],
        "protocol_json_required_fields": ["spsc", "writers", "readers"],
        "exit_mapping": {"0": "PASS", "2": "FAIL", "3": "INCOMPLETE_COVERAGE", "4": "NOT_RUN"},
        "workload": {
            "slots": ["preflight_slot", "liveness_slot", "workload_slot"],
            "spsc_publications": 256,
            "spsc_writer_id_range": [0, 0],
            "spsc_publication_id_range": [1, 256],
            "concurrent_writers": 8,
            "concurrent_readers": 4,
            "concurrent_writer_id_range": [0, 7],
            "concurrent_iteration_range": [1, 100000],
            "attempts_per_participant": 100000,
            "counter_design": "owner-only thread-local non-atomic uint64 records; aggregate only after join",
            "spsc_ready_ordering": "reader initial miss then release-store ready; writer acquire-load before first publication",
            "spsc_ack_ordering": "reader release-store publication id; writer acquire-load before next publication",
        },
        "run_matrix": RUN_MATRIX,
        "classification": {
            "precedence": ["FAIL", "NOT_RUN", "INCOMPLETE_COVERAGE", "PASS"],
            "compile_error_supported_toolchain": "FAIL",
            "missing_compiler_or_runtime": "NOT_RUN",
            "executing_protocol_timeout_or_deadlock": "FAIL",
            "incomplete_coverage_scope": "concurrent stress only",
            "fixed_slot_policy": "continue all remaining slots after FAIL/INCOMPLETE; shared blocker emits NOT_RUN for every remaining slot",
        },
        "scope": "publication protocol only; no production change, promotion, SPRT, or automatic G2 closure",
    }
    destination.mkdir(parents=True)
    for name, data in raw.items():
        path = destination / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name, data in artifacts.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", default=HANDOFF)
    args = parser.parse_args()
    destination = args.output if args.output.is_absolute() else ROOT / args.output
    manifest = write_bundle(destination.resolve())
    print(json.dumps({"path": str(destination.resolve()), "probe_sha256": manifest["probe_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
