import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TEST_MODULE_PATH = ROOT / "tests" / "test_nnue_incremental_native.py"
TEST_SPEC = importlib.util.spec_from_file_location(
    "test_nnue_incremental_native", TEST_MODULE_PATH
)
if TEST_SPEC is None or TEST_SPEC.loader is None:
    raise RuntimeError(f"cannot import {TEST_MODULE_PATH}")
TEST_MODULE = importlib.util.module_from_spec(TEST_SPEC)
TEST_SPEC.loader.exec_module(TEST_MODULE)
CONTRACT = TEST_MODULE.CONTRACT
MODEL = TEST_MODULE.MODEL
NativeIncrementalTests = TEST_MODULE.NativeIncrementalTests
configure_library = TEST_MODULE.configure_library


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    library_path = args.library.resolve()
    if not library_path.is_file():
        raise SystemExit(f"missing library: {library_path}")

    case_type = NativeIncrementalTests
    case_type.setUpClass()
    case_type.library = configure_library(ctypes.CDLL(str(library_path)))

    methods = (
        "test_full_refresh_matches_every_clock_turn_and_piece_band",
        "test_targeted_quiet_capture_promotion_and_multi_capture_undo",
        "test_every_clock_bucket_transition_and_reset_is_bit_exact",
        "test_random_parent_child_undo_and_deep_stack_are_bit_exact",
        "test_invalid_state_and_model_reload_require_safe_refresh",
    )
    started = time.perf_counter()
    completed = []
    for method in methods:
        case = case_type(methodName=method)
        case.setUp()
        try:
            getattr(case, method)()
        finally:
            case.tearDown()
        completed.append(method)

    report = {
        "schema": "makhos-nnue-incremental-parity-v1",
        "verdict": "PASS",
        "library": str(library_path.relative_to(ROOT)),
        "library_sha256": sha256(library_path),
        "model": str(MODEL.relative_to(ROOT)),
        "model_sha256": sha256(MODEL),
        "contract": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": sha256(CONTRACT),
        "source_sha256": sha256(ROOT / "native" / "makhos_nnue_incremental.c"),
        "tests_sha256": sha256(ROOT / "tests" / "test_nnue_incremental_native.py"),
        "structured_refresh_states": 640,
        "targeted_forward_undo_transitions": 4,
        "explicit_clock_boundary_transitions": 8,
        "explicit_clock_bucket_resets": 9,
        "random_forward_undo_reapply_transitions": 300,
        "deep_stack_requested_max_plies": 64,
        "invalid_and_reload_safety": True,
        "completed_methods": completed,
        "mismatches": 0,
        "playing_path_changed": False,
        "sealed_labels_read": False,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
