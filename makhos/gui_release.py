"""Hash-bound GUI release selection; failed verification never selects HCE."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POINTER = ROOT / "config/gui_release.json"


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest().upper()


def contained_path(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Release path escapes project: {name}")
    return path


def load_release(pointer: Path = DEFAULT_POINTER, *, root: Path = ROOT,
                 profile: str | None = None) -> dict | None:
    if not pointer.is_file():
        if pointer == DEFAULT_POINTER and profile is None:
            return None  # An unconfigured development checkout retains HCE.
        raise FileNotFoundError(f"GUI release pointer not found: {pointer}")
    selection = json.loads(pointer.read_text(encoding="utf-8"))
    if selection.get("format") != "thai-makhos-gui-release-pointer-v1":
        raise ValueError("Invalid GUI release pointer")
    manifest_path = contained_path(root, selection["manifest"])
    digest = sha256(manifest_path)
    if digest != selection["manifest_sha256"]:
        raise ValueError("GUI release manifest checksum mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "thai-makhos-gui-release-v1":
        raise ValueError("Unsupported GUI release format")
    selected = profile or selection["profile"]
    if selected not in ("nnue", "hce"):
        raise ValueError("GUI profile must be nnue or hce")
    config = dict(manifest["profiles"][selected])
    if config["nnue_enabled"] != (selected == "nnue"):
        raise ValueError("Release evaluator and profile disagree")
    for key in ("native_library", "nnue_model"):
        name = config[key]
        if name is None:
            if key == "native_library" or selected == "nnue":
                raise ValueError(f"Release missing {key}")
            continue
        artifact = contained_path(root, name)
        if sha256(artifact) != config[key + "_sha256"]:
            raise ValueError(f"GUI release {key} checksum mismatch: {artifact}")
        config[key] = artifact
    if sha256(root / "RULESET.json") != manifest["rules_sha256"]:
        raise ValueError("GUI release rules checksum mismatch")
    # The full hashes are verified during release freeze/smoke. Startup checks
    # presence/size without rereading 5 GB and delaying the browser.
    for table in manifest["tablebases"]:
        path = contained_path(root, table["path"])
        if not path.is_file():
            raise FileNotFoundError(
                f"Tablebase file missing: {path}. Download it from the release "
                "page and place it in the build folder."
            )
        if path.stat().st_size != table["bytes"]:
            raise ValueError(f"GUI release tablebase size mismatch: {path}")
    return {**config, "release_id": manifest["release_id"], "profile": selected,
            "manifest_sha256": digest, "settings": manifest["settings"],
            "tablebases": manifest["tablebases"]}
