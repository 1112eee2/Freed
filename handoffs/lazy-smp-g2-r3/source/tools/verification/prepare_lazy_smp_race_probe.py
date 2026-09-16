"""Export verbatim production publication code for a portable race-detector run.

No replacement implementation and no playing binary changes. This only prepares
an evidence bundle; successful export or ASan execution does not pass the TSan gate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.verification.run_tests import new_output_directory


def extract(source, pattern):
    matches = re.findall(pattern, source, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"expected one production declaration, found {len(matches)}")
    return matches[0]


def prepare(output):
    paths = ("native/makhos_native.c", "native/makhos_types.h",
             "tests/native_lazy_smp_portable.c")
    raw = {name: (ROOT / name).read_bytes() for name in paths}
    source = raw[paths[0]].decode().replace("\r\n", "\n")
    types = raw[paths[1]].decode().replace("\r\n", "\n")
    declarations = [extract(types, rf"^typedef struct \{{[^{{}}]*\}} {name};")
                    for name in ("NativeCompactMove", "SharedMoveHintEntry")]
    declarations += [extract(source, rf"^static inline bool {name}\([\s\S]*?^\}}")
                     for name in ("shared_move_hint_write", "shared_move_hint_read")]
    content = "#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\n#include <stdatomic.h>\n"
    content += "\n\n".join(declarations) + "\n"
    content += raw[paths[2]].decode().replace("\r\n", "\n")
    output = new_output_directory(Path(output))
    (output / "probe.c").write_text(content, encoding="utf-8", newline="\n")
    manifest = {"status": "PREPARED_NOT_RUN", "source_sha256": {
        name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
        "probe_sha256": hashlib.sha256((output / "probe.c").read_bytes()).hexdigest(),
        "scope": "actual publication functions and types; not Windows worker lifecycle",
        "linux_build": "clang -std=c17 -O1 -g -fsanitize=thread -pthread probe.c -o probe",
        "linux_run": "TSAN_OPTIONS=halt_on_error=1 ./probe",
        "gate": "require zero exit, zero detector reports, and protocol PASS; unsupported runtime is NOT_RUN"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output), indent=2))
