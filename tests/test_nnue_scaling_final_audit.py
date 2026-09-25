import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from makhos.core import legal_moves, parse_position
from makhos.eval_corpus import canonical_position_id
from makhos.game_analysis import player_name
from scratch.nnue_quiet_leaf_acquire import (
    EXPECTED_ACCEPTED_SHA256,
    FORMAT as ANALYSIS_FORMAT,
    TEACHER_MAX_DEPTH,
    count_kings,
    count_pieces,
    phase_band,
    selection_binding_sha256,
)
import scratch.nnue_scaling_final_audit as final_audit


TRAIN_POSITION = "B:BM21,22,25,27:BK30:RM5,7,8,10:RK2"
VALIDATION_POSITION = "B:BM20,22,25,27:BK30:RM5,7,8,10:RK2"


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def write_json(path, payload):
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def position(position_text, *, split="train", eligible=True, ply=4):
    state = parse_position(position_text, reversible_plies=3, ply=ply)
    moves = [move.notation for move in legal_moves(state)]
    scores = (5, 10, 12) if eligible else (5, 10, 100)
    searches = [
        {
            "budget_ms": budget,
            "elapsed_ms": float(budget),
            "move": moves[0],
            "score": score,
            "depth": 5,
            "nodes": budget * 10,
            "pv": [moves[0]],
            "native_library_sha256": EXPECTED_ACCEPTED_SHA256,
        }
        for budget, score in zip((100, 500, 2000), scores, strict=True)
    ]
    outcome = "black"
    turn = player_name(state.turn)
    return {
        "canonical_position_id": canonical_position_id(state),
        "eligible": eligible,
        "exact_wdl": None,
        "game_outcome": outcome,
        "game_outcome_from_side_to_move": "win" if outcome == turn else "loss",
        "game_truncated": False,
        "gate_reason": "accepted" if eligible else "last_two_score_delta",
        "history": {
            "entries": 4,
            "current_repetition_count": 1,
            "sha256": "A" * 64,
        },
        "king_count": count_kings(state),
        "last_two_score_delta": abs(scores[-1] - scores[-2]),
        "legal_moves": moves,
        "phase_band": phase_band(count_pieces(state)),
        "piece_count": count_pieces(state),
        "ply": ply,
        "position": position_text,
        "reversible_plies": 3,
        "searches": searches,
        "split": split,
        "teacher_score": scores[-1] if eligible else None,
        "turn": turn,
    }


def game_and_analysis(
    game_id,
    *,
    accepted_library,
    split="train",
    position_text=TRAIN_POSITION,
):
    row = position(position_text, split=split)
    selected = {
        key: row[key]
        for key in (
            "ply",
            "canonical_position_id",
            "phase_band",
            "piece_count",
            "king_count",
        )
    }
    selected["legal_move_count"] = len(row["legal_moves"])
    game = {
        "game_id": game_id,
        "split": split,
        "path": str(Path(f"D:/synthetic/{game_id}.json").resolve()),
        "sha256": "B" * 64,
        "provisional_positions": 1,
        "selected_positions": 1,
        "selected": [selected],
    }
    game["selection_sha256"] = selection_binding_sha256(game)
    payload = {
        "format": ANALYSIS_FORMAT,
        "kind": "game-analysis",
        "game_id": game_id,
        "game_path": game["path"],
        "game_sha256": game["sha256"],
        "split": split,
        "selection_sha256": game["selection_sha256"],
        "accepted_library": str(Path(accepted_library).resolve()),
        "accepted_library_sha256": EXPECTED_ACCEPTED_SHA256,
        "threads": 1,
        "persistent_search": True,
        "clear_once_per_position_before_ascending_budgets": True,
        "hash_mb": 256,
        "budgets_ms": [100, 500, 2000],
        "teacher_max_depth": TEACHER_MAX_DEPTH,
        "rules_profile": "project",
        "positions": [row],
    }
    return game, payload


def requirements(value=1):
    return {
        "total": value,
        "with_kings": value,
        "phase_13_to_16": 0,
        "phase_9_to_12": value,
        "phase_5_to_8": 0,
        "turn_black": value,
        "turn_red": 0,
        "validation_total": value,
        "sealed_test_total": value,
    }


def commitment(*, development_games=None, development_path=None):
    return {
        "format": final_audit.EXPECTED_COORDINATOR_FORMAT,
        "kind": "selection-partition-commitment",
        "development_manifest": str(
            development_path or Path("D:/synthetic/development.json").resolve()
        ),
        "development_manifest_sha256": (
            final_audit.EXPECTED_DEVELOPMENT_MANIFEST_SHA256
        ),
        "development_games": (
            final_audit.EXPECTED_DEVELOPMENT_GAMES
            if development_games is None
            else development_games
        ),
        "sealed_test_manifest": str(
            Path("D:/synthetic/sealed_test_selection_manifest.json").resolve()
        ),
        "sealed_test_manifest_sha256": (
            final_audit.EXPECTED_SEALED_TEST_MANIFEST_SHA256
        ),
        "sealed_test_games": final_audit.EXPECTED_SEALED_TEST_GAMES,
        "sealed_test_selected_positions": (
            final_audit.EXPECTED_SEALED_TEST_SELECTED_POSITIONS
        ),
        "test_analysis_files_may_be_read": False,
        "global_unique_trajectories": 15_335,
        "generated_source_game_files": 15_360,
    }


def coordinator_summary(partition=None, hashes=None):
    partition = partition or commitment()
    hashes = hashes or {
        f"game-{index}.analysis.json": "A" * 64
        for index in range(final_audit.EXPECTED_DEVELOPMENT_GAMES)
    }
    return {
        "format": final_audit.EXPECTED_COORDINATOR_FORMAT,
        "kind": final_audit.EXPECTED_COORDINATOR_KIND,
        "verdict": "PASS",
        "contract": final_audit.EXPECTED_COORDINATOR_CONTRACT,
        "accepted_library_sha256": EXPECTED_ACCEPTED_SHA256,
        "config_sha256": final_audit.EXPECTED_CONFIG_SHA256,
        "acquisition_script_sha256": final_audit.EXPECTED_ACQUISITION_SHA256,
        "coordinator_script_sha256": final_audit.EXPECTED_COORDINATOR_SHA256,
        "selection_partition": partition,
        "gates": {
            key: True for key in final_audit.EXPECTED_COORDINATOR_GATES
        },
        "resume_reproduction": {
            "source_games_byte_identical": True,
            "development_analyses_byte_identical": True,
            "development_manifest_byte_identical": True,
            "sealed_test_manifest_byte_identical": True,
        },
        "outputs": {
            "generated_source_files": 15_360,
            "source_game_hashes": {
                f"game_{index:05d}.json": "D" * 64
                for index in range(15_360)
            },
            "generation_shard_manifest_hashes": {
                f"generation_{index}.json": "E" * 64 for index in range(6)
            },
            "analysis_shard_manifest_hashes": {
                f"analysis_{index}.json": "F" * 64 for index in range(6)
            },
            "analysis_files": final_audit.EXPECTED_DEVELOPMENT_GAMES,
            "development_games": final_audit.EXPECTED_DEVELOPMENT_GAMES,
            "development_manifest_sha256": (
                final_audit.EXPECTED_DEVELOPMENT_MANIFEST_SHA256
            ),
            "sealed_test_games": final_audit.EXPECTED_SEALED_TEST_GAMES,
            "sealed_test_selected_positions": (
                final_audit.EXPECTED_SEALED_TEST_SELECTED_POSITIONS
            ),
            "sealed_test_manifest_sha256": (
                final_audit.EXPECTED_SEALED_TEST_MANIFEST_SHA256
            ),
            "test_analysis_files_read": 0,
            "stderr_bytes": 0,
            "temporary_files": 0,
            "development_analysis_hashes": hashes,
        },
    }


def development_manifest(game, sealed_hash=None):
    split = game["split"]
    selected = game["selected"]
    return {
        "format": ANALYSIS_FORMAT,
        "kind": "development-selection-manifest",
        "split_rule": "sha256(game_id) modulo 10: 0-7 train, 8 validation, 9 test",
        "split_before_sampling": True,
        "position_identity": "color-rotation canonical position plus reversible clock",
        "generated_source_game_files": 15_360,
        "unique_source_game_trajectories": 1,
        "global_deduplication": {
            "duplicate_source_game_files_dropped": 25,
            "cross_split_symmetry_duplicates_dropped": 0,
            "within_split_duplicates_dropped": 0,
        },
        "games_by_split": {split: 1},
        "selected_by_split": {split: len(selected)},
        "selected_phase_bands": {selected[0]["phase_band"]: 1},
        "selected_mixed_king_positions": int(selected[0]["king_count"] > 0),
        "sealed_test_commitment": {
            "manifest_sha256": (
                sealed_hash or final_audit.EXPECTED_SEALED_TEST_MANIFEST_SHA256
            ),
            "games": final_audit.EXPECTED_SEALED_TEST_GAMES,
            "selected_positions": (
                final_audit.EXPECTED_SEALED_TEST_SELECTED_POSITIONS
            ),
            "model_selection_may_read": False,
        },
        "games": [game],
    }


class NnueScalingFinalAuditTests(unittest.TestCase):
    def test_coordinator_contract_uses_locked_cli_budget_serialization(self):
        self.assertEqual(
            final_audit.EXPECTED_COORDINATOR_CONTRACT["budgets_ms"],
            "100,500,2000",
        )

    def test_analysis_set_hash_is_order_independent(self):
        first = [("b", "B" * 64), ("a", "A" * 64)]
        self.assertEqual(
            final_audit.analysis_set_sha256(first),
            final_audit.analysis_set_sha256(list(reversed(first))),
        )

    def test_coverage_counts_and_gates_use_production_contract(self):
        accepted = Path("D:/synthetic/accepted.dll")
        train_game, train_payload = game_and_analysis(
            "train", accepted_library=accepted
        )
        validation_game, validation_payload = game_and_analysis(
            "validation",
            accepted_library=accepted,
            split="validation",
            position_text=VALIDATION_POSITION,
        )
        coverage, gates = final_audit.audit_payloads(
            [
                ("train.analysis.json", train_payload, train_game),
                (
                    "validation.analysis.json",
                    validation_payload,
                    validation_game,
                ),
            ],
            accepted_library=accepted,
            requirements=requirements(),
            sealed_test_selected_positions=(
                final_audit.EXPECTED_SEALED_TEST_SELECTED_POSITIONS
            ),
        )
        self.assertEqual(coverage["train"]["eligible"], 1)
        self.assertEqual(coverage["validation"]["eligible"], 1)
        self.assertTrue(all(gates.values()))

    def test_duplicate_canonical_position_is_rejected(self):
        accepted = Path("D:/synthetic/accepted.dll")
        game_a, payload_a = game_and_analysis("a", accepted_library=accepted)
        game_b, payload_b = game_and_analysis("b", accepted_library=accepted)
        with self.assertRaises(RuntimeError):
            final_audit.audit_payloads(
                [
                    ("a.analysis.json", payload_a, game_a),
                    ("b.analysis.json", payload_b, game_b),
                ],
                accepted_library=accepted,
                requirements=requirements(),
                sealed_test_selected_positions=(
                    final_audit.EXPECTED_SEALED_TEST_SELECTED_POSITIONS
                ),
            )

    def test_recomputed_metadata_and_teacher_contract_reject_fabrication(self):
        accepted = Path("D:/synthetic/accepted.dll")
        game, payload = game_and_analysis("a", accepted_library=accepted)
        payload["hash_mb"] = 4
        with self.assertRaises(RuntimeError):
            final_audit.validate_analysis_contract(
                payload,
                analysis_name="a.analysis.json",
                game=game,
                accepted_library=accepted,
            )
        game, payload = game_and_analysis("a", accepted_library=accepted)
        payload["positions"][0]["king_count"] += 1
        game["selected"][0]["king_count"] += 1
        game["selection_sha256"] = selection_binding_sha256(game)
        payload["selection_sha256"] = game["selection_sha256"]
        with self.assertRaises(RuntimeError):
            final_audit.validate_analysis_contract(
                payload,
                analysis_name="a.analysis.json",
                game=game,
                accepted_library=accepted,
            )

    def test_coordinator_requires_strict_schema_and_zero_test_reads(self):
        summary = coordinator_summary()
        partition = summary["selection_partition"]
        final_audit.validate_final_summary(summary, partition)
        summary["outputs"]["test_analysis_files_read"] = 1
        with self.assertRaises(RuntimeError):
            final_audit.validate_final_summary(summary, partition)
        summary = coordinator_summary()
        partition = summary["selection_partition"]
        gate = next(iter(summary["gates"]))
        summary["gates"][gate] = 1
        with self.assertRaises(RuntimeError):
            final_audit.validate_final_summary(summary, partition)

    def test_build_audit_never_opens_sealed_manifest_or_test_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            work = temp_path / "work"
            analyses = work / "analyses"
            analyses.mkdir(parents=True)
            accepted = Path("D:/ThaiMakhosEngine/build/makhos_native_accepted.dll")
            game, payload = game_and_analysis(
                "game-a", accepted_library=accepted
            )
            analysis_path = analyses / "game-a.analysis.json"
            write_json(analysis_path, payload)
            analysis_sha = file_sha256(analysis_path)

            sealed_path = work / "sealed_test_selection_manifest.json"
            development_path = work / "development_selection_manifest.json"
            dev = development_manifest(game, sealed_hash="C" * 64)
            dev["sealed_test_commitment"].update(
                {"games": 1, "selected_positions": 1}
            )
            write_json(development_path, dev)
            dev_sha = file_sha256(development_path)
            partition = {
                "format": final_audit.EXPECTED_COORDINATOR_FORMAT,
                "kind": "selection-partition-commitment",
                "development_manifest": str(development_path.resolve()),
                "development_manifest_sha256": dev_sha,
                "development_games": 1,
                "sealed_test_manifest": str(sealed_path.resolve()),
                "sealed_test_manifest_sha256": "C" * 64,
                "sealed_test_games": 1,
                "sealed_test_selected_positions": 1,
                "test_analysis_files_may_be_read": False,
                "global_unique_trajectories": 2,
                "generated_source_game_files": 15_360,
            }
            write_json(work / "selection_partition_commitment.json", partition)
            commitment_sha = file_sha256(
                work / "selection_partition_commitment.json"
            )
            config = {"accepted_library": str(accepted.resolve())}
            write_json(work / "config.json", config)
            config_sha = file_sha256(work / "config.json")
            capacity = {
                "verdict": "SCALING_SIZE_READY_FOR_HARNESS_PREFLIGHT",
                "model_trained": False,
                "playing_code_changed": False,
                "test_policy": {"future_test_rows_may_select_model": False},
                "sizing_contract": {
                    "requirements": {
                        **requirements(),
                        "validation_total": 0,
                    }
                },
            }
            capacity_path = temp_path / "capacity.json"
            write_json(capacity_path, capacity)
            capacity_sha = file_sha256(capacity_path)
            # The frozen audit pins the acquisition-era workload_isolation.py
            # and fails closed on the real run once that file changes.  This
            # test covers the audit logic, so it binds the live file like its
            # other synthetic inputs.
            isolation_sha = file_sha256(
                final_audit.ROOT / "makhos" / "workload_isolation.py"
            )
            full_manifest = {
                "format": "thai-makhos-nnue-scaling-full-run-v1",
                "kind": "locked-full-run-manifest",
                "contract": final_audit.EXPECTED_FULL_RUN_CONTRACT,
                "acquisition_script_sha256": (
                    final_audit.EXPECTED_ACQUISITION_SHA256
                ),
                "coordinator_script_sha256": (
                    final_audit.EXPECTED_COORDINATOR_SHA256
                ),
                "supervisor_script_sha256": (
                    final_audit.EXPECTED_SUPERVISOR_SHA256
                ),
                "workload_isolation_sha256": isolation_sha,
                "config_sha256": config_sha,
                "sealed_test_labels_opened": False,
                "model_trained": False,
                "playing_code_changed": False,
                "authorization": {
                    "accepted_library_sha256": EXPECTED_ACCEPTED_SHA256,
                    "capacity_audit_sha256": capacity_sha,
                    "preflight_summary_sha256": (
                        final_audit.EXPECTED_PREFLIGHT_SUMMARY_SHA256
                    ),
                },
            }
            write_json(work / "full_run_manifest.json", full_manifest)
            full_manifest_sha = file_sha256(work / "full_run_manifest.json")
            summary = coordinator_summary(
                partition=partition,
                hashes={analysis_path.name: analysis_sha},
            )
            summary["config_sha256"] = config_sha
            summary["outputs"].update(
                {
                    "analysis_files": 1,
                    "development_games": 1,
                    "development_manifest_sha256": dev_sha,
                    "sealed_test_games": 1,
                    "sealed_test_selected_positions": 1,
                    "sealed_test_manifest_sha256": "C" * 64,
                }
            )
            write_json(work / "preflight_summary.json", summary)

            opened = []
            original_open = Path.open

            def guarded_open(path_self, *args, **kwargs):
                lowered = path_self.name.lower()
                if path_self.resolve() == sealed_path.resolve() or (
                    "test" in lowered and lowered.endswith(".analysis.json")
                ):
                    raise AssertionError(f"sealed/test file opened: {path_self}")
                opened.append(path_self.resolve())
                return original_open(path_self, *args, **kwargs)

            with (
                patch.object(final_audit, "CAPACITY_AUDIT_PATH", capacity_path),
                patch.object(final_audit, "EXPECTED_CONFIG_SHA256", config_sha),
                patch.object(
                    final_audit,
                    "EXPECTED_COMMITMENT_SHA256",
                    commitment_sha,
                ),
                patch.object(
                    final_audit,
                    "EXPECTED_DEVELOPMENT_MANIFEST_SHA256",
                    dev_sha,
                ),
                patch.object(
                    final_audit,
                    "EXPECTED_SEALED_TEST_MANIFEST_SHA256",
                    "C" * 64,
                ),
                patch.object(final_audit, "EXPECTED_DEVELOPMENT_GAMES", 1),
                patch.object(final_audit, "EXPECTED_SEALED_TEST_GAMES", 1),
                patch.object(
                    final_audit,
                    "EXPECTED_SEALED_TEST_SELECTED_POSITIONS",
                    1,
                ),
                patch.object(
                    final_audit,
                    "EXPECTED_CAPACITY_AUDIT_SHA256",
                    capacity_sha,
                ),
                patch.object(
                    final_audit,
                    "EXPECTED_FULL_RUN_MANIFEST_SHA256",
                    full_manifest_sha,
                ),
                patch.object(
                    final_audit,
                    "EXPECTED_WORKLOAD_ISOLATION_SHA256",
                    isolation_sha,
                ),
                patch.object(Path, "open", guarded_open),
            ):
                result = final_audit.build_audit(work)

            self.assertEqual(result["verdict"], "PASS")
            self.assertFalse(result["sealed_test_manifest_read"])
            self.assertNotIn(sealed_path.resolve(), opened)


if __name__ == "__main__":
    unittest.main()
