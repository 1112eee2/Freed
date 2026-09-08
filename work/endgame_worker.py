import argparse
import json
import os
import sys
import time

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-path', required=True)
    parser.add_argument('--tb4-path', required=True)
    parser.add_argument('--tb3-path', default=None)
    return parser.parse_args()

def main():
    args = parse_args()
    sys.path.insert(0, os.path.abspath(args.repo_path))
    import psutil
    from collections import Counter
    from makhos.core import parse_position
    from makhos.search import Engine, SearchLimits, Mode
    from makhos.ranked_tablebase import RankedTablebase
    from makhos.native_tablebase import NativeTablebase
    
    proc = psutil.Process(os.getpid())
    tb4 = RankedTablebase(args.tb4_path)
    tb3 = None
    if args.tb3_path and os.path.isfile(args.tb3_path):
        tb3 = NativeTablebase(args.tb3_path)
    
    engine = Engine(ranked_tablebase=tb4, native_tablebase=tb3)
    
    sys.stdout.write(json.dumps({'status': 'ready'}) + '\n')
    sys.stdout.flush()
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        cmd = req.get('command')
        if cmd == 'quit':
            break
        elif cmd == 'search':
            pos_str = req['position']
            mode_str = req.get('mode', 'BEST')
            mode = Mode.WIN if mode_str == 'WIN' else Mode.BEST
            time_ms = req.get('time_ms')
            depth = req.get('depth', 6)
            history_dict = req.get('history', {})
            
            history = Counter()
            for k, v in history_dict.items():
                if isinstance(k, str) and (':' in k):
                    try:
                        history[parse_position(k).position_key] = v
                    except Exception:
                        history[k] = v
                else:
                    history[k] = v
                    
            limits = SearchLimits(depth=depth, time_ms=time_ms)
            state = parse_position(pos_str)
            
            mem_before = proc.memory_info().rss / (1024 * 1024)
            t0 = time.perf_counter()
            res = engine.search(state, limits, mode=mode, history=history)
            t1 = time.perf_counter()
            mem_after = proc.memory_info().rss / (1024 * 1024)
            elapsed_ms = (t1 - t0) * 1000.0
            resp = {
                'status': 'ok',
                'move': res.move.notation if res.move else None,
                'score': res.score,
                'depth': res.depth,
                'nodes': res.nodes,
                'elapsed_ms': elapsed_ms,
                'bound': [res.bound.lower.name, res.bound.upper.name] if res.bound else None,
                'mem_rss_mb': mem_after,
            }
            sys.stdout.write(json.dumps(resp) + '\n')
            sys.stdout.flush()

if __name__ == '__main__':
    main()
