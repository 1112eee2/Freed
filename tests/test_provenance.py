import json
import tempfile
import unittest
from pathlib import Path

from makhos.provenance import (
    GENERATOR_SOURCE_FILES,
    PROVENANCE_FORMAT,
    PROVENANCE_VERSION,
    SOURCE_HASH_ALGORITHM,
    TablebaseProvenanceError,
    file_sha256,
    generator_source_sha256,
    ruleset_sha256,
)
from makhos.ranked_tablebase import (
    RankedTablebase,
    _COMPACT_HEADER,
    _COMPACT_MAGIC,
    _SIGNATURE_HEADER,
    _VERSION,
    _canonical_signature_counts,
    _completion_count,
)


class TablebaseProvenanceTests(unittest.TestCase):
    @staticmethod
    def _write_compact_draw_tablebase(path: Path) -> None:
        piece_count = 4
        no_progress_plies = 1
        signatures = _canonical_signature_counts(piece_count)
        boards = {
            counts: _completion_count(0, *counts)
            for counts in signatures
        }
        total_positions = 2 * sum(boards.values())
        total_states = total_positions * (no_progress_plies + 1)
        with path.open("wb") as file:
            file.write(_COMPACT_HEADER.pack(
                _COMPACT_MAGIC,
                _VERSION,
                piece_count,
                no_progress_plies,
                len(signatures),
                total_positions,
                total_states,
                0,
            ))
            for counts in signatures:
                byte_count = boards[counts] * 2
                file.write(_SIGNATURE_HEADER.pack(
                    *counts, boards[counts], byte_count
                ))
                file.seek(byte_count, 1)
            file.truncate()

    @staticmethod
    def _manifest(path: Path, tablebase: Path) -> dict:
        return {
            "format": PROVENANCE_FORMAT,
            "version": PROVENANCE_VERSION,
            "hash_algorithm": "sha256",
            "ruleset": {
                "path": "RULESET.json",
                "canonical_json_sha256": ruleset_sha256(),
            },
            "generator": {
                "algorithm": SOURCE_HASH_ALGORITHM,
                "files": list(GENERATOR_SOURCE_FILES),
                "bundle_sha256": generator_source_sha256(),
            },
            "artifacts": [{
                "piece_count": 4,
                "no_progress_plies": 1,
                "representation": "compact",
                "file_name": tablebase.name,
                "file_bytes": tablebase.stat().st_size,
                "fnv1a64": "0000000000000000",
                "sha256": file_sha256(tablebase),
            }],
        }

    def test_ranked_reader_verifies_rules_source_and_complete_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tablebase_path = root / "fixture.compact.bin"
            manifest_path = root / "manifest.json"
            self._write_compact_draw_tablebase(tablebase_path)
            manifest = self._manifest(manifest_path, tablebase_path)
            manifest_path.write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            with RankedTablebase(tablebase_path) as tablebase:
                binding = tablebase.verify_provenance(manifest_path)
                self.assertTrue(tablebase.provenance_verified)
                self.assertEqual(binding.piece_count, 4)

            with tablebase_path.open("r+b") as file:
                file.seek(-1, 2)
                original = file.read(1)
                file.seek(-1, 2)
                file.write(bytes([original[0] ^ 1]))
            with RankedTablebase(tablebase_path) as tablebase:
                with self.assertRaisesRegex(
                    TablebaseProvenanceError, "SHA-256 mismatch"
                ):
                    tablebase.verify_provenance(manifest_path)

            manifest["ruleset"]["canonical_json_sha256"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with RankedTablebase(tablebase_path) as tablebase:
                with self.assertRaisesRegex(
                    TablebaseProvenanceError, "ruleset SHA-256"
                ):
                    tablebase.verify_provenance(manifest_path)

            manifest["ruleset"]["canonical_json_sha256"] = ruleset_sha256()
            manifest["generator"]["bundle_sha256"] = "f" * 64
            manifest_path.write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with RankedTablebase(tablebase_path) as tablebase:
                with self.assertRaisesRegex(
                    TablebaseProvenanceError, "generator source SHA-256"
                ):
                    tablebase.verify_provenance(manifest_path)


if __name__ == "__main__":
    unittest.main()
