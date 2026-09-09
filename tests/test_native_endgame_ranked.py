"""C1 compact reader parity. Sparse synthetic WDL, not solved TB acceptance."""
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import tempfile
import unittest

from makhos.compact_tb3 import CompactTablebase
from makhos.core import State, parse_position
from makhos.exact import Outcome
from makhos.native_endgame import DEFAULT_LIBRARY, NativeEndgameTablebase, Position, Probe, RankedInfo
from makhos.provenance import (DEFAULT_MANIFEST_PATH, TablebaseProvenanceError,
                               generator_source_sha256)
from makhos.ranked_tablebase import (
    RankedTablebase, _canonical_signature_counts, _completion_count, _unrank_board,
)


def make_sparse(file):
    # NTFS otherwise materializes multi-GB gaps on some Windows configurations.
    if os.name == "nt":
        import msvcrt
        dll = C.WinDLL("kernel32", use_last_error=True)
        dll.DeviceIoControl.argtypes = [C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32,
                                       C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32), C.c_void_p]
        dll.DeviceIoControl.restype = C.c_int
        returned = C.c_uint32()
        if not dll.DeviceIoControl(msvcrt.get_osfhandle(file.fileno()), 0x900C4,
                                   None, 0, None, 0, C.byref(returned), None):
            raise OSError(C.get_last_error(), "C1 fixtures require a sparse-file capable filesystem")


def write_fixture(path, pieces=4, clock=80):
    """Real v1 layout, every signature, independently planted threshold bytes.

    FNV skips zero runs with modular exponentiation, so even the >4-GiB TB6
    fixture takes only KB on disk. No tablebase solving or allocation by size.
    """
    signatures = _canonical_signature_counts(pieces)
    total = sum(2 * _completion_count(0, *c) for c in signatures)
    rng = random.Random(20260909 + pieces)
    records = []
    checksum = 1469598103934665603
    prime, modulus = 1099511628211, 1 << 64
    with path.open("w+b") as file:
        make_sparse(file)
        file.write(struct.pack("<8sIIIIQQQ", b"MKTCWDL1", 1, pieces, clock,
                               len(signatures), total, total * (clock + 1), 0))
        for counts in signatures:
            boards = _completion_count(0, *counts)
            header = file.tell()
            file.write(struct.pack("<4BQQ", *counts, boards, boards * 2))
            payload = file.tell()
            ranks = sorted({0, 1, boards // 2, boards - 2, boards - 1,
                            *rng.sample(range(2, boards - 2), 11)})
            palette = (0, 1, 2, clock - 1, clock, 0x81, 0x82, 0x80 | (clock - 1), 0x80 | clock)
            last = 0
            samples = []
            for i, rank in enumerate(ranks):
                for turn in (1, 2):
                    encoded = palette[(i * 2 + turn + sum(counts)) % len(palette)]
                    offset = rank * 2 + turn - 1
                    checksum = checksum * pow(prime, offset - last, modulus) % modulus
                    checksum = (checksum ^ encoded) * prime % modulus
                    last = offset + 1
                    file.seek(payload + offset)
                    file.write(bytes([encoded]))
                    samples.append((rank, turn, encoded))
            checksum = checksum * pow(prime, boards * 2 - last, modulus) % modulus
            records.append(dict(counts=counts, boards=boards, header=header,
                                payload=payload, samples=samples))
            file.seek(payload + boards * 2)
        file.truncate()
        file.seek(40)
        file.write(struct.pack("<Q", checksum))
    return records


def position(state):
    red = black = kings = 0
    for sq, piece in enumerate(state.board):
        if piece in (1, 3):
            red |= 1 << sq
        if piece in (2, 4):
            black |= 1 << sq
        if piece in (3, 4):
            kings |= 1 << sq
    return Position(red, black, kings, state.turn, state.reversible_plies)


@unittest.skipUnless(DEFAULT_LIBRARY.is_file(), "isolated C1 library not built")
class NativeEndgameRankedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.paths, cls.records = {}, {}
        for n in (4, 5, 6):
            path = cls.root / f"ฐานข้อมูล-{n}.compact.bin"
            cls.paths[n] = path
            cls.records[n] = write_fixture(path, n)
        cls.native = NativeEndgameTablebase(ranked_paths=list(cls.paths.values()))
        cls.addClassCleanup(cls.native.close)

    def fixture(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "mutant.bin"
        return path, write_fixture(path, **kwargs)

    def test_all_139_signatures_both_turns_all_81_clocks(self):
        signatures = probes = 0
        for n, path in self.paths.items():
            with RankedTablebase(path) as reference:
                self.assertEqual(reference.material_signatures,
                                 tuple(r["counts"] for r in self.records[n]))
                for record in self.records[n]:
                    signatures += 1
                    for rank, turn, encoded in record["samples"]:
                        board = _unrank_board(rank, record["counts"])
                        for clock in range(81):
                            state = State(board, turn, clock)
                            expected = (Outcome.DRAW if not encoded or clock >= (encoded & 127)
                                        else Outcome.WIN if encoded & 128 else Outcome.LOSS)
                            actual = self.native.probe(state)
                            self.assertEqual(actual, reference.probe(state), (n, rank, turn, clock))
                            self.assertEqual(actual.outcome, expected)
                            self.assertIsNone(actual.distance)
                            probes += 1
        self.assertEqual(signatures, 139)
        self.assertEqual(probes, 360288)

    def test_unplanted_ranks_decode_draw(self):
        rng = random.Random(42)
        for n, records in self.records.items():
            with RankedTablebase(self.paths[n]) as reference:
                for record in records:
                    planted = {rank for rank, _, _ in record["samples"]}
                    for _ in range(10):
                        rank = rng.randrange(record["boards"])
                        if rank in planted:
                            continue
                        state = State(_unrank_board(rank, record["counts"]), rng.choice((1, 2)), 0)
                        self.assertEqual(self.native.probe(state), reference.probe(state))
                        self.assertEqual(self.native.probe(state).outcome, Outcome.DRAW)

    def test_unified_tb3_through_tb6_and_reference_close(self):
        with CompactTablebase() as source:
            native = NativeEndgameTablebase(source, ranked_paths=list(reversed(self.paths.values())))
            self.addCleanup(native.close)
            state = parse_position("B:BK6,15:RK28")
            expected = source.probe(state)
        self.assertEqual(native.piece_counts, (3, 4, 5, 6))
        self.assertEqual(native.max_pieces, 6)
        self.assertEqual(native.probe(state), expected)
        for n in (4, 5, 6):
            state = State(_unrank_board(0, self.records[n][0]["counts"]), 1, 0)
            with RankedTablebase(self.paths[n]) as reference:
                expected = reference.probe(state)
            self.assertEqual(native.probe(state), expected)

    def test_info_uses_64_bit_offsets_and_handle_identity(self):
        self.assertEqual(C.sizeof(RankedInfo), 72)
        for n in (4, 5, 6):
            info = self.native.ranked_info(n)
            self.assertEqual(info["signature_count"], {4: 25, 5: 44, 6: 70}[n])
            self.assertEqual(info["file_bytes"], self.paths[n].stat().st_size)
            self.assertEqual(info["total_states"], info["total_positions"] * 81)
            self.assertEqual(info["checksum_verified"], 0)
            if os.name != "nt":
                self.assertEqual(info["file_id"], self.paths[n].stat().st_ino)
        self.assertGreater(self.records[6][-1]["payload"], 2**32)

    def test_checksum_and_actual_mapped_sha256(self):
        path = self.paths[4]
        with NativeEndgameTablebase(ranked_paths=[path], verify_checksum=True) as native:
            self.assertEqual(native.ranked_info(4)["checksum_verified"], 1)
            digest = hashlib.sha256()
            with path.open("rb") as file:
                while data := file.read(1 << 20):
                    digest.update(data)
            self.assertEqual(native.mapped_sha256(4), digest.hexdigest())
        path, _ = self.fixture()
        with path.open("r+b") as file:
            file.seek(40)
            file.write(bytes(8))
        with self.assertRaisesRegex(ValueError, "status=4"):
            NativeEndgameTablebase(ranked_paths=[path], verify_checksum=True)

    def test_provenance_rejects_wrong_binding_and_hashes_actual_mapping(self):
        path, _ = self.fixture()
        manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text())
        # Synthetic fixture binds this checkout, not the historical TB generator.
        manifest["generator"]["bundle_sha256"] = generator_source_sha256()
        with NativeEndgameTablebase(ranked_paths=[path]) as native:
            info = native.ranked_info(4)
            digest = native.mapped_sha256(4)
            manifest["artifacts"] = [dict(
                piece_count=4, no_progress_plies=80, representation="compact",
                file_name=path.name, file_bytes=info["file_bytes"],
                fnv1a64=f'{info["expected_checksum"]:016x}', sha256=digest,
            )]
            mp = path.with_suffix(".json")
            mp.write_text(json.dumps(manifest))
            self.assertEqual(native.verify_provenance(mp)[0].sha256, digest)
            # Path replacement cannot authenticate a different file on POSIX.
            # Windows denies rename while mapped; this is the stronger OS contract.
            if os.name != "nt":
                path.rename(path.with_suffix(".original"))
                path.write_bytes(b"replacement")
                self.assertEqual(native.mapped_sha256(4), digest)
                self.assertEqual(native.verify_provenance(mp)[0].sha256, digest)
            manifest["artifacts"][0]["sha256"] = "0" * 64
            mp.write_text(json.dumps(manifest))
            with self.assertRaises(TablebaseProvenanceError):
                native.verify_provenance(mp)

    def test_invalid_metadata_rejected_before_probe(self):
        path, records = self.fixture()
        modifications = [
            (0, b"MKT4WDL1"), (8, struct.pack("<I", 2)),
            (12, struct.pack("<I", 7)), (16, struct.pack("<I", 0)),
            (16, struct.pack("<I", 127)), (16, struct.pack("<I", 79)),
            (20, struct.pack("<I", 24)), (24, struct.pack("<Q", 1)),
            (32, struct.pack("<Q", 1)), (48, b"\xff" * 4),
            (52, struct.pack("<Q", 2**64 - 1)), (60, struct.pack("<Q", 2**64 - 1)),
        ]
        by_size = {}
        for record in records:
            by_size.setdefault(record["boards"], []).append(record)
        left, right = next(group[:2] for group in by_size.values() if len(group) > 1)
        modifications.append((left["header"], bytes(right["counts"])))
        for offset, data in modifications:
            with self.subTest(offset=offset, value=data):
                with path.open("r+b") as file:
                    file.seek(offset)
                    original = file.read(len(data))
                    file.seek(offset)
                    file.write(data)
                try:
                    with self.assertRaisesRegex(ValueError, "status=4"):
                        NativeEndgameTablebase(ranked_paths=[path])
                finally:
                    with path.open("r+b") as file:
                        file.seek(offset)
                        file.write(original)

    def test_truncated_and_trailing_payload_rejected(self):
        path, _ = self.fixture()
        size = path.stat().st_size
        with path.open("ab") as file:
            file.write(b"extra")
        with self.assertRaisesRegex(ValueError, "status=4"):
            NativeEndgameTablebase(ranked_paths=[path])
        for length in (size - 1, 60, 47, 0):
            with path.open("r+b") as file:
                file.truncate(length)
            with self.assertRaisesRegex(ValueError, "status=4"):
                NativeEndgameTablebase(ranked_paths=[path])

    def test_reserved_thresholds_are_corrupt_even_at_draw_horizon(self):
        path, records = self.fixture()
        record = records[0]
        state = State(_unrank_board(0, record["counts"]), 1, 0)
        for encoded in (0x80, 81, 127, 0xD1, 0xFF):
            with path.open("r+b") as file:
                file.seek(record["payload"])
                file.write(bytes([encoded]))
            with NativeEndgameTablebase(ranked_paths=[path]) as native, RankedTablebase(path) as reference:
                for clock in (0, 80):
                    current = replace(state, reversible_plies=clock)
                    with self.assertRaises(ValueError):
                        reference.probe(current)
                    pos = position(current)
                    out = Probe(C.sizeof(Probe), 1, 99, 99, 99, 99)
                    before = bytes(out)
                    self.assertEqual(native._dll.makhos_tb_set_probe(native._handle,
                                     C.byref(pos), C.byref(out)), 4)
                    self.assertEqual(bytes(out), before)

    def test_miss_invalid_and_metadata_abi_leave_output_unchanged(self):
        native = self.native
        for pos, status in ((Position(1, 2, 3, 1, 0), 1),
                            (Position(15, 0, 15, 1, 0), 1),
                            (Position(1, 14, 1, 1, 0), 3),  # black men on final rank
                            (Position(1, 14, 15, 1, 81), 3),
                            (Position(1, 14, 15, 3, 0), 3)):
            out = Probe(C.sizeof(Probe), 1, 99, 99, 99, 99)
            before = bytes(out)
            self.assertEqual(native._dll.makhos_tb_set_probe(native._handle,
                             C.byref(pos), C.byref(out)), status)
            self.assertEqual(bytes(out), before)
        for info in (RankedInfo(0, 1), RankedInfo(C.sizeof(RankedInfo), 2)):
            before = bytes(info)
            self.assertEqual(native._dll.makhos_tb_set_ranked_info(native._handle, 4, C.byref(info)), 3)
            self.assertEqual(bytes(info), before)

    def test_failed_preparation_releases_partial_mappings(self):
        path, _ = self.fixture()
        bad = path.with_suffix(".bad")
        bad.write_bytes(b"bad")
        for paths, status in (([path, path], 3), ([path, bad], 4),
                              ([path, path.with_suffix(".absent")], 7)):
            for _ in range(5):
                with self.assertRaisesRegex(ValueError, f"status={status}"):
                    NativeEndgameTablebase(ranked_paths=paths)
            # On Windows a leaked FILE_SHARE_READ-only handle prevents this.
            with path.open("r+b"):
                pass
        with NativeEndgameTablebase(ranked_paths=[path]) as native:
            self.assertEqual(native.piece_counts, (4,))
        path.unlink()

    def test_raw_workers_keep_mapping_alive_after_owner_close(self):
        native = NativeEndgameTablebase(ranked_paths=list(self.paths.values()))
        dll, handle = native._dll, native._handle
        samples = []
        for n, records in self.records.items():
            for record in records:
                rank, turn, _ = record["samples"][-1]
                state = State(_unrank_board(rank, record["counts"]), turn, 0)
                samples.append((position(state), native.probe(state).outcome))
        for _ in range(4):
            dll.makhos_tb_set_retain(handle)
        native.close()
        def worker(_):
            try:
                for _ in range(5):
                    for pos, expected in samples:
                        out = Probe(C.sizeof(Probe), 1)
                        self.assertEqual(dll.makhos_tb_set_probe(handle, C.byref(pos), C.byref(out)), 0)
                        self.assertEqual(out.outcome, expected)
                        self.assertEqual(out.distance, -1)
            finally:
                dll.makhos_tb_set_release(handle)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(worker, range(4)))
        native.close()
        for call in (lambda: native.probe(State(_unrank_board(0, (0, 2, 0, 2)), 1, 0)),
                     lambda: native.ranked_info(4), lambda: native.mapped_sha256(4)):
            with self.assertRaises(RuntimeError):
                call()

    def test_bridge_argument_validation(self):
        for kwargs in ({}, {"ranked_paths": self.paths[4]},
                       {"ranked_paths": [self.paths[4]] * 4},
                       {"ranked_paths": [self.paths[4]], "no_progress_plies": 2**32 + 80},
                       {"ranked_paths": [self.paths[4]], "no_progress_plies": 0}):
            with self.assertRaises((ValueError, TypeError)):
                NativeEndgameTablebase(**kwargs)
        with CompactTablebase() as source:
            with self.assertRaisesRegex(ValueError, "horizons"):
                NativeEndgameTablebase(source, ranked_paths=[self.paths[4]], no_progress_plies=79)


if __name__ == "__main__":
    unittest.main()
