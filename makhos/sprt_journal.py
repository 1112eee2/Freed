"""Durable append-only pair journals for resumable pentanomial SPRT."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


SPRT_JOURNAL_FORMAT = "thai-makhos-sprt-journal-v1"


class SPRTJournalError(ValueError):
    """Raised when a journal is corrupt or incompatible with the requested run."""


@dataclass(frozen=True, slots=True)
class PairJournalRecord:
    pair_index: int
    opening_id: str
    opening_moves: tuple[str, ...]
    opening_position: str
    opening_reversible_plies: int
    first_score: float
    second_score: float
    first_reason: str
    second_reason: str
    bucket: int


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def config_sha256(config: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()


class SPRTJournal:
    """Create or resume a journal, committing only complete colour-swapped pairs."""

    def __init__(
        self,
        path: str | Path,
        *,
        config: Mapping[str, Any],
        resume: bool,
    ) -> None:
        self.path = Path(path).resolve()
        self.config = dict(config)
        self.config_hash = config_sha256(self.config)
        self.recovered_tail_bytes = 0
        self.partial_path: Path | None = None
        if resume:
            if not self.path.is_file():
                raise FileNotFoundError(f"SPRT journal does not exist: {self.path}")
            self.records = self._load_and_recover()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            header = {
                "format": SPRT_JOURNAL_FORMAT,
                "type": "header",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "config_sha256": self.config_hash,
                "config": self.config,
            }
            try:
                with self.path.open("x", encoding="utf-8", newline="\n") as file:
                    file.write(canonical_json(header) + "\n")
                    file.flush()
                    os.fsync(file.fileno())
            except FileExistsError as error:
                raise FileExistsError(
                    f"SPRT journal already exists; use --resume: {self.path}"
                ) from error
            self.records = ()

    def _load_and_recover(self) -> tuple[PairJournalRecord, ...]:
        raw = self.path.read_bytes()
        if not raw:
            raise SPRTJournalError("SPRT journal is empty")
        if not raw.endswith(b"\n"):
            last_newline = raw.rfind(b"\n")
            if last_newline < 0:
                raise SPRTJournalError("SPRT journal has no complete header")
            complete = raw[: last_newline + 1]
            partial = raw[last_newline + 1 :]
            partial_path = self.path.with_name(self.path.name + ".partial")
            try:
                with partial_path.open("xb") as file:
                    file.write(partial)
                    file.flush()
                    os.fsync(file.fileno())
            except FileExistsError as error:
                raise SPRTJournalError(
                    f"cannot preserve partial journal tail; file exists: {partial_path}"
                ) from error
            with self.path.open("r+b") as file:
                file.truncate(len(complete))
                file.flush()
                os.fsync(file.fileno())
            raw = complete
            self.recovered_tail_bytes = len(partial)
            self.partial_path = partial_path

        lines = raw.decode("utf-8").splitlines()
        if not lines:
            raise SPRTJournalError("SPRT journal is empty")
        try:
            header = json.loads(lines[0])
        except json.JSONDecodeError as error:
            raise SPRTJournalError(f"invalid journal header: {error}") from error
        if not isinstance(header, Mapping):
            raise SPRTJournalError("journal header must be a JSON object")
        if header.get("format") != SPRT_JOURNAL_FORMAT or header.get("type") != "header":
            raise SPRTJournalError("unsupported SPRT journal header")
        stored_config = header.get("config")
        if not isinstance(stored_config, Mapping):
            raise SPRTJournalError("journal header has no config object")
        stored_hash = header.get("config_sha256")
        if stored_hash != config_sha256(stored_config):
            raise SPRTJournalError("journal config checksum mismatch")
        if canonical_json(stored_config) != canonical_json(self.config):
            raise SPRTJournalError(
                "journal config does not match this run; do not mix match evidence"
            )
        if stored_hash != self.config_hash:
            raise SPRTJournalError("journal config hash does not match this run")

        records: list[PairJournalRecord] = []
        wins = draws = losses = 0
        pentanomial = [0, 0, 0, 0, 0]
        for line_number, line in enumerate(lines[1:], start=2):
            if not line:
                raise SPRTJournalError(f"blank journal line {line_number}")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise SPRTJournalError(
                    f"invalid journal JSON at line {line_number}: {error}"
                ) from error
            record = self._parse_pair(payload, expected_index=len(records) + 1)
            records.append(record)
            for score in (record.first_score, record.second_score):
                if score == 1.0:
                    wins += 1
                elif score == 0.5:
                    draws += 1
                else:
                    losses += 1
            pentanomial[record.bucket] += 1
            expected_snapshot = {
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "pentanomial": pentanomial,
            }
            if payload.get("snapshot") != expected_snapshot:
                raise SPRTJournalError(
                    f"journal pair {record.pair_index} snapshot does not match pair history"
                )
        return tuple(records)

    @staticmethod
    def _parse_pair(payload: Any, *, expected_index: int) -> PairJournalRecord:
        if not isinstance(payload, Mapping) or payload.get("type") != "pair":
            raise SPRTJournalError(f"journal pair {expected_index} must be an object")
        pair_index = payload.get("pair")
        if pair_index != expected_index:
            raise SPRTJournalError(
                f"journal pair index must be {expected_index}, got {pair_index}"
            )
        opening_id = payload.get("opening_id")
        opening_moves = payload.get("opening_moves")
        opening_position = payload.get("opening_position")
        opening_clock = payload.get("opening_reversible_plies")
        if not isinstance(opening_id, str) or not opening_id:
            raise SPRTJournalError(f"journal pair {pair_index} has invalid opening_id")
        if not isinstance(opening_moves, list) or any(
            not isinstance(move, str) or not move for move in opening_moves
        ):
            raise SPRTJournalError(f"journal pair {pair_index} has invalid opening_moves")
        if not isinstance(opening_position, str) or not opening_position:
            raise SPRTJournalError(f"journal pair {pair_index} has invalid position")
        if (
            isinstance(opening_clock, bool)
            or not isinstance(opening_clock, int)
            or opening_clock < 0
        ):
            raise SPRTJournalError(f"journal pair {pair_index} has invalid clock")
        first_score = payload.get("first_score")
        second_score = payload.get("second_score")
        if first_score not in (0.0, 0.5, 1.0) or second_score not in (0.0, 0.5, 1.0):
            raise SPRTJournalError(f"journal pair {pair_index} has invalid scores")
        first_reason = payload.get("first_reason")
        second_reason = payload.get("second_reason")
        if not isinstance(first_reason, str) or not isinstance(second_reason, str):
            raise SPRTJournalError(f"journal pair {pair_index} has invalid reasons")
        bucket = round(2.0 * (first_score + second_score))
        if payload.get("bucket") != bucket or bucket not in range(5):
            raise SPRTJournalError(f"journal pair {pair_index} has invalid bucket")
        return PairJournalRecord(
            pair_index=pair_index,
            opening_id=opening_id,
            opening_moves=tuple(opening_moves),
            opening_position=opening_position,
            opening_reversible_plies=opening_clock,
            first_score=float(first_score),
            second_score=float(second_score),
            first_reason=first_reason,
            second_reason=second_reason,
            bucket=bucket,
        )

    def append_pair(
        self,
        record: PairJournalRecord,
        *,
        snapshot: Mapping[str, Any],
    ) -> None:
        expected = len(self.records) + 1
        if record.pair_index != expected:
            raise SPRTJournalError(
                f"next journal pair must be {expected}, got {record.pair_index}"
            )
        expected_keys = {"wins", "draws", "losses", "pentanomial"}
        if set(snapshot) != expected_keys:
            raise SPRTJournalError(
                "journal snapshot must contain wins, draws, losses, and pentanomial"
            )
        payload = {
            "type": "pair",
            "pair": record.pair_index,
            "opening_id": record.opening_id,
            "opening_moves": record.opening_moves,
            "opening_position": record.opening_position,
            "opening_reversible_plies": record.opening_reversible_plies,
            "first_score": record.first_score,
            "second_score": record.second_score,
            "first_reason": record.first_reason,
            "second_reason": record.second_reason,
            "bucket": record.bucket,
            "snapshot": dict(snapshot),
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(canonical_json(payload) + "\n")
            file.flush()
            os.fsync(file.fileno())
        self.records = self.records + (record,)
