"""Cryptographic provenance checks for the accepted ranked tablebases.

The version-1 tablebase headers predate cryptographic provenance and have no
reserved space.  A committed manifest therefore pins the complete file hash,
the canonical ruleset, and the audited generator-source bundle without moving
multi-gigabyte payloads or weakening compatibility with the native readers.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


PROVENANCE_FORMAT = "makhos-tablebase-provenance"
PROVENANCE_VERSION = 1
HASH_ALGORITHM = "sha256"
SOURCE_HASH_ALGORITHM = "sha256-path-length-lf-v1"
GENERATOR_SOURCE_FILES = (
    "native/makhos_native.c",
    "native/makhos_tb4.c",
    "native/makhos_tb5.c",
    "native/makhos_tb6.c",
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULESET_PATH = PROJECT_ROOT / "RULESET.json"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "TABLEBASE_PROVENANCE.json"


class TablebaseProvenanceError(ValueError):
    """The provenance manifest or an artifact does not match its binding."""


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise TablebaseProvenanceError(f"{field} must be a 64-digit SHA-256")
    lowered = value.lower()
    if any(character not in "0123456789abcdef" for character in lowered):
        raise TablebaseProvenanceError(f"{field} must be hexadecimal")
    return lowered


def canonical_ruleset_bytes(path: str | Path = DEFAULT_RULESET_PATH) -> bytes:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TablebaseProvenanceError(f"unable to read canonical ruleset: {error}") from error
    if not isinstance(value, dict):
        raise TablebaseProvenanceError("canonical ruleset must be a JSON object")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def ruleset_sha256(path: str | Path = DEFAULT_RULESET_PATH) -> str:
    return hashlib.sha256(canonical_ruleset_bytes(path)).hexdigest()


def generator_source_sha256(
    project_root: str | Path = PROJECT_ROOT,
    files: Iterable[str] = GENERATOR_SOURCE_FILES,
) -> str:
    root = Path(project_root)
    digest = hashlib.sha256()
    digest.update(b"makhos-tablebase-generator-source-v1\0")
    for relative in files:
        normalized_name = str(relative).replace("\\", "/")
        path_bytes = normalized_name.encode("utf-8")
        try:
            source = (root / normalized_name).read_bytes()
        except OSError as error:
            raise TablebaseProvenanceError(
                f"unable to read generator source {normalized_name}: {error}"
            ) from error
        source = source.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(len(path_bytes).to_bytes(4, "little"))
        digest.update(path_bytes)
        digest.update(len(source).to_bytes(8, "little"))
        digest.update(source)
    return digest.hexdigest()


def file_sha256(path: str | Path, *, chunk_bytes: int = 8 << 20) -> str:
    if chunk_bytes < 1:
        raise ValueError("chunk_bytes must be positive")
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as file:
            while chunk := file.read(chunk_bytes):
                digest.update(chunk)
    except OSError as error:
        raise TablebaseProvenanceError(f"unable to hash tablebase: {error}") from error
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class TablebaseArtifactBinding:
    piece_count: int
    no_progress_plies: int
    representation: str
    file_name: str
    file_bytes: int
    fnv1a64: int
    sha256: str

    @property
    def identity(self) -> tuple[int, int, str]:
        return self.piece_count, self.no_progress_plies, self.representation


@dataclass(frozen=True, slots=True)
class TablebaseProvenanceManifest:
    path: Path
    ruleset_digest: str
    generator_digest: str
    artifacts: tuple[TablebaseArtifactBinding, ...]

    def artifact_for(
        self,
        piece_count: int,
        no_progress_plies: int,
        representation: str,
    ) -> TablebaseArtifactBinding:
        identity = piece_count, no_progress_plies, representation
        matches = tuple(
            artifact for artifact in self.artifacts
            if artifact.identity == identity
        )
        if len(matches) != 1:
            raise TablebaseProvenanceError(
                "manifest does not contain exactly one binding for "
                f"{piece_count}-piece/{no_progress_plies}/{representation}"
            )
        return matches[0]


def _artifact_from_json(value: Any, index: int) -> TablebaseArtifactBinding:
    if not isinstance(value, dict):
        raise TablebaseProvenanceError(f"artifacts[{index}] must be an object")
    try:
        piece_count = int(value["piece_count"])
        no_progress_plies = int(value["no_progress_plies"])
        representation = value["representation"]
        file_name = value["file_name"]
        file_bytes = int(value["file_bytes"])
        fnv_text = value["fnv1a64"]
        digest = _require_sha256(value["sha256"], f"artifacts[{index}].sha256")
    except (KeyError, TypeError, ValueError) as error:
        raise TablebaseProvenanceError(
            f"invalid artifacts[{index}] binding"
        ) from error
    if piece_count not in (4, 5, 6):
        raise TablebaseProvenanceError(f"artifacts[{index}] piece count is invalid")
    if not 1 <= no_progress_plies <= 200:
        raise TablebaseProvenanceError(f"artifacts[{index}] horizon is invalid")
    if representation not in ("full", "compact"):
        raise TablebaseProvenanceError(
            f"artifacts[{index}] representation is invalid"
        )
    if not isinstance(file_name, str) or not file_name or Path(file_name).name != file_name:
        raise TablebaseProvenanceError(f"artifacts[{index}] file name is invalid")
    if file_bytes < 1:
        raise TablebaseProvenanceError(f"artifacts[{index}] byte count is invalid")
    if not isinstance(fnv_text, str) or len(fnv_text) != 16:
        raise TablebaseProvenanceError(f"artifacts[{index}] FNV checksum is invalid")
    try:
        fnv1a64 = int(fnv_text, 16)
    except ValueError as error:
        raise TablebaseProvenanceError(
            f"artifacts[{index}] FNV checksum is invalid"
        ) from error
    return TablebaseArtifactBinding(
        piece_count,
        no_progress_plies,
        representation,
        file_name,
        file_bytes,
        fnv1a64,
        digest,
    )


def load_provenance_manifest(
    path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    project_root: str | Path = PROJECT_ROOT,
    ruleset_path: str | Path | None = None,
    validate_project: bool = True,
) -> TablebaseProvenanceManifest:
    manifest_path = Path(path).resolve()
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TablebaseProvenanceError(f"unable to read provenance manifest: {error}") from error
    if not isinstance(value, dict):
        raise TablebaseProvenanceError("provenance manifest must be a JSON object")
    if value.get("format") != PROVENANCE_FORMAT:
        raise TablebaseProvenanceError("unsupported provenance manifest format")
    if value.get("version") != PROVENANCE_VERSION:
        raise TablebaseProvenanceError("unsupported provenance manifest version")
    if value.get("hash_algorithm") != HASH_ALGORITHM:
        raise TablebaseProvenanceError("unsupported provenance hash algorithm")
    ruleset = value.get("ruleset")
    generator = value.get("generator")
    artifacts_value = value.get("artifacts")
    if not isinstance(ruleset, dict) or not isinstance(generator, dict):
        raise TablebaseProvenanceError("manifest ruleset/generator binding is missing")
    ruleset_digest = _require_sha256(
        ruleset.get("canonical_json_sha256"),
        "ruleset.canonical_json_sha256",
    )
    if generator.get("algorithm") != SOURCE_HASH_ALGORITHM:
        raise TablebaseProvenanceError("unsupported generator source hash algorithm")
    source_files = generator.get("files")
    if source_files != list(GENERATOR_SOURCE_FILES):
        raise TablebaseProvenanceError("generator source file list mismatch")
    generator_digest = _require_sha256(
        generator.get("bundle_sha256"),
        "generator.bundle_sha256",
    )
    if not isinstance(artifacts_value, list) or not artifacts_value:
        raise TablebaseProvenanceError("manifest artifacts must be a non-empty list")
    artifacts = tuple(
        _artifact_from_json(item, index)
        for index, item in enumerate(artifacts_value)
    )
    identities = {artifact.identity for artifact in artifacts}
    if len(identities) != len(artifacts):
        raise TablebaseProvenanceError("manifest contains duplicate artifact identities")
    if validate_project:
        actual_ruleset = ruleset_sha256(
            DEFAULT_RULESET_PATH if ruleset_path is None else ruleset_path
        )
        if actual_ruleset != ruleset_digest:
            raise TablebaseProvenanceError(
                "canonical ruleset SHA-256 does not match the manifest"
            )
        actual_generator = generator_source_sha256(project_root)
        if actual_generator != generator_digest:
            raise TablebaseProvenanceError(
                "generator source SHA-256 does not match the manifest"
            )
    return TablebaseProvenanceManifest(
        manifest_path,
        ruleset_digest,
        generator_digest,
        artifacts,
    )


def verify_tablebase_artifact(
    path: str | Path,
    *,
    piece_count: int,
    no_progress_plies: int,
    representation: str,
    expected_fnv1a64: int,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    verify_file_hash: bool = True,
) -> TablebaseArtifactBinding:
    manifest = load_provenance_manifest(manifest_path)
    artifact = manifest.artifact_for(
        piece_count, no_progress_plies, representation
    )
    artifact_path = Path(path).resolve()
    try:
        file_bytes = artifact_path.stat().st_size
    except OSError as error:
        raise TablebaseProvenanceError(f"unable to stat tablebase: {error}") from error
    if file_bytes != artifact.file_bytes:
        raise TablebaseProvenanceError(
            f"tablebase byte count mismatch: expected {artifact.file_bytes}, "
            f"got {file_bytes}"
        )
    if expected_fnv1a64 != artifact.fnv1a64:
        raise TablebaseProvenanceError(
            "tablebase header FNV checksum does not match the provenance manifest"
        )
    if verify_file_hash:
        digest = file_sha256(artifact_path)
        if digest != artifact.sha256:
            raise TablebaseProvenanceError(
                f"tablebase SHA-256 mismatch: expected {artifact.sha256}, got {digest}"
            )
    return artifact
