"""Measure the production HTTP handler under an exclusive batch lease.

Fresh process != cold OS page cache. Never flush the user's OS caches.
Profiled observations attribute work; only unprofiled runs measure latency.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def cases() -> list[dict]:
    from makhos.core import apply_move, format_position, legal_moves, parse_position

    state = parse_position("B:BK1,5,9:RK32")
    history = [format_position(state)]
    for notation in ("9-6", "32-28", "6-9", "28-32", "9-6", "32-28"):
        state = apply_move(state, next(m for m in legal_moves(state) if m.notation == notation))
        history.append(format_position(state))
    threat = {"position": format_position(state), "clock": state.reversible_plies, "history": history}
    losing = apply_move(state, next(m for m in legal_moves(state) if m.notation == "6-9"))
    return [
        {"id": "tb3_kings", "position": "B:BK6,15:RK28"},
        {"id": "tb4_repetition", **threat},
        {"id": "tb4_clean", "position": format_position(state)},
        {"id": "tb4_clock78", **threat, "clock": 78},
        {"id": "tb4_clock79", **threat, "clock": 79},
        {"id": "tb4_draw_defence", "position": format_position(losing),
         "clock": losing.reversible_plies, "history": [*history, format_position(losing)]},
        {"id": "tb5_mixed", "position": "B:BM12:BK5,9:RM21:RK28"},
        {"id": "tb6_kings", "position": "B:BK1,5,6:RK24,28,32"},
        {"id": "native7_mixed", "position": "B:BM12:BK1,5,9:RM21:RK24,28"},
    ]


def percentiles(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {"n": 0, "p50": None, "p95": None, "p99": None, "max": None}
    return {"n": len(ordered), **{
        f"p{p}": ordered[max(0, math.ceil(len(ordered) * p / 100) - 1)]
        for p in (50, 95, 99)
    }, "max": ordered[-1]}


def post(url: str, route: str, body: dict, timeout: float = 60) -> dict:
    request = urllib.request.Request(url + route, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def process_snapshot(process) -> dict:
    memory, io, cpu = process.memory_info(), process.io_counters(), process.cpu_times()
    return {"rss_bytes": memory.rss, "page_faults": getattr(memory, "num_page_faults", None),
            "read_bytes": io.read_bytes, "read_count": io.read_count,
            "cpu_ms": (cpu.user + cpu.system) * 1000}


def result_signature(response: dict) -> dict:
    return {key: response[key] for key in ("bestmove", "score", "pv", "depth", "nodes", "wdl", "tablebase_hits")}


def stop_owned_process(process) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait(timeout=15)


def worker(ready: Path) -> None:
    import psutil
    from makhos import server

    if sys.platform == "win32":
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    release = server.load_release(server.DEFAULT_POINTER)
    if release is None:
        raise RuntimeError("benchmark requires an explicit production release")
    server.configure_gui_native_search(release["native_library"], release["nnue_model"])
    server.GUI_RELEASE = release
    httpd = server.MakhosHTTPServer(("127.0.0.1", 0), server.EngineRequestHandler)
    httpd.runtime_isolation = "exclusive-batch-v1"
    # Search engine setup is still measured on the first request. TB3 moved to
    # startup in Phase 1B: preload it separately, as the production server does.
    server.start_native_tablebase_warmup()
    temporary = ready.with_suffix(".tmp")
    temporary.write_text(json.dumps({"url": f"http://127.0.0.1:{httpd.server_port}"}), encoding="utf-8")
    temporary.replace(ready)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        server.close_global_engine()


def run(args) -> None:
    import psutil
    from makhos.core import EMPTY, parse_position
    from scratch.nnue_full_suite_attestation import ExclusiveSuiteLease

    output = args.output.resolve()
    if output.is_relative_to((ROOT / "build/nnue_sprt_6t_vs_12t").resolve()):
        raise ValueError("the frozen SPRT directory cannot contain benchmark output")
    output.mkdir(parents=True, exist_ok=False)
    selected = [case for case in cases() if not args.case or case["id"] in args.case]
    if not selected or (args.case and set(args.case) - {case["id"] for case in selected}):
        raise ValueError("unknown or empty case selection")
    report = {
        "format": "thai-makhos-endgame-latency-v1", "status": "RUNNING",
        "status_contract": "completion and fixed-depth profile parity; not a latency or strength acceptance gate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted({
            "RULESET.json", "benchmarks/endgame_latency.py", "config/gui_release.json",
            *(path.relative_to(ROOT).as_posix() for path in (ROOT / "makhos").glob("*.py")),
        })},
        "settings": {"threads": args.threads, "hash_mb": args.hash_mb, "time_ms": args.time_ms,
                     "repeats": args.repeats, "profile_depth": args.profile_depth},
        "isolation": "exclusive-batch-v1", "strength_evidence": False,
        "cold_os_cache": "uncontrolled", "background_engine_warmup": False,
        "tb3_startup_policy": "artifact-background-v1",
        "page_faults_include_soft_faults": True, "io_wait_separated": False,
        "profile_scope": "calling thread only; native helpers and native internals opaque",
        "observations": [],
    }
    ready = output / "ready.json"
    process = None
    try:
        with ExclusiveSuiteLease(ROOT) as lease, \
                (output / "server.log").open("w", encoding="utf-8") as log, ExitStack() as cleanup:
            started = time.perf_counter()
            process = subprocess.Popen(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--worker-ready", str(ready)],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # Stop the child before releasing the workload lease, including errors.
            cleanup.callback(stop_owned_process, process)
            while not ready.exists():
                lease.checkpoint("during latency worker startup")
                if process.poll() is not None or time.perf_counter() - started > 60:
                    raise RuntimeError("latency worker startup failed; see server.log")
                time.sleep(0.05)
            report["worker_ready_ms"] = (time.perf_counter() - started) * 1000
            url = json.loads(ready.read_text(encoding="utf-8"))["url"]
            tb3_started = time.perf_counter()
            while True:
                lease.checkpoint("during TB3 startup")
                with urllib.request.urlopen(url + "/api/readiness", timeout=5) as response:
                    tb3_status = json.load(response)["tb3"]
                if tb3_status["ready"]:
                    break
                if tb3_status["state"] in ("error", "timeout") or time.perf_counter() - tb3_started > 5:
                    raise RuntimeError(f"TB3 startup failed: {tb3_status}")
                time.sleep(0.01)
            report["tb3_startup"] = tb3_status
            observed_process = psutil.Process(process.pid)

            def observe(case, mode, kind, profiled=False, fixed_depth=False):
                lease.checkpoint("before latency request")
                payload = {key: value for key, value in case.items() if key != "id"}
                payload.update(mode=mode, threads=args.threads, hash_mb=args.hash_mb,
                               time_sec=30 if fixed_depth else args.time_ms / 1000,
                               depth=args.profile_depth if fixed_depth else 64,
                               use_full_time=not fixed_depth, profile_request=profiled,
                               rules_profile="project")
                before = process_snapshot(observed_process)
                start = time.perf_counter()
                response = post(url, "/api/bestmove", payload)
                client_ms = (time.perf_counter() - start) * 1000
                after = process_snapshot(observed_process)
                observation = {"case": case["id"], "mode": mode, "kind": kind,
                               "client_ms": client_ms, "request": payload, "response": response,
                               "process_delta": {key: None if before[key] is None or after[key] is None
                                                 else after[key] - before[key] for key in before}}
                report["observations"].append(observation)
                lease.checkpoint("after latency request")
                if response.get("native_error") or response.get("native_tablebase_error"):
                    raise RuntimeError("backend/tablebase failure invalidates benchmark")
                pieces = sum(piece != EMPTY for piece in parse_position(case["position"]).board)
                if 4 <= pieces <= 6 and pieces not in response["ranked_tablebase_pieces"]:
                    raise RuntimeError(f"TB{pieces} missing for {case['id']}")
                if fixed_depth and response["search_backend"] != "forced" and response["depth"] != args.profile_depth:
                    raise RuntimeError("fixed-depth observation reached its safety time cap")
                return response

            # Capture cold search-engine setup (TB3 is already ready), then attribute
            # steady-state search in independent fixed-depth comparisons.
            observe(selected[0], "best", "cold_process", fixed_depth=True)
            for case in selected:
                for mode in ("best", "win"):
                    for trial in range(args.repeats):
                        post(url, "/api/state", {})
                        observe(case, mode, "warm_timed")
                    post(url, "/api/state", {})
                    plain = observe(case, mode, "fixed_plain", fixed_depth=True)
                    post(url, "/api/state", {})
                    profiled = observe(case, mode, "fixed_profiled", profiled=True, fixed_depth=True)
                    if result_signature(plain) != result_signature(profiled):
                        raise RuntimeError(f"profile parity mismatch: {case['id']} {mode}")
                print(f"Completed {case['id']}", flush=True)
            report["summary"] = {
                f"{case['id']}:{mode}": {
                    metric: percentiles([row["client_ms"] if metric == "client_ms" else row["response"][metric]
                                         for row in report["observations"]
                                         if row["case"] == case["id"] and row["mode"] == mode and row["kind"] == "warm_timed"])
                    for metric in ("client_ms", "request_elapsed_ms", "request_overshoot_ms")
                } for case in selected for mode in ("best", "win")
            }
            report["status"] = "PASS"
            report["fixed_depth_parity_pairs"] = len(selected) * 2
    except BaseException as error:
        report["status"] = "ERROR"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        # Only terminate our own diagnostic child. Partial evidence is retained.
        stop_owned_process(process)
        (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--time-ms", type=int, default=1000)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--hash-mb", type=int, default=512)
    parser.add_argument("--profile-depth", type=int, default=2)
    parser.add_argument("--case", action="append")
    parser.add_argument("--worker-ready", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_ready:
        worker(args.worker_ready)
        return
    if args.output is None or not 1 <= args.repeats <= 1000 or not 10 <= args.time_ms <= 60000:
        parser.error("provide a fresh --output directory, 1..1000 repeats and 10..60000 time-ms")
    if not 1 <= args.threads <= 12 or not 4 <= args.hash_mb <= 1024 or not 1 <= args.profile_depth <= 8:
        parser.error("threads 1..12, hash-mb 4..1024, profile-depth 1..8 required")
    run(args)


if __name__ == "__main__":
    main()
