"""RFP_01 measurement-only census: can the static evaluation stand in for a
shallow null-window search?

Builds, from the current source with the production NNUE search flags, the
control and a census library (``MAKHOS_RFP_CENSUS=1``). The census library
searches exactly like the control. At every null-window node of depth 1..4 it
records which reverse-futility guard rejected the node. For guarded nodes it
also records ``static evaluation - beta`` against the node's real outcome
(fail high or fail low).

For a margin ``M``, reverse futility at depth ``d`` would return beta exactly
when ``eval - beta >= M * d``. The histograms therefore give, for every margin
at once, how many guarded nodes it would prune and how many of those the real
search failed low on.

Positions are a seeded selection from the *train* split of
``corpora/nnue_quiet_leaf_pilot_v4.jsonl``, never validation or test rows.
Each search uses a fresh context. The census and control results must match in
move, score, nodes and PV. Results go to a new directory; nothing is
overwritten.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from makhos.core import DEFAULT_RULES, parse_position  # noqa: E402
from makhos.native import NativeSearch  # noqa: E402

CORPUS = ROOT / "corpora" / "nnue_quiet_leaf_pilot_v4.jsonl"
MODEL = ROOT / "build" / "nnue_quantized_v1" / "model_a.mknnue"
SOURCES = (
    "native/makhos_native.c",
    "native/makhos_native_nnue.c",
    "native/makhos_nnue_avx2_update.c",
)
WINDOWS_CLANG = Path(r"C:\Program Files\LLVM\bin\clang.exe")
PRODUCTION_FLAGS = [
    "-O3", "-march=x86-64", "-std=c17", "-Wall", "-Wextra", "-Werror",
    "-Wno-unused-function", "-shared",
]
CENSUS_DEFINE = "-DMAKHOS_RFP_CENSUS=1"
DEPTHS = 4
REASONS = (
    "eligible", "mate_window", "capture", "pieces", "repetition",
    "no_progress", "threat_capture", "threat_promotion",
)
BINS = 128
BIN_WIDTH = 8
MARGINS = (0, 48, 64, 80, 96, 112, 128, 160, 192, 224, 240)
GROUPS = {
    # Middlegame positions inside the candidate's piece guard.
    "pieces_11_to_14": lambda row: 11 <= row["piece_count"] <= 14,
    # Opening and early middlegame positions.
    "pieces_15_plus": lambda row: row["piece_count"] >= 15,
}


class RfpCensus(ctypes.Structure):
    _fields_ = [
        ("rejected", (ctypes.c_uint64 * len(REASONS)) * DEPTHS),
        ("below_beta", (ctypes.c_uint64 * 2) * DEPTHS),
        ("fail_low", (ctypes.c_uint64 * BINS) * DEPTHS),
        ("fail_high", (ctypes.c_uint64 * BINS) * DEPTHS),
    ]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lower_priority() -> None:
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.nice(10)


def select_positions(count: int, seed: int) -> dict[str, list[dict]]:
    with CORPUS.open(encoding="utf-8") as stream:
        stream.readline()  # metadata header
        train = [
            row for row in map(json.loads, stream) if row["split"] == "train"
        ]
    train.sort(key=lambda row: row["sample_id"])
    rng = random.Random(seed)
    return {
        name: rng.sample([row for row in train if keep(row)], count)
        for name, keep in GROUPS.items()
    }


def compile_library(
    compiler: str, output: Path, defines: list[str]
) -> dict:
    platform_flags = (
        ["-Wl,/Brepro"] if os.name == "nt" else ["-fPIC", "-D_POSIX_C_SOURCE=200809L"]
    )
    command = [
        compiler, *PRODUCTION_FLAGS, *platform_flags, *defines,
        "-I", str(ROOT / "native"), str(ROOT / "native" / "makhos_native_nnue.c"),
        "-o", str(output),
    ]
    if os.name != "nt":
        command += ["-lm", "-lpthread"]
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError(f"build failed for {output.name}:\n{process.stderr}")
    return {"path": str(output), "sha256": sha256(output), "command": command}


def fresh_search(
    library: str, state, *, depth: int, hash_power: int, census: bool
) -> tuple[dict, dict | None]:
    """Search once in a new context; return the outcome and census counts."""
    with NativeSearch(
        library, hash_power=hash_power, persistent=True, nnue_model=MODEL
    ) as engine:
        result = engine.search(
            state,
            depth=depth,
            time_ms=None,
            no_progress_plies=DEFAULT_RULES.no_progress_plies,
            repetition_limit=DEFAULT_RULES.repetition_limit,
            history={state.position_key: 1},
        )
        counts = None
        if census:
            values = RfpCensus()
            read = engine._library.makhos_search_rfp_census
            read.argtypes = [ctypes.c_void_p, ctypes.POINTER(RfpCensus)]
            read.restype = ctypes.c_int
            if read(engine._handle, ctypes.byref(values)) != 0:
                raise RuntimeError("census read failed")
            counts = {
                "rejected": [
                    dict(zip(REASONS, map(int, values.rejected[d])))
                    for d in range(DEPTHS)
                ],
                "below_beta": [
                    {"fail_low": int(values.below_beta[d][0]),
                     "fail_high": int(values.below_beta[d][1])}
                    for d in range(DEPTHS)
                ],
                "fail_low": [list(map(int, values.fail_low[d])) for d in range(DEPTHS)],
                "fail_high": [list(map(int, values.fail_high[d])) for d in range(DEPTHS)],
            }
    if result.depth != depth:
        raise RuntimeError(f"completed depth {result.depth}, expected {depth}")
    outcome = {
        "move": result.move.notation,
        "score": result.score,
        "nodes": result.nodes,
        "pv": [move.notation for move in result.pv],
    }
    return outcome, counts


def empty_totals() -> dict:
    return {
        "rejected": [dict.fromkeys(REASONS, 0) for _ in range(DEPTHS)],
        "below_beta": [{"fail_low": 0, "fail_high": 0} for _ in range(DEPTHS)],
        "fail_low": [[0] * BINS for _ in range(DEPTHS)],
        "fail_high": [[0] * BINS for _ in range(DEPTHS)],
    }


def accumulate(totals: dict, counts: dict) -> None:
    for d in range(DEPTHS):
        for reason in REASONS:
            totals["rejected"][d][reason] += counts["rejected"][d][reason]
        for key in ("fail_low", "fail_high"):
            totals["below_beta"][d][key] += counts["below_beta"][d][key]
        for b in range(BINS):
            totals["fail_low"][d][b] += counts["fail_low"][d][b]
            totals["fail_high"][d][b] += counts["fail_high"][d][b]


def margin_table(totals: dict) -> list[dict]:
    """Prune and false-prune counts for each depth and margin."""
    table = []
    for d in range(DEPTHS):
        depth = d + 1
        eligible = totals["rejected"][d]["eligible"]
        shallow = sum(totals["rejected"][d].values())
        for margin in MARGINS:
            threshold = margin * depth
            if threshold % BIN_WIDTH or threshold // BIN_WIDTH >= BINS:
                continue
            first = threshold // BIN_WIDTH
            pruned_low = sum(totals["fail_low"][d][first:])
            pruned_high = sum(totals["fail_high"][d][first:])
            pruned = pruned_low + pruned_high
            table.append({
                "depth": depth,
                "margin": margin,
                "null_window_nodes": shallow,
                "eligible": eligible,
                "pruned": pruned,
                "pruned_share_of_eligible": round(pruned / eligible, 4) if eligible else None,
                "false_prunes": pruned_low,
                "false_prune_rate": round(pruned_low / pruned, 5) if pruned else None,
            })
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=20)
    parser.add_argument("--hash-power", type=int, default=20)
    parser.add_argument("--count", type=int, default=64, help="positions per group")
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--compiler", default=None)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise SystemExit(f"output directory already exists: {args.output_dir}")
    compiler = args.compiler or (
        str(WINDOWS_CLANG) if WINDOWS_CLANG.is_file() else shutil.which("clang")
    )
    if compiler is None:
        raise SystemExit("clang is required")
    lower_priority()
    args.output_dir.mkdir(parents=True)
    lib_dir = args.output_dir / "lib"
    lib_dir.mkdir()
    suffix = ".dll" if os.name == "nt" else ".so"
    libraries = {
        "control": compile_library(compiler, lib_dir / f"control{suffix}", []),
        "census": compile_library(
            compiler, lib_dir / f"rfp_census{suffix}", [CENSUS_DEFINE]
        ),
    }
    selection = select_positions(args.count, args.seed)
    started = time.time()
    groups = {}
    for name, rows in selection.items():
        totals = empty_totals()
        mismatches = []
        for index, row in enumerate(rows):
            state = parse_position(
                row["position"], reversible_plies=row["reversible_plies"]
            )
            search = dict(depth=args.depth, hash_power=args.hash_power)
            control, _ = fresh_search(
                libraries["control"]["path"], state, census=False, **search
            )
            census, counts = fresh_search(
                libraries["census"]["path"], state, census=True, **search
            )
            if census != control:
                mismatches.append(row["sample_id"])
            accumulate(totals, counts)
            print(f"{name} {index + 1}/{len(rows)} {row['sample_id']}", flush=True)
        groups[name] = {
            "positions": [row["sample_id"] for row in rows],
            "census_control_mismatches": mismatches,
            "totals": totals,
            "margin_table": margin_table(totals),
        }
    combined = empty_totals()
    for group in groups.values():
        accumulate(combined, group["totals"])
    report = {
        "format": "thai-makhos-rfp-census-v1",
        "hypothesis": "RFP_01",
        "config": {
            "depth": args.depth,
            "hash_power": args.hash_power,
            "count_per_group": args.count,
            "seed": args.seed,
            "bin_width": BIN_WIDTH,
            "bins": BINS,
            "reasons": list(REASONS),
            "rules": {
                "repetition_limit": DEFAULT_RULES.repetition_limit,
                "no_progress_plies": DEFAULT_RULES.no_progress_plies,
            },
            "history": "fresh single-entry history per search",
            "corpus_split": "train",
        },
        "identity": {
            "sources": {path: sha256(ROOT / path) for path in SOURCES},
            "corpus_sha256": sha256(CORPUS),
            "model_sha256": sha256(MODEL),
            "compiler": compiler,
            "compiler_version": subprocess.run(
                [compiler, "--version"], capture_output=True, text=True
            ).stdout.splitlines()[0],
            "platform": platform.platform(),
            "python": platform.python_version(),
            "libraries": libraries,
        },
        "elapsed_s": round(time.time() - started, 1),
        "groups": groups,
        "combined_margin_table": margin_table(combined),
    }
    with (args.output_dir / "census.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=1, sort_keys=True)
        stream.write("\n")
    for row in report["combined_margin_table"]:
        print(json.dumps(row, sort_keys=True))
    for name, group in groups.items():
        print(name, "mismatches", len(group["census_control_mismatches"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
