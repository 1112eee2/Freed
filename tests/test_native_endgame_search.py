"""C2 1T differential gate against Engine.search in reference configuration."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import ctypes as C
from dataclasses import replace
from pathlib import Path
import random
import subprocess
import tempfile
import time
import unittest

from makhos.compact_tb3 import CompactTablebase, BOARD_COUNT
from makhos.core import Rules, State, apply_move, legal_moves, parse_position, terminal_status
from makhos.native_endgame import NativeEndgameTablebase
from makhos.native_endgame_search import DEFAULT_LIBRARY, NativeEndgameSearch, Summary
from makhos.ranked_tablebase import RankedTablebase, _canonical_signature_counts, _completion_count, _unrank_board
from makhos.search import Engine, Mode, SearchLimits, TTEntry, TTFlag
from tests.test_endgame_repetition import repetition_fixture, WINNING_MOVES

ROOT = Path(__file__).resolve().parents[1]
PATHS = tuple(ROOT / f'build/tb{n}_np80.compact.bin' for n in (4, 5, 6))


@unittest.skipUnless(DEFAULT_LIBRARY.is_file() and all(p.is_file() for p in PATHS),
                     'build isolated C2 DLL and supply real TB4-TB6 artifacts')
class NativeEndgameSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.tb3 = cls.stack.enter_context(CompactTablebase())
        cls.ranked = tuple(cls.stack.enter_context(RankedTablebase(p)) for p in PATHS)
        cls.tb = cls.stack.enter_context(NativeEndgameTablebase(cls.tb3, library=DEFAULT_LIBRARY, ranked_paths=PATHS))

    def setUp(self):
        self.native = NativeEndgameSearch(self.tb)
        self.addCleanup(self.native.close)

    def engine(self, rules=Rules()):
        return Engine(rules, native_tablebase=self.tb3, ranked_tablebases=self.ranked,
                      exact_piece_limit=0, reference_search=True)

    def compare(self, state, depth, rules=Rules(), history=None, modes=tuple(Mode)):
        engine = self.engine(rules)
        result = self.native.search(state, depth, rules=rules, history=history)
        status = terminal_status(state, repetition_count=(history or {}).get(state.position_key, 1), rules=rules)
        if status.terminal:
            reasons = {'repetition': 1, 'no_progress': 2, 'no_legal_move': 3}
            self.assertEqual(result.terminal_reason, reasons[status.reason])
            self.assertFalse(result.roots)
            self.assertEqual(sum(result.tb_hits), 0)
            self.assertEqual(result.terminal_score, 0 if status.winner is None else -1_000_000)
            with self.assertRaisesRegex(ValueError, 'terminal'):
                engine.search(state, SearchLimits(depth=depth), history=history)
            return result
        self.assertEqual((result.status, result.depth, result.terminal_reason), (0, depth, 0))
        actual = {root.pv[0].notation: (root.score, root.bound, root.pv) for root in result.roots}
        for mode in modes:
            reference = engine.search(state, SearchLimits(depth=depth), history=history, mode=mode)
            expected = {root.move.notation: (root.score, root.bound, root.pv) for root in reference.candidates}
            self.assertEqual(actual, expected, (state, depth, mode))
            chosen = result.choose(engine, state, mode)
            self.assertEqual((chosen.move, chosen.score, chosen.bound, chosen.pv),
                             (reference.move, reference.score, reference.bound, reference.pv))
        for root in result.roots:
            cursor = state
            for move in root.pv:
                self.assertIn(move, legal_moves(cursor))
                cursor = apply_move(cursor, move)
        return result

    def test_standard_positions_depth_1_2_4_6(self):
        for notation in ('B:BK6,15:RK28', 'B:BM18:RM14,1', 'B:BK1:RK32',
                         'B:BK1,5,6:RK28', 'B:BM5,9:RM1,14',
                         'B:BK1,5,6:RK24,28', 'B:BK1,5,6:RK24,28,32'):
            for repetition in (None, 3):
                for depth in (1, 2, 4, 6):
                    with self.subTest(position=notation, repetition=repetition, depth=depth):
                        self.compare(parse_position(notation), depth, Rules(repetition_limit=repetition))

    def test_repetition_win_and_defender_depth_1_2_3_8(self):
        state, history = repetition_fixture()
        for depth in (1, 2, 3, 8):
            result = self.compare(state, depth, history=history)
            for mode in Mode:
                chosen = result.choose(self.engine(), state, mode)
                self.assertIn(chosen.move.notation, WINNING_MOVES)
                child = apply_move(state, chosen.move)
                counts = history.copy(); counts[child.position_key] += 1
                for reply in legal_moves(child):
                    after = apply_move(child, reply)
                    terminal = terminal_status(after, repetition_count=counts[after.position_key]+1)
                    self.assertFalse(terminal.terminal and terminal.winner is None)
            bad = next(m for m in legal_moves(state) if m.notation == '6-9')
            defender = apply_move(state, bad)
            counts = history.copy(); counts[defender.position_key] += 1
            response = self.compare(defender, depth, history=counts)
            for mode in Mode:
                self.assertEqual(response.choose(self.engine(), defender, mode).move.notation, '28-32')

    def test_clock_history_and_terminal_precedence(self):
        state, history = repetition_fixture()
        for clock in (0, 1, 77, 78, 79, 80):
            for count in (1, 2, 3):
                root = replace(state, reversible_plies=clock)
                counts = history.copy(); counts[root.position_key] = count
                for depth in (1, 2, 4, 6):
                    with self.subTest(clock=clock, count=count, depth=depth):
                        self.compare(root, depth, history=counts)
        no_moves = parse_position('B::RK32')
        self.compare(no_moves, 1)
        self.compare(replace(no_moves, reversible_plies=80), 1)
        self.compare(replace(no_moves, reversible_plies=80), 1, history={no_moves.position_key:3})

    def test_all_139_material_signatures(self):
        rng = random.Random(20260910)
        covered = 0
        for pieces in (4, 5, 6):
            for counts in _canonical_signature_counts(pieces):
                rank = rng.randrange(_completion_count(0, *counts))
                board = _unrank_board(rank, counts)
                for turn in (1, 2):
                    for repetition in (None, 3):
                        # Near-clock cases keep full-depth verification bounded.
                        state = State(board, turn, 79)
                        self.compare(state, 2, Rules(repetition_limit=repetition), modes=(Mode.BEST,))
                covered += 1
        self.assertEqual(covered, 139)

    def test_non_tb_ancestor_and_material_transitions(self):
        # Search expands a 7-piece ancestor and captures through the 6-piece boundary.
        state = parse_position('B:BM18,25,26,27:RM14,1,2')
        self.assertEqual(sum(bool(p) for p in state.board), 7)
        self.assertTrue(any(sum(bool(p) for p in apply_move(state,m).board)==6 for m in legal_moves(state)))
        for depth in (1, 2, 4, 6):
            self.compare(state, depth)
        transition = parse_position('B:BM18,25:RM14,1')
        result = self.compare(transition, 2)
        self.assertGreater(result.tb_hits[3], 0)

    def test_tt_poison_and_repeated_histories(self):
        state, history = repetition_fixture()
        engine = self.engine()
        poisoned = TTEntry(state.position_key, 99, 999999, TTFlag.EXACT)
        for move in legal_moves(state):
            engine._tt[apply_move(state, move).position_key] = poisoned
        original = dict(engine._tt)
        for count in (1, 3, 2, 1):
            counts = history.copy(); counts[state.position_key] = count
            result = self.native.search(state, 2, history=counts)
            if count == 3:
                self.assertEqual(result.terminal_reason, 1)
                continue
            reference = engine.search(state, SearchLimits(depth=2), history=counts)
            self.assertEqual(result.choose(engine, state).move, reference.move)
        self.assertEqual(engine._tt, original)  # reference reads/writes no scores

    def test_cancel_publishes_completed_layers_only_and_reuse(self):
        state, history = repetition_fixture()
        before = history.copy()
        depth1 = self.native.search(state, 1, history=history)
        stopped = self.native.search(state, 6, history=history, node_limit=1)
        self.assertEqual((stopped.status, stopped.depth, stopped.roots), (2, 0, ()))
        with self.assertRaises(ValueError): stopped.choose(self.engine(), state)
        stopped = self.native.search(state, 6, history=history, node_limit=depth1.nodes+1)
        self.assertEqual((stopped.status, stopped.depth, stopped.roots), (2, 1, depth1.roots))
        self.assertEqual(self.native.search(state, 1, history=history).roots, depth1.roots)
        self.assertEqual(history, before)

    def test_session_retains_tb_and_validates_inputs(self):
        tb = NativeEndgameTablebase(self.tb3, library=DEFAULT_LIBRARY)
        native = NativeEndgameSearch(tb)
        self.addCleanup(native.close)
        tb.close()
        state = parse_position('B:BK6,15:RK28')
        self.assertEqual(native.search(state, 2).depth, 2)
        for kwargs in ({'depth':0}, {'depth':95}, {'time_ms':-1}, {'node_limit':-1},
                       {'rules':Rules(no_progress_plies=79)}, {'history':{state.position_key:256}}):
            with self.assertRaises(ValueError): native.search(state, **kwargs)
        output = Summary(0, 1)
        self.assertEqual(native._dll.makhos_endgame_results(native._handle, C.byref(output), None, 0), 3)
        native.close(); native.close()
        with self.assertRaises(RuntimeError): native.search(state)

    def test_real_deadline_and_external_cancel(self):
        # Large enough to stay active until the explicit stop; no GUI resources.
        state = parse_position('B:BK1,5,6,9:RK24,28,31,32')
        result = self.native.search(state, 40, time_ms=1)
        self.assertEqual(result.status, 2)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.native.search, state, 40, time_ms=2000)
            deadline = time.monotonic() + 3
            while not future.done() and time.monotonic() < deadline:
                self.native.cancel()
                time.sleep(0.001)
            result = future.result(timeout=3)
        self.assertEqual(result.status, 2)
        self.assertTrue(all(root.pv for root in result.roots))
        # A cancelled session must accept a fresh request with reset stop state.
        self.assertEqual(self.native.search(parse_position('B:BK1:RK32'), 1).status, 0)

    def test_corrupt_tb_search_fails_closed(self):
        class CorruptImage:
            def export_native_image(self):
                # Structurally valid image, unsupported encoded value everywhere.
                return bytes(BOARD_COUNT*4) + b'\xff\xff'*81, 80, 1
        with NativeEndgameTablebase(CorruptImage(), library=DEFAULT_LIBRARY) as tb, NativeEndgameSearch(tb) as native:
            with self.assertRaisesRegex(ValueError, 'status=4'):
                native.search(parse_position('B:BK6,15:RK28'), 2)
            summary = Summary(C.sizeof(Summary), 1)
            self.assertEqual(native._dll.makhos_endgame_results(native._handle, C.byref(summary), None, 0), 4)

    def test_native_internal_boundaries(self):
        executable = DEFAULT_LIBRARY.parent / 'native_endgame_boundaries.exe'
        self.assertTrue(executable.is_file(), 'build the C2 boundary harness')
        image, clock, vectors = self.tb3.export_native_image()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.bin'
            path.write_bytes(image)
            result = subprocess.run([str(executable), str(path), str(clock), str(vectors)],
                                    capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
