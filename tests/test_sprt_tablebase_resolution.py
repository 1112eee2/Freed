import os
import tempfile
import unittest
from pathlib import Path

from makhos.cli_handlers.sprt_handler import (
    DEFAULT_RANKED_TABLEBASES,
    _resolve_ranked_tablebase_paths,
)


class RankedTablebaseResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._cwd = os.getcwd()
        self.addCleanup(os.chdir, self._cwd)
        os.chdir(self.root)

    def _make_defaults(self, names=DEFAULT_RANKED_TABLEBASES) -> None:
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

    def test_default_set_resolves_when_all_present(self) -> None:
        self._make_defaults()
        paths = _resolve_ranked_tablebase_paths(None)
        self.assertEqual(
            [p.name for p in paths], [Path(n).name for n in DEFAULT_RANKED_TABLEBASES]
        )

    def test_missing_default_file_fails_closed(self) -> None:
        self._make_defaults(DEFAULT_RANKED_TABLEBASES[:2])
        with self.assertRaises(FileNotFoundError) as ctx:
            _resolve_ranked_tablebase_paths(None)
        self.assertIn("tb6_np80", str(ctx.exception))
        self.assertIn("--no-tablebase", str(ctx.exception))

    def test_all_default_files_missing_fails_closed(self) -> None:
        with self.assertRaises(FileNotFoundError):
            _resolve_ranked_tablebase_paths(None)

    def test_missing_explicit_file_fails_closed(self) -> None:
        self._make_defaults()
        with self.assertRaises(FileNotFoundError):
            _resolve_ranked_tablebase_paths(
                [DEFAULT_RANKED_TABLEBASES[0], "build/absent.bin"]
            )

    def test_explicit_files_are_used_instead_of_defaults(self) -> None:
        extra = self.root / "custom.bin"
        extra.write_bytes(b"x")
        self.assertEqual(
            _resolve_ranked_tablebase_paths(["custom.bin"]), [extra.resolve()]
        )


if __name__ == "__main__":
    unittest.main()
