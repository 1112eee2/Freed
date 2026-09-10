"""Reproduce this review; search requires --search or --endgame.

Run from any directory. TB4-6 are mapped read-only; their multi-GB payloads
are not rescanned. --search requires an idle host, uses 1T/BelowNormal, and
releases its batch slot if GUI priority is asserted between bounded searches.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from makhos.compact_tb3 import CompactTablebase
from makhos.core import BLACK, DEFAULT_RULES, apply_move, format_position, legal_moves, terminal_status
from makhos.exact import Outcome
from makhos.game_analysis import load_game_record, replay_game
from makhos.ranked_tablebase import RankedTablebase

SOURCE_SHA = '57dbeb7b304ade200de8889f2d70db062ba0d4605d546fb3ecd57bf27f7f4c29'
DLL = ROOT / 'build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll'
MODEL = ROOT / 'build/nnue_quantized_v1/model_a.mknnue'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name, value):
    (HERE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def pieces(state):
    return sum(bool(p) for p in state.board)


def audit():
    source = HERE / 'game.json'
    assert sha(source) == SOURCE_SHA, 'source game bytes changed'
    payload = json.loads(source.read_text(encoding='utf-8'))
    replay = replay_game(load_game_record(source))
    assert replay.record.game_id == payload['game_id'] == HERE.name
    assert payload['position_history'] == [format_position(replay.record.start)] + [format_position(x.child) for x in replay.plies]
    final = terminal_status(replay.final, repetition_count=replay.history[replay.final.position_key])
    assert final.terminal and final.winner == BLACK and final.reason == 'no_legal_move'
    assert payload['result'] == {'source': 'rules', 'winner': 'black', 'reason': final.reason}
    assert payload['rules_result'] == {'terminal': True, 'winner': 'black', 'reason': final.reason}
    evidence = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'game_id': replay.record.game_id, 'source_sha256': SOURCE_SHA,
        'invariant_sha256': {p: sha(ROOT / p) for p in ('RULESET.json', 'makhos/core.py', 'build/makhos_native_accepted.dll')},
        'actual_result': {'winner': 'black', 'reason': final.reason, 'plies': len(replay.plies)},
        'max_game_repetition_count': max(replay.history.values()),
        'max_game_clock': max(x.state.reversible_plies for x in replay.plies),
        'raw_wdl_semantics': 'Side to move, 80-ply clock, no repetition history; WIN/LOSS are not repetition-safe proof.',
        'ranked_full_checksum_verified_this_run': False,
        'engine_backends': dict(Counter(x.engine['search_backend'] for x in replay.plies if x.engine)),
        'recorded_budgets_ms': dict(Counter(x.engine['requested_time_ms'] for x in replay.plies if x.engine)),
        'ranked_files': [], 'plies': [], 'native_pv_tb_frontiers': [],
    }
    with ExitStack() as stack:
        tb3 = stack.enter_context(CompactTablebase())
        tables = {n: stack.enter_context(RankedTablebase(ROOT / f'build/tb{n}_np80.compact.bin')) for n in (4, 5, 6)}
        evidence['tb3_sha256'] = tb3.sha256
        for n, tb in tables.items():
            with tb.path.open('rb') as f:
                header_sha = hashlib.sha256(f.read(8192)).hexdigest()
            evidence['ranked_files'].append({'pieces': n, 'path': str(tb.path.relative_to(ROOT)),
                                             'bytes': tb.path.stat().st_size, 'first_8192_bytes_sha256': header_sha})

        def raw(state):
            status = terminal_status(state, repetition_count=1)
            if status.terminal:
                return Outcome.DRAW if status.winner is None else Outcome.WIN if status.winner == state.turn else Outcome.LOSS
            if pieces(state) > 6:
                return None
            return (tb3 if pieces(state) <= 3 else tables[pieces(state)]).probe(state).outcome

        for item in replay.plies:
            row = {'ply': item.ply, 'player': 'black' if item.player == BLACK else 'red',
                   'played': item.notation, 'position': format_position(item.state),
                   'clock': item.state.reversible_plies, 'pieces': pieces(item.state),
                   'history_count': item.history[item.state.position_key],
                   'recorded_engine': item.engine}
            value = raw(item.state)
            row['raw_turn_wdl'] = None if value is None else value.name
            options = {}
            for move in legal_moves(item.state):
                child = apply_move(item.state, move)
                child_value = raw(child)
                options[move.notation] = None if child_value is None else Outcome(-int(child_value)).name
            row['raw_candidate_wdl_mover'] = options
            row['raw_played_wdl_mover'] = options[item.notation]
            if item.engine:
                meta = item.engine
                assert meta['pv'][0] == item.notation
                assert meta['native_library_sha256'].lower() == sha(DLL)
                assert meta['nnue_model_sha256'].lower() == sha(MODEL)
                state = item.state
                counts = Counter(item.history)
                first_tb = None
                for index, notation in enumerate(meta['pv'], 1):
                    assert not terminal_status(state, repetition_count=counts[state.position_key]).terminal
                    move = next(m for m in legal_moves(state) if m.notation == notation)
                    state = apply_move(state, move)
                    counts[state.position_key] += 1
                    if pieces(state) <= 6 and first_tb is None:
                        wdl = raw(state)
                        first_tb = {'offset': index, 'position': format_position(state),
                                    'clock': state.reversible_plies,
                                    'raw_black_wdl': (wdl if state.turn == BLACK else Outcome(-int(wdl))).name}
                if first_tb and meta['search_backend'] == 'native-root-split':
                    evidence['native_pv_tb_frontiers'].append({'ply': item.ply, 'recorded_score': meta['score'], **first_tb})
                row['pv_legal'] = True
            evidence['plies'].append(row)

    by_ply = {row['ply']: row for row in evidence['plies']}
    for ply, only in ((55, '24-15'), (65, '19-16'), (67, '16-11')):
        assert [m for m, wdl in by_ply[ply]['raw_candidate_wdl_mover'].items() if wdl == 'DRAW'] == [only]
    assert by_ply[70]['raw_candidate_wdl_mover'] == {'13-17': 'DRAW', '21-25': 'LOSS'}
    assert by_ply[51]['raw_played_wdl_mover'] == 'DRAW'
    assert all(by_ply[p]['raw_played_wdl_mover'] == 'DRAW' for p in range(52, 70))
    evidence['validation'] = 'PASS: 81 legal moves, 82 exact history positions, 41 legal PVs, result and targeted TB assertions'
    write_json('evidence.json', evidence)
    print(evidence['validation'], flush=True)
    return replay


def below_normal():
    import ctypes
    if sys.platform == 'win32':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
            raise ctypes.WinError(ctypes.get_last_error())


def search_diagnostics(replay):
    """A new 1T observation, deliberately not labelled a 12T reproduction."""
    from makhos.native import NativeSearch
    from makhos.workload_isolation import BatchWorkLease

    below_normal()
    result = {'purpose': 'diagnostic, not a matched 12T reproduction or solved root label',
              'dll_sha256': sha(DLL), 'model_sha256': sha(MODEL), 'threads': 1,
              'hash_power': 20, 'clear_tt_before_each_search': True, 'history': 'full replay prefix',
              'depth_limit': 64, 'budgets_ms': [2000, 5000], 'priority': 'BelowNormal',
              'observations': [], 'complete': False}
    try:
        with BatchWorkLease(ROOT) as lease, NativeSearch(DLL, hash_power=20, persistent=True, nnue_model=MODEL) as native:
            assert native.nnue_enabled and native.nnue_model_sha256.lower() == sha(MODEL)
            result['allocated_hash_mb'] = native.allocated_hash_mb
            for ply in (25, 27, 35, 41, 42, 44, 47, 51):
                item = replay.plies[ply - 1]
                for budget in result['budgets_ms']:
                    lease.checkpoint(f'ply {ply} budget {budget}')
                    native.clear()
                    obs = native.search(item.state, depth=64, time_ms=budget,
                                        no_progress_plies=DEFAULT_RULES.no_progress_plies,
                                        repetition_limit=DEFAULT_RULES.repetition_limit, history=item.history)
                    state = item.state
                    counts = Counter(item.history)
                    for move in obs.pv:
                        assert not terminal_status(state, repetition_count=counts[state.position_key]).terminal
                        assert move in legal_moves(state)
                        state = apply_move(state, move)
                        counts[state.position_key] += 1
                    entry = {'ply': ply, 'budget_ms': budget, 'recorded_move': item.notation,
                             'move': obs.move.notation, 'score_side_to_move': obs.score,
                             'score_black': obs.score if item.player == BLACK else -obs.score,
                             'depth': obs.depth, 'nodes': obs.nodes, 'elapsed_ms': obs.elapsed_ms,
                             'pv': [m.notation for m in obs.pv]}
                    result['observations'].append(entry)
                    write_json('search_1t.json', result)
                    print({k: v for k, v in entry.items() if k != 'pv'}, flush=True)
            result['complete'] = True
    finally:
        write_json('search_1t.json', result)


def endgame_diagnostics(replay):
    """Check project-rule intervals using the installed isolated C2 1T kernel."""
    from makhos.native_endgame import NativeEndgameTablebase
    from makhos.native_endgame_search import NativeEndgameSearch
    from makhos.search import Engine, SearchLimits
    from makhos.workload_isolation import BatchWorkLease

    below_normal()
    library = ROOT / 'build/native_endgame_c2/makhos_endgame_search.dll'
    result = {'dll': str(library.relative_to(ROOT)), 'dll_sha256': sha(library),
              'evaluator': 'hce', 'threads': 1, 'history': 'full replay prefix',
              'rules': 'project: repetition=3, no_progress=80', 'observations': []}
    with ExitStack() as stack:
        lease = stack.enter_context(BatchWorkLease(ROOT))
        tb3 = stack.enter_context(CompactTablebase())
        tb = stack.enter_context(NativeEndgameTablebase(tb3, library=library,
                                 ranked_paths=[ROOT / f'build/tb{n}_np80.compact.bin' for n in (4, 5, 6)]))
        native = NativeEndgameSearch(tb)
        stack.callback(native.close)
        for ply, depth in ((55, 2), (65, 2), (67, 4), (70, 12), (71, 12)):
            lease.checkpoint(f'endgame ply {ply}')
            item = replay.plies[ply - 1]
            obs = native.search(item.state, depth, history=item.history, rules=DEFAULT_RULES, time_ms=3000)
            assert obs.status == 0 and obs.depth == depth, 'incomplete endgame observation'
            for root in obs.roots:
                state = item.state
                counts = Counter(item.history)
                for move in root.pv:
                    assert not terminal_status(state, repetition_count=counts[state.position_key]).terminal
                    assert move in legal_moves(state)
                    state = apply_move(state, move)
                    counts[state.position_key] += 1
            entry = {'ply': ply, 'requested_depth': depth, 'depth': obs.depth, 'status': obs.status,
                     'nodes': obs.nodes, 'tb_hits': obs.tb_hits, 'repetition_draws': obs.repetition_draws,
                     'roots': [{'move': r.pv[0].notation, 'score': r.score,
                                'lower': r.bound.lower.name, 'upper': r.bound.upper.name,
                                'pv': [m.notation for m in r.pv]} for r in obs.roots]}
            result['observations'].append(entry)
            write_json('endgame_history.json', result)
            print(entry, flush=True)
        lease.checkpoint('Python reference ply 70')
        ranked = [stack.enter_context(RankedTablebase(ROOT / f'build/tb{n}_np80.compact.bin')) for n in (4, 5, 6)]
        reference = Engine(native_tablebase=tb3, ranked_tablebases=ranked,
                           exact_piece_limit=0, reference_search=True)
        item = replay.plies[69]
        check = reference.search(item.state, SearchLimits(depth=12, time_ms=5000), history=item.history)
        expected = next(x for x in result['observations'] if x['ply'] == 70)
        actual = [{'move': r.move.notation, 'score': r.score,
                   'lower': r.bound.lower.name, 'upper': r.bound.upper.name,
                   'pv': [m.notation for m in r.pv]} for r in check.candidates]
        assert check.depth == 12
        assert sorted(actual, key=lambda x: x['move']) == sorted(expected['roots'], key=lambda x: x['move'])
        assert {x['move']: (x['lower'], x['upper']) for x in actual} == {
            '13-17': ('DRAW', 'DRAW'), '21-25': ('LOSS', 'LOSS')}
        winning = next(x for x in result['observations'] if x['ply'] == 71)
        assert [x['move'] for x in winning['roots'] if (x['lower'], x['upper']) == ('WIN', 'WIN')] == ['3-8']
        result['python_reference_ply70'] = {'depth': check.depth, 'nodes': check.nodes,
                                           'elapsed_ms': check.elapsed_ms, 'roots': actual, 'parity': 'PASS'}
        write_json('endgame_history.json', result)
        print('Python reference ply 70: score/WDL/PV parity PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--search', action='store_true', help='Only on an idle host: 16 bounded native NNUE searches, 1T')
    parser.add_argument('--endgame', action='store_true', help='Only on an idle host: five bounded C2 history-aware checks')
    args = parser.parse_args()
    game = audit()
    if args.search:
        search_diagnostics(game)
    if args.endgame:
        endgame_diagnostics(game)
