import unittest
from dataclasses import replace

from makhos.core import apply_move, initial_state, legal_moves
from makhos.native import NativeSearchResult
from makhos.search import Engine, SearchLimits


class _Backend:
    nnue_enabled = False

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def search(self, state, **_kwargs):
        self.calls += 1
        return self.result

    def clear(self):
        pass


def _engine(result):
    return Engine(exact_piece_limit=0, native_search=_Backend(result))


class NativePvValidationTests(unittest.TestCase):
    def setUp(self):
        self.state = initial_state()
        self.first = legal_moves(self.state)[0]
        child = apply_move(self.state, self.first, validate=False)
        self.reply = legal_moves(child)[0]
        self.bogus = replace(self.reply, path=(0, 31))

    def result(self, pv, move=None):
        return NativeSearchResult(
            move=move or self.first, score=12, depth=9, nodes=10, elapsed_ms=1, pv=pv
        )

    def test_illegal_pv_tail_keeps_the_native_move(self):
        engine = _engine(self.result((self.first, self.reply, self.bogus)))
        result = engine.search(self.state, SearchLimits(depth=9, time_ms=100))
        self.assertEqual(engine.last_search_backend, "native")
        self.assertEqual(result.move, self.first)
        self.assertEqual(result.pv, (self.first, self.reply))
        self.assertEqual(engine.native_pv_truncations, 1)
        self.assertIsNone(engine.last_native_error)

    def test_legal_pv_is_untouched(self):
        engine = _engine(self.result((self.first, self.reply)))
        result = engine.search(self.state, SearchLimits(depth=9, time_ms=100))
        self.assertEqual(result.pv, (self.first, self.reply))
        self.assertEqual(engine.native_pv_truncations, 0)

    def test_promotes_flag_is_not_part_of_move_identity(self):
        flagged_first = replace(self.first, promotes=True)
        flagged_reply = replace(self.reply, promotes=True)
        engine = _engine(self.result((flagged_first, flagged_reply), move=flagged_first))
        result = engine.search(self.state, SearchLimits(depth=9, time_ms=100))
        self.assertEqual(engine.last_search_backend, "native")
        self.assertEqual(result.move, self.first)
        self.assertFalse(result.move.promotes)
        self.assertEqual(result.pv, (self.first, self.reply))

    def test_illegal_root_move_still_falls_back_to_python(self):
        engine = _engine(self.result((self.bogus,), move=self.bogus))
        result = engine.search(self.state, SearchLimits(depth=1))
        self.assertEqual(engine.last_search_backend, "python-fallback")
        self.assertIn(result.move, legal_moves(self.state))
        self.assertIn("illegal root move", engine.last_native_error)


if __name__ == "__main__":
    unittest.main()
