"""Fail closed on r5 frozen-input drift or non-verbatim extraction."""
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
