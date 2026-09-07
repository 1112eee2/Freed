"""Gate C runtime diagnostics using the production GUI engine factory.

No HTTP server or production-default change. Fixed predeclared corpus,
two repetitions at 1/2 seconds, existing frozen engines only. Not Elo evidence.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from makhos import server
from makhos.core import format_position, legal_moves, parse_position, terminal_status
from makhos.native_benchmark import generate_native_benchmark_cases
from makhos.search import Mode, SearchLimits
from makhos.cli import _set_batch_process_priority
from scratch.nnue_full_suite_attestation import ExclusiveSuiteLease
from scratch.nnue_quiet_leaf_acquire import write_locked_json
from scratch.nnue_search_candidate_audit import TARGETS

OUTPUT = ROOT / 'build/nnue_gate_c_runtime_v1.json'
IDENTITIES = {
    'build/makhos_native_accepted.dll': 'FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD',
    'build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll': '32C323026A7F78CCD9C4013FC3067422A564EE3D0A6ADE4F1CE5C62356747E79',
    'build/nnue_quantized_v1/model_a.mknnue': '07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C',
}


def verify_identities():
    for name, expected in IDENTITIES.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest().upper() == expected, name


def main():
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    verify_identities()
    priority = _set_batch_process_priority()
    cases = [(f'random-{c.index}', c.state, Counter(c.history))
             for c in generate_native_benchmark_cases(count=8, seed=20261104)]
    for target in TARGETS:
        state = parse_position(target['position'], reversible_plies=target['reversible_plies'])
        cases.append((target['id'], state, Counter({state.position_key: 1})))
    # A mandatory single capture tests the intentional early-return path.
    state = parse_position('B:BM18:RM14,1')
    assert len(legal_moves(state)) == 1 and legal_moves(state)[0].is_capture
    cases.append(('forced-capture', state, Counter({state.position_key: 1})))
    rows, loads = [], []
    with ExclusiveSuiteLease(ROOT) as lease:
        for label, library, model in (
            ('accepted', ROOT / 'build/makhos_native_accepted.dll', None),
            ('nnue', ROOT / 'build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll',
             ROOT / 'build/nnue_quantized_v1/model_a.mknnue')):
            lease.checkpoint(f'before {label} load')
            started = time.perf_counter()
            server.configure_gui_native_search(library, model)
            try:
                engine = server.get_default_engine(threads=12, hash_mb=512)
                native = engine.native_search
                assert native is not None and len(native._workers) == 12
                assert 0 < native.allocated_hash_mb <= 512
                assert all(w.nnue_enabled == (label == 'nnue') for w in native._workers)
                assert set(engine.ranked_tablebases) == {4, 5, 6}
                assert server.ensure_native_tablebase_ready(engine)
                loads.append(dict(engine=label, load_ms=(time.perf_counter()-started)*1000,
                    requested_hash_mb=512, allocated_hash_mb=native.allocated_hash_mb,
                    worker_count=len(native._workers), memory_bytes=native.memory_bytes,
                    ranked_piece_counts=sorted(engine.ranked_tablebases)))
                for budget in (1000, 2000):
                    for case_id, state, history in cases:
                        assert not terminal_status(state, repetition_count=history[state.position_key]).terminal
                        for repetition in range(2):
                            lease.checkpoint(f'{label}/{budget}/{case_id}/{repetition}')
                            native.clear()
                            start = time.perf_counter()
                            result = engine.search(state, SearchLimits(depth=64, time_ms=budget),
                                                   mode=Mode.WIN, history=history)
                            wall_ms = (time.perf_counter()-start)*1000
                            provenance = server.engine_search_provenance(engine)
                            assert result.move in legal_moves(state)
                            assert not provenance['native_error']
                            assert provenance['search_backend'] != 'python-fallback'
                            assert provenance['nnue_enabled'] == (label == 'nnue')
                            row = dict(engine=label, budget_ms=budget, case=case_id,
                                repetition=repetition, position=format_position(state),
                                reversible_plies=state.reversible_plies,
                                legal_moves=len(legal_moves(state)), move=result.move.notation,
                                score=result.score, depth=result.depth, nodes=result.nodes,
                                elapsed_ms=result.elapsed_ms, wall_ms=wall_ms,
                                overshoot_ms=max(0, wall_ms-budget),
                                timing_review_needed=wall_ms > budget+max(250, budget*0.2),
                                pv=[m.notation for m in result.pv],
                                tablebase_hits=result.tablebase_hits, provenance=provenance,
                                memory_bytes=native.memory_bytes)
                            rows.append(row)
                            print(json.dumps({'progress': len(rows), 'total': 96,
                                'engine': label, 'case': case_id, 'budget_ms': budget,
                                'wall_ms': round(wall_ms, 1), 'backend': provenance['search_backend']}), flush=True)
            finally:
                server.close_global_engine()
        lease.checkpoint('before report')
        verify_identities()
        assert len(rows) == 96
        report = dict(format='thai-makhos-gate-c-runtime-audit-v1',
            verdict='RUNTIME_DIAGNOSTICS_COMPLETE_REVIEW_REQUIRED_NOT_STRENGTH_PASS',
            script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper(),
            identities=IDENTITIES, priority=priority, cases=12, repetitions=2,
            requested_threads=12, requested_hash_mb=512, budgets_ms=[1000,2000],
            timing_review_threshold='wall > budget + max(250ms, 20% budget); diagnostic flag only',
            loads=loads, rows=rows,
            timing_flag_count=sum(r['timing_review_needed'] for r in rows))
        write_locked_json(OUTPUT, report)
        print(json.dumps({'output': str(OUTPUT), 'rows':len(rows),
                          'timing_flags':report['timing_flag_count']}), flush=True)


if __name__ == '__main__':
    main()
