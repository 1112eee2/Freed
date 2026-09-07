import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy

from makhos.core import parse_position
from makhos.nnue_features import ordered_accumulator_features
from scratch import nnue_quantized_export as exporter


def tensor(shape, values=None):
    count = int(numpy.prod(shape))
    return {
        "shape": list(shape),
        "values": list(values) if values is not None else [0.0] * count,
    }


def synthetic_model():
    feature = numpy.zeros((137, 128), dtype=numpy.float64)
    feature[0, 0] = 0.25
    feature[1, 0] = -0.125
    feature[2, 1] = 0.375
    feature[136, 2] = 0.0625
    hidden = numpy.zeros((32, 256), dtype=numpy.float64)
    hidden[0, 0] = 0.375
    hidden[0, 128] = -0.25
    hidden[1, 1] = 0.375
    output = numpy.zeros((1, 32), dtype=numpy.float64)
    output[0, 0] = 0.5
    output[0, 1] = -0.25
    return {
        "format": "thai-makhos-float-nnue-model-v1",
        "kind": "float-nnue-checkpoint",
        "feature_spec": copy.deepcopy(exporter.EXPECTED_FEATURE_SPEC),
        "network": copy.deepcopy(exporter.EXPECTED_NETWORK),
        "state": {
            "feature_bias": tensor((128,), [0.01] * 128),
            "feature_weights": tensor((137, 128), feature.reshape(-1)),
            "hidden.bias": tensor((32,), [0.02] * 32),
            "hidden.weight": tensor((32, 256), hidden.reshape(-1)),
            "output.bias": tensor((1,), [0.01]),
            "output.weight": tensor((1, 32), output.reshape(-1)),
        },
    }


def contract(model_sha="A" * 64):
    return {
        "format": exporter.CONTRACT_FORMAT,
        "kind": "first-quantized-nnue-v1",
        "status": "FROZEN",
        "source_model_sha256": model_sha,
        "float_contract_sha256": "B" * 64,
        "exporter_source_sha256": "C" * 64,
        "validation_inventory_sha256": "D" * 64,
        "feature_spec_sha256": exporter.EXPECTED_FEATURE_SPEC_SHA256,
        "ruleset_sha256": exporter.EXPECTED_RULESET_SHA256,
        "dimensions": copy.deepcopy(exporter.EXPECTED_DIMENSIONS),
        "scales": copy.deepcopy(exporter.EXPECTED_SCALES),
        "integer_types": copy.deepcopy(exporter.EXPECTED_INTEGER_TYPES),
        "payload_order": list(exporter.EXPECTED_PAYLOAD_ORDER),
        "nonterminal_cp_bound": 30000,
        "parity_limits": {
            "mae": 0.005,
            "rmse": 0.0075,
            "max_abs": 0.05,
            "sign_mismatch_rate": 0.01,
        },
        "sealed_test_labels_opened": False,
        "playing_code_changed": False,
    }


class QuantizedExportTests(unittest.TestCase):
    def test_feature_adapter_uses_named_oracle_fields(self):
        state = parse_position(
            "B:BM21,22,25,27:BK30:RM5,7,8,10:RK2",
            reversible_plies=3,
            ply=4,
        )
        first, second = exporter.ordered_feature_indices(state)
        oracle = ordered_accumulator_features(state)
        self.assertEqual(first, oracle.side_to_move)
        self.assertEqual(second, oracle.opponent)

    def test_quantized_inference_tracks_float_and_proves_overflow_bounds(self):
        model = synthetic_model()
        frozen = contract()
        quantized = exporter.quantize_model(model, frozen)
        float_value = exporter.float_infer(model, (0, 2, 136), (1, 136))
        integer_value = exporter.quantized_infer(
            quantized,
            (0, 2, 136),
            (1, 136),
        )
        self.assertLess(abs(float_value - integer_value), 0.005)
        bounds = exporter.prove_overflow_bounds(quantized, frozen)
        self.assertTrue(bounds["all_safe"])
        self.assertLessEqual(bounds["feature_accumulator_abs_max"], 32767)
        self.assertLessEqual(bounds["dense_sum_abs_max"], 2147483647)

    def test_binary_export_is_deterministic_and_corruption_fails_closed(self):
        frozen = contract()
        quantized = exporter.quantize_model(synthetic_model(), frozen)
        first = exporter.serialize_quantized_model(quantized, frozen)
        second = exporter.serialize_quantized_model(quantized, frozen)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith(b"MKNNUE1"))
        loaded = exporter.parse_quantized_model(first, frozen)
        self.assertEqual(
            exporter.quantized_infer(loaded, (0, 136), (1, 136)),
            exporter.quantized_infer(quantized, (0, 136), (1, 136)),
        )
        with self.assertRaises(exporter.QuantizedExportError):
            exporter.parse_quantized_model(first[:-1], frozen)
        corrupted = bytearray(first)
        corrupted[-1] ^= 1
        with self.assertRaises(exporter.QuantizedExportError):
            exporter.parse_quantized_model(bytes(corrupted), frozen)

    def test_contract_rejects_test_leakage_and_identity_drift(self):
        frozen = contract()
        frozen["sealed_test_labels_opened"] = True
        with self.assertRaises(exporter.QuantizedExportError):
            exporter.validate_contract(frozen, source_model_sha256="A" * 64)
        frozen = contract()
        with self.assertRaises(exporter.QuantizedExportError):
            exporter.validate_contract(frozen, source_model_sha256="E" * 64)

    def test_cli_imports_from_outside_repo(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-B", str(Path(exporter.__file__).resolve()), "--help"],
                cwd=directory,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--quantization-contract", result.stdout)
        self.assertIn("--binary-output", result.stdout)


if __name__ == "__main__":
    unittest.main()
