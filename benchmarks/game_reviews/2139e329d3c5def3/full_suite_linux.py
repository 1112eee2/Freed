"""Linux diagnosis only, not a post-acquisition PASS attestation.
Reuse unchanged maintained guard/lease/runner definitions without importing
unavailable pipeline process dependencies. All test modules still discover normally.
"""
from __future__ import annotations
import ast, hashlib, io, json, os, platform, sys, time, unittest
from pathlib import Path
from typing import Callable
root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=False)
os.chdir(root)
sys.path.insert(0, str(root))
from makhos.workload_isolation import LOCK_SLOTS, _RangeLock, interactive_session_active
names = {'FullSuiteGateError','InteractivePriorityChanged','ExclusiveSuiteLease','GuardedTextResult','execute_suite','ProductionOpenGuard'}
source = root/'tools/verification/full_suite_attestation.py'
tree = ast.parse(source.read_text())
definitions = [n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names]
assert len(definitions) == len(names)
exec(compile(ast.Module(body=definitions,type_ignores=[]),str(source),'exec'))
def hashes():
 paths = [p for d in ['makhos','native','tests','tools','scratch','work'] for p in (root/d).rglob('*') if p.is_file() and p.suffix in ['.py','.c','.h','.ps1']]
 paths += [root/n for n in ['RULESET.json','makhos/core.py','build/makhos_native_accepted.dll']]
 return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
# Actual canonical production directory, and frozen arena records, remain unread.
guard = ProductionOpenGuard(root/'build/nnue_scaling_full_v1')
guard.forbidden_roots.update((root/'build'/n).resolve() for n in ['nnue_sprt_6t_vs_12t','nnue_sprt_6t_vs_12t_c4_v1'])
sys.addaudithook(guard.hook)
os.nice(10)
before = hashes()
with ExclusiveSuiteLease(root) as lease:
 suite = unittest.defaultTestLoader.discover(str(root/'tests'))
 discovered = suite.countTestCases()
 result, log, duration = execute_suite(suite,checkpoint=lease.checkpoint)
 after = hashes()
(out/'full_suite.log').write_text(log)
report = dict(status='PASS' if result.wasSuccessful() and before==after and not guard.triggered else 'NOT_PASS',runner=__doc__,platform=platform.platform(),tests_discovered=discovered,tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),passed=sum(line.endswith(" ... ok") for line in log.splitlines()),failure_ids=[t.id() for t,_ in result.failures],error_ids=[t.id() for t,_ in result.errors],elapsed_seconds=duration,source_inventory_sha256=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),source_inventories_unchanged=before==after,protected_open_attempts=len(guard.triggered),protected_work_dir=str(root/'build/nnue_scaling_full_v1'),invariant_sha256={n:before[n] for n in ['RULESET.json','makhos/core.py','build/makhos_native_accepted.dll']})
(out/'full_suite.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
