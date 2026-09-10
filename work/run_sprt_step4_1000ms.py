"""Step 4 Experiment A (1000ms, 6T vs 12T C4) SPRT Runner."""

from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "build" / "nnue_sprt_6t_vs_12t_c4_v1"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CHECKPOINT_PATH = OUTPUT_DIR / "sprt_6t_vs_12t_1000ms_seed20261108.json"
LOG_PATH = OUTPUT_DIR / "sprt_6t_vs_12t_1000ms_seed20261108.log"

cmd = [
    sys.executable,
    "-u",
    "-B",
    "-m",
    "makhos",
    "sprt",
    "--dev-library",
    "build/nnue_sprt_6t_vs_12t/makhos_native_6t.dll",
    "--master-library",
    "build/nnue_sprt_6t_vs_12t/makhos_native_12t.dll",
    "--dev-nnue-model",
    "build/nnue_quantized_v1/model_a.mknnue",
    "--master-nnue-model",
    "build/nnue_quantized_v1/model_a.mknnue",
    "--dev-threads",
    "6",
    "--master-threads",
    "12",
    "--hash-mb",
    "512",
    "--fixed-move-time-ms",
    "1000",
    "--opening-plies",
    "6",
    "--seed",
    "20261108",
    "--parallel-games",
    "1",
    "--pairs",
    "10000",
    "--native-endgame",
    "--native-endgame-library",
    "build/native_endgame_c4/makhos_endgame_search_nnue.dll",
    "--resume",
    "--output",
    str(CHECKPOINT_PATH),
]

print("Launching Step 4 SPRT: " + " ".join(cmd), flush=True)
print(f"Log destination: {LOG_PATH}", flush=True)

with open(LOG_PATH, "a", encoding="utf-8") as log_file:
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        log_file.write(line)
        log_file.flush()
    proc.wait()
    sys.exit(proc.returncode)
