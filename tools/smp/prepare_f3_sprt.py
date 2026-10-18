"""Prepare (never start) the Track F3 SPRT: Lazy SMP 12T against root split 12T.

Both sides run the same SEARCH_INT_01 search and NNUE; only the parallel
search differs.  Conditions are W2's: 12 Threads, 512 MiB, fixed 1 s per move,
TB4-6 plus the C4 endgame library.  H1 = +5 because a large gain is expected.

The script freezes a run tree (``git archive`` of a commit plus the verified
DLLs and model) and writes ``launch_f3.py`` into it.  Start that launcher only
when no other gate is running and the GUI is closed.

    python -B tools/smp/prepare_f3_sprt.py --commit HEAD
"""

from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
PROJECT = Path(r"D:\ThaiMakhosEngine")
DLL = "makhos_native_nnue_candidate_v1.dll"
# (source, path inside the tree, expected SHA-256)
ARTIFACTS = (
    (ROOT / "build" / "lazy_smp_01" / "candidate" / DLL,
     Path("build/lazy_smp_01/candidate") / DLL,
     "B397B0841661E30E14FD511A26304ECEB867389B494BE8793FCEBD8724845768"),
    (PROJECT / "build" / "search_int01" / "candidate" / DLL,
     Path("build/search_int01/candidate") / DLL,
     "5ED1FE187A09A060C02E1C433C5C9C6813D01D7B8C21B71A67323546B695EAC9"),
    (PROJECT / "build" / "nnue_quantized_v1" / "model_a.mknnue",
     Path("build/nnue_quantized_v1/model_a.mknnue"),
     None),
)
MANIFESTS = (
    (ROOT / "build" / "lazy_smp_01" / "candidate" / "build_manifest.json",
     Path("build/lazy_smp_01/candidate/build_manifest.json")),
    (PROJECT / "build" / "search_int01" / "candidate" / "build_manifest.json",
     Path("build/search_int01/candidate/build_manifest.json")),
)
MODEL_SHA256 = "07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C"

LAUNCHER = '''"""Launch LAZY_SMP_01 F3 (Track F), detached, BelowNormal, no console.

Lazy SMP 12T (candidate {dev_sha}) against root split 12T (control {master_sha}),
same SEARCH_INT_01 search and NNUE.  W2 conditions: 12 Threads, 512 MiB, fixed
1 s, TB4-6 + C4 endgame, H0=0/H1=+5, cap {pairs} pairs, seed {seed}.
Source commit {commit}.  Re-running resumes (--resume); old logs are renamed.
Run only when no other gate is running and the GUI is closed.
"""

import ctypes
import subprocess
import sys
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

TREE = Path(r"{tree}")
RUN = TREE / "build" / "lazy_smp_01" / "sprt-f3-{seed}"
FLAGS = 0x00000008 | 0x00000200 | 0x00004000  # DETACHED, NEW_PROCESS_GROUP, BELOW_NORMAL
TB = r"{project_build}"


def creation_utc(pid: int) -> str:
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    h = k.OpenProcess(0x1000, False, pid)
    times = [wintypes.FILETIME() for _ in range(4)]
    k.GetProcessTimes(h, *[ctypes.byref(t) for t in times])
    k.CloseHandle(h)
    ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    return datetime.fromtimestamp((ticks - 116444736000000000) / 1e7, timezone.utc).isoformat()


RUN.mkdir(parents=True, exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d%H%M%S")
for name in ("stdout.log", "stderr.log", "launch.txt"):
    old = RUN / name
    if old.exists():
        old.rename(RUN / f"{{name}}.before-{{stamp}}")

args = [
    sys.executable, "-B", "-m", "makhos", "sprt",
    "--dev-library", r"build\\lazy_smp_01\\candidate\\{dll}",
    "--master-library", r"build\\search_int01\\candidate\\{dll}",
    "--dev-nnue-model", r"build\\nnue_quantized_v1\\model_a.mknnue",
    "--master-nnue-model", r"build\\nnue_quantized_v1\\model_a.mknnue",
    "--threads", "12", "--hash-mb", "512", "--fixed-move-time-ms", "1000",
    "--lazy-smp",
    "--elo0", "0", "--elo1", "5", "--pairs", "{pairs}", "--seed", "{seed}",
    "--ranked-tablebase", TB + r"\\tb4_np80.compact.bin",
    "--ranked-tablebase", TB + r"\\tb5_np80.compact.bin",
    "--ranked-tablebase", TB + r"\\tb6_np80.compact.bin",
    "--native-endgame-library", TB + r"\\native_endgame_c4\\makhos_endgame_search_nnue.dll",
    "--output", r"build\\lazy_smp_01\\sprt-f3-{seed}\\sprt.json", "--resume",
]
with (RUN / "stdout.log").open("wb") as out, (RUN / "stderr.log").open("wb") as err:
    proc = subprocess.Popen(args, cwd=TREE, stdout=out, stderr=err,
                            stdin=subprocess.DEVNULL, creationflags=FLAGS)
(RUN / "launch.txt").write_text("\\n".join([
    f"launch_utc={{datetime.now(timezone.utc).isoformat()}}",
    f"pid={{proc.pid}}",
    f"creation={{creation_utc(proc.pid)}}",
    f"cwd={{TREE}}",
    "note=LAZY_SMP_01 F3: Lazy SMP 12T {dev_short} vs root split 12T {master_short}; commit {commit}; detached, no console",
    "command=" + " ".join(args),
]) + "\\n", encoding="utf-8")
print(f"started pid {{proc.pid}}")
'''


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--tree", type=Path, default=PROJECT / "build" / "runs" / "lazysmp_f3")
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--pairs", type=int, default=1000)
    args = parser.parse_args()

    if args.tree.exists():
        raise SystemExit(f"{args.tree} exists; pick a new --tree")
    for source, _, expected in ARTIFACTS:
        actual = sha256(source)
        if actual != (expected or MODEL_SHA256):
            raise SystemExit(f"{source} has SHA-256 {actual}, expected {expected or MODEL_SHA256}")
    commit = subprocess.run(
        ["git", "rev-parse", args.commit], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit], cwd=ROOT, capture_output=True, check=True
    ).stdout

    args.tree.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(args.tree, filter="data")
    for source, target, _ in ARTIFACTS:
        (args.tree / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, args.tree / target)
    for source, target in MANIFESTS:
        shutil.copy2(source, args.tree / target)

    launcher = LAUNCHER.format(
        tree=args.tree,
        project_build=PROJECT / "build",
        dll=DLL,
        seed=args.seed,
        pairs=args.pairs,
        commit=commit,
        dev_sha=ARTIFACTS[0][2][:8].lower(),
        master_sha=ARTIFACTS[1][2][:8].lower(),
        dev_short=ARTIFACTS[0][2][:8].lower(),
        master_short=ARTIFACTS[1][2][:8].lower(),
    )
    (args.tree / "launch_f3.py").write_text(launcher, encoding="utf-8", newline="\n")
    print(f"prepared {args.tree} from {commit}; start with: python -B {args.tree / 'launch_f3.py'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
