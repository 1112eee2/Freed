import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "verification"))
import verify_immutable_artifacts as verifier  # noqa: E402


class VerifyImmutableArtifactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "a.txt").write_bytes(b"alpha")
        self.manifest = self.root / "manifest.json"

    def _write(self, artifacts) -> None:
        self.manifest.write_text(
            json.dumps(
                {"format": "thai-makhos-immutable-artifacts-v1", "artifacts": artifacts}
            ),
            encoding="utf-8",
        )

    def test_matching_file_passes(self) -> None:
        sha = hashlib.sha256(b"alpha").hexdigest()
        self._write([{"path": "a.txt", "sha256": sha, "tracked": True}])
        self.assertEqual(verifier.verify(self.root, self.manifest), [])

    def test_changed_and_absent_files_fail(self) -> None:
        self._write(
            [
                {"path": "a.txt", "sha256": "0" * 64, "tracked": True},
                {"path": "gone.bin", "sha256": "0" * 64, "tracked": False},
            ]
        )
        self.assertEqual(len(verifier.verify(self.root, self.manifest)), 2)

    def test_skip_flag_only_forgives_absent_untracked_files(self) -> None:
        self._write(
            [
                {"path": "gone.bin", "sha256": "0" * 64, "tracked": False},
                {"path": "gone_tracked.bin", "sha256": "0" * 64, "tracked": True},
            ]
        )
        problems = verifier.verify(self.root, self.manifest, skip_untracked_missing=True)
        self.assertEqual(problems, ["absent: gone_tracked.bin"])

    def test_wrong_format_is_rejected(self) -> None:
        self.manifest.write_text(json.dumps({"format": "x", "artifacts": []}), encoding="utf-8")
        self.assertTrue(verifier.verify(self.root, self.manifest))

    def test_repository_ruleset_and_core_match_the_real_manifest(self) -> None:
        data = json.loads(verifier.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        tracked = [e for e in data["artifacts"] if e["path"] in ("RULESET.json", "makhos/core.py")]
        self.assertEqual(len(tracked), 2)
        for entry in tracked:
            self.assertEqual(verifier.sha256_file(ROOT / entry["path"]), entry["sha256"])


if __name__ == "__main__":
    unittest.main()
