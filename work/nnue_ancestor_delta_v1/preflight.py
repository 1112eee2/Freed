"""Lightweight algebra/isolation preflight; never builds or loads native DLLs."""
from pathlib import Path
import hashlib
import json
import random
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from makhos.core import (BLACK, RED, BLACK_MAN, RED_MAN, apply_move,
                         initial_state, legal_moves, parse_position,
                         state_from_pieces)
from makhos.nnue_features import (clock_feature_index, piece_feature_index,
                                  perspective_active_features)
from scratch.nnue_full_suite_attestation import (inventory_sha256,
    source_inventory_paths, test_inventory_paths)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def check_chain(chain):
    """Compare changed-square net deltas against independent full feature sets.

    Synthetic integer weights test telescoping only, not real model overflow.
    Both directions cover undo algebra; native undo uses stored parent state.
    """
    checks = 0
    for before, after in ((chain[0], chain[-1]), (chain[-1], chain[0])):
        for perspective in (BLACK, RED):
            removed, added = [], []
            for square, (old, new) in enumerate(zip(before.board, after.board)):
                if old == new:
                    continue
                if old:
                    removed.append(piece_feature_index(old, square, perspective))
                if new:
                    added.append(piece_feature_index(new, square, perspective))
            old_clock = clock_feature_index(before.reversible_plies)
            new_clock = clock_feature_index(after.reversible_plies)
            if old_clock != new_clock:
                removed.append(old_clock)
                added.append(new_clock)
            a = set(perspective_active_features(before, perspective))
            b = set(perspective_active_features(after, perspective))
            assert set(removed) == a - b
            assert set(added) == b - a
            assert len(removed) <= 17 and len(added) <= 17
            assert (a - set(removed)) | set(added) == b
            for lane in range(8):
                def weight(feature):
                    return ((feature * 31 + lane * 17) % 101) - 50
                net = (sum(map(weight, a)) - sum(map(weight, removed))
                       + sum(map(weight, added)))
                assert net == sum(map(weight, b))
            checks += 1
    return checks


def main():
    bound = {
        'build/makhos_native_accepted.dll': 'FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD',
        'build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll': '32C323026A7F78CCD9C4013FC3067422A564EE3D0A6ADE4F1CE5C62356747E79',
        'build/nnue_quantized_v1/model_a.mknnue': '07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C',
    }
    for relative, expected in bound.items():
        assert sha(ROOT / relative) == expected, relative
    source_hash = inventory_sha256(source_inventory_paths(ROOT), root=ROOT)
    test_hash = inventory_sha256(test_inventory_paths(ROOT), root=ROOT)
    assert source_hash == 'BE1F791F157E17775BAFB17A56F2E461FC14A66F4B973E733F4FCE9BA09367FB'
    assert test_hash == 'E461DD8FFF212682C0D12DA158A8E0E0B25A0B2AF5A64695D362D64F6BA3629D'
    snapshot = {}
    for path in sorted((HERE / 'control/native').glob('*.c')):
        assert sha(path) == sha(ROOT / 'native' / path.name), path.name
        snapshot[path.name] = sha(path)
        if path.name != 'makhos_native.c':
            assert sha(path) == sha(HERE / 'candidate/native' / path.name)

    seeds = [parse_position('B:BM25:RK1', reversible_plies=n)
             for n in (0, 9, 19, 29, 39, 49, 59, 69, 78)]
    seeds += [parse_position('R:RM25:BK5', reversible_plies=7),
        state_from_pieces({(4, 3): BLACK_MAN, (3, 2): RED_MAN,
                           (5, 2): RED_MAN}, BLACK, reversible_plies=37),
        state_from_pieces({(6, 1): BLACK_MAN, (5, 2): RED_MAN,
                           (3, 4): RED_MAN}, BLACK, reversible_plies=12)]
    checks = 0
    promotions = captures = multi_captures = 0
    for state in seeds:
        for move in legal_moves(state):
            child = apply_move(state, move)
            if child.reversible_plies >= 80:
                continue  # Terminal handling is a pending native gate.
            checks += check_chain([state, child])
            promotions += int(move.promotes)
            captures += int(move.is_capture)
            multi_captures += int(len(move.captures) > 1)
    rng = random.Random(20260905)
    trajectories = 0
    for _ in range(8):
        chain = [initial_state()]
        for _ in range(32):
            moves = legal_moves(chain[-1])
            if not moves:
                break
            child = apply_move(chain[-1], rng.choice(moves))
            if child.reversible_plies >= 80:
                break
            chain.append(child)
            for span in (1, 2, 4, 8):
                if len(chain) > span:
                    checks += check_chain(chain[-span - 1:])
        trajectories += 1
    assert promotions and captures and multi_captures
    print(json.dumps(dict(status='ALGEBRA_AND_ISOLATION_PREFLIGHT_ONLY',
        checks=checks, random_trajectories=trajectories,
        promotions=promotions, captures=captures, multi_captures=multi_captures,
        source_sha256=source_hash, test_sha256=test_hash,
        control_source_hashes=snapshot,
        candidate_source_sha256=sha(HERE / 'candidate/native/makhos_native.c'),
        native_compiled=False, native_parity_verified=False,
        performance_verified=False, strength_verified=False), indent=2))


if __name__ == '__main__':
    main()
