"""Fail closed on input drift or non-verbatim production extraction."""
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
parts = [extract(types, rf"^typedef struct \{{[^{{}}]*\}} {name};")
         for name in ("NativeCompactMove", "SharedMoveHintEntry")]
parts += [extract(source, rf"^static inline bool {name}\([\s\S]*?^\}}")
          for name in ("shared_move_hint_write", "shared_move_hint_read")]
expected = "#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\n#include <stdatomic.h>\n"
expected += "\n\n".join(parts) + "\n"
expected += (root / "source/tests/native_lazy_smp_portable.c").read_text()
if probe.read_text() != expected:
    raise SystemExit("probe is not the verbatim production extraction")
print("PASS: source hashes, probe hash and exact production extraction")
