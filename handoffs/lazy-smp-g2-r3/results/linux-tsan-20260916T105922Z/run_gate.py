"""Capture exact commands/logs; GCC runs are supplemental, not the README Clang gate."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import time
from datetime import datetime, timezone

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent.parent
os.chdir(ROOT)
records = []

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(label, command, limit=130):
    started = datetime.now(timezone.utc).isoformat()
    t = time.monotonic()
    timed_out = False
    env = os.environ.copy()
    # Do not inherit sanitizer suppressions/options from the host.
    env.pop('TSAN_OPTIONS', None)
    try:
        p = subprocess.run(['/bin/bash', '-c', command], capture_output=True, env=env, timeout=limit)
        code, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        code, stdout, stderr = None, e.stdout or b'', e.stderr or b''
        timed_out = True
    elapsed = time.monotonic() - t
    (OUT / (label+'.stdout.log')).write_bytes(stdout)
    (OUT / (label+'.stderr.log')).write_bytes(stderr)
    record = dict(label=label, command=command, cwd=str(ROOT), started_utc=started,
                  exit_code=code, elapsed_seconds=elapsed, runner_timeout=timed_out,
                  stdout=label+'.stdout.log', stderr=label+'.stderr.log',
                  stdout_sha256=sha(OUT/(label+'.stdout.log')),
                  stderr_sha256=sha(OUT/(label+'.stderr.log')))
    records.append(record)
    print(label, code, round(elapsed, 3), stderr.decode(errors='replace')[:200], flush=True)
    (OUT/'commands.json').write_text(json.dumps(records, indent=2)+'\n')
    return record

input_hashes = {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob('*')
                if p.is_file() and 'results' not in p.relative_to(ROOT).parts}
verify = run('verify_before', 'python3 verify_snapshot.py')
if verify['exit_code'] != 0:
    raise SystemExit('Snapshot verification failed; no compilation attempted')
run('environment', 'uname -a\ncat /etc/os-release\ngetconf GNU_LIBC_VERSION\npython3 --version\ntimeout --version\ngcc --version\ndpkg-query -W gcc-13 libtsan2 libc6\ncat /proc/sys/vm/mmap_rnd_bits\nps -eo pid,comm --sort=pid')
run('clang_discovery', 'command -v clang clang-14 clang-15 clang-16 clang-17 clang-18 clang-19 clang-20 clang-21 clang-22\nls /usr/local/swift/usr/bin/clang /opt/llvm/bin/clang /usr/lib/llvm-*/bin/clang')
run('clang_version', 'clang --version')
tmp = ROOT / '.tsan-run-binaries'
tmp.mkdir(exist_ok=True)
negative = tmp/'negative-gcc-tsan'
probe = tmp/'probe-gcc-tsan'
negsrc = shlex.quote(str(OUT.relative_to(ROOT)/'negative_control.c'))
run('negative_clang_compile', f'clang -std=c17 -O1 -g -fsanitize=thread -pthread {negsrc} -o .tsan-run-binaries/negative-clang-tsan')
nc = run('negative_gcc_compile', f'gcc -std=c17 -O1 -g -fsanitize=thread -pthread {negsrc} -o .tsan-run-binaries/negative-gcc-tsan')
nr = run('negative_gcc_run', 'TSAN_OPTIONS=halt_on_error=1 timeout 120s ./.tsan-run-binaries/negative-gcc-tsan') if nc['exit_code'] == 0 else None
canonical = run('probe_clang_compile', 'clang -std=c17 -O1 -g -fsanitize=thread -pthread probe.c -o probe')
gc = run('probe_gcc_compile', 'gcc -std=c17 -O1 -g -fsanitize=thread -pthread probe.c -o .tsan-run-binaries/probe-gcc-tsan')
supplemental = []
if gc['exit_code'] == 0:
    run('binary_linkage', 'ldd .tsan-run-binaries/negative-gcc-tsan\nldd .tsan-run-binaries/probe-gcc-tsan\ngcc -print-file-name=libtsan.so')
    for i in range(1, 6):
        supplemental.append(run(f'probe_gcc_run_{i:02}', 'TSAN_OPTIONS=halt_on_error=1 timeout 120s ./.tsan-run-binaries/probe-gcc-tsan'))
after = run('verify_after', 'python3 verify_snapshot.py')
unchanged = all(sha(ROOT/p) == h for p,h in input_hashes.items())
negative_detected = nr is not None and b'WARNING: ThreadSanitizer: data race' in (OUT/nr['stderr']).read_bytes()
runtime_path = Path('/lib/x86_64-linux-gnu/libtsan.so.2')
result = {
 'schema': 'thai-makhos-linux-tsan-result-v1',
 'status': 'NOT_RUN',
 'scope': 'Snapshot publication functions/types only; not Windows lifecycle or full G2-G6 acceptance',
 'repository': '1112eee2/ThaiMakhosEngine',
 'base_commit': 'ed89600cdc92944efc158050b71ce5c0f9c881f1',
 'target_branch': 'codex/astra-g2-race-handoff',
 'run_id': OUT.name,
 'snapshot_verification': {'before': verify['exit_code'], 'after': after['exit_code'], 'inputs_unchanged': unchanged, 'sha256': input_hashes},
 'environment': {'platform': platform.platform(), 'machine': platform.machine(), 'details': 'environment.stdout.log', 'tsan_options': 'halt_on_error=1', 'suppressions_added': False, 'runtime_path': str(runtime_path.resolve()), 'runtime_sha256': sha(runtime_path)},
 'negative_control': {'compiler': 'gcc (supplemental; required clang unavailable)', 'compile': nc, 'run': nr, 'real_data_race_report_observed': negative_detected},
 'readme_clang_gate': {'compile': canonical, 'runs': [{'index': i, 'status':'NOT_RUN', 'reason':'Clang compilation could not execute; no Clang-built probe exists', 'planned_command':'TSAN_OPTIONS=halt_on_error=1 timeout 120s ./probe', 'exit_code':None, 'elapsed_seconds':None} for i in range(1,6)]},
 'supplemental_gcc_tsan': {'compile':gc, 'runs':supplemental, 'does_not_replace_readme_clang_gate':True},
 'binary_sha256_not_committed': {str(p.relative_to(ROOT)):sha(p) for p in (negative,probe) if p.exists()},
 'promotion': False,
 'notes': ['Only source files inside the requested handoff were used.', 'GCC/TSan diagnostics are explicitly additional attempts; no compiler or atomic substitutions hidden as README compliance.', 'Read raw stderr for runtime failure; nonzero negative-control exit is not proof of race detection.']
}
(OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
assert unchanged and after['exit_code'] == 0
