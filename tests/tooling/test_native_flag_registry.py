import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "verification"))
import native_flag_registry as registry  # noqa: E402


class NativeFlagRegistryTests(unittest.TestCase):
    def test_parse_defaults_pairs_guard_and_define(self) -> None:
        text = (
            "#ifndef MAKHOS_A\n#define MAKHOS_A 1\n#endif\n"
            "#define MAKHOS_NOT_GUARDED 5\n"
            "#ifndef MAKHOS_B\n#define MAKHOS_OTHER 2\n#endif\n"
            "#ifndef MAKHOS_C\n#define MAKHOS_C -12\n#endif\n"
        )
        self.assertEqual(
            registry.parse_defaults(text), [("MAKHOS_A", "1", 1), ("MAKHOS_C", "-12", 8)]
        )

    def test_switch_mapping_comes_from_the_orchestrator(self) -> None:
        text = "        if ($StrictSearchKey) { $Flags += '-DMAKHOS_STRICT_SEARCH_POSITION_KEY=1' }\n"
        self.assertEqual(
            registry.parse_switches(text),
            {"MAKHOS_STRICT_SEARCH_POSITION_KEY": "StrictSearchKey"},
        )

    def test_committed_registry_is_current(self) -> None:
        expected = registry.render(
            registry.SOURCE.read_text(encoding="utf-8"),
            registry.ORCHESTRATOR.read_text(encoding="utf-8"),
        )
        self.assertEqual(registry.OUTPUT.read_text(encoding="utf-8"), expected)

    def test_known_flags_are_listed_with_their_switch(self) -> None:
        text = registry.OUTPUT.read_text(encoding="utf-8")
        self.assertIn("| `MAKHOS_STRICT_SEARCH_POSITION_KEY` | `0` |", text)
        self.assertIn("`-StrictSearchKey`", text)
        self.assertIn("`-ReverseFutility`", text)


if __name__ == "__main__":
    unittest.main()
