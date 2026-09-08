"""Small diagnostic controls. In-memory variants are not production fixes."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import reproduce  # Sets the repository import path and BelowNormal priority.
from makhos import server
from makhos.core import Rules, apply_move, parse_position
from makhos.distance import DistanceOracle
from makhos.exact import ExactSolver
from makhos.ranked_tablebase import RankedTablebase
from makhos.search import Engine, Mode, SearchLimits


class TraceEngine(Engine):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.visited_plies = Counter()

    def _negamax(self, state, depth, alpha, beta, counts, *, ply_from_root):
        self.visited_plies[ply_from_root] += 1
        return super()._negamax(state, depth, alpha, beta, counts,
                                ply_from_root=ply_from_root)


class NoTBCutoff(TraceEngine):
    def _probe_exact(self, state):
        return None


class CaptureHandler(server.EngineRequestHandler):
    def __init__(self):
        self.response = None

    def send_json(self, data, status=200):
        self.response = {"status": status, "data": data}


def main():
    folder = Path(__file__).resolve().parent
    fixture = json.loads((folder / "reproduction.json").read_text())
    state = parse_position(fixture["root"], reversible_plies=fixture["clock"])
    history = server.parse_position_history(fixture, state)
    report = {}
    with RankedTablebase(reproduce.ROOT / "build/tb4_np80.compact.bin") as tb:
        search_controls = []
        for engine_type in (TraceEngine, NoTBCutoff):
            engine = engine_type(ranked_tablebase=tb)
            result = engine.search(state, SearchLimits(depth=3),
                                   history=history, mode=Mode.WIN)
            search_controls.append({
                "variant": engine_type.__name__, "move": result.move.notation,
                "score": result.score,
                "bound": [result.bound.lower.name, result.bound.upper.name],
                "visited_plies": dict(engine.visited_plies),
                "candidate_details": [{
                    "move": candidate.move.notation,
                    "pressure": candidate.pressure,
                    "policy_value": asdict(candidate.policy_value),
                } for candidate in result.candidates
                    if candidate.move.notation in ("6-24", "6-9")],
            })
        report["cutoff_control"] = search_controls
        assert search_controls[0]["move"] == "6-9"
        assert search_controls[0]["visited_plies"] == {1: 39}
        assert search_controls[1]["move"] != "6-9"
        assert search_controls[1]["bound"] == ["WIN", "WIN"]

        # Same small, complete lower-piece oracle in both budget trials.
        # It solves the forced capture leaf in only two states; no TB3 builder.
        distance_controls = []
        for piece_limit, budget in ((3, 0), (3, 1), (2, 1)):
            rules = Rules(repetition_limit=None, no_progress_plies=80)
            solver = ExactSolver(rules, max_states=32)
            oracle = DistanceOracle(rules, ranked_tablebases=(tb,),
                                    exact_solver=solver,
                                    exact_piece_limit=piece_limit, max_nodes=budget)
            distance = oracle.for_move(state, reproduce.named_move(state, "6-24"))
            distance_controls.append({
                "lower_piece_limit": piece_limit, "budget": budget,
                "distance": asdict(distance), "expanded": oracle._nodes,
                "exact_solver_states": solver.state_count,
            })
        report["distance_control"] = distance_controls
        assert distance_controls[0]["distance"]["dtm"] is None
        assert distance_controls[1]["distance"]["dtm"] == 3
        assert distance_controls[1]["distance"]["exact"]
        assert distance_controls[2]["distance"]["dtm"] is None

        # Execute the real server handler with only engine construction replaced.
        # No HTTP listener, native search, shared workload lease, or live GUI.
        engine = TraceEngine(ranked_tablebase=tb)
        handler = CaptureHandler()
        with patch.object(server, "get_default_engine", return_value=engine):
            handler.handle_bestmove({
                "position": fixture["root"], "clock": fixture["clock"],
                "history": fixture["history"], "rules_profile": "project",
                "mode": "win", "depth": 3, "use_full_time": False,
                "time_sec": 0.05, "threads": 1, "hash_mb": 4,
            })
        response = handler.response
        report["handler_control"] = {
            "status": response["status"],
            **{key: response["data"].get(key) for key in
               ("bestmove", "score", "wdl", "tablebase_hits", "search_backend")},
            "history_current_root_count": history[state.position_key],
            "scope": "Real handler, isolated real Engine; engine factory replaced",
        }
        assert response["status"] == 200
        assert response["data"]["bestmove"] == "6-9"
        assert response["data"]["wdl"] == "DRAW..WIN"

        # Repetition is checked at the immediate child. The gap is one ply later.
        child = apply_move(state, reproduce.named_move(state, "6-9"))
        immediate_history = history.copy()
        immediate_history[child.position_key] = 2
        result = engine.search(state, SearchLimits(depth=1),
                               history=immediate_history, mode=Mode.WIN)
        candidate = next(c for c in result.candidates if c.move.notation == "6-9")
        report["immediate_repetition_control"] = {
            "score": candidate.score,
            "bound": [candidate.bound.lower.name, candidate.bound.upper.name],
        }
        assert candidate.score == 0
        assert candidate.bound.exact_outcome.name == "DRAW"

    print(json.dumps(report, indent=2))
    (folder / "controls.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
