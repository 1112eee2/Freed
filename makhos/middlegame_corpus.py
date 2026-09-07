"""Build reproducible middlegame search-stability corpora.

The labels in this corpus are deliberately observational.  A long search move
is not treated as a proven best move; it is retained as a stability signal
alongside the played move, short-search move, root scores, and static feature
traces.  This keeps external-game evidence useful without turning one engine's
own horizon into ground truth.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .core import EMPTY, format_position, legal_moves, parse_position


MIDDLEGAME_CORPUS_FORMAT = "thai-makhos-middlegame-search-v1"
MIDDLEGAME_CORPUS_VERSION = 1
GAME_ANALYSIS_FORMAT = "thai-makhos-analysis-v1"


class MiddlegameCorpusError(ValueError):
    """Raised when an analysis report cannot be trusted as corpus evidence."""


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MiddlegameCorpusError(f"{name} must be an object")
    return value


def _int(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MiddlegameCorpusError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise MiddlegameCorpusError(f"{name} must be >= {minimum}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _position_id(position: str, reversible_plies: int) -> str:
    payload = f"{position}|{reversible_plies}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def _relative_terms(value: Any, name: str) -> dict[str, int]:
    mapping = _mapping(value, name)
    terms: dict[str, int] = {}
    for key, raw in mapping.items():
        terms[str(key)] = _int(raw, f"{name}.{key}")
    return terms


def _analysis_samples(
    report: Mapping[str, Any],
    source_path: Path,
    *,
    min_pieces: int,
    max_pieces: int,
    stable_only: bool,
) -> list[dict[str, Any]]:
    if report.get("format") != GAME_ANALYSIS_FORMAT:
        raise MiddlegameCorpusError(
            f"{source_path} is not {GAME_ANALYSIS_FORMAT!r}"
        )
    game_id = report.get("game_id")
    if not isinstance(game_id, str) or not game_id:
        raise MiddlegameCorpusError(f"{source_path}: missing game_id")
    library_sha256 = report.get("library_sha256")
    if not isinstance(library_sha256, str) or len(library_sha256) != 64:
        raise MiddlegameCorpusError(
            f"{source_path}: library_sha256 must be a 64-character hex digest"
        )
    budgets = report.get("budgets_ms")
    if not isinstance(budgets, list) or len(budgets) < 2:
        raise MiddlegameCorpusError(
            f"{source_path}: analysis must contain at least two budgets"
        )
    parsed_budgets = tuple(
        _int(value, f"{source_path}.budgets_ms[{index}]", minimum=1)
        for index, value in enumerate(budgets)
    )
    if parsed_budgets != tuple(sorted(set(parsed_budgets))):
        raise MiddlegameCorpusError(
            f"{source_path}: budgets_ms must be strictly increasing"
        )
    raw_positions = report.get("positions")
    if not isinstance(raw_positions, list):
        raise MiddlegameCorpusError(f"{source_path}: positions must be an array")

    samples: list[dict[str, Any]] = []
    for position_index, raw_position in enumerate(raw_positions):
        item = _mapping(raw_position, f"{source_path}.positions[{position_index}]")
        position_text = item.get("position")
        if not isinstance(position_text, str) or not position_text:
            raise MiddlegameCorpusError(
                f"{source_path}.positions[{position_index}].position is invalid"
            )
        reversible_plies = _int(
            item.get("reversible_plies"),
            f"{source_path}.positions[{position_index}].reversible_plies",
            minimum=0,
        )
        try:
            state = parse_position(
                position_text,
                reversible_plies=reversible_plies,
            )
        except ValueError as error:
            raise MiddlegameCorpusError(
                f"{source_path}.positions[{position_index}] has invalid position: {error}"
            ) from error
        canonical_position = format_position(state)
        if canonical_position != position_text:
            raise MiddlegameCorpusError(
                f"{source_path}.positions[{position_index}] is not canonical"
            )
        legal = tuple(move.notation for move in legal_moves(state))
        legal_set = set(legal)
        if len(legal) < 2:
            continue
        piece_count = sum(piece != EMPTY for piece in state.board)
        if not min_pieces <= piece_count <= max_pieces:
            continue
        played_move = item.get("played_move")
        if not isinstance(played_move, str) or played_move not in legal_set:
            raise MiddlegameCorpusError(
                f"{source_path}.positions[{position_index}].played_move is illegal"
            )
        raw_searches = item.get("searches")
        if not isinstance(raw_searches, list) or len(raw_searches) < 2:
            raise MiddlegameCorpusError(
                f"{source_path}.positions[{position_index}] needs two searches"
            )
        searches: list[dict[str, Any]] = []
        for search_index, raw_search in enumerate(raw_searches):
            search = _mapping(
                raw_search,
                f"{source_path}.positions[{position_index}].searches[{search_index}]",
            )
            budget = _int(
                search.get("budget_ms"),
                "search.budget_ms",
                minimum=1,
            )
            move = search.get("move")
            if not isinstance(move, str) or move not in legal_set:
                raise MiddlegameCorpusError(
                    f"{source_path}.positions[{position_index}] search move is illegal"
                )
            searches.append(
                {
                    "budget_ms": budget,
                    "move": move,
                    "score": _int(search.get("score"), "search.score"),
                    "depth": _int(search.get("depth"), "search.depth", minimum=0),
                    "nodes": _int(search.get("nodes"), "search.nodes", minimum=0),
                    "elapsed_ms": _int(
                        search.get("elapsed_ms"),
                        "search.elapsed_ms",
                        minimum=0,
                    ),
                }
            )
        search_budgets = tuple(item["budget_ms"] for item in searches)
        if search_budgets != parsed_budgets:
            raise MiddlegameCorpusError(
                f"{source_path}.positions[{position_index}] search budgets do not match report"
            )
        stable_move = (
            searches[-1]["move"]
            if searches[-1]["move"] == searches[-2]["move"]
            else None
        )
        if stable_only and stable_move is None:
            continue
        child_static_raw = _mapping(
            item.get("candidate_child_static", {}),
            "candidate_child_static",
        )
        child_static: dict[str, dict[str, int]] = {}
        for move, raw_trace in child_static_raw.items():
            if not isinstance(move, str):
                raise MiddlegameCorpusError("candidate child move must be a string")
            trace = _mapping(raw_trace, f"child_static.{move}")
            child_static[move] = _relative_terms(
                trace.get("relative_terms", {}),
                f"child_static.{move}.relative_terms",
            )
        source = {
            "analysis": str(source_path.resolve()),
            "analysis_sha256": _sha256(source_path),
            "game_id": game_id,
            "source_game": report.get("source_game"),
            "library": report.get("library"),
            "library_sha256": library_sha256,
            "threads": report.get("threads"),
            "hash_mb": report.get("hash_mb"),
            "rules_profile": report.get("rules_profile"),
            "ply": _int(item.get("ply"), "position.ply", minimum=1),
        }
        sample_id = _position_id(canonical_position, reversible_plies)
        samples.append(
            {
                "kind": "sample",
                "id": sample_id,
                "position": canonical_position,
                "reversible_plies": reversible_plies,
                "piece_count": piece_count,
                "legal_moves": list(legal),
                "source": source,
                "label": {
                    "kind": "search-stability",
                    "classification": item.get("classification", "unanalysed"),
                    "played_move": played_move,
                    "short_move": searches[0]["move"],
                    "long_move": searches[-1]["move"],
                    "stable_move": stable_move,
                    "played_matches_long": played_move == searches[-1]["move"],
                    "usable_for_supervised_training": stable_move is not None,
                },
                "search_trace": searches,
                "static_features": {
                    "root": _relative_terms(
                        _mapping(item.get("root_static", {}), "root_static").get(
                            "relative_terms", {}
                        ),
                        "root_static.relative_terms",
                    ),
                    "children": child_static,
                },
                "observations": [],
            }
        )
    return samples


def build_middlegame_corpus(
    analysis_paths: Iterable[str | Path],
    output_path: str | Path,
    *,
    min_pieces: int = 8,
    max_pieces: int = 24,
    stable_only: bool = False,
) -> dict[str, Any]:
    """Validate analysis reports and write a deduplicated JSONL corpus."""

    if min_pieces < 1 or max_pieces < min_pieces:
        raise ValueError("piece-count range is invalid")
    paths = tuple(sorted((Path(path).resolve() for path in analysis_paths), key=str))
    if not paths:
        raise ValueError("at least one analysis report is required")

    grouped: dict[str, dict[str, Any]] = {}
    analysis_metadata: list[dict[str, Any]] = []
    for path in paths:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise MiddlegameCorpusError(f"cannot read {path}: {error}") from error
        report_mapping = _mapping(report, str(path))
        samples = _analysis_samples(
            report_mapping,
            path,
            min_pieces=min_pieces,
            max_pieces=max_pieces,
            stable_only=stable_only,
        )
        analysis_metadata.append(
            {
                "path": str(path),
                "sha256": _sha256(path),
                "game_id": report_mapping.get("game_id"),
                "library_sha256": report_mapping.get("library_sha256"),
                "budgets_ms": report_mapping.get("budgets_ms"),
                "sample_count": len(samples),
            }
        )
        for sample in samples:
            existing = grouped.get(sample["id"])
            if existing is None:
                sample["observations"].append(
                    {
                        "source": sample["source"],
                        "label": sample["label"],
                        "search_trace": sample["search_trace"],
                    }
                )
                grouped[sample["id"]] = sample
                continue
            existing["observations"].append(
                {
                    "source": sample["source"],
                    "label": sample["label"],
                    "search_trace": sample["search_trace"],
                }
            )
            if existing["label"]["stable_move"] != sample["label"]["stable_move"]:
                existing["label"]["classification"] = "conflicting-search-labels"
                existing["label"]["stable_move"] = None
                existing["label"]["usable_for_supervised_training"] = False

    samples = [grouped[key] for key in sorted(grouped)]
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "kind": "metadata",
        "format": MIDDLEGAME_CORPUS_FORMAT,
        "version": MIDDLEGAME_CORPUS_VERSION,
        "sample_count": len(samples),
        "stable_sample_count": sum(
            sample["label"]["stable_move"] is not None for sample in samples
        ),
        "conflict_sample_count": sum(
            sample["label"]["classification"] == "conflicting-search-labels"
            for sample in samples
        ),
        "filters": {
            "min_pieces": min_pieces,
            "max_pieces": max_pieces,
            "stable_only": stable_only,
            "deduplicated_by_position_and_clock": True,
        },
        "label_semantics": (
            "search-stability observations; long_move is not a proven best-move label"
        ),
        "analysis_sources": analysis_metadata,
    }
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n")
        for sample in samples:
            handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
    return metadata
