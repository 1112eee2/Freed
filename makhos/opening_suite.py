"""Versioned, rules-verified opening suites for paired engine matches."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Mapping

from .core import (
    DEFAULT_RULES,
    State,
    apply_move,
    format_position,
    initial_state,
    legal_moves,
    parse_position,
    terminal_status,
)


OPENING_SUITE_FORMAT = "thai-makhos-opening-suite-v1"


class OpeningSuiteError(ValueError):
    """Raised when an opening suite cannot be trusted for match evidence."""


@dataclass(frozen=True, slots=True)
class Opening:
    opening_id: str
    moves: tuple[str, ...]
    state: State
    history: Mapping[tuple[tuple[int, ...], int], int]


@dataclass(frozen=True, slots=True)
class OpeningSuite:
    name: str
    path: Path
    sha256: str
    opening_plies: int
    openings: tuple[Opening, ...]


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OpeningSuiteError(f"{name} must be a JSON object")
    return value


def _replay_opening(
    start: State,
    moves: tuple[str, ...],
    *,
    opening_id: str,
) -> tuple[State, dict[tuple[tuple[int, ...], int], int]]:
    state = start
    history: Counter[tuple[tuple[int, ...], int]] = Counter({state.position_key: 1})
    for ply, notation in enumerate(moves, start=1):
        status = terminal_status(
            state,
            repetition_count=history[state.position_key],
            rules=DEFAULT_RULES,
        )
        if status.terminal:
            raise OpeningSuiteError(
                f"opening {opening_id} continues after terminal ply {ply - 1}"
            )
        matches = tuple(
            move for move in legal_moves(state)
            if move.notation.lower() == notation.lower()
        )
        if len(matches) != 1:
            raise OpeningSuiteError(
                f"opening {opening_id} ply {ply} is not uniquely legal: {notation}"
            )
        state = apply_move(state, matches[0], validate=False)
        history[state.position_key] += 1
    status = terminal_status(
        state,
        repetition_count=history[state.position_key],
        rules=DEFAULT_RULES,
    )
    if status.terminal:
        raise OpeningSuiteError(
            f"opening {opening_id} ends in a terminal state ({status.reason})"
        )
    return state, dict(history)


def load_opening_suite(path: str | Path) -> OpeningSuite:
    """Load and independently replay every committed opening line."""

    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OpeningSuiteError(f"cannot read opening suite {source}: {error}") from error
    data = _mapping(payload, "opening suite")
    allowed = {
        "format",
        "name",
        "opening_plies",
        "start_position",
        "start_reversible_plies",
        "openings",
    }
    extra = set(data) - allowed
    if extra:
        raise OpeningSuiteError(
            "unknown opening-suite fields: " + ", ".join(sorted(extra))
        )
    if data.get("format") != OPENING_SUITE_FORMAT:
        raise OpeningSuiteError(f"format must be {OPENING_SUITE_FORMAT!r}")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise OpeningSuiteError("name must be a non-empty string")
    opening_plies = data.get("opening_plies")
    if isinstance(opening_plies, bool) or not isinstance(opening_plies, int):
        raise OpeningSuiteError("opening_plies must be an integer")
    if not 0 <= opening_plies <= 80:
        raise OpeningSuiteError("opening_plies must be in 0..80")
    start_text = data.get("start_position")
    if not isinstance(start_text, str) or not start_text.strip():
        raise OpeningSuiteError("start_position must be a non-empty string")
    start_clock = data.get("start_reversible_plies", 0)
    if isinstance(start_clock, bool) or not isinstance(start_clock, int) or start_clock < 0:
        raise OpeningSuiteError("start_reversible_plies must be non-negative")
    try:
        start = parse_position(start_text, reversible_plies=start_clock)
    except ValueError as error:
        raise OpeningSuiteError(f"invalid start_position: {error}") from error

    raw_openings = data.get("openings")
    if not isinstance(raw_openings, list) or not raw_openings:
        raise OpeningSuiteError("openings must be a non-empty JSON array")
    openings: list[Opening] = []
    seen_ids: set[str] = set()
    seen_positions: set[tuple[tuple[int, ...], int, int]] = set()
    for index, raw_opening in enumerate(raw_openings):
        item = _mapping(raw_opening, f"openings[{index}]")
        extra = set(item) - {"id", "moves", "position", "reversible_plies"}
        if extra:
            raise OpeningSuiteError(
                f"unknown fields in openings[{index}]: " + ", ".join(sorted(extra))
            )
        opening_id = item.get("id")
        if not isinstance(opening_id, str) or not opening_id.strip():
            raise OpeningSuiteError(f"openings[{index}].id must be non-empty")
        if opening_id in seen_ids:
            raise OpeningSuiteError(f"duplicate opening id: {opening_id}")
        seen_ids.add(opening_id)
        raw_moves = item.get("moves")
        if not isinstance(raw_moves, list) or any(
            not isinstance(move, str) or not move.strip() for move in raw_moves
        ):
            raise OpeningSuiteError(f"opening {opening_id} moves must be strings")
        moves = tuple(move.strip() for move in raw_moves)
        if len(moves) != opening_plies:
            raise OpeningSuiteError(
                f"opening {opening_id} has {len(moves)} plies, expected {opening_plies}"
            )
        state, history = _replay_opening(start, moves, opening_id=opening_id)
        position_text = item.get("position")
        if position_text != format_position(state):
            raise OpeningSuiteError(
                f"opening {opening_id} position does not match its replayed moves"
            )
        reversible_plies = item.get("reversible_plies")
        if reversible_plies != state.reversible_plies:
            raise OpeningSuiteError(
                f"opening {opening_id} reversible_plies does not match replay"
            )
        key = state.position_key + (state.reversible_plies,)
        if key in seen_positions:
            raise OpeningSuiteError(f"duplicate opening position: {opening_id}")
        seen_positions.add(key)
        openings.append(Opening(opening_id, moves, state, history))

    return OpeningSuite(
        name=name.strip(),
        path=source,
        sha256=hashlib.sha256(raw).hexdigest(),
        opening_plies=opening_plies,
        openings=tuple(openings),
    )


def select_opening(suite: OpeningSuite, *, seed: int, pair_index: int) -> Opening:
    """Shuffle each complete suite cycle deterministically without replacement."""

    if pair_index < 1:
        raise ValueError("pair_index must be positive")
    count = len(suite.openings)
    cycle, offset = divmod(pair_index - 1, count)
    material = f"{suite.sha256}:{seed}:{cycle}".encode("ascii")
    cycle_seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    order = list(range(count))
    random.Random(cycle_seed).shuffle(order)
    return suite.openings[order[offset]]


def generate_opening_suite_payload(
    *,
    name: str,
    count: int,
    opening_plies: int,
    seed: int,
) -> dict[str, Any]:
    """Generate a deduplicated payload; callers must still persist and reload it."""

    if not name.strip():
        raise ValueError("name must be non-empty")
    if count < 1:
        raise ValueError("count must be positive")
    if not 0 <= opening_plies <= 80:
        raise ValueError("opening_plies must be in 0..80")
    rng = random.Random(seed)
    start = initial_state(rules=DEFAULT_RULES)
    entries: list[dict[str, Any]] = []
    seen: set[tuple[tuple[int, ...], int, int]] = set()
    attempts = 0
    maximum_attempts = max(1000, count * 100)
    while len(entries) < count and attempts < maximum_attempts:
        attempts += 1
        state = start
        moves: list[str] = []
        valid = True
        for _ in range(opening_plies):
            choices = legal_moves(state)
            if not choices:
                valid = False
                break
            move = rng.choice(choices)
            moves.append(move.notation)
            state = apply_move(state, move, validate=False)
        if not valid or len(legal_moves(state)) < 2:
            continue
        key = state.position_key + (state.reversible_plies,)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "id": f"{name}-{len(entries) + 1:04d}",
                "moves": moves,
                "position": format_position(state),
                "reversible_plies": state.reversible_plies,
            }
        )
    if len(entries) != count:
        raise RuntimeError(
            f"generated only {len(entries)} unique openings in {attempts} attempts"
        )
    return {
        "format": OPENING_SUITE_FORMAT,
        "name": name,
        "opening_plies": opening_plies,
        "start_position": format_position(start),
        "start_reversible_plies": start.reversible_plies,
        "openings": entries,
    }
