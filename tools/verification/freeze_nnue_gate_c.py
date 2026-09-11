"""Predeclare both production-time strength tests before any Gate C game."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.verification.full_suite_attestation import (
    source_inventory_paths, test_inventory_paths, inventory_sha256,
    ExclusiveSuiteLease)
from scratch.nnue_quiet_leaf_acquire import write_locked_json


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main():
    contract_path = ROOT / 'build/nnue_gate_c_contract_v1.json'
    if contract_path.exists():
        raise FileExistsError('Contract already frozen; verify it instead of regenerating')
    evidence = {
        'build/nnue_phase9_gate_b_contract.json': 'DD56A5709348F6CE88B13EC14A33DFC4A8F36AE4156298962427E28D7C3A7FB8',
        'build/nnue_phase9_gate_b_seed20261102.json': '1D439C7E96E189377D9865FA03AABD08D89611F7C903F3BB5B31C714853EAAB3',
        'build/nnue_phase1_evidence/full_suite_attestation_v22.json': '1271ECBFE903FC8D672CA250BC4D135F8D5C9C2BB6CBF28533CEE154FD9DE7A8',
        'build/nnue_gate_c_fixed_smoke_v1/result.json': 'A5C329DE2B3BBCA94E8FF2F18398C3887B28B357C4E8CDF3BB0D2C48B6801E80',
        'build/nnue_gate_c_runtime_v1.json': '57A521D9178677F6568F5107F83E81F9D042EEB9775B2C9C10948B7D5A0EA732',
    }
    with ExclusiveSuiteLease(ROOT):
        for name, expected in evidence.items():
            assert sha(ROOT / name) == expected, name
        gate_b = json.loads((ROOT / 'build/nnue_phase9_gate_b_contract.json').read_text())
        suite = json.loads((ROOT / 'build/nnue_phase1_evidence/full_suite_attestation_v22.json').read_text())
        assert suite['verdict'] == 'PASS' and suite['tests_run'] == 393
        assert suite['skipped'] == suite['errors'] == suite['failures'] == 0
        assert inventory_sha256(source_inventory_paths(ROOT), root=ROOT) == suite['source_inventory_sha256']
        assert inventory_sha256(test_inventory_paths(ROOT), root=ROOT) == suite['test_inventory_sha256']
        control, candidate = gate_b['accepted_control'], gate_b['candidate']
        artifacts = {control['library']: control['sha256'],
                     candidate['library']: candidate['library_sha256'],
                     candidate['model']: candidate['model_sha256']}
        artifacts.update({t['path']:t['sha256'] for t in gate_b['tablebases']})
        for name, expected in artifacts.items():
            assert sha(ROOT / name) == expected, name
        matches = []
        for budget, seed in ((1000, 20261105), (2000, 20261106)):
            output = f'build/nnue_gate_c_{budget}ms_seed{seed}.json'
            assert not (ROOT / output).exists(), 'Result predates contract'
            argv = ['-B','-u','-m','makhos','sprt','--pairs','10000',
                '--elo0','0','--elo1','2','--fixed-move-time-ms',str(budget),
                '--threads','12','--hash-mb','512','--persistent-search',
                '--parallel-games','1','--opening-plies','8','--seed',str(seed),
                '--max-game-plies','300','--dev-library',candidate['library'],
                '--master-library',control['library'],
                '--dev-nnue-model',candidate['model'], '--resume','--output',output]
            for tablebase in gate_b['tablebases']:
                argv.extend(['--ranked-tablebase', tablebase['path']])
            matches.append(dict(fixed_move_time_ms=budget, seed=seed, output=output, argv=argv))
        payload = dict(format='thai-makhos-gate-c-contract-v1', declared_before_games=True,
            evidence_sha256=evidence, artifact_sha256=artifacts,
            source_inventory_sha256=suite['source_inventory_sha256'],
            test_inventory_sha256=suite['test_inventory_sha256'],
            python_executable=sys.executable, python_version=sys.version.split()[0],
            settings=dict(threads_per_engine=12, hash_mb_total_per_engine=512,
                observed_allocated_tt_mb_per_engine=480, parallel_games=1,
                paired_color_swapped=True, max_pairs_per_time_control=10000,
                elo0=0, elo1=2, alpha=0.05, beta=0.05, max_game_plies=300,
                opening_plies=8, persistent_search=True),
            matches=matches,
            execution='Run 1000ms then 2000ms sequentially; GUI priority and atomic completed-pair resume',
            acceptance='Both independent time controls must PASS; then production smoke and reversible promotion review',
            stopping='FAIL or INCONCLUSIVE at cap: no promotion; investigate without changing seed/settings or pooling controls',
            exclusion='Smoke games and runtime diagnostics are excluded from strength results; ancestor-delta candidate excluded')
        write_locked_json(contract_path, payload)
        print(json.dumps({'contract':str(contract_path),'sha256':sha(contract_path)}))


if __name__ == '__main__':
    main()
