import json
import math
import random
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path

from makhos.core import apply_move, initial_state, legal_moves, parse_position
from makhos.native import NativeSearch
from makhos.parallel_native import ParallelNativeSearch
from scratch import nnue_quantized_export as exporter


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native" / "makhos_native_nnue.c"
LIBRARY = ROOT / "build" / "makhos_native_nnue_search_test.dll"
PARITY_LIBRARY = ROOT / "build" / "makhos_native_nnue_search_parity_test.dll"
COMPILER = Path(r"C:\Program Files\LLVM\bin\clang.exe")
MODEL = ROOT / "build" / "nnue_quantized_v1" / "model_a.mknnue"
CONTRACT = (
    ROOT / "build" / "nnue_phase1_evidence" / "quantization_contract_v2.json"
)


def normalized_to_cp(value: float) -> int:
    clip = math.tanh(2000.0 / 600.0)
    if value >= clip:
        return 2000
    if value <= -clip:
        return -2000
    centipawns = 600.0 * math.atanh(value)
    return (
        math.floor(centipawns + 0.5)
        if centipawns >= 0.0
        else math.ceil(centipawns - 0.5)
    )


class NativeNnueSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common = [
            str(COMPILER),
            "-O3",
            "-march=x86-64",
            "-std=c17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-unused-function",
            "-shared",
            str(SOURCE),
        ]
        for output, extra in (
            (LIBRARY, []),
            (PARITY_LIBRARY, ["-DMAKHOS_NNUE_PARITY_GUARD=1"]),
        ):
            result = subprocess.run(
                [*common, *extra, "-o", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                raise AssertionError(result.stderr)
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.quantized = exporter.parse_quantized_model(
            MODEL.read_bytes(), cls.contract
        )

    def test_model_is_explicit_and_provenance_is_exact(self):
        with self.assertRaisesRegex(ValueError, "explicit nnue_model"):
            NativeSearch(LIBRARY, hash_power=16, persistent=True)
        with NativeSearch(
            LIBRARY,
            hash_power=16,
            persistent=True,
            nnue_model=MODEL,
        ) as engine:
            self.assertTrue(engine.nnue_enabled)
            self.assertEqual(engine.nnue_feature_abi, "thai-makhos-shared-137-v1")
            self.assertEqual(
                engine.nnue_model_sha256,
                "07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C",
            )
            self.assertEqual(
                engine.nnue_source_model_sha256,
                "5FD87ABD2F9CAAC81045A58AEA420445B90CAC9A70D5FFBDFC5694BA1338CA4E",
            )

    def test_native_evaluation_matches_quantized_python_oracle(self):
        rng = random.Random(20260831)
        states = []
        state = initial_state()
        while len(states) < 256:
            moves = legal_moves(state)
            if not moves:
                state = initial_state()
                continue
            state = apply_move(state, rng.choice(moves))
            if not legal_moves(state):
                state = initial_state()
                continue
            state = replace(state, reversible_plies=rng.randrange(0, 80))
            states.append(state)
        with NativeSearch(
            LIBRARY,
            hash_power=16,
            persistent=True,
            nnue_model=MODEL,
        ) as engine:
            for state in states:
                first, second = exporter.ordered_feature_indices(state)
                expected = normalized_to_cp(
                    exporter.quantized_infer(self.quantized, first, second)
                )
                self.assertEqual(engine.evaluate(state), expected)

    def test_recursive_accumulator_matches_full_refresh(self):
        rng = random.Random(20260832)
        state = initial_state()
        checked = 0
        total_nodes = 0
        with NativeSearch(
            PARITY_LIBRARY,
            hash_power=16,
            persistent=True,
            nnue_model=MODEL,
        ) as engine:
            for _ in range(40):
                moves = legal_moves(state)
                if not moves:
                    state = initial_state()
                    moves = legal_moves(state)
                state = apply_move(state, rng.choice(moves))
                if state.reversible_plies >= 79:
                    state = replace(
                        state, reversible_plies=rng.randrange(0, 79)
                    )
                moves = legal_moves(state)
                if not moves:
                    continue
                result = engine.search(
                    state,
                    depth=6,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                )
                self.assertIn(result.move, moves)
                checked += 1
                total_nodes += result.nodes
            telemetry = engine.nnue_telemetry()
        self.assertGreaterEqual(checked, 32)
        self.assertGreater(total_nodes, 20_000)
        self.assertIsNotNone(telemetry)
        refreshes, updates, evaluations = telemetry
        self.assertEqual(refreshes, 1)
        self.assertGreater(updates, 0)
        self.assertGreater(evaluations, 0)

    def test_terminal_and_no_progress_precede_nnue(self):
        with NativeSearch(
            LIBRARY,
            hash_power=16,
            persistent=True,
            nnue_model=MODEL,
        ) as engine:
            clock_terminal = replace(initial_state(), reversible_plies=80)
            self.assertEqual(engine.evaluate(clock_terminal), 0)
            with self.assertRaisesRegex(RuntimeError, "position is terminal"):
                engine.search(
                    clock_terminal,
                    depth=6,
                    time_ms=None,
                    no_progress_plies=80,
                    repetition_limit=3,
                )
            red_only = parse_position("R:RM25")
            self.assertEqual(engine.evaluate(red_only), 999999)

    def test_parallel_search_loads_the_same_model_for_every_worker(self):
        state = initial_state()
        with ParallelNativeSearch(
            LIBRARY,
            threads=2,
            hash_mb=16,
            nnue_model=MODEL,
        ) as engine:
            result = engine.search(
                state,
                depth=6,
                time_ms=None,
                no_progress_plies=80,
                repetition_limit=3,
            )
            telemetry = tuple(
                worker.nnue_telemetry() for worker in engine._workers
            )
        self.assertIn(result.move, legal_moves(state))
        self.assertEqual(result.depth, 6)
        self.assertTrue(all(item is not None for item in telemetry))
        self.assertTrue(all(item[2] > 0 for item in telemetry))


if __name__ == "__main__":
    unittest.main()
