"""Replay evidence and bounded, fresh-state searches for game 2139e329d3c5def3.

Search results are observations, not solved labels or Windows reproductions.
The optional audit ABI belongs only to instrument_tt.py's diagnostic builds.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from makhos.core import apply_move, format_position, legal_moves, terminal_status
from makhos.game_analysis import load_game_record, replay_game
from makhos.native import NativeSearch, hash_power_for_megabytes, native_tt_entry_bytes
from makhos.parallel_native import ParallelNativeSearch
from makhos.workload_isolation import BatchWorkLease

GAME_SHA = '5afd9031f611a6842872330dc47af10e4984cb0e111d51fced24c84829d54d9f'
MODEL_SHA = '07b9ab0f83e253cb74b2acd2bd5291f5f91eb086e042790f33ea0a8c0914164c'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit_game():
    source = HERE / 'game.json'
    assert sha(source) == GAME_SHA, 'source game bytes changed'
    payload = json.loads(source.read_text(encoding='utf-8'))
    game = replay_game(load_game_record(source))
    assert game.record.game_id == HERE.name
    assert payload['position_history'] == [format_position(game.record.start)] + [
        format_position(row.child) for row in game.plies]
    status = terminal_status(game.final, repetition_count=game.history[game.final.position_key])
    assert status.terminal and status.winner == 2 and status.reason == 'no_legal_move'
    rows = []
    for row in game.plies:
        if row.engine is None:
            continue
        state, history = row.state, Counter(row.history)
        for notation in row.engine['pv']:
            assert not terminal_status(state, repetition_count=history[state.position_key]).terminal
            matches = [move for move in legal_moves(state) if move.notation == notation]
            assert len(matches) == 1, (row.ply, notation)
            state = apply_move(state, matches[0])
            history[state.position_key] += 1
        assert row.engine['nnue_model_sha256'].lower() == MODEL_SHA
        rows.append({'ply': row.ply, 'position': format_position(row.state),
                     'clock': row.state.reversible_plies, 'played': row.notation,
                     'legal': [move.notation for move in legal_moves(row.state)],
                     'recorded_score': row.engine['score'], 'recorded_depth': row.engine['depth'],
                     'backend': row.engine['search_backend'], 'wdl': row.engine['wdl']})
    return game, {'game_id': game.record.game_id, 'source_sha256': GAME_SHA,
                  'plies': len(game.plies), 'legal_engine_pvs': len(rows),
                  'result': payload['result'], 'rows': rows,
                  'provenance_limits': ['No recorded source revision',
                     'native-endgame plies identify the ordinary NNUE DLL, not the effective endgame DLL',
                     'No per-move WDL lower/upper or effective thread count'],
                  'status': 'REPLAY_PASS'}


def priority():
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.nice(10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path)
    parser.add_argument('--model', type=Path, default=ROOT / 'build/nnue_quantized_v1/model_a.mknnue')
    parser.add_argument('--ply', type=int, action='append')
    parser.add_argument('--budget-ms', type=int, action='append')
    parser.add_argument('--depth', type=int, default=64)
    parser.add_argument('--threads', type=int, default=1, choices=range(1, 13))
    parser.add_argument('--hash-mb', type=int, default=512)
    parser.add_argument('--hash-power', type=int, help='explicit TT size for 1T diagnostic parity')
    parser.add_argument('--tt-audit', action='store_true')
    parser.add_argument('--root-move', action='append', help='analyse selected legal children; requires one ply and 1T')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists; preserve earlier observations')
    game, report = audit_game()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.library is None:
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(report['status'])
        return
    if not args.ply or any(p < 1 or p > len(game.plies) for p in args.ply):
        parser.error('search requires valid explicit --ply values')
    if args.hash_power is not None and (args.threads != 1 or not 12 <= args.hash_power <= 24):
        parser.error('hash-power requires 1T and a value from 12 through 24')
    if args.tt_audit and args.threads != 1:
        parser.error('TT instrumentation supports only private 1T contexts')
    if args.root_move and (len(args.ply) != 1 or args.threads != 1):
        parser.error('root-move analysis requires exactly one ply and 1T')
    budgets = args.budget_ms or [1000]
    if any(ms < 0 for ms in budgets) or (0 in budgets and args.depth == 64):
        parser.error('use positive budgets, or 0 with an explicit bounded fixed depth')
    if not 1 <= args.depth <= 64 or args.hash_mb <= 0:
        parser.error('invalid depth or hash budget')
    assert sha(args.model) == MODEL_SHA, 'model differs from the game'
    report.update({'purpose': 'diagnostic; not a solved label or strength gate',
                   'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                   'platform': platform.platform(), 'library': str(args.library.resolve()),
                   'library_sha256': sha(args.library), 'model_sha256': sha(args.model),
                   'threads': args.threads, 'requested_hash_mb': args.hash_mb,
                   'clear_state': 'new context for every observation',
                   'history': 'full replay prefix', 'complete': False, 'observations': []})
    priority()
    with BatchWorkLease(ROOT) as lease:
        for ply in args.ply:
            row = game.plies[ply - 1]
            for notation in args.root_move or [None]:
                state, history = row.state, Counter(row.history)
                if notation is not None:
                    matches = [m for m in legal_moves(state) if m.notation == notation]
                    if len(matches) != 1:
                        parser.error('root move is not a unique legal move')
                    state = apply_move(state, matches[0])
                    history[state.position_key] += 1
                for ms in budgets:
                    lease.checkpoint(str((ply, notation, ms)))
                    common = {'library': args.library, 'nnue_model': args.model}
                    if args.threads == 1:
                        power = args.hash_power if args.hash_power is not None else hash_power_for_megabytes(
                            args.hash_mb, entry_bytes=native_tt_entry_bytes(args.library))
                        engine = NativeSearch(hash_power=power, persistent=True, **common)
                    else:
                        engine = ParallelNativeSearch(threads=args.threads, hash_mb=args.hash_mb, **common)
                    try:
                        started = time.perf_counter()
                        result = engine.search(state, depth=args.depth, time_ms=ms or None,
                                               no_progress_plies=80, repetition_limit=3, history=history)
                        assert result.move in legal_moves(state), 'illegal search result'
                        pv_state = state
                        pv_history = Counter(history)
                        for move in result.pv:
                            assert not terminal_status(pv_state, repetition_count=pv_history[pv_state.position_key]).terminal
                            assert move in legal_moves(pv_state), 'illegal search PV'
                            pv_state = apply_move(pv_state, move)
                            pv_history[pv_state.position_key] += 1
                        obs = {'ply': ply, 'played': row.notation, 'root_move': notation,
                               'budget_ms': ms, 'move': result.move.notation,
                               'score_original_mover': -result.score if notation else result.score,
                               'completed_depth': result.depth, 'nodes': result.nodes,
                               'elapsed_ms': result.elapsed_ms,
                               'wall_ms': 1000 * (time.perf_counter() - started),
                               'allocated_tt_mb': engine.allocated_hash_mb,
                               'pv': ([notation] if notation else []) + [m.notation for m in result.pv]}
                        if args.tt_audit:
                            values = (ctypes.c_uint64 * 20)()
                            fn = engine._library.makhos_loss_audit
                            fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]
                            fn.restype = None
                            fn(engine._handle, values)
                            obs['audit_counts'] = dict(zip(
                                ['hits', 'false_hits', 'king_false_hits', 'cutoffs', 'false_cutoffs', 'king_false_cutoffs'],
                                list(values)[:6]))
                            obs['audit_sample'] = list(values)[6:]
                            obs['diagnostic_sidecar_bytes'] = (1 << power) * 16
                        report['observations'].append(obs)
                        print(json.dumps(obs), flush=True)
                    finally:
                        engine.close()
                    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    report['complete'] = True
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
