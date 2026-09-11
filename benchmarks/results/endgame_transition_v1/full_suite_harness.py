from pathlib import Path
import sys,json,hashlib,subprocess,unittest,platform
root=Path.cwd();sys.path.insert(0,str(root))
from scratch.nnue_full_suite_attestation import ExclusiveSuiteLease,ProductionOpenGuard,execute_suite,inventory_sha256,source_inventory_paths,test_inventory_paths
from scratch.nnue_scaling_final_audit import DEFAULT_WORK_DIR
out=root/'build/transition_validation/full';out.mkdir(parents=True,exist_ok=False)
guard=ProductionOpenGuard(DEFAULT_WORK_DIR)
for d in ('nnue_sprt_6t_vs_12t','nnue_sprt_6t_vs_12t_c4_v1'): guard.forbidden_roots.add((root/'build'/d).resolve())
sys.addaudithook(guard.hook)
paths=source_inventory_paths(root);tests=test_inventory_paths(root)
identities=lambda:{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in ('RULESET.json','makhos/core.py','build/makhos_native_accepted.dll')}
before=identities();source=inventory_sha256(paths,root=root);test=inventory_sha256(tests,root=root)
with ExclusiveSuiteLease(root) as lease:
 suite=unittest.defaultTestLoader.discover(str(root/'tests'));discovered=suite.countTestCases()
 print('Discovered',discovered,flush=True)
 result,log,elapsed=execute_suite(suite,checkpoint=lease.checkpoint)
 report=dict(base_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),platform=platform.platform(),tests_discovered=discovered,tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),failure_ids=[t.id() for t,_ in result.failures],error_ids=[t.id() for t,_ in result.errors],skip_reasons=[(t.id(),r) for t,r in result.skipped],elapsed_seconds=elapsed,source_inventory_sha256=source,test_inventory_sha256=test,invariant_sha256=before,invariants_unchanged=before==identities(),inventories_unchanged=source==inventory_sha256(paths,root=root) and test==inventory_sha256(tests,root=root),protected_open_attempts=len(guard.triggered))
 report['status']='PASS' if result.wasSuccessful() and not result.skipped and report['inventories_unchanged'] and report['invariants_unchanged'] and not guard.triggered else 'NOT_PASS'
 (out/'full_suite.log').write_text(log,encoding='utf-8');(out/'full_suite.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k not in ('skip_reasons','failure_ids','error_ids')},indent=2),flush=True)
