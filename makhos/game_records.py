"""Validate and save GUI games without loading an engine or tablebase."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from .core import BLACK, RED, Rules, format_position, parse_position, terminal_status
from .game_analysis import GameRecordError, parse_game_record, replay_game


MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_RECORD_PLIES = 999  # GUI history API accepts at most 1,000 positions.


def save_game_record(payload: dict, directory: Path, *, rules: Rules) -> Path:
    """Replay first, then create a unique file; user results remain annotations."""
    if not isinstance(payload, dict):
        raise GameRecordError("game record must be a JSON object")
    moves = payload.get("moves")
    if not isinstance(moves, list) or len(moves) > MAX_RECORD_PLIES:
        raise GameRecordError(f"moves must be an array of at most {MAX_RECORD_PLIES} plies")
    record = parse_game_record(payload)
    if record.final_position is None or record.final_reversible_plies is None:
        raise GameRecordError("final_position and reversible_plies are required")
    game = replay_game(record, rules=rules)
    positions = [record.start, *(ply.child for ply in game.plies)]
    history = payload.get("position_history")
    if not isinstance(history, list) or len(history) != len(positions):
        raise GameRecordError("position_history must contain the start and every completed ply")
    for text, state in zip(history, positions):
        if not isinstance(text, str) or parse_position(text).position_key != state.position_key:
            raise GameRecordError("position_history does not match the replayed moves")

    status = terminal_status(
        game.final, repetition_count=game.history[game.final.position_key], rules=rules,
    )
    winner = "black" if status.winner == BLACK else "red" if status.winner == RED else None
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("source") not in ("user", "rules"):
        raise GameRecordError("finish the game or select a user result before saving")
    if "winner" not in result or result["winner"] not in ("black", "red", None):
        raise GameRecordError("result.winner must be black, red, or null (draw)")
    if result["source"] == "rules" and (not status.terminal or result["winner"] != winner):
        raise GameRecordError("rules result does not match the replayed game")

    now = datetime.now(timezone.utc)
    saved = {
        **payload,
        "game_id": record.game_id,
        "saved_at": now.isoformat(),
        "position_history": [format_position(state) for state in positions],
        "result": {
            "source": result["source"],
            "winner": result["winner"],
            "reason": "user_adjudication" if result["source"] == "user" else status.reason,
        },
        # This is computed from the rules, never from the user's chosen label.
        "rules_result": {"terminal": status.terminal, "winner": winner, "reason": status.reason},
    }
    encoded = (json.dumps(saved, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_RECORD_BYTES:
        raise GameRecordError("game record is too large")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"game_{now:%Y%m%dT%H%M%S%fZ}_{uuid4().hex}.json"
    # Exclusive creation prevents overwriting any previous record. Remove a
    # partial file on write failure, so the GUI can offer a clean retry.
    with path.open("xb") as stream:
        try:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        except OSError:
            stream.close()
            path.unlink(missing_ok=True)
            raise
    return path
