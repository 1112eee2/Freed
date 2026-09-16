"""Run frozen handoff plus separate threading diagnostics; never alter inputs."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / sys.argv[1]
OUT.mkdir(exist_ok=False)
BIN = OUT / 'binaries'
BIN.mkdir()
os.chdir(ROOT)
records = []

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def q(p): return shlex.quote(str(p))
def run(name, command):
    import time
    t = time.monotonic()
    env = os.environ.copy(); env.pop('TSAN_OPTIONS', None)
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    p = subprocess.Popen(['/bin/bash','-c',command], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    killed = False
    try: stdout, stderr = p.communicate(timeout=130)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL); stdout, stderr = p.communicate(); killed = True
    for suffix, content in [('stdout',stdout),('stderr',stderr)]:
        (OUT/f'{name}.{suffix}.log').write_bytes(content)
    item = dict(name=name, command=command, cwd=str(ROOT), started_utc=stamp,
                exit_code=p.returncode, elapsed_seconds=time.monotonic()-t, runner_killed=killed,
                stdout=f'{name}.stdout.log',stderr=f'{name}.stderr.log',
                stdout_sha256=hashlib.sha256(stdout).hexdigest(),stderr_sha256=hashlib.sha256(stderr).hexdigest())
    records.append(item)
    (OUT/'commands.json').write_text(json.dumps(records,indent=2)+'\n')
    print(name, p.returncode, round(item['elapsed_seconds'],3), stderr.decode(errors='replace')[:120],flush=True)
    return item

inputs = {str(p.relative_to(ROOT)): digest(p) for p in ROOT.rglob('*') if p.is_file() and p.relative_to(ROOT).parts[0] in ('source','README.md','manifest.json','probe.c','verify_snapshot.py','windows_smoke.json','.gitattributes')}
assert run('verify_before','python3 verify_snapshot.py')['exit_code'] == 0
run('environment','uname -a\ncat /etc/os-release\ngetconf GNU_LIBC_VERSION\npython3 --version\nclang --version\ngcc --version\ngdb --version\ntimeout --version\ndpkg-query -W clang clang-18 libclang-rt-18-dev gcc-13 libtsan2 libc6 gdb\ncat /proc/sys/vm/mmap_rnd_bits\nps -eo pid,comm --sort=pid')
results = {}
sources = {'pthread_negative':HERE/'pthread_negative.c','c11_smoke':HERE/'c11_smoke.c','c11_negative':HERE/'c11_negative.c','probe':ROOT/'probe.c'}
for compiler in ('gcc','clang'):
    tests={}
    for name, source in sources.items():
        modes=('plain','tsan') if compiler=='gcc' else ('tsan',)
        for mode in modes:
            ident=f'{compiler}_{name}_{mode}'
            binary=BIN/ident
            flags='-fsanitize=thread ' if mode=='tsan' else ''
            # Frozen probe command has exactly the README flags; only output path differs here.
            cmd=f'{compiler} -std=c17 -O1 -g {flags}-pthread {q(source)} -o {q(binary)}'
            if compiler=='clang' and name=='probe':
                cmd='clang -std=c17 -O1 -g -fsanitize=thread -pthread probe.c -o probe'
                binary=ROOT/'probe'
            built=run(ident+'_compile',cmd)
            entry={'compile':built,'runs':[]}
            tests[ident]=entry
            if built['exit_code'] != 0:
                entry['status']='NOT_RUN';continue
            entry['binary_sha256']=digest(binary)
            entry['binary_path']=str(binary)
            if mode=='tsan': run(ident+'_linkage',f'ldd {q(binary)}')
            for i in range(5 if name=='probe' and mode=='tsan' else 1):
                prefix='TSAN_OPTIONS=halt_on_error=1 ' if mode=='tsan' else ''
                command=f'{prefix}timeout 120s {q(binary)}'
                if compiler=='clang' and name=='probe': command='TSAN_OPTIONS=halt_on_error=1 timeout 120s ./probe'
                entry['runs'].append(run(f'{ident}_run_{i+1:02}',command))
            if mode=='tsan' and name in ('c11_smoke','probe') and any(x['exit_code'] for x in entry['runs']):
                run(ident+'_gdb',f'TSAN_OPTIONS=halt_on_error=1 timeout 120s gdb -q -batch -ex "set pagination off" -ex "set disable-randomization off" -ex "handle SIGSEGV stop print nopass" -ex run -ex "thread apply all bt" -ex "info sharedlibrary" -ex "info registers" --args {q(binary)}')
    results[compiler]=tests
run('verify_after','python3 verify_snapshot.py')
assert all(digest(ROOT/p)==h for p,h in inputs.items())
result={'status':'REVIEW_REQUIRED','snapshot_commit':'ed89600cdc92944efc158050b71ce5c0f9c881f1',
        'scope':'publication protocol and separate threading diagnostics only','input_sha256':inputs,
        'inputs_unchanged':True,'prior_PR_18_status':'NOT_RUN (preserved)','tests':results,
        'tsan_options':'halt_on_error=1','suppressions':False,'aslr_modified':False}
(OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
