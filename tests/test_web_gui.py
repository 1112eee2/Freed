"""Static contract tests for settings wired by the browser GUI."""

from pathlib import Path
import re
import unittest


WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class WebGuiContractTests(unittest.TestCase):
    def test_flip_only_changes_board_orientation(self) -> None:
        app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        match = re.search(
            r"function toggleFlipBoard\(\) \{(?P<body>.*?)\n\}",
            app,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("gameState.isFlipped = !gameState.isFlipped", body)
        self.assertNotIn("humanSide", body)
        self.assertNotIn("checkBotTurn", body)

    def test_engine_settings_are_sent_with_time_control_depth(self) -> None:
        app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        page = (WEB_DIR / "index.html").read_text(encoding="utf-8")

        self.assertIn("depth: 64", app)
        self.assertIn("use_full_time: true", app)
        self.assertIn("threads: gameState.engineThreads", app)
        self.assertIn("hash_mb: gameState.engineHashMb", app)
        self.assertIn("rules_profile: gameState.rulesProfile", app)
        self.assertIn('id="select-engine-threads"', page)
        self.assertIn('id="select-engine-hash"', page)
        self.assertIn('<option value="12">12 Threads (root split ทดลอง)</option>', page)
        self.assertIn('ENGINE v2.1', page)
        self.assertIn('id="select-rules-profile"', page)
        self.assertIn('value="external-no-repetition"', page)
        self.assertIn('app.js?v=20260831-1', page)

    def test_engine_settings_persist_across_refreshes(self) -> None:
        app = (WEB_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("SETTINGS_STORAGE_KEY", app)
        self.assertIn("restoreSettings();", app)
        self.assertIn("persistSettings();", app)
        self.assertIn("engineThreads: gameState.engineThreads", app)
        self.assertIn("engineHashMb: gameState.engineHashMb", app)

    def test_game_record_can_be_copied_for_external_analysis(self) -> None:
        app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        page = (WEB_DIR / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="btn-copy-game"', page)
        self.assertIn("format: 'thai-makhos-game-v1'", app)
        self.assertIn("start_position: gameState.startPosition", app)
        self.assertIn("start_reversible_plies: gameState.startReversiblePlies", app)
        self.assertIn("final_position: generatePositionString()", app)
        self.assertIn("game_mode: gameState.gameMode", app)
        self.assertIn("human_side: gameState.humanSide", app)
        self.assertIn("rules_profile: gameState.rulesProfile", app)
        self.assertIn("actor: 'human'", app)
        self.assertIn("actor: 'engine'", app)
        self.assertIn("...(move.engine ? { engine: move.engine } : {})", app)
        self.assertIn("moves: gameState.moveHistory.map", app)
        self.assertIn("provenance_version: 'search-v1'", app)
        self.assertIn("requested_time_ms: data.requested_time_ms", app)
        self.assertIn("elapsed_ms: data.elapsed_ms", app)
        self.assertIn("request_elapsed_ms: data.request_elapsed_ms", app)
        self.assertIn("pre_search_setup_ms: data.pre_search_setup_ms", app)
        self.assertIn("common_depth: data.common_depth", app)
        self.assertIn("nodes: data.nodes", app)
        self.assertIn("search_backend: data.search_backend", app)
        self.assertIn("native_library_sha256: data.native_library_sha256", app)
        self.assertIn("native_search_abi: data.native_search_abi", app)
        self.assertIn("runtime_isolation: data.runtime_isolation", app)
        self.assertIn("native_tablebase_error: data.native_tablebase_error", app)
        self.assertIn("navigator.clipboard.writeText(record)", app)


if __name__ == "__main__":
    unittest.main()
