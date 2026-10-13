"""``sprt --games-dir`` records satisfy the match-game schema and still replay."""

import json
import re
import unittest
from pathlib import Path

from makhos.game_analysis import (
    build_match_game_record,
    load_game_record,
    parse_game_record,
    replay_game,
)
from tests.test_sprt import _recorded_games

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
MATCH_SCHEMA = json.loads(
    (SCHEMAS / "thai-makhos-match-game-v1.schema.json").read_text(encoding="utf-8")
)
GUI_SCHEMA = json.loads(
    (SCHEMAS / "thai-makhos-game-v1.schema.json").read_text(encoding="utf-8")
)

_TYPES = {
    "null": lambda v: v is None,
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
}


def schema_errors(value, node, root, where="$"):
    """Validate the JSON Schema subset these schemas use; return error strings."""
    if "$ref" in node:
        target = root
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return schema_errors(value, target, root, where)
    if "oneOf" in node:
        passing = [c for c in node["oneOf"] if not schema_errors(value, c, root, where)]
        return [] if len(passing) == 1 else [f"{where}: matches {len(passing)} oneOf"]
    errors = []
    if "const" in node and value != node["const"]:
        errors.append(f"{where}: expected {node['const']!r}")
    if "enum" in node and value not in node["enum"]:
        errors.append(f"{where}: {value!r} not in enum")
    if "type" in node:
        types = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not any(_TYPES[t](value) for t in types):
            return errors + [f"{where}: wrong type"]
    if isinstance(value, bool) or value is None:
        return errors
    if isinstance(value, (int, float)):
        if "minimum" in node and value < node["minimum"]:
            errors.append(f"{where}: below minimum")
        if "maximum" in node and value > node["maximum"]:
            errors.append(f"{where}: above maximum")
        if "exclusiveMinimum" in node and value <= node["exclusiveMinimum"]:
            errors.append(f"{where}: not above exclusiveMinimum")
    if isinstance(value, str):
        if "minLength" in node and len(value) < node["minLength"]:
            errors.append(f"{where}: too short")
        if "pattern" in node and not re.search(node["pattern"], value):
            errors.append(f"{where}: pattern mismatch")
    if isinstance(value, list):
        if "minItems" in node and len(value) < node["minItems"]:
            errors.append(f"{where}: too few items")
        if "items" in node:
            for index, item in enumerate(value):
                errors += schema_errors(item, node["items"], root, f"{where}[{index}]")
    if isinstance(value, dict):
        properties = node.get("properties", {})
        for key in node.get("required", ()):
            if key not in value:
                errors.append(f"{where}: missing {key}")
        for key, item in value.items():
            if key in properties:
                errors += schema_errors(item, properties[key], root, f"{where}.{key}")
            elif node.get("additionalProperties") is False:
                errors.append(f"{where}: unexpected {key}")
    return errors


MATCH = {
    "tool": "makhos sprt",
    "seed": 8675309,
    "candidate": {"sha256": "a" * 64, "threads": 1},
    "baseline": {"sha256": "b" * 64, "threads": 1},
}


class SprtGameRecordSchemaTests(unittest.TestCase):
    def test_validator_rejects_a_bad_record(self) -> None:
        self.assertTrue(schema_errors({"format": "nope"}, MATCH_SCHEMA, MATCH_SCHEMA))

    def test_match_records_satisfy_the_schema_and_replay(self) -> None:
        _result, games = _recorded_games(max_pairs=2)
        self.assertTrue(games)
        for game in games:
            record = build_match_game_record(game, match=MATCH)
            self.assertEqual(schema_errors(record, MATCH_SCHEMA, MATCH_SCHEMA), [])
            replayed = replay_game(parse_game_record(record))
            self.assertEqual(
                len(replayed.plies), len(game["opening"]) + len(game["moves"])
            )

    def test_missing_role_or_match_is_rejected(self) -> None:
        _result, games = _recorded_games()
        record = build_match_game_record(games[0], match=MATCH)
        engine_move = next(m for m in record["moves"] if m.get("actor"))
        del engine_move["engine"]["role"]
        self.assertTrue(schema_errors(record, MATCH_SCHEMA, MATCH_SCHEMA))
        record = build_match_game_record(games[0], match=MATCH)
        del record["match"]
        self.assertTrue(schema_errors(record, MATCH_SCHEMA, MATCH_SCHEMA))

    def test_gui_schema_is_not_loosened(self) -> None:
        self.assertNotIn("match", GUI_SCHEMA["properties"])
        self.assertIs(GUI_SCHEMA["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
