import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from makhos.cli import build_parser
from makhos.cli_handlers import analysis_handler
from makhos.core import BLACK, RED, format_position, legal_moves
from makhos.game_analysis import (
    GameRecordError,
    EXTERNAL_NO_REPETITION_RULES,
    SearchObservation,
    classify_search_observations,
    engine_provenance_issues,
    engine_provenance_mismatches,
    inferred_engine_players,
    parse_game_record,
    replay_game,
)


def sample_record() -> dict:
    return {
        "format": "thai-makhos-game-v1",
        "start_position": "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8",
        "start_reversible_plies": 0,
        "final_position": "B:BM17,26,27,28,29,30,31,32:RM2,3,4,5,6,7,8,9",
        "reversible_plies": 4,
        "moves": [
            {
                "ply": 1,
                "player": "black",
                "notation": "25-21",
                "actor": "engine",
                "engine": {
                    "think_time_seconds": 2,
                    "threads": 4,
                    "hash_mb": 64,
                    "mode": "win",
                },
            },
            {"ply": 2, "player": "red", "notation": "5-9", "actor": "human"},
            {
                "ply": 3,
                "player": "black",
                "notation": "21-17",
                "actor": "engine",
                "engine": {
                    "think_time_seconds": 2,
                    "threads": 4,
                    "hash_mb": 64,
                    "mode": "win",
                },
            },
            {"ply": 4, "player": "red", "notation": "1-5", "actor": "human"},
        ],
        "engine": {
            "think_time_seconds": 2,
            "threads": 4,
            "hash_mb": 64,
            "mode": "win",
            "game_mode": "human",
            "human_side": "red",
        },
    }


class GameAnalysisTests(unittest.TestCase):
    @staticmethod
    def complete_search_provenance() -> dict:
        return {
            "provenance_version": "search-v1",
            "think_time_seconds": 2,
            "requested_time_ms": 2000,
            "elapsed_ms": 2001,
            "depth_limit": 64,
            "depth": 22,
            "common_depth": 22,
            "selective_root": False,
            "nodes": 123456,
            "score": -12,
            "pv": ["28-24", "9-14"],
            "wdl": "UNKNOWN",
            "tablebase_hits": 0,
            "threads": 12,
            "hash_mb": 512,
            "hash_allocated_mb": 480.0,
            "mode": "best",
            "rules_profile": "project",
            "search_backend": "native-root-split",
            "native_library": r"D:\ThaiMakhosEngine\build\makhos_native_accepted.dll",
            "native_library_sha256": "a" * 64,
            "native_search_abi": 5,
            "nnue_enabled": True,
            "nnue_feature_abi": "thai-makhos-shared-137-v1",
            "nnue_model_sha256": "c" * 64,
            "native_error": None,
        }

    def test_record_replays_every_verified_edge(self) -> None:
        record = parse_game_record(sample_record())
        replayed = replay_game(record)
        self.assertEqual(len(replayed.plies), 4)
        self.assertEqual(format_position(replayed.final), sample_record()["final_position"])
        self.assertEqual(replayed.final.reversible_plies, 4)
        self.assertEqual(inferred_engine_players(record), (BLACK,))
        self.assertEqual(replayed.plies[0].actor, "engine")
        self.assertEqual(replayed.plies[0].engine["threads"], 4)
        self.assertEqual(replayed.plies[0].history[replayed.plies[0].state.position_key], 1)

    def test_game_id_is_content_stable(self) -> None:
        left = parse_game_record(sample_record())
        right_payload = sample_record()
        right_payload["engine"]["threads"] = 12
        right = parse_game_record(right_payload)
        self.assertEqual(left.game_id, right.game_id)

    def test_complete_per_move_search_provenance_is_reproducible(self) -> None:
        metadata = self.complete_search_provenance()
        self.assertEqual(engine_provenance_issues(metadata), ())
        self.assertEqual(
            engine_provenance_mismatches(
                metadata,
                library_sha256="a" * 64,
                native_search_abi=5,
                threads=12,
                hash_mb=512,
                rules_profile="project",
                budget_ms=2000,
                nnue_enabled=True,
                nnue_feature_abi="thai-makhos-shared-137-v1",
                nnue_model_sha256="c" * 64,
            ),
            (),
        )

        payload = sample_record()
        payload["moves"][0]["engine"] = metadata
        record = parse_game_record(payload)
        self.assertEqual(
            record.moves[0].engine["native_library_sha256"],
            "a" * 64,
        )

    def test_provenance_mismatch_identifies_wrong_replay_configuration(self) -> None:
        metadata = self.complete_search_provenance()
        mismatches = engine_provenance_mismatches(
            metadata,
            library_sha256="b" * 64,
            native_search_abi=6,
            threads=1,
            hash_mb=128,
            rules_profile="external-no-repetition",
            budget_ms=1000,
            nnue_enabled=False,
            nnue_feature_abi="wrong-feature-abi",
            nnue_model_sha256="b" * 64,
        )
        self.assertEqual(
            mismatches,
            (
                "native_library_sha256",
                "native_search_abi",
                "nnue_enabled",
                "nnue_feature_abi",
                "nnue_model_sha256",
                "threads",
                "hash_mb",
                "rules_profile",
                "requested_time_ms",
                "search_backend",
            ),
        )

    def test_legacy_engine_metadata_reports_missing_provenance(self) -> None:
        metadata = sample_record()["moves"][0]["engine"]
        issues = engine_provenance_issues(metadata)
        self.assertIn("missing:provenance_version", issues)
        self.assertIn("missing:native_library_sha256", issues)
        self.assertIn("missing:nnue_model_sha256", issues)
        self.assertIn("missing:elapsed_ms", issues)

    def test_nnue_enabled_metadata_requires_model_and_feature_identities(self) -> None:
        metadata = self.complete_search_provenance()
        metadata["nnue_model_sha256"] = None
        metadata["nnue_feature_abi"] = None
        issues = engine_provenance_issues(metadata)
        self.assertIn("missing:nnue_model_sha256", issues)
        self.assertIn("missing:nnue_feature_abi", issues)

    def test_illegal_or_inconsistent_record_is_rejected(self) -> None:
        bad_move = sample_record()
        bad_move["moves"][0]["notation"] = "25-20"
        with self.assertRaisesRegex(GameRecordError, "unique legal move"):
            replay_game(parse_game_record(bad_move))

        bad_player = sample_record()
        bad_player["moves"][1]["player"] = "black"
        with self.assertRaisesRegex(GameRecordError, "red is to move"):
            replay_game(parse_game_record(bad_player))

        bad_final = sample_record()
        bad_final["final_position"] = bad_final["start_position"]
        with self.assertRaisesRegex(GameRecordError, "final_position"):
            replay_game(parse_game_record(bad_final))

        bad_clock = sample_record()
        bad_clock["reversible_plies"] = 3
        with self.assertRaisesRegex(GameRecordError, "reversible_plies"):
            replay_game(parse_game_record(bad_clock))

        bad_actor = sample_record()
        bad_actor["moves"][1]["engine"] = {"threads": 4}
        with self.assertRaisesRegex(GameRecordError, "requires actor 'engine'"):
            parse_game_record(bad_actor)

    def test_search_divergence_classification(self) -> None:
        def observation(budget: int, move: str) -> SearchObservation:
            return SearchObservation(budget, move, 0, 1, 1, budget, (move,))

        self.assertEqual(
            classify_search_observations(
                "25-21",
                [observation(2000, "25-21"), observation(5000, "25-21")],
            ),
            "stable",
        )
        self.assertEqual(
            classify_search_observations(
                "25-21",
                [
                    observation(2000, "25-21"),
                    observation(5000, "26-22"),
                    observation(20000, "26-22"),
                ],
            ),
            "short-search-divergence",
        )
        self.assertEqual(
            classify_search_observations(
                "25-21",
                [
                    observation(2000, "25-21"),
                    observation(5000, "25-21"),
                    observation(20000, "26-22"),
                ],
            ),
            "long-horizon-divergence",
        )

    def test_search_observation_root_moves_default_empty(self) -> None:
        observation = SearchObservation(1000, "25-21", 0, 1, 1, 1000, ("25-21",))
        self.assertEqual(observation.root_moves, ())
        self.assertIsNone(observation.common_depth)
        self.assertFalse(observation.selective_root)

    def test_cli_budget_defaults_can_be_overridden(self) -> None:
        parser = build_parser()
        defaults = parser.parse_args(["analyze-game", "--game", "game.json"])
        self.assertIsNone(defaults.budget_ms)
        self.assertIsNone(defaults.nnue_model)
        custom = parser.parse_args(
            [
                "analyze-game",
                "--game",
                "game.json",
                "--nnue-model",
                "model.mknnue",
                "--budget-ms",
                "10",
                "--budget-ms",
                "20",
            ]
        )
        self.assertEqual(custom.budget_ms, [10, 20])
        self.assertEqual(custom.nnue_model, "model.mknnue")

    def test_analyze_game_binds_explicit_nnue_model_for_both_search_backends(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game_path = root / "game.json"
            library_path = root / "candidate.dll"
            model_path = root / "model.mknnue"
            game_path.write_text(json.dumps(sample_record()), encoding="utf-8")
            library_path.write_bytes(b"test library identity")
            model_path.write_bytes(b"test model identity")

            start = parse_game_record(sample_record()).start
            selected_move = next(
                move for move in legal_moves(start) if move.notation == "25-21"
            )
            model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()

            class SearcherStub:
                def __init__(self) -> None:
                    self._open = True
                    self.abi_version = 5

                def _require_open(self):
                    if not self._open:
                        raise RuntimeError("searcher closed")

                @property
                def nnue_enabled(self):
                    self._require_open()
                    return True

                @property
                def nnue_model_path(self):
                    self._require_open()
                    return model_path.resolve()

                @property
                def nnue_model_sha256(self):
                    self._require_open()
                    return model_sha256

                @property
                def nnue_feature_abi(self):
                    self._require_open()
                    return "thai-makhos-shared-137-v1"

                @property
                def nnue_source_model_sha256(self):
                    self._require_open()
                    return "d" * 64

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    self._open = False
                    return False

                def clear(self):
                    pass

                def search(self, *_args, **_kwargs):
                    return SimpleNamespace(
                        move=selected_move,
                        score=0,
                        depth=1,
                        nodes=1,
                        elapsed_ms=10,
                        pv=(selected_move,),
                        root_moves=(),
                        common_depth=1,
                        selective_root=False,
                    )

            for threads in (1, 2):
                with self.subTest(threads=threads):
                    searcher = SearcherStub()
                    output_path = root / f"analysis-{threads}t.json"
                    args = build_parser().parse_args(
                        [
                            "analyze-game",
                            "--game",
                            str(game_path),
                            "--library",
                            str(library_path),
                            "--nnue-model",
                            str(model_path),
                            "--side",
                            "engine",
                            "--ply",
                            "1",
                            "--budget-ms",
                            "10",
                            "--budget-ms",
                            "20",
                            "--threads",
                            str(threads),
                            "--output",
                            str(output_path),
                        ]
                    )
                    with (
                        patch.object(
                            analysis_handler,
                            "native_tt_entry_bytes",
                            return_value=32,
                        ),
                        patch.object(
                            analysis_handler,
                            "NativeSearch",
                            return_value=searcher,
                        ) as one_thread,
                        patch.object(
                            analysis_handler,
                            "ParallelNativeSearch",
                            return_value=searcher,
                        ) as root_split,
                        contextlib.redirect_stdout(io.StringIO()),
                    ):
                        self.assertEqual(
                            analysis_handler.command_analyze_game(args), 0
                        )

                    constructor = one_thread if threads == 1 else root_split
                    self.assertEqual(
                        Path(constructor.call_args.kwargs["nnue_model"]).resolve(),
                        model_path.resolve(),
                    )
                    report = json.loads(output_path.read_text(encoding="utf-8"))
                    self.assertTrue(report["nnue_enabled"])
                    self.assertEqual(report["nnue_model_sha256"], model_sha256)
                    self.assertEqual(
                        report["nnue_feature_abi"], "thai-makhos-shared-137-v1"
                    )

    def test_per_move_actor_can_identify_engine_after_side_change(self) -> None:
        payload = sample_record()
        payload["engine"]["human_side"] = "black"
        payload["moves"][0]["actor"] = "human"
        payload["moves"][0].pop("engine")
        payload["moves"][1]["actor"] = "engine"
        payload["moves"][1]["engine"] = {
            "think_time_seconds": 2,
            "threads": 2,
            "hash_mb": 64,
            "mode": "win",
        }
        record = parse_game_record(payload)
        replayed = replay_game(record)
        engine_plies = [item.ply for item in replayed.plies if item.actor == "engine"]
        self.assertEqual(engine_plies, [2, 3])
        self.assertEqual(replayed.plies[1].player, RED)

    def test_external_profile_can_replay_past_project_threefold(self) -> None:
        payload = sample_record()
        payload["start_position"] = "B:BM5:BK8:RK1,6"
        payload["final_position"] = "B:BM5:BK8:RK1,6"
        payload["reversible_plies"] = 4
        payload["moves"] = [
            {"ply": 1, "player": "black", "notation": "8-4"},
            {"ply": 2, "player": "red", "notation": "6-2"},
            {"ply": 3, "player": "black", "notation": "4-8"},
            {"ply": 4, "player": "red", "notation": "2-6"},
        ]
        record = parse_game_record(payload)
        replayed = replay_game(record, rules=EXTERNAL_NO_REPETITION_RULES)
        self.assertEqual(format_position(replayed.final), payload["final_position"])


if __name__ == "__main__":
    unittest.main()
