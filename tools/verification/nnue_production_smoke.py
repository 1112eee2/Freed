"""Freeze Gate C release identities and exercise the real GUI HTTP process.

Every invocation creates a new evidence directory. No native compilation,
model selection, Gate C restart, or accepted-DLL replacement is performed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INITIAL = "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8"
MANIFEST = ROOT / "releases/nnue-v1-20260908/manifest.json"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def freeze():
    from work.nnue_gate_c_control import (
        contract_at, expected_configs, checked_result, read_json, verify_bindings,
        snapshot,
    )
    from makhos.native import NativeSearch
    from tools.verification.full_suite_attestation import ExclusiveSuiteLease
    if MANIFEST.exists():
        raise FileExistsError(MANIFEST)
    status = snapshot()
    if status["gui_active"] or any(m["state"] != "FINISHED_PASS" for m in status["matches"]):
        raise RuntimeError("Both stopped Gate C controls must PASS and GUI must be idle")
    contract = contract_at()
    with ExclusiveSuiteLease(ROOT):
        verify_bindings(contract)
        results = []
        for match, config in zip(contract["matches"], expected_configs(contract)):
            path = ROOT / match["output"]
            payload = read_json(path)
            result = checked_result(payload, config)
            if not payload["complete"] or result["status"] != "PASS":
                raise ValueError("Independent Gate C PASS missing")
            results.append({"path": match["output"], "sha256": sha(path),
                            "config": config, "result": result})
        profiles = {}
        for name, dll, model in (
            ("nnue", "build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll",
             "build/nnue_quantized_v1/model_a.mknnue"),
            ("hce", "build/makhos_native_accepted.dll", None),
        ):
            with NativeSearch(ROOT / dll, hash_power=12, persistent=True,
                              nnue_model=None if model is None else ROOT / model) as probe:
                profiles[name] = {
                    "native_library": dll, "native_library_sha256": sha(ROOT / dll),
                    "native_search_abi": probe.abi_version,
                    "nnue_model": model,
                    "nnue_model_sha256": None if model is None else sha(ROOT / model),
                    "nnue_feature_abi": probe.nnue_feature_abi,
                    "nnue_enabled": probe.nnue_enabled,
                }
        tables = [{"path": name, "sha256": digest, "bytes": (ROOT / name).stat().st_size}
                  for name, digest in contract["artifact_sha256"].items()
                  if name.endswith(".bin")]
        bundle = {
            "format": "thai-makhos-gui-release-v1", "release_id": "nnue-v1-20260908",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "gate_contract_sha256": sha(ROOT / "build/nnue_gate_c_contract_v1.json"),
            "gate_source_inventory_sha256": contract["source_inventory_sha256"],
            "gate_test_inventory_sha256": contract["test_inventory_sha256"],
            "gate_results": results, "profiles": profiles,
            "settings": {"threads": 12, "hash_mb_total": 512, "rules_profile": "project",
                         "mode": "win", "budgets_ms": [1000, 2000]},
            "rules_sha256": sha(ROOT / "RULESET.json"), "tablebases": tables,
            "freeze_script_sha256": sha(__file__),
            "promotion": "REQUIRES_HTTP_BROWSER_FULL_SUITE_AND_ROLLBACK_EVIDENCE",
        }
        write_new(MANIFEST, bundle)
    print(json.dumps({"manifest": str(MANIFEST), "sha256": sha(MANIFEST)}), flush=True)


def post(base, endpoint, payload):
    request = urllib.request.Request(base + endpoint,
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


@contextmanager
def running_server(output, *, explicit, profile):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    bundle = json.loads(MANIFEST.read_text(encoding="utf-8"))
    args = [sys.executable, "-B", "-u"]
    if explicit:
        args += ["-m", "makhos", "gui"]
    else:
        args += ["server.py"]
    args += ["--port", str(port), "--no-browser"]
    if explicit:
        selected = bundle["profiles"][profile]
        args += ["--native-library", selected["native_library"]]
        if selected["nnue_model"]:
            args += ["--nnue-model", selected["nnue_model"]]
    with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
        start = time.perf_counter()
        process = subprocess.Popen(args, cwd=ROOT, stdout=stdout, stderr=stderr,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.perf_counter() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"GUI exited before ready: {process.returncode}")
                try:
                    code, state = post(base, "/api/state", {})
                    if code == 200:
                        break
                except OSError:
                    pass
                if time.perf_counter() >= deadline:
                    raise TimeoutError("GUI cold readiness exceeded 15s")
                time.sleep(.03)
            yield base, {"command": args, "pid": process.pid,
                         "ready_ms": (time.perf_counter() - start) * 1000,
                         "initial_position": state["position"]}
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def smoke(output, explicit, profile):
    from makhos.core import parse_position, legal_moves, apply_move
    output.mkdir(parents=True, exist_ok=False)
    report = {"format": "thai-makhos-production-http-smoke-v1", "verdict": "FAIL",
              "script_sha256": sha(__file__), "profile": profile, "rows": []}
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["profiles"][profile]
    try:
        with running_server(output, explicit=explicit, profile=profile) as (base, startup):
            report["startup"] = startup
            assert startup["initial_position"] == INITIAL
            assert startup["ready_ms"] < 5000
            with urllib.request.urlopen(base) as page:
                assert b'checkers-board' in page.read()
            for name, position, clock, threads, memory, seconds in (
                ("first_move", INITIAL, 0, 12, 512, 1),
                ("second_budget", INITIAL, 0, 12, 512, 2),
                ("settings_single", INITIAL, 0, 1, 64, .1),
                ("settings_restore", INITIAL, 0, 12, 512, .1),
                ("forced", "B:BM18:RM14,1", 0, 12, 512, 1),
                ("tablebase4", "B:BK25,26:RK1,2", 0, 12, 512, 1),
            ):
                state = parse_position(position, reversible_plies=clock)
                payload = {"position": position, "clock": clock, "history": [position],
                           "threads": threads, "hash_mb": memory, "time_sec": seconds}
                start = time.perf_counter()
                code, result = post(base, "/api/bestmove", payload)
                wall = (time.perf_counter() - start) * 1000
                report["rows"].append({"case": name, "http_status": code, "wall_ms": wall, "response": result})
                assert code == 200, result
                assert result["native_library_sha256"].upper() == expected["native_library_sha256"]
                assert result["nnue_enabled"] == (profile == "nnue")
                assert result["nnue_model_sha256"] == expected["nnue_model_sha256"]
                assert result["native_error"] is None
                assert result["search_backend"] != "python-fallback"
                assert 0 < result["hash_allocated_mb"] <= memory
                move = next(m for m in legal_moves(state) if m.notation == result["bestmove"])
                # Every returned PV must be a legal sequence from this root.
                pv_state = state
                for notation in result["pv"]:
                    pv_move = next(m for m in legal_moves(pv_state) if m.notation == notation)
                    pv_state = apply_move(pv_state, pv_move)
                if name in ("first_move", "second_budget"):
                    assert result["depth"] > 0 and result["pv"][0] == move.notation
                    assert 0.8 * seconds * 1000 <= result["elapsed_ms"] <= seconds * 1000 + 250
                    assert wall < seconds * 1000 + 1000
                if name == "forced":
                    assert len(legal_moves(state)) == 1 and result["search_backend"] == "forced"
                    assert wall < 250, "forced move unnecessarily initialized TB3"
                if name == "tablebase4":
                    assert result["tablebase_hits"] > 0
                print(json.dumps({"case": name, "wall_ms": round(wall, 1), "backend": result["search_backend"]}), flush=True)
            for name, payload, reason in (
                ("terminal", {"position": "R:BM25"}, "no_legal_move"),
                ("clock80", {"position": "B:BK25:RK1", "clock": 80}, "no_progress"),
                ("repetition", {"position": "B:BK25:RK1", "history": ["B:BK25:RK1"] * 3}, "repetition"),
            ):
                code, result = post(base, "/api/bestmove", payload)
                report["rows"].append({"case": name, "http_status": code, "response": result})
                assert code == 409 and result["terminal"] and reason in result["reason"], result
            report["verdict"] = "PASS_HTTP_BROWSER_REVIEW_STILL_REQUIRED"
    except Exception as error:
        report["error"] = repr(error)
        raise
    finally:
        write_new(output / "result.json", report)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "smoke"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launcher", action="store_true")
    parser.add_argument("--profile", choices=["nnue", "hce"], default="nnue")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    else:
        if args.output is None:
            parser.error("smoke requires a new --output directory")
        smoke(args.output, not args.launcher, args.profile)


if __name__ == "__main__":
    main()
