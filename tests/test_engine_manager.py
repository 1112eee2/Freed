"""Unit tests for makhos.engine_manager and server-manager delegation."""

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import makhos.engine_manager as em
import makhos.server as server


class EngineManagerTests(unittest.TestCase):

    def tearDown(self) -> None:
        em.close_global_engine()

    def test_engine_manager_exposes_canonical_constants(self) -> None:
        self.assertEqual(em.DEFAULT_ENGINE_THREADS, 1)
        self.assertEqual(em.DEFAULT_ENGINE_HASH_MB, 64)
        self.assertEqual(em.GUI_SEARCH_DEPTH, 64)
        self.assertIn("project", em.RULE_PROFILES)
        self.assertIn("external-no-repetition", em.RULE_PROFILES)

    def test_server_facade_delegates_attributes_to_engine_manager(self) -> None:
        self.assertIs(server.TB3_SERVICE, em.TB3_SERVICE)
        self.assertIs(server.ENGINE_SEARCH_LOCK, em.ENGINE_SEARCH_LOCK)
        self.assertEqual(server.DEFAULT_ENGINE_THREADS, em.DEFAULT_ENGINE_THREADS)
        self.assertEqual(server.DEFAULT_ENGINE_HASH_MB, em.DEFAULT_ENGINE_HASH_MB)

    def test_reconfiguration_preserves_engine_identity(self) -> None:
        em.close_global_engine()
        engine_1 = em.get_default_engine(threads=1, hash_mb=16)
        with patch("makhos.engine_manager._create_native_search") as mock_create:
            mock_search = Mock()
            mock_search.abi_version = 5
            mock_search.allocated_hash_mb = 32
            mock_create.return_value = mock_search
            engine_2 = em.get_default_engine(threads=2, hash_mb=32)

        self.assertIs(engine_1, engine_2)
        self.assertIs(em.GLOBAL_ENGINE, engine_1)
        self.assertIs(server.GLOBAL_ENGINE, engine_1)

    def test_closing_engine_cleans_resources_and_resets_state(self) -> None:
        em.get_default_engine(threads=1, hash_mb=16)
        self.assertIsNotNone(em.GLOBAL_ENGINE)
        self.assertIsNotNone(server.GLOBAL_ENGINE)
        em.close_global_engine()
        self.assertIsNone(em.GLOBAL_ENGINE)
        self.assertIsNone(server.GLOBAL_ENGINE)
        self.assertIsNone(em.GLOBAL_ENGINE_CONFIG)
        self.assertIsNone(em.GLOBAL_ENGINE_PROVENANCE)

    def test_patching_server_synchronizes_engine_manager(self) -> None:
        mock_service = Mock()
        mock_service.status.return_value = {"state": "mock_ready"}
        with patch("makhos.server.TB3_SERVICE", mock_service):
            self.assertIs(server.TB3_SERVICE, mock_service)
            self.assertIs(em.TB3_SERVICE, mock_service)
            self.assertEqual(em.TB3_SERVICE.status()["state"], "mock_ready")

        self.assertIsNot(em.TB3_SERVICE, mock_service)
        self.assertIs(server.TB3_SERVICE, em.TB3_SERVICE)

    def test_lazy_smp_backend_is_opt_in_and_off_by_default(self) -> None:
        """Without the opt-in the production backend objects must be unchanged."""

        from makhos.native import NativeLazySmpSearch, NativeSearch
        from makhos.parallel_native import ParallelNativeSearch

        em.close_global_engine()
        em.configure_gui_native_search()
        self.assertIsNone(em.GUI_LAZY_SMP_OVERRIDE)

        production = em.production_native_library()
        self.assertTrue(production.is_file(), "production native library missing")
        with em._create_native_search(production, threads=1, hash_mb=16) as single:
            self.assertIsInstance(single, NativeSearch)
        with em._create_native_search(production, threads=4, hash_mb=64) as parallel:
            self.assertIsInstance(parallel, ParallelNativeSearch)
            self.assertNotIsInstance(parallel, NativeLazySmpSearch)

    def test_engine_config_records_the_lazy_smp_flag_as_the_eighth_field(self) -> None:
        em.close_global_engine()
        em.configure_gui_native_search()
        try:
            em.get_default_engine(threads=1, hash_mb=16)
            self.assertEqual(len(em.GLOBAL_ENGINE_CONFIG), 8)
            self.assertIs(em.GLOBAL_ENGINE_CONFIG[7], False)
        finally:
            em.close_global_engine()
            em.configure_gui_native_search()


if __name__ == "__main__":
    unittest.main()
