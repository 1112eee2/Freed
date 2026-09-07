"""Bound low-resource verification of guide/lifecycle/fixture changes only."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import nnue_gate_c_control as control
from prepare_nnue_thread_audit import prepare, digest
from scratch.nnue_full_suite_attestation import (
    inventory_sha256, source_inventory_paths, test_inventory_paths)
from scratch.nnue_quiet_leaf_acquire import write_locked_json


def main():
    evidence_dir = ROOT / "build/nnue_guide_implementation_v1"
    evidence_dir.mkdir(exist_ok=True)
    contract = control.contract_at()
    documents = ["DEVELOPMENT_PLAN_TH.md", "NNUE_ROADMAP.md",
        ".agents/skills/thai-makhos-engine/SKILL.md",
        ".agents/skills/thai-makhos-engine/references/current-state.md"]
    tools = ["work/nnue_gate_c_control.py", "work/test_nnue_gate_c_control.py",
        "work/nnue_gate_c_status_terminal.ps1", "work/test_nnue_gate_c_status_terminal.ps1",
        "work/prepare_nnue_thread_audit.py", "work/test_prepare_nnue_thread_audit.py",
        "work/verify_nnue_guide_implementation.py", "work/nnue_ancestor_delta_v1/README.md"]
    before = {name: control.sha(ROOT / name) for name in documents + tools}
    for key, paths in (("source_inventory_sha256", source_inventory_paths(ROOT)),
                       ("test_inventory_sha256", test_inventory_paths(ROOT))):
        if inventory_sha256(paths, root=ROOT) != contract[key]:
            raise ValueError(f"Frozen {key} changed")
    # Small DLL/model identities only; do not rehash large TBs during the arena.
    for name, expected in contract["artifact_sha256"].items():
        if name.endswith((".dll", ".mknnue")) and control.sha(ROOT / name) != expected:
            raise ValueError(f"Engine/model changed: {name}")
    link_count = 0
    for name in documents:
        path = ROOT / name
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = target.strip("<>").split("#", 1)[0]
            if not target or "://" in target:
                continue
            if not (path.parent / target).resolve().exists():
                raise ValueError(f"Broken link in {name}: {target}")
            link_count += 1
    py = str(Path(sys.executable))
    shell = str(Path(os.environ["USERPROFILE"]) / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe")
    validator = str(Path(os.environ["USERPROFILE"]) / ".codex/skills/.system/skill-creator/scripts/quick_validate.py")
    commands = {
        "lifecycle": [py, "-B", "work/test_nnue_gate_c_control.py"],
        "audit_preparation": [py, "-B", "work/test_prepare_nnue_thread_audit.py"],
        "monitor_locales": [shell, "-NoProfile", "-File", "work/test_nnue_gate_c_status_terminal.ps1"],
        "skill_validation": [py, "-B", validator, str(ROOT / ".agents/skills/thai-makhos-engine")],
    }
    checks = {}
    for label, command in commands.items():
        environment = dict(os.environ)
        if label == "skill_validation":
            environment["PYTHONPATH"] = str(ROOT / "work/skill_validator_dependencies")
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True)
        log_path = evidence_dir / (label + ".log")
        log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode != 0:
            raise RuntimeError(f"{label} failed; inspect {log_path}")
        checks[label] = {"command": command, "exit_code": result.returncode,
                         "log": str(log_path), "log_sha256": control.sha(log_path)}
    fixtures = control.read_json(ROOT / "build/nnue_thread_scaling_preparation_v2/fixtures_and_schedule.json")
    if digest(fixtures) != digest(prepare()):
        raise ValueError("Fixture/schedule reproduction mismatch")
    after = {name: control.sha(ROOT / name) for name in documents + tools}
    if before != after:
        raise ValueError("Document/tool sources changed during verification")
    suite = control.read_json(ROOT / "build/nnue_phase1_evidence/full_suite_attestation_v23.json")
    if (suite["verdict"] != "PASS" or suite["source_inventory_sha256"] != contract["source_inventory_sha256"]
            or suite["test_inventory_sha256"] != contract["test_inventory_sha256"]):
        raise ValueError("Fresh complete suite does not bind the frozen inventory")
    payload = {"format": "thai-makhos-guide-implementation-evidence-v1",
        "verdict": "KEEP_TOOLING_AND_PREPARATION_NOT_PLAYING_PROMOTION",
        "changed_file_sha256": after, "checks": checks, "local_links_verified": link_count,
        "full_suite": {"artifact": "build/nnue_phase1_evidence/full_suite_attestation_v23.json",
                       "sha256": control.sha(ROOT / "build/nnue_phase1_evidence/full_suite_attestation_v23.json"),
                       "tests_run": suite["tests_run"], "duration_seconds": suite["duration_seconds"]},
        "source_inventory_sha256": contract["source_inventory_sha256"],
        "test_inventory_sha256": contract["test_inventory_sha256"],
        "fixture_reproduction": True, "fixture_coverage": fixtures["coverage"],
        "fixtures_sha256": control.sha(ROOT / "build/nnue_thread_scaling_preparation_v2/fixtures_and_schedule.json"),
        "diagnostic_searches_scheduled_not_run": len(fixtures["schedule"]),
        "invalidated_preparation": "build/nnue_thread_scaling_preparation_v1/INVALIDATED.md",
        "status_snapshot": control.snapshot(), "native_search_changed": False,
        "production_promoted": False, "thread_strength_proven": False,
        "next_action": "Finish frozen Gate C 2000ms; PASS permits production review, not automatic promotion"}
    output = evidence_dir / "evidence.json"
    write_locked_json(output, payload)
    print(json.dumps({"output": str(output), "sha256": control.sha(output),
        "verdict": payload["verdict"], "local_links_verified": link_count,
        "checks": list(checks), "frozen_source_preserved": True}, sort_keys=True))


if __name__ == "__main__":
    main()
