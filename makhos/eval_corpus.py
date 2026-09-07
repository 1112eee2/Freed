"""Deterministic exact-WDL corpus construction for evaluator tuning."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
from typing import Iterable, Mapping

from .core import (
    BLACK,
    BLACK_KING,
    BLACK_MAN,
    EMPTY,
    RED,
    RED_KING,
    RED_MAN,
    State,
    format_position,
    legal_moves,
    opponent,
)
from .eval import CURRENT_EVALUATION_WEIGHTS, evaluation_features
from .exact import Outcome
from .provenance import (
    DEFAULT_MANIFEST_PATH,
    load_provenance_manifest,
    ruleset_sha256,
)
from .ranked_tablebase import RankedTablebase


EVAL_CORPUS_FORMAT = "thai-makhos-exact-wdl-eval-v1"
EVAL_CORPUS_VERSION = 1
OUTCOME_NAME = {
    Outcome.LOSS: "loss",
    Outcome.DRAW: "draw",
    Outcome.WIN: "win",
}
SWAP_PIECE = {
    EMPTY: EMPTY,
    RED_MAN: BLACK_MAN,
    BLACK_MAN: RED_MAN,
    RED_KING: BLACK_KING,
    BLACK_KING: RED_KING,
}


def _position_bytes(state: State) -> bytes:
    return bytes(state.board) + bytes((state.turn, state.reversible_plies))


def rotate_swap_state(state: State) -> State:
    """Apply the exact color-rotation symmetry used by the rules tests."""

    return State(
        tuple(SWAP_PIECE[piece] for piece in reversed(state.board)),
        opponent(state.turn),
        state.reversible_plies,
        state.ply,
    )


def canonical_position_id(state: State) -> str:
    """Deduplicate a state and its color-rotated equivalent."""

    canonical = min(
        _position_bytes(state),
        _position_bytes(rotate_swap_state(state)),
    )
    return hashlib.sha256(canonical).hexdigest()[:24]


def corpus_split(position_id: str, validation_percent: int = 20) -> str:
    if not 1 <= validation_percent <= 50:
        raise ValueError("validation_percent must be in 1..50")
    bucket = int(position_id[:8], 16) % 100
    return "validation" if bucket < validation_percent else "train"


def _source_metadata(
    tablebase: RankedTablebase,
    manifest_path: str | Path,
) -> dict:
    manifest = load_provenance_manifest(
        manifest_path,
        validate_project=False,
    )
    if ruleset_sha256() != manifest.ruleset_digest:
        raise ValueError("current canonical ruleset differs from tablebase manifest")
    representation = "compact" if tablebase._compact else "full"
    artifact = manifest.artifact_for(
        tablebase.piece_count,
        tablebase.no_progress_plies,
        representation,
    )
    stat = tablebase.path.stat()
    if stat.st_size != artifact.file_bytes:
        raise ValueError("tablebase byte count differs from provenance manifest")
    if tablebase.expected_checksum != artifact.fnv1a64:
        raise ValueError("tablebase checksum differs from provenance manifest")
    return {
        "piece_count": tablebase.piece_count,
        "path": str(tablebase.path),
        "file_name": tablebase.path.name,
        "file_bytes": stat.st_size,
        "representation": representation,
        "no_progress_plies": tablebase.no_progress_plies,
        "header_fnv1a64": f"{tablebase.expected_checksum:016x}",
        "manifest_sha256": artifact.sha256,
        "total_positions": tablebase.total_positions,
        "material_signatures": len(tablebase.material_signatures),
    }


def build_exact_wdl_corpus(
    tablebase_paths: Iterable[str | Path],
    output_path: str | Path,
    *,
    samples_per_outcome: int = 1000,
    seed: int = 20260910,
    validation_percent: int = 20,
    verify_checksums: bool = True,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    max_attempt_multiplier: int = 500,
) -> dict:
    """Create balanced quiet-position WDL labels from exact tablebases."""

    if samples_per_outcome < 1:
        raise ValueError("samples_per_outcome must be positive")
    paths = tuple(Path(path).resolve() for path in tablebase_paths)
    if not paths:
        raise ValueError("at least one tablebase is required")
    rng = random.Random(seed)
    samples: list[dict] = []
    sources: list[dict] = []
    seen: set[str] = set()
    rejection_counts: Counter[str] = Counter()
    bucket_counts: Counter[tuple[int, str, str]] = Counter()
    desired_split_counts = {
        "validation": round(samples_per_outcome * validation_percent / 100),
    }
    desired_split_counts["train"] = (
        samples_per_outcome - desired_split_counts["validation"]
    )

    for path in paths:
        with RankedTablebase(path) as tablebase:
            source = _source_metadata(tablebase, manifest_path)
            if verify_checksums:
                tablebase.verify_checksum()
            source["fnv1a64_verified"] = bool(tablebase.checksum_verified)
            sources.append(source)
            piece_count = tablebase.piece_count
            signatures = tablebase.material_signatures
            needed = samples_per_outcome * len(OUTCOME_NAME)
            attempts = 0
            maximum_attempts = needed * max_attempt_multiplier
            while sum(
                count
                for (pieces, _outcome, _split), count in bucket_counts.items()
                if pieces == piece_count
            ) < needed:
                attempts += 1
                if attempts > maximum_attempts:
                    missing = {
                        f"{outcome}/{split}": target - bucket_counts[
                            piece_count, outcome, split
                        ]
                        for outcome in OUTCOME_NAME.values()
                        for split, target in desired_split_counts.items()
                        if bucket_counts[piece_count, outcome, split] < target
                    }
                    raise RuntimeError(
                        f"unable to fill {piece_count}-piece corpus buckets: {missing}"
                    )
                signature = rng.choice(signatures)
                rank = rng.randrange(tablebase.board_count(signature))
                turn = rng.choice((RED, BLACK))
                state = tablebase.state_from_rank(signature, rank, turn)
                moves = legal_moves(state)
                if not moves:
                    rejection_counts["terminal"] += 1
                    continue
                if moves[0].is_capture:
                    rejection_counts["mandatory_capture"] += 1
                    continue
                outcome = OUTCOME_NAME[tablebase.probe(state).outcome]
                position_id = canonical_position_id(state)
                if position_id in seen:
                    rejection_counts["duplicate_or_symmetric"] += 1
                    continue
                split = corpus_split(position_id, validation_percent)
                target = desired_split_counts[split]
                bucket = piece_count, outcome, split
                if bucket_counts[bucket] >= target:
                    rejection_counts["filled_bucket"] += 1
                    continue
                features = evaluation_features(state, state.turn)
                samples.append({
                    "kind": "sample",
                    "id": position_id,
                    "split": split,
                    "piece_count": piece_count,
                    "signature": list(signature),
                    "rank": rank,
                    "turn": "black" if turn == BLACK else "red",
                    "position": format_position(state),
                    "reversible_plies": state.reversible_plies,
                    "outcome": outcome,
                    "quiet_legal_moves": len(moves),
                    "features": asdict(features),
                    "current_score": int(features.score()),
                    "source_file": path.name,
                })
                seen.add(position_id)
                bucket_counts[bucket] += 1
            source["sampling_attempts"] = attempts

    samples.sort(key=lambda item: item["id"])
    metadata = {
        "kind": "metadata",
        "format": EVAL_CORPUS_FORMAT,
        "version": EVAL_CORPUS_VERSION,
        "seed": seed,
        "samples_per_piece_outcome": samples_per_outcome,
        "validation_percent": validation_percent,
        "filters": {
            "reversible_plies": 0,
            "non_terminal": True,
            "quiet_only": True,
            "color_rotation_deduplicated": True,
        },
        "ruleset_sha256": ruleset_sha256(),
        "provenance_manifest": str(Path(manifest_path).resolve()),
        "current_evaluation_weights": CURRENT_EVALUATION_WEIGHTS,
        "sources": sources,
        "sample_count": len(samples),
        "bucket_counts": {
            f"{pieces}/{outcome}/{split}": count
            for (pieces, outcome, split), count in sorted(bucket_counts.items())
        },
        "rejections": dict(sorted(rejection_counts.items())),
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(metadata, sort_keys=True) + "\n")
        for sample in samples:
            file.write(json.dumps(sample, sort_keys=True) + "\n")
    return metadata


def load_exact_wdl_corpus(
    path: str | Path,
) -> tuple[dict, tuple[Mapping, ...]]:
    with Path(path).open("r", encoding="utf-8") as file:
        try:
            metadata = json.loads(next(file))
        except (StopIteration, json.JSONDecodeError) as error:
            raise ValueError("invalid or empty evaluation corpus") from error
        if metadata.get("format") != EVAL_CORPUS_FORMAT:
            raise ValueError("unsupported evaluation corpus format")
        samples = tuple(json.loads(line) for line in file if line.strip())
    if len(samples) != metadata.get("sample_count"):
        raise ValueError("evaluation corpus sample count mismatch")
    return metadata, samples
