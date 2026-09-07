"""Resumable quiet-leaf scalar-label acquisition for Thai Makhos NNUE.

This is a measurement/data experiment.  It never changes engine playing code,
trains no model, and accepts labels only from the byte-locked classical DLL.
Games are split before position sampling; color-rotation-equivalent states stay
inside one split or are dropped when they cross splits.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time
from typing import Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from makhos.core import (  # noqa: E402
    BLACK,
    BLACK_KING,
    DEFAULT_RULES,
    EMPTY,
    RED,
    RED_KING,
    State,
    apply_move,
    format_position,
    initial_state,
    legal_moves,
    terminal_status,
)
from makhos.eval_corpus import canonical_position_id  # noqa: E402
from makhos.exact import Outcome  # noqa: E402
from makhos.game_analysis import (  # noqa: E402
    load_game_record,
    player_name,
    replay_game,
)
from makhos.native import (  # noqa: E402
    NativeSearch,
    hash_power_for_megabytes,
    native_tt_entry_bytes,
)
from makhos.provenance import ruleset_sha256  # noqa: E402
from makhos.ranked_tablebase import RankedTablebase  # noqa: E402
from makhos.search import Engine, SearchLimits  # noqa: E402
from makhos.workload_isolation import (  # noqa: E402
    BatchWorkLease,
    InteractiveSessionActive,
)


FORMAT = "thai-makhos-nnue-quiet-leaf-acquisition-v1"
CORPUS_FORMAT = "thai-makhos-nnue-quiet-leaf-v1"
EXPECTED_ACCEPTED_SHA256 = (
    "FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD"
)
DEFAULT_SEED_START = 20263001
DEFAULT_BUDGETS_MS = (100, 500, 2000)
TEACHER_MAX_DEPTH = 90
DEFAULT_PILOT_TARGET = 8000
OPENING_SCHEDULE = (2, 4, 6, 8, 10, 12)
EXPLORATION_SCHEDULE = (0.05, 0.10, 0.15, 0.20)
PHASE_BANDS = ("13_to_16", "9_to_12", "5_to_8")
OUTCOME_NAME = {
    Outcome.LOSS: "loss",
    Outcome.DRAW: "draw",
    Outcome.WIN: "win",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_json_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def encoded_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, payload: object) -> None:
    atomic_write_text(path, encoded_json(payload))


def write_locked_json(path: Path, payload: object) -> None:
    text = encoded_json(payload)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"locked artifact differs: {path}")
        return
    atomic_write_text(path, text)


def parse_budgets(text: str) -> tuple[int, ...]:
    try:
        budgets = tuple(int(item.strip()) for item in text.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("budgets must be comma-separated integers") from error
    if len(budgets) < 2 or any(value < 1 for value in budgets):
        raise argparse.ArgumentTypeError("at least two positive budgets are required")
    if tuple(sorted(set(budgets))) != budgets:
        raise argparse.ArgumentTypeError("budgets must be strictly increasing")
    return budgets


def parse_analysis_splits(text: str) -> tuple[str, ...]:
    allowed = {"train", "validation", "test"}
    splits = tuple(item.strip() for item in text.split(",") if item.strip())
    if not splits or len(set(splits)) != len(splits) or any(
        split not in allowed for split in splits
    ):
        raise argparse.ArgumentTypeError(
            "analysis splits must be unique values from train,validation,test"
        )
    return splits


def phase_band(piece_count: int) -> str | None:
    if 13 <= piece_count <= 16:
        return "13_to_16"
    if 9 <= piece_count <= 12:
        return "9_to_12"
    if 5 <= piece_count <= 8:
        return "5_to_8"
    return None


def game_split(game_id: str) -> str:
    """Deterministic 80/10/10 split assigned before sampling positions."""

    bucket = int(hashlib.sha256(game_id.encode("ascii")).hexdigest()[:8], 16) % 10
    if bucket < 8:
        return "train"
    return "validation" if bucket == 8 else "test"


def analysis_shard(game_id: str, shard_count: int) -> int:
    """Assign one source game to exactly one deterministic analysis worker."""

    if shard_count < 1:
        raise ValueError("shard count must be positive")
    return int(hashlib.sha256(game_id.encode("ascii")).hexdigest(), 16) % shard_count


def generation_shard(game_index: int, shard_count: int) -> int:
    """Assign each scheduled source file to one deterministic generator."""

    if game_index < 1 or shard_count < 1:
        raise ValueError("game index and shard count must be positive")
    return (game_index - 1) % shard_count


def game_schedule(index: int, seed_start: int) -> dict:
    return {
        "index": index,
        "seed": seed_start + index - 1,
        "opening_plies": OPENING_SCHEDULE[(index - 1) % len(OPENING_SCHEDULE)],
        "exploration_rate": EXPLORATION_SCHEDULE[
            ((index - 1) // len(OPENING_SCHEDULE)) % len(EXPLORATION_SCHEDULE)
        ],
    }


def count_pieces(state: State) -> int:
    return sum(piece != EMPTY for piece in state.board)


def count_kings(state: State) -> int:
    return sum(piece in (BLACK_KING, RED_KING) for piece in state.board)


def game_result_payload(status, *, truncated: bool) -> dict:
    if truncated:
        return {
            "terminal": False,
            "reason": "max_game_plies",
            "winner": None,
            "outcome": None,
            "truncated": True,
        }
    if not status.terminal:
        raise ValueError("non-truncated game result must be terminal")
    winner = None if status.winner is None else player_name(status.winner)
    return {
        "terminal": True,
        "reason": status.reason,
        "winner": winner,
        "outcome": "draw" if winner is None else winner,
        "truncated": False,
    }


def outcome_from_turn(game_outcome: str | None, turn: int) -> str | None:
    if game_outcome is None:
        return None
    if game_outcome == "draw":
        return "draw"
    return "win" if game_outcome == player_name(turn) else "loss"


def search_payload(result, *, backend: str, library_sha256: str) -> dict:
    return {
        "backend": backend,
        "native_library_sha256": library_sha256,
        "move": result.move.notation,
        "score": result.score,
        "depth": result.depth,
        "nodes": result.nodes,
        "pv": [move.notation for move in result.pv],
        "tablebase_hits": result.tablebase_hits,
    }


def generate_game(
    schedule: Mapping[str, object],
    *,
    engine: Engine,
    native_search: NativeSearch,
    library: Path,
    library_sha256: str,
    generation_depth: int,
    max_game_plies: int,
    tablebase_bindings: Sequence[dict],
) -> dict:
    rng = random.Random(int(schedule["seed"]))
    state = initial_state()
    history: Counter = Counter({state.position_key: 1})
    moves: list[dict] = []
    final_status = terminal_status(
        state,
        repetition_count=history[state.position_key],
        rules=DEFAULT_RULES,
    )
    for ply in range(1, max_game_plies + 1):
        if interactive_session_active_for_batch():
            raise InteractiveSessionActive(
                "PAUSED_FOR_INTERACTIVE_PLAY before generated game ply"
            )
        final_status = terminal_status(
            state,
            repetition_count=history[state.position_key],
            rules=DEFAULT_RULES,
        )
        if final_status.terminal:
            break
        legal = legal_moves(state)
        random_opening = ply <= int(schedule["opening_plies"])
        explore = (
            not random_opening
            and len(legal) > 1
            and rng.random() < float(schedule["exploration_rate"])
        )
        metadata = None
        if random_opening or explore:
            move = rng.choice(legal)
            actor = "human"
        elif len(legal) == 1:
            move = legal[0]
            actor = "engine"
            metadata = {
                "backend": "forced",
                "native_library_sha256": library_sha256,
            }
        else:
            native_search.clear()
            result = engine.search(
                state,
                SearchLimits(depth=generation_depth),
                history=history,
            )
            move = result.move
            actor = "engine"
            metadata = search_payload(
                result,
                backend=engine.last_search_backend,
                library_sha256=library_sha256,
            )
        moves.append(
            {
                "ply": ply,
                "player": player_name(state.turn),
                "notation": move.notation,
                "actor": actor,
                "engine": metadata,
            }
        )
        state = apply_move(state, move, validate=False)
        history[state.position_key] += 1
    final_status = terminal_status(
        state,
        repetition_count=history[state.position_key],
        rules=DEFAULT_RULES,
    )
    result = game_result_payload(final_status, truncated=not final_status.terminal)
    return {
        "format": "thai-makhos-game-v1",
        "start_position": format_position(initial_state()),
        "start_reversible_plies": 0,
        "moves": moves,
        "final_position": format_position(state),
        "reversible_plies": state.reversible_plies,
        "engine": {
            "game_mode": "accepted-selfplay-nnue-label-source",
            "corpus_role": "quiet-leaf-scalar-label-acquisition",
            "library": str(library),
            "library_sha256": library_sha256,
            "rules_profile": "project",
            "generation_depth": generation_depth,
            "random_opening_plies": schedule["opening_plies"],
            "exploration_rate": schedule["exploration_rate"],
            "seed": schedule["seed"],
            "tablebases": list(tablebase_bindings),
            "game_result": result,
        },
    }


def validate_existing_game_payload(
    payload: dict,
    *,
    schedule: Mapping[str, object],
    library_sha256: str,
    generation_depth: int,
    tablebase_bindings: Sequence[dict],
) -> None:
    engine = payload.get("engine", {})
    expected = {
        "format": "thai-makhos-game-v1",
        "game_mode": "accepted-selfplay-nnue-label-source",
        "corpus_role": "quiet-leaf-scalar-label-acquisition",
        "library_sha256": library_sha256,
        "rules_profile": "project",
        "generation_depth": generation_depth,
        "random_opening_plies": schedule["opening_plies"],
        "exploration_rate": schedule["exploration_rate"],
        "seed": schedule["seed"],
        "tablebases": list(tablebase_bindings),
    }
    actual = {"format": payload.get("format"), **engine}
    for key, value in expected.items():
        if actual.get(key) != value:
            raise RuntimeError(f"existing source game has stale {key}")
    for move in payload.get("moves", []):
        metadata = move.get("engine")
        if move.get("actor") == "engine" and (
            not isinstance(metadata, dict)
            or metadata.get("native_library_sha256") != library_sha256
        ):
            raise RuntimeError("existing source game has stale engine-move provenance")


def validate_existing_game(
    path: Path,
    *,
    schedule: Mapping[str, object],
    library_sha256: str,
    generation_depth: int,
    tablebase_bindings: Sequence[dict],
) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_existing_game_payload(
        payload,
        schedule=schedule,
        library_sha256=library_sha256,
        generation_depth=generation_depth,
        tablebase_bindings=tablebase_bindings,
    )
    replay_game(load_game_record(path), rules=DEFAULT_RULES)


def evenly_spaced(rows: Sequence[dict], count: int) -> list[dict]:
    if count <= 0 or not rows:
        return []
    if len(rows) <= count:
        return list(rows)
    if count == 1:
        return [rows[len(rows) // 2]]
    indexes = [round(offset * (len(rows) - 1) / (count - 1)) for offset in range(count)]
    return [rows[index] for index in indexes]


def select_quiet_candidates(replayed, *, max_positions: int) -> list[dict]:
    candidates: list[dict] = []
    for item in replayed.plies:
        moves = legal_moves(item.state)
        if not moves or moves[0].is_capture:
            continue
        pieces = count_pieces(item.state)
        band = phase_band(pieces)
        if band is None:
            continue
        candidates.append(
            {
                "item": item,
                "canonical_position_id": canonical_position_id(item.state),
                "phase_band": band,
                "piece_count": pieces,
                "king_count": count_kings(item.state),
                "legal_move_count": len(moves),
            }
        )

    selected: list[dict] = []
    selected_plies: set[int] = set()
    base_quota, remainder = divmod(max_positions, len(PHASE_BANDS))
    for band_index, band in enumerate(PHASE_BANDS):
        quota = base_quota + int(band_index < remainder)
        rows = [row for row in candidates if row["phase_band"] == band]
        with_kings = [row for row in rows if row["king_count"] > 0]
        king_quota = min(len(with_kings), math.ceil(quota / 2))
        chosen = evenly_spaced(with_kings, king_quota)
        chosen_ids = {row["item"].ply for row in chosen}
        chosen += evenly_spaced(
            [row for row in rows if row["item"].ply not in chosen_ids],
            quota - len(chosen),
        )
        for row in chosen:
            if row["item"].ply not in selected_plies:
                selected.append(row)
                selected_plies.add(row["item"].ply)

    if len(selected) < max_positions:
        remaining_rows = [
            row for row in candidates if row["item"].ply not in selected_plies
        ]
        remaining_rows.sort(
            key=lambda row: hashlib.sha256(
                (
                    f"{replayed.record.game_id}|{row['item'].ply}|"
                    f"{row['canonical_position_id']}"
                ).encode("ascii")
            ).hexdigest()
        )
        selected.extend(remaining_rows[: max_positions - len(selected)])
    return sorted(selected[:max_positions], key=lambda row: row["item"].ply)


def resolve_position_owners(
    occurrences: Mapping[str, Sequence[tuple[str, str, dict]]],
) -> tuple[set[str], dict[str, tuple[str, int]], int]:
    """Drop cross-split symmetry duplicates and choose one in-split owner."""

    cross_split_ids: set[str] = set()
    owner: dict[str, tuple[str, int]] = {}
    within_split_duplicates = 0
    for position_id, rows in occurrences.items():
        splits = {split for split, _game_id, _row in rows}
        if len(splits) > 1:
            cross_split_ids.add(position_id)
            continue
        selected = min(rows, key=lambda row: (row[1], row[2]["item"].ply))
        owner[position_id] = (selected[1], selected[2]["item"].ply)
        within_split_duplicates += len(rows) - 1
    return cross_split_ids, owner, within_split_duplicates


def deduplicate_source_game_rows(rows: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """Keep one deterministic file for each content-stable game trajectory."""

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["game_id"], []).append(row)
    unique: list[dict] = []
    duplicate_groups: list[dict] = []
    for game_id, group in sorted(groups.items()):
        ordered = sorted(group, key=lambda row: row["path"])
        unique.append(ordered[0])
        if len(ordered) > 1:
            duplicate_groups.append(
                {
                    "game_id": game_id,
                    "kept_path": ordered[0]["path"],
                    "kept_sha256": ordered[0]["sha256"],
                    "dropped": [
                        {"path": row["path"], "sha256": row["sha256"]}
                        for row in ordered[1:]
                    ],
                }
            )
    return unique, duplicate_groups


def selection_binding_sha256(game: Mapping[str, object]) -> str:
    return canonical_json_sha256(
        {
            "game_id": game["game_id"],
            "game_sha256": game["sha256"],
            "selected": game["selected"],
        }
    )


def validate_selection_manifest(manifest: dict) -> None:
    game_ids = [game["game_id"] for game in manifest["games"]]
    if len(set(game_ids)) != len(game_ids):
        raise RuntimeError("selection manifest contains duplicate game ids")
    for game in manifest["games"]:
        expected = selection_binding_sha256(game)
        if game.get("selection_sha256") != expected:
            raise RuntimeError(f"selection binding differs: {game['game_id']}")


def build_selection_manifest(
    game_paths: Sequence[Path],
    *,
    max_positions_per_game: int,
    checkpoint: Callable[[str], None] | None = None,
) -> tuple[dict, dict[str, list[int]]]:
    games: list[dict] = []
    occurrences: dict[str, list[tuple[str, str, dict]]] = {}
    source_rows: list[dict] = []
    for path in game_paths:
        if checkpoint is not None:
            checkpoint(f"selection source replay {path.name}")
        replayed = replay_game(load_game_record(path), rules=DEFAULT_RULES)
        source_rows.append(
            {
                "game_id": replayed.record.game_id,
                "path": str(path.resolve()),
                "sha256": sha256(path),
                "replayed": replayed,
            }
        )
    unique_source_rows, duplicate_source_groups = deduplicate_source_game_rows(
        source_rows
    )
    for source in unique_source_rows:
        if checkpoint is not None:
            checkpoint(f"selection candidate scan {source['game_id']}")
        replayed = source["replayed"]
        game_id = source["game_id"]
        split = game_split(game_id)
        candidates = select_quiet_candidates(
            replayed,
            max_positions=max_positions_per_game,
        )
        game = {
            "game_id": game_id,
            "split": split,
            "path": source["path"],
            "sha256": source["sha256"],
            "provisional_positions": len(candidates),
            "candidates": candidates,
        }
        games.append(game)
        for row in candidates:
            occurrences.setdefault(row["canonical_position_id"], []).append(
                (split, game_id, row)
            )

    cross_split_ids, owner, within_split_duplicates = resolve_position_owners(
        occurrences
    )

    selected_by_game: dict[str, list[int]] = {}
    manifest_games: list[dict] = []
    for game in sorted(games, key=lambda row: row["game_id"]):
        if checkpoint is not None:
            checkpoint(f"selection ownership {game['game_id']}")
        selected_rows = [
            row
            for row in game["candidates"]
            if row["canonical_position_id"] not in cross_split_ids
            and owner.get(row["canonical_position_id"])
            == (game["game_id"], row["item"].ply)
        ]
        selected_by_game[game["game_id"]] = [row["item"].ply for row in selected_rows]
        manifest_game = {
                "game_id": game["game_id"],
                "split": game["split"],
                "path": game["path"],
                "sha256": game["sha256"],
                "provisional_positions": game["provisional_positions"],
                "selected_positions": len(selected_rows),
                "selected": [
                    {
                        "ply": row["item"].ply,
                        "canonical_position_id": row["canonical_position_id"],
                        "phase_band": row["phase_band"],
                        "piece_count": row["piece_count"],
                        "king_count": row["king_count"],
                        "legal_move_count": row["legal_move_count"],
                    }
                    for row in selected_rows
                ],
            }
        manifest_game["selection_sha256"] = selection_binding_sha256(manifest_game)
        manifest_games.append(manifest_game)
    selected_rows = [row for game in manifest_games for row in game["selected"]]
    manifest = {
        "format": FORMAT,
        "kind": "selection-manifest",
        "split_rule": "sha256(game_id) modulo 10: 0-7 train, 8 validation, 9 test",
        "split_before_sampling": True,
        "position_identity": "color-rotation canonical position plus reversible clock",
        "generated_source_game_files": len(game_paths),
        "unique_source_game_trajectories": len(manifest_games),
        "duplicate_source_game_files_dropped": sum(
            len(group["dropped"]) for group in duplicate_source_groups
        ),
        "duplicate_source_game_groups": duplicate_source_groups,
        "cross_split_symmetry_duplicates_dropped": len(cross_split_ids),
        "within_split_duplicates_dropped": within_split_duplicates,
        "games_by_split": dict(sorted(Counter(
            game["split"] for game in manifest_games
        ).items())),
        "selected_by_split": dict(sorted(Counter(
            game["split"]
            for game in manifest_games
            for _row in game["selected"]
        ).items())),
        "selected_phase_bands": dict(sorted(Counter(
            row["phase_band"] for row in selected_rows
        ).items())),
        "selected_mixed_king_positions": sum(
            row["king_count"] > 0 for row in selected_rows
        ),
        "games": manifest_games,
    }
    validate_selection_manifest(manifest)
    return manifest, selected_by_game


def history_digest(history: Mapping[tuple[tuple[int, ...], int], int]) -> str:
    rows = [
        {
            "board": list(board),
            "turn": turn,
            "count": count,
        }
        for (board, turn), count in history.items()
        if count > 0
    ]
    rows.sort(key=lambda row: (row["board"], row["turn"], row["count"]))
    return canonical_json_sha256(rows)


def label_gate(searches: Sequence[dict], *, maximum_delta: int = 50) -> tuple[bool, str]:
    if len(searches) < 2:
        return False, "fewer_than_two_budgets"
    if any(int(search["depth"]) < 1 for search in searches[-2:]):
        return False, "incomplete_search"
    if any(abs(int(search["score"])) >= 999000 for search in searches[-2:]):
        return False, "mate_like_score"
    delta = abs(int(searches[-1]["score"]) - int(searches[-2]["score"]))
    if delta > maximum_delta:
        return False, "last_two_score_delta"
    return True, "accepted"


def exact_wdl_payload(state: State, tablebases: Mapping[int, RankedTablebase]) -> dict | None:
    tablebase = tablebases.get(count_pieces(state))
    if tablebase is None:
        return None
    probe = tablebase.probe(state)
    return {
        "outcome": OUTCOME_NAME[probe.outcome],
        "perspective": "side_to_move",
        "piece_count": tablebase.piece_count,
        "tablebase_path": str(tablebase.path),
        "tablebase_expected_fnv1a64": f"{tablebase.expected_checksum:016x}",
    }


def analyze_game(
    game_path: Path,
    selected_plies: set[int],
    *,
    split: str,
    selection_sha256: str,
    searcher: NativeSearch,
    library: Path,
    library_sha256: str,
    budgets_ms: Sequence[int],
    hash_mb: int,
    tablebases: Mapping[int, RankedTablebase],
) -> dict:
    replayed = replay_game(load_game_record(game_path), rules=DEFAULT_RULES)
    selected = [item for item in replayed.plies if item.ply in selected_plies]
    if len(selected) != len(selected_plies):
        raise RuntimeError(f"selected ply missing while replaying {game_path}")
    game_result = replayed.record.engine.get("game_result", {})
    game_outcome = game_result.get("outcome")
    if game_result.get("truncated") and game_outcome is not None:
        raise RuntimeError("truncated game must not have an outcome label")

    positions: list[dict] = []
    for item in selected:
        if interactive_session_active_for_batch():
            raise InteractiveSessionActive(
                "PAUSED_FOR_INTERACTIVE_PLAY before quiet-leaf position"
            )
        moves = legal_moves(item.state)
        if not moves or moves[0].is_capture:
            raise RuntimeError("selection manifest contains a non-quiet position")
        searcher.clear()
        searches: list[dict] = []
        for budget_ms in budgets_ms:
            started = time.perf_counter()
            result = searcher.search(
                item.state,
                depth=TEACHER_MAX_DEPTH,
                time_ms=budget_ms,
                no_progress_plies=DEFAULT_RULES.no_progress_plies,
                repetition_limit=DEFAULT_RULES.repetition_limit,
                history=item.history,
            )
            searches.append(
                {
                    "budget_ms": budget_ms,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "move": result.move.notation,
                    "score": result.score,
                    "depth": result.depth,
                    "nodes": result.nodes,
                    "pv": [move.notation for move in result.pv],
                    "native_library_sha256": library_sha256,
                }
            )
        eligible, gate_reason = label_gate(searches)
        positions.append(
            {
                "ply": item.ply,
                "split": split,
                "position": format_position(item.state),
                "reversible_plies": item.state.reversible_plies,
                "turn": player_name(item.state.turn),
                "canonical_position_id": canonical_position_id(item.state),
                "piece_count": count_pieces(item.state),
                "phase_band": phase_band(count_pieces(item.state)),
                "king_count": count_kings(item.state),
                "legal_moves": [move.notation for move in moves],
                "history": {
                    "entries": len(item.history),
                    "current_repetition_count": int(item.history[item.state.position_key]),
                    "sha256": history_digest(item.history),
                },
                "searches": searches,
                "last_two_score_delta": abs(
                    int(searches[-1]["score"]) - int(searches[-2]["score"])
                ),
                "eligible": eligible,
                "gate_reason": gate_reason,
                "teacher_score": int(searches[-1]["score"]) if eligible else None,
                "game_outcome": game_outcome,
                "game_outcome_from_side_to_move": outcome_from_turn(
                    game_outcome,
                    item.state.turn,
                ),
                "game_truncated": bool(game_result.get("truncated")),
                "exact_wdl": exact_wdl_payload(item.state, tablebases),
            }
        )
    return {
        "format": FORMAT,
        "kind": "game-analysis",
        "game_id": replayed.record.game_id,
        "game_path": str(game_path.resolve()),
        "game_sha256": sha256(game_path),
        "split": split,
        "selection_sha256": selection_sha256,
        "accepted_library": str(library),
        "accepted_library_sha256": library_sha256,
        "threads": 1,
        "persistent_search": True,
        "clear_once_per_position_before_ascending_budgets": True,
        "hash_mb": hash_mb,
        "budgets_ms": list(budgets_ms),
        "teacher_max_depth": TEACHER_MAX_DEPTH,
        "rules_profile": "project",
        "positions": positions,
    }


def validate_existing_analysis(
    payload: dict,
    *,
    game: dict,
    library_sha256: str,
    budgets_ms: Sequence[int],
) -> None:
    expected = {
        "format": FORMAT,
        "kind": "game-analysis",
        "game_id": game["game_id"],
        "game_sha256": game["sha256"],
        "split": game["split"],
        "selection_sha256": game["selection_sha256"],
        "accepted_library_sha256": library_sha256,
        "budgets_ms": list(budgets_ms),
        "teacher_max_depth": TEACHER_MAX_DEPTH,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(f"existing analysis has stale {key}: {game['game_id']}")


def build_corpus(
    manifest: dict,
    analysis_paths: Sequence[Path],
    *,
    config_path: Path,
    manifest_path: Path,
    corpus_path: Path,
    library_sha256: str,
    budgets_ms: Sequence[int],
    coverage_target: int | None = None,
) -> tuple[list[dict], dict]:
    games = {game["game_id"]: game for game in manifest["games"]}
    samples: list[dict] = []
    teacher_hashes: set[str] = set()
    for analysis_path in analysis_paths:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        game = games.get(analysis.get("game_id"))
        if game is None:
            raise RuntimeError(f"analysis references an unselected game: {analysis_path}")
        validate_existing_analysis(
            analysis,
            game=game,
            library_sha256=library_sha256,
            budgets_ms=budgets_ms,
        )
        for position in analysis["positions"]:
            for search in position["searches"]:
                teacher_hashes.add(search["native_library_sha256"])
            if not position["eligible"]:
                continue
            final_search = position["searches"][-1]
            samples.append(
                {
                    "kind": "sample",
                    "sample_id": position["canonical_position_id"],
                    "split": position["split"],
                    "position": position["position"],
                    "reversible_plies": position["reversible_plies"],
                    "turn": position["turn"],
                    "piece_count": position["piece_count"],
                    "phase_band": position["phase_band"],
                    "king_count": position["king_count"],
                    "legal_move_count": len(position["legal_moves"]),
                    "teacher_score": position["teacher_score"],
                    "teacher_score_perspective": "side_to_move",
                    "teacher": {
                        "budget_ms": final_search["budget_ms"],
                        "depth": final_search["depth"],
                        "nodes": final_search["nodes"],
                        "move": final_search["move"],
                        "pv": final_search["pv"],
                        "last_two_score_delta": position["last_two_score_delta"],
                        "native_library_sha256": library_sha256,
                    },
                    "search_trace": position["searches"],
                    "history": position["history"],
                    "game_outcome": position["game_outcome"],
                    "game_outcome_from_side_to_move": position[
                        "game_outcome_from_side_to_move"
                    ],
                    "game_truncated": position["game_truncated"],
                    "exact_wdl": position["exact_wdl"],
                    "source": {
                        "game_id": analysis["game_id"],
                        "game_sha256": analysis["game_sha256"],
                        "ply": position["ply"],
                        "analysis_sha256": sha256(analysis_path),
                    },
                }
            )
    samples.sort(key=lambda row: (row["split"], row["source"]["game_id"], row["source"]["ply"]))
    identifiers = [row["sample_id"] for row in samples]
    if len(set(identifiers)) != len(identifiers):
        raise RuntimeError("eligible corpus contains duplicate canonical positions")

    eligible_before_coverage_sampling = len(samples)
    coverage_details = None
    if coverage_target is not None:
        samples, coverage_details = coverage_select_samples(samples, coverage_target)

    metadata = {
        "kind": "metadata",
        "format": CORPUS_FORMAT,
        "version": 1,
        "sample_count": len(samples),
        "eligible_before_coverage_sampling": eligible_before_coverage_sampling,
        "label_semantics": {
            "teacher_score": "accepted classical search score from side to move",
            "game_outcome": "actual terminal result; null when truncated",
            "exact_wdl": "independent ranked tablebase outcome when available",
        },
        "accepted_library_sha256": library_sha256,
        "threads": 1,
        "persistent_search": True,
        "budgets_ms": list(budgets_ms),
        "teacher_max_depth": TEACHER_MAX_DEPTH,
        "score_stability_gate_cp": 50,
        "quiet_roots_only": True,
        "ruleset_sha256": ruleset_sha256().upper(),
        "config_sha256": sha256(config_path),
        "selection_manifest_sha256": sha256(manifest_path),
        "coverage_sampling": coverage_details,
    }
    corpus_text = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False)
        for row in (metadata, *samples)
    ) + "\n"
    atomic_write_text(corpus_path, corpus_text)
    return samples, {
        "teacher_hashes": sorted(teacher_hashes),
        "metadata": metadata,
        "eligible_before_coverage_sampling": eligible_before_coverage_sampling,
        "coverage_sampling": coverage_details,
    }


def coverage_select_samples(
    samples: Sequence[dict],
    target: int,
) -> tuple[list[dict], dict]:
    """Choose a deterministic coverage-qualified pilot subset.

    Analyses retain every eligible label. This selection only controls the
    published corpus so a large easy phase cannot hide missing king or phase
    coverage.
    """

    if target < 1:
        raise ValueError("coverage target must be positive")
    if len(samples) < target:
        raise RuntimeError(
            f"coverage target needs {target} eligible labels; only {len(samples)} exist"
        )

    by_id = {row["sample_id"]: row for row in samples}
    if len(by_id) != len(samples):
        raise RuntimeError("coverage sampler received duplicate sample ids")
    selected_ids: set[str] = set()
    turn_counts: Counter[str] = Counter()
    max_per_turn = math.floor(target * 0.55)

    def stable_key(row: dict, salt: str) -> tuple[str, str]:
        digest = hashlib.sha256(
            f"{salt}|{row['sample_id']}".encode("ascii")
        ).hexdigest()
        return digest, row["sample_id"]

    def take(rows: Sequence[dict], count: int, salt: str) -> None:
        if count <= 0:
            return
        available = {
            turn: sorted(
                (
                    row
                    for row in rows
                    if row["sample_id"] not in selected_ids and row["turn"] == turn
                ),
                key=lambda row: stable_key(row, salt),
            )
            for turn in ("black", "red")
        }
        offsets = {"black": 0, "red": 0}
        for _index in range(count):
            turns = sorted(
                ("black", "red"),
                key=lambda turn: (turn_counts[turn], turn),
            )
            chosen = None
            for turn in turns:
                if turn_counts[turn] >= max_per_turn:
                    continue
                offset = offsets[turn]
                if offset < len(available[turn]):
                    chosen = available[turn][offset]
                    offsets[turn] += 1
                    break
            if chosen is None:
                raise RuntimeError(f"coverage quota cannot be satisfied: {salt}")
            selected_ids.add(chosen["sample_id"])
            turn_counts[chosen["turn"]] += 1

    king_minimum = math.ceil(target * 0.30)
    phase_minimum = math.ceil(target * 0.20)
    take(
        [row for row in samples if row["king_count"] > 0],
        king_minimum,
        "king-minimum",
    )
    for band in PHASE_BANDS:
        present = sum(
            by_id[sample_id]["phase_band"] == band for sample_id in selected_ids
        )
        take(
            [row for row in samples if row["phase_band"] == band],
            phase_minimum - present,
            f"phase-minimum-{band}",
        )
    take(samples, target - len(selected_ids), "coverage-fill")

    selected = [row for row in samples if row["sample_id"] in selected_ids]
    selected.sort(
        key=lambda row: (row["split"], row["source"]["game_id"], row["source"]["ply"])
    )
    final_turns = Counter(row["turn"] for row in selected)
    final_phases = Counter(row["phase_band"] for row in selected)
    final_kings = sum(row["king_count"] > 0 for row in selected)
    if len(selected) != target:
        raise RuntimeError("coverage sampler did not reach its exact target")
    if any(percent(final_turns[turn], target) < 45.0 for turn in ("black", "red")):
        raise RuntimeError("coverage sampler could not meet turn balance")
    if any(final_phases[band] < phase_minimum for band in PHASE_BANDS):
        raise RuntimeError("coverage sampler could not meet phase coverage")
    if final_kings < king_minimum:
        raise RuntimeError("coverage sampler could not meet king coverage")
    return selected, {
        "algorithm": "deterministic-minimum-coverage-v1",
        "eligible_before_sampling": len(samples),
        "target": target,
        "king_minimum": king_minimum,
        "phase_minimum_each": phase_minimum,
        "turn_range_percent": [45, 55],
    }


def percent(part: int, total: int) -> float:
    return 0.0 if total == 0 else part * 100.0 / total


def build_preflight_summary(manifest: dict, analysis_paths: Sequence[Path]) -> dict:
    positions: list[dict] = []
    analysis_hashes: list[dict] = []
    for path in sorted(analysis_paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        positions.extend(payload["positions"])
        analysis_hashes.append(
            {
                "game_id": payload["game_id"],
                "path": str(path.resolve()),
                "sha256": sha256(path),
            }
        )
    eligible = [row for row in positions if row["eligible"]]
    selected_pool = sum(game["selected_positions"] for game in manifest["games"])
    observed_retention = percent(len(eligible), len(positions))
    projected = round(selected_pool * observed_retention / 100.0)
    pool_rows = [row for game in manifest["games"] for row in game["selected"]]
    phase_rows = {}
    projected_by_phase: dict[str, int] = {}
    projected_kings = 0
    for band in PHASE_BANDS:
        selected = [row for row in positions if row["phase_band"] == band]
        retained = [row for row in selected if row["eligible"]]
        projected_phase = 0
        strata = {}
        for with_kings in (False, True):
            stratum = [
                row for row in selected if (row["king_count"] > 0) == with_kings
            ]
            stratum_eligible = [row for row in stratum if row["eligible"]]
            pool = [
                row
                for row in pool_rows
                if row["phase_band"] == band
                and (row["king_count"] > 0) == with_kings
            ]
            retention = percent(len(stratum_eligible), len(stratum))
            stratum_projection = round(len(pool) * retention / 100.0)
            projected_phase += stratum_projection
            if with_kings:
                projected_kings += stratum_projection
            strata["with_kings" if with_kings else "without_kings"] = {
                "selected": len(stratum),
                "eligible": len(stratum_eligible),
                "retention_percent": retention,
                "pool": len(pool),
                "projected_eligible": stratum_projection,
            }
        projected_by_phase[band] = projected_phase
        phase_rows[band] = {
            "selected": len(selected),
            "eligible": len(retained),
            "retention_percent": percent(len(retained), len(selected)),
            "projected_eligible": projected_phase,
            "strata": strata,
        }
    stratified_projection = sum(projected_by_phase.values())
    safety_factor = 1.25
    safety_gates = {
        "total_at_least_125_percent_of_target": (
            stratified_projection >= math.ceil(DEFAULT_PILOT_TARGET * safety_factor)
        ),
        "kings_at_least_125_percent_of_minimum": (
            projected_kings
            >= math.ceil(DEFAULT_PILOT_TARGET * 0.30 * safety_factor)
        ),
        "each_phase_at_least_125_percent_of_minimum": all(
            projected_by_phase[band]
            >= math.ceil(DEFAULT_PILOT_TARGET * 0.20 * safety_factor)
            for band in PHASE_BANDS
        ),
    }
    if positions and stratified_projection < DEFAULT_PILOT_TARGET:
        verdict = "CAPACITY_FAIL"
    elif positions and all(safety_gates.values()):
        verdict = "READY_FOR_FULL_LABELING"
    else:
        verdict = "COVERAGE_CAPACITY_RISK" if positions else "INCOMPLETE"
    return {
        "format": FORMAT,
        "kind": "label-yield-preflight",
        "verdict": verdict,
        "games_analyzed": len(analysis_paths),
        "positions_analyzed": len(positions),
        "eligible": len(eligible),
        "observed_retention_percent": observed_retention,
        "selected_pool": selected_pool,
        "required_target": DEFAULT_PILOT_TARGET,
        "required_retention_percent": percent(DEFAULT_PILOT_TARGET, selected_pool),
        "projected_eligible": projected,
        "stratified_projected_eligible": stratified_projection,
        "projected_eligible_with_kings": projected_kings,
        "projected_eligible_by_phase": projected_by_phase,
        "capacity_safety_factor": safety_factor,
        "capacity_safety_gates": safety_gates,
        "gate_reasons": dict(sorted(Counter(row["gate_reason"] for row in positions).items())),
        "phase_bands": phase_rows,
        "turns": dict(sorted(Counter(row["turn"] for row in eligible).items())),
        "eligible_with_kings": sum(row["king_count"] > 0 for row in eligible),
        "analyses": analysis_hashes,
    }


def build_summary(
    config: dict,
    manifest: dict,
    samples: Sequence[dict],
    corpus_details: dict,
    *,
    config_path: Path,
    manifest_path: Path,
    corpus_path: Path,
    game_paths: Sequence[Path],
    analysis_paths: Sequence[Path],
    resume_corpus_reproduced: bool,
) -> dict:
    sample_count = len(samples)
    turn_counts = Counter(row["turn"] for row in samples)
    phase_counts = Counter(row["phase_band"] for row in samples)
    split_counts = Counter(row["split"] for row in samples)
    mixed_kings = sum(row["king_count"] > 0 for row in samples)
    exact_labels = sum(row["exact_wdl"] is not None for row in samples)
    truncated_draws = sum(
        row["game_truncated"] and row["game_outcome"] == "draw"
        for row in samples
    )
    identities_by_split: dict[str, set[str]] = {}
    for row in samples:
        identities_by_split.setdefault(row["split"], set()).add(row["sample_id"])
    leakage = 0
    split_names = sorted(identities_by_split)
    for index, first in enumerate(split_names):
        for second in split_names[index + 1:]:
            leakage += len(identities_by_split[first] & identities_by_split[second])

    gates = {
        "at_least_256_source_games_and_all_configured_games_complete": (
            config["games"] >= 256 and len(game_paths) == config["games"]
        ),
        "at_least_8000_unique_quiet_positions": sample_count >= DEFAULT_PILOT_TARGET,
        "zero_position_or_symmetry_leakage": leakage == 0,
        "all_teacher_hashes_match_accepted": corpus_details["teacher_hashes"]
        == [config["accepted_library_sha256"]],
        "black_turn_45_to_55_percent": 45.0 <= percent(turn_counts["black"], sample_count) <= 55.0,
        "red_turn_45_to_55_percent": 45.0 <= percent(turn_counts["red"], sample_count) <= 55.0,
        "each_phase_band_at_least_20_percent": all(
            percent(phase_counts[band], sample_count) >= 20.0 for band in PHASE_BANDS
        ),
        "at_least_30_percent_with_kings": percent(mixed_kings, sample_count) >= 30.0,
        "no_truncated_game_labeled_draw": truncated_draws == 0,
        "all_games_analyzed": len(analysis_paths) == len(manifest["games"]),
        "resume_reproduced_corpus_byte_for_byte": resume_corpus_reproduced,
    }
    return {
        "format": FORMAT,
        "kind": "pilot-summary",
        "verdict": "PASS" if all(gates.values()) else "INCOMPLETE",
        "gates": gates,
        "accepted_library_sha256": config["accepted_library_sha256"],
        "ruleset_sha256": ruleset_sha256().upper(),
        "artifacts": {
            "config": str(config_path.resolve()),
            "config_sha256": sha256(config_path),
            "selection_manifest": str(manifest_path.resolve()),
            "selection_manifest_sha256": sha256(manifest_path),
            "corpus": str(corpus_path.resolve()),
            "corpus_sha256": sha256(corpus_path),
        },
        "games": {
            "count": len(game_paths),
            "unique_trajectories": manifest["unique_source_game_trajectories"],
            "duplicate_source_files_dropped": manifest[
                "duplicate_source_game_files_dropped"
            ],
            "by_split": manifest["games_by_split"],
            "truncated": sum(
                json.loads(path.read_text(encoding="utf-8"))["engine"]["game_result"]["truncated"]
                for path in game_paths
            ),
        },
        "selection": {
            "provisional": sum(game["provisional_positions"] for game in manifest["games"]),
            "selected": sum(game["selected_positions"] for game in manifest["games"]),
            "cross_split_symmetry_duplicates_dropped": manifest[
                "cross_split_symmetry_duplicates_dropped"
            ],
            "within_split_duplicates_dropped": manifest[
                "within_split_duplicates_dropped"
            ],
        },
        "samples": {
            "count": sample_count,
            "eligible_before_coverage_sampling": corpus_details[
                "eligible_before_coverage_sampling"
            ],
            "coverage_sampling": corpus_details["coverage_sampling"],
            "by_split": dict(sorted(split_counts.items())),
            "turns": dict(sorted(turn_counts.items())),
            "turn_percent": {
                key: percent(turn_counts[key], sample_count) for key in ("black", "red")
            },
            "phase_bands": dict(sorted(phase_counts.items())),
            "phase_percent": {
                band: percent(phase_counts[band], sample_count) for band in PHASE_BANDS
            },
            "mixed_king_positions": mixed_kings,
            "mixed_king_percent": percent(mixed_kings, sample_count),
            "exact_wdl_labels": exact_labels,
            "game_outcomes": dict(sorted(Counter(
                str(row["game_outcome"]) for row in samples
            ).items())),
            "truncated_labeled_draw": truncated_draws,
        },
        "teacher_hashes": corpus_details["teacher_hashes"],
        "symmetry_leakage_count": leakage,
        "resume_reproduction": {
            "locked_config_revalidated": True,
            "locked_manifest_revalidated": True,
            "corpus_byte_identical_to_previous_completed_run": resume_corpus_reproduced,
        },
        "next_gate": (
            "scale to at least 100000 broad-phase labels with a fresh unopened test split"
            if all(gates.values())
            else "finish or repair the 256-game pilot gates before training"
        ),
    }


def load_tablebase_manifest(path: Path) -> dict[int, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != "makhos-tablebase-provenance":
        raise ValueError("unexpected tablebase provenance format")
    if payload.get("ruleset", {}).get("canonical_json_sha256", "").upper() != ruleset_sha256().upper():
        raise RuntimeError("tablebase manifest ruleset differs from current rules")
    return {int(item["piece_count"]): item for item in payload["artifacts"]}


def open_ranked_tablebases(
    paths: Sequence[Path],
    *,
    stack: ExitStack,
    provenance_path: Path,
) -> tuple[dict[int, RankedTablebase], list[dict]]:
    provenance = load_tablebase_manifest(provenance_path)
    tablebases: dict[int, RankedTablebase] = {}
    bindings: list[dict] = []
    for path in paths:
        tablebase = stack.enter_context(RankedTablebase(path))
        expected = provenance[tablebase.piece_count]
        if path.stat().st_size != int(expected["file_bytes"]):
            raise RuntimeError("tablebase size differs from provenance manifest")
        expected_representation = "compact" if tablebase._compact else "full"
        if expected["representation"] != expected_representation:
            raise RuntimeError("tablebase representation differs from provenance manifest")
        if tablebase.expected_checksum != int(expected["fnv1a64"], 16):
            raise RuntimeError("tablebase header checksum differs from provenance manifest")
        tablebases[tablebase.piece_count] = tablebase
        bindings.append(
            {
                "piece_count": tablebase.piece_count,
                "path": str(path.resolve()),
                "file_bytes": path.stat().st_size,
                "expected_sha256": expected["sha256"].upper(),
                "expected_fnv1a64": expected["fnv1a64"],
                "manifest_rules_size_header_binding_verified": True,
                "full_file_sha256_rehashed_this_run": False,
            }
        )
    return tablebases, sorted(bindings, key=lambda row: row["piece_count"])


def progress_payload(stage: str, **values: object) -> None:
    print(json.dumps({"stage": stage, **values}, sort_keys=True), flush=True)


def interactive_session_active_for_batch() -> bool:
    """Patchable checkpoint used by long-running acquisition loops."""

    from makhos.workload_isolation import interactive_session_active

    return interactive_session_active()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--accepted-library",
        type=Path,
        default=ROOT / "build" / "makhos_native_accepted.dll",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=ROOT / "build" / "nnue_quiet_leaf_pilot_v1",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "corpora" / "nnue_quiet_leaf_pilot_v1.jsonl",
    )
    parser.add_argument("--games", type=int, default=256)
    parser.add_argument("--seed-start", type=int, default=DEFAULT_SEED_START)
    parser.add_argument("--generation-depth", type=int, default=7)
    parser.add_argument("--max-game-plies", type=int, default=200)
    parser.add_argument("--max-positions-per-game", type=int, default=64)
    parser.add_argument("--hash-mb", type=int, default=256)
    parser.add_argument("--budgets-ms", type=parse_budgets, default=DEFAULT_BUDGETS_MS)
    parser.add_argument(
        "--tablebase",
        type=Path,
        action="append",
        default=None,
    )
    parser.add_argument(
        "--tablebase-provenance",
        type=Path,
        default=ROOT / "TABLEBASE_PROVENANCE.json",
    )
    parser.add_argument("--generation-only", action="store_true")
    parser.add_argument("--config-only", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--stop-after-game", type=int)
    parser.add_argument("--stop-after-analysis", type=int)
    parser.add_argument("--coverage-target", type=int)
    parser.add_argument("--analysis-shard-count", type=int, default=1)
    parser.add_argument("--analysis-shard-index", type=int, default=0)
    parser.add_argument("--generation-shard-count", type=int, default=1)
    parser.add_argument("--generation-shard-index", type=int, default=0)
    parser.add_argument("--selection-manifest", type=Path, default=None)
    parser.add_argument(
        "--analysis-splits",
        type=parse_analysis_splits,
        default=("train", "validation", "test"),
    )
    args = parser.parse_args()

    if args.games < 1 or args.generation_depth < 1 or args.max_game_plies < 1:
        parser.error("games, generation depth, and max game plies must be positive")
    if args.max_positions_per_game < 3:
        parser.error("max positions per game must be at least three")
    if args.hash_mb < 4:
        parser.error("Hash must be at least 4 MiB")
    if args.stop_after_game is not None and not 1 <= args.stop_after_game <= args.games:
        parser.error("stop-after-game must be within the configured game count")
    if args.stop_after_analysis is not None and args.stop_after_analysis < 1:
        parser.error("stop-after-analysis must be positive")
    if args.coverage_target is not None and args.coverage_target < 1:
        parser.error("coverage-target must be positive")
    if args.analysis_shard_count < 1:
        parser.error("analysis-shard-count must be positive")
    if not 0 <= args.analysis_shard_index < args.analysis_shard_count:
        parser.error("analysis-shard-index must be within the shard count")
    if args.generation_shard_count < 1:
        parser.error("generation-shard-count must be positive")
    if not 0 <= args.generation_shard_index < args.generation_shard_count:
        parser.error("generation-shard-index must be within the shard count")
    if args.generation_shard_count > 1 and not args.generation_only:
        parser.error("sharded generation requires --generation-only")
    if args.config_only and (
        args.generation_only or args.preflight_only or args.stop_after_analysis
    ):
        parser.error("config-only cannot be combined with generation/analysis modes")
    if args.preflight_only and set(args.analysis_splits) != {
        "train",
        "validation",
        "test",
    }:
        parser.error("preflight-only requires all analysis splits")

    library = args.accepted_library.resolve()
    library_sha256 = sha256(library)
    if library_sha256 != EXPECTED_ACCEPTED_SHA256:
        raise RuntimeError(
            "accepted library identity changed: "
            f"expected {EXPECTED_ACCEPTED_SHA256}, got {library_sha256}"
        )
    work_dir = args.work_dir.resolve()
    corpus_path = args.corpus.resolve()
    games_dir = work_dir / "games"
    analyses_dir = work_dir / "analyses"
    config_path = work_dir / "config.json"
    manifest_path = (
        args.selection_manifest.resolve()
        if args.selection_manifest is not None
        else work_dir / "selection_manifest.json"
    )
    summary_path = work_dir / "summary.json"
    preflight_path = work_dir / "preflight_summary.json"
    tablebase_paths = args.tablebase or [
        ROOT / "build" / "tb4_np80.bin",
        ROOT / "build" / "tb5_np80.compact.bin",
        ROOT / "build" / "tb6_np80.compact.bin",
    ]
    tablebase_paths = [path.resolve() for path in tablebase_paths]
    schedules = [game_schedule(index, args.seed_start) for index in range(1, args.games + 1)]

    with BatchWorkLease(ROOT) as batch_lease, ExitStack() as stack:
        tablebases, tablebase_bindings = open_ranked_tablebases(
            tablebase_paths,
            stack=stack,
            provenance_path=args.tablebase_provenance.resolve(),
        )
        config = {
            "format": FORMAT,
            "kind": "locked-config",
            "accepted_library": str(library),
            "accepted_library_sha256": library_sha256,
            "games": args.games,
            "seed_start": args.seed_start,
            "generation_depth": args.generation_depth,
            "max_game_plies": args.max_game_plies,
            "max_positions_per_game": args.max_positions_per_game,
            "budgets_ms": list(args.budgets_ms),
            "teacher_max_depth": TEACHER_MAX_DEPTH,
            "threads": 1,
            "hash_mb": args.hash_mb,
            "persistent_search": True,
            "teacher_clear_protocol": "clear once per position, then ascending warm budgets",
            "rules_profile": "project",
            "ruleset_sha256": ruleset_sha256().upper(),
            "split_rule": "80/10/10 by source game id hash before sampling",
            "quiet_gate": "no mandatory capture at root",
            "score_gate": "absolute last-two score delta at most 50 cp",
            "tablebase_provenance": str(args.tablebase_provenance.resolve()),
            "tablebase_provenance_sha256": sha256(args.tablebase_provenance.resolve()),
            "tablebases": tablebase_bindings,
            "schedules": schedules,
        }
        if args.coverage_target is not None:
            config["coverage_target"] = args.coverage_target
            config["coverage_sampling"] = "deterministic-minimum-coverage-v1"
        write_locked_json(config_path, config)
        if args.config_only:
            progress_payload(
                "config-locked",
                config=str(config_path),
                config_sha256=sha256(config_path),
            )
            return
        if args.generation_shard_count > 1:
            assigned_schedules = [
                schedule
                for schedule in schedules
                if generation_shard(
                    int(schedule["index"]), args.generation_shard_count
                )
                == args.generation_shard_index
            ]
            generation_manifest = {
                "format": FORMAT,
                "kind": "generation-execution-shard",
                "assignment": "(one-based game index - 1) modulo shard_count",
                "shard_count": args.generation_shard_count,
                "shard_index": args.generation_shard_index,
                "accepted_library_sha256": library_sha256,
                "config_sha256": sha256(config_path),
                "assigned_source_files": len(assigned_schedules),
                "assigned_schedules": assigned_schedules,
            }
            write_locked_json(
                work_dir
                / "generation_shards"
                / (
                    f"shard_{args.generation_shard_index:02d}_of_"
                    f"{args.generation_shard_count:02d}.json"
                ),
                generation_manifest,
            )

        generation_power = hash_power_for_megabytes(
            args.hash_mb,
            entry_bytes=native_tt_entry_bytes(library),
        )
        with NativeSearch(
            library,
            hash_power=generation_power,
            persistent=True,
        ) as native_search:
            engine = Engine(
                DEFAULT_RULES,
                exact_piece_limit=2,
                ranked_tablebases=tablebases.values(),
                native_search=native_search,
            )
            for schedule in schedules:
                index = int(schedule["index"])
                if (
                    generation_shard(index, args.generation_shard_count)
                    != args.generation_shard_index
                ):
                    continue
                batch_lease.checkpoint(f"source game {index}")
                game_path = games_dir / f"game_{index:03d}_seed_{schedule['seed']}.json"
                if game_path.exists():
                    validate_existing_game(
                        game_path,
                        schedule=schedule,
                        library_sha256=library_sha256,
                        generation_depth=args.generation_depth,
                        tablebase_bindings=tablebase_bindings,
                    )
                else:
                    payload = generate_game(
                        schedule,
                        engine=engine,
                        native_search=native_search,
                        library=library,
                        library_sha256=library_sha256,
                        generation_depth=args.generation_depth,
                        max_game_plies=args.max_game_plies,
                        tablebase_bindings=tablebase_bindings,
                    )
                    write_json(game_path, payload)
                    progress_payload(
                        "generated",
                        game=index,
                        plies=len(payload["moves"]),
                        result=payload["engine"]["game_result"],
                    )
                if args.stop_after_game == index:
                    progress_payload("stopped-after-game", game=index)
                    return

        if args.generation_shard_count > 1:
            assigned = sum(
                generation_shard(int(schedule["index"]), args.generation_shard_count)
                == args.generation_shard_index
                for schedule in schedules
            )
            progress_payload(
                "generation-shard-complete",
                shard=args.generation_shard_index,
                shard_count=args.generation_shard_count,
                assigned=assigned,
            )
            return

        game_paths = [
            games_dir / f"game_{schedule['index']:03d}_seed_{schedule['seed']}.json"
            for schedule in schedules
        ]
        missing_games = [path for path in game_paths if not path.exists()]
        if missing_games:
            progress_payload("generation-incomplete", missing=len(missing_games))
            return

        if manifest_path.exists():
            batch_lease.checkpoint("selection manifest load")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_selection_manifest(manifest)
            selected_by_game = {
                game["game_id"]: [row["ply"] for row in game["selected"]]
                for game in manifest["games"]
            }
        elif args.selection_manifest is not None:
            raise RuntimeError(f"custom selection manifest does not exist: {manifest_path}")
        else:
            manifest, selected_by_game = build_selection_manifest(
                game_paths,
                max_positions_per_game=args.max_positions_per_game,
                checkpoint=batch_lease.checkpoint,
            )
            write_locked_json(manifest_path, manifest)
        progress_payload(
            "selected",
            games=len(manifest["games"]),
            positions=sum(game["selected_positions"] for game in manifest["games"]),
            phase_bands=manifest["selected_phase_bands"],
            games_by_split=manifest["games_by_split"],
        )
        if args.generation_only:
            return
        if args.analysis_shard_count > 1:
            shard_manifest = {
                "format": FORMAT,
                "kind": "analysis-execution-shard",
                "assignment": "sha256(game_id) modulo shard_count",
                "shard_count": args.analysis_shard_count,
                "shard_index": args.analysis_shard_index,
                "threads_per_teacher": 1,
                "persistent_search": True,
                "hash_mb_per_teacher": args.hash_mb,
                "budgets_ms": list(args.budgets_ms),
                "accepted_library_sha256": library_sha256,
                "config_sha256": sha256(config_path),
                "selection_manifest_sha256": sha256(manifest_path),
                "analysis_splits": list(args.analysis_splits),
            }
            write_locked_json(
                work_dir
                / "execution_shards"
                / (
                    f"shard_{args.analysis_shard_index:02d}_of_"
                    f"{args.analysis_shard_count:02d}.json"
                ),
                shard_manifest,
            )
        if args.preflight_only:
            existing_analysis_paths = sorted(analyses_dir.glob("*.analysis.json"))
            if not existing_analysis_paths:
                raise RuntimeError("preflight needs at least one completed analysis")
            preflight = build_preflight_summary(manifest, existing_analysis_paths)
            write_json(preflight_path, preflight)
            progress_payload(
                "preflight",
                verdict=preflight["verdict"],
                games_analyzed=preflight["games_analyzed"],
                projected_eligible=preflight["projected_eligible"],
                summary=str(preflight_path),
            )
            return

        teacher_power = hash_power_for_megabytes(
            args.hash_mb,
            entry_bytes=native_tt_entry_bytes(library),
        )
        completed_new = 0
        with NativeSearch(
            library,
            hash_power=teacher_power,
            persistent=True,
        ) as teacher:
            for game in manifest["games"]:
                if game["split"] not in args.analysis_splits:
                    continue
                if (
                    analysis_shard(game["game_id"], args.analysis_shard_count)
                    != args.analysis_shard_index
                ):
                    continue
                batch_lease.checkpoint(f"analysis game {game['game_id']}")
                analysis_path = analyses_dir / f"{game['game_id']}.analysis.json"
                if analysis_path.exists():
                    validate_existing_analysis(
                        json.loads(analysis_path.read_text(encoding="utf-8")),
                        game=game,
                        library_sha256=library_sha256,
                        budgets_ms=args.budgets_ms,
                    )
                    continue
                report = analyze_game(
                    Path(game["path"]),
                    set(selected_by_game[game["game_id"]]),
                    split=game["split"],
                    selection_sha256=game["selection_sha256"],
                    searcher=teacher,
                    library=library,
                    library_sha256=library_sha256,
                    budgets_ms=args.budgets_ms,
                    hash_mb=args.hash_mb,
                    tablebases=tablebases,
                )
                write_json(analysis_path, report)
                completed_new += 1
                eligible = sum(row["eligible"] for row in report["positions"])
                progress_payload(
                    "analyzed",
                    game_id=game["game_id"],
                    positions=len(report["positions"]),
                    eligible=eligible,
                    completed_new=completed_new,
                )
                if (
                    args.stop_after_analysis is not None
                    and completed_new >= args.stop_after_analysis
                ):
                    existing_analysis_paths = sorted(analyses_dir.glob("*.analysis.json"))
                    write_json(
                        preflight_path,
                        build_preflight_summary(manifest, existing_analysis_paths),
                    )
                    progress_payload("stopped-after-analysis", completed_new=completed_new)
                    return

        required_games = [
            game for game in manifest["games"] if game["split"] in args.analysis_splits
        ]
        analysis_paths = [
            analyses_dir / f"{game['game_id']}.analysis.json" for game in required_games
        ]
        missing_analyses = [path for path in analysis_paths if not path.exists()]
        if missing_analyses:
            progress_payload("analysis-incomplete", missing=len(missing_analyses))
            return
        if set(args.analysis_splits) != {"train", "validation", "test"}:
            progress_payload(
                "analysis-splits-complete",
                splits=list(args.analysis_splits),
                analyses=len(analysis_paths),
            )
            return
        previous_corpus_sha256 = sha256(corpus_path) if corpus_path.exists() else None
        samples, corpus_details = build_corpus(
            manifest,
            analysis_paths,
            config_path=config_path,
            manifest_path=manifest_path,
            corpus_path=corpus_path,
            library_sha256=library_sha256,
            budgets_ms=args.budgets_ms,
            coverage_target=config.get("coverage_target"),
        )
        summary = build_summary(
            config,
            manifest,
            samples,
            corpus_details,
            config_path=config_path,
            manifest_path=manifest_path,
            corpus_path=corpus_path,
            game_paths=game_paths,
            analysis_paths=analysis_paths,
            resume_corpus_reproduced=(
                previous_corpus_sha256 is not None
                and previous_corpus_sha256 == sha256(corpus_path)
            ),
        )
        write_json(summary_path, summary)
        progress_payload(
            "complete",
            verdict=summary["verdict"],
            samples=len(samples),
            corpus_sha256=summary["artifacts"]["corpus_sha256"],
            summary=str(summary_path),
        )


if __name__ == "__main__":
    try:
        main()
    except InteractiveSessionActive as error:
        progress_payload(
            "paused-for-interactive-play",
            reason=str(error),
        )
