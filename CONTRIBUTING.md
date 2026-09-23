# Developing ThaiMakhosEngine

Start with [AGENTS.md](AGENTS.md) and the
[current state](.agents/skills/thai-makhos-engine/references/current-state.md).
Historical plans and experiment commands describe past work; they do not
authorize restarting experiments. Check `git status` and preserve existing edits.

## Setup and daily checks

Run from a source checkout with Python 3.11+ and Node.js 24 for the browser tests.
The engine and the tests themselves use the standard library, but the developer
checks import the acquisition supervisor for its live-process guard, so install
the one third-party dependency first:

```powershell
python -m pip install psutil
```

`psutil` is used only for live process inspection. A virtual environment is
optional. Run commands from the repository root; installing a wheel is not the
supported GUI/artifact setup.

```powershell
python -B tools/verification/run_tests.py
```

The default **reference** suite runs the explicitly listed portable Python
tests and both Node GUI suites. It needs no native DLL, model or large TB4–6
artifacts. The runner lists the selected tests and fails on missing tests,
failures, errors or skips. A reference PASS is not a full native/release gate.

On the Windows validation host with all candidate DLLs and TB3–6 available:

```powershell
python -B tools/verification/run_tests.py --suite full
```

**Full** discovers all Python tests, including `tests/tooling`, and runs the same
Node suites. Missing artifacts remain visible failures/skips; the command
returns failure rather than calling a partial run PASS. Results and logs go to a
new directory under `build/development_checks/`; `--output-dir` selects another
new directory within `build/`.

Both modes use the existing exclusive workload lease and yield at test
boundaries when GUI priority appears. Inspect running engine/batch processes
first: legacy processes may not participate in that lease. Tests block access
to protected acquisition data and the stopped Experiment A directories. Never
stop a user's workload to make a check run.
Custom output paths are rejected before directory creation if they point into
a stopped Experiment A run or the protected acquisition run directory.

The developer report is **not a promotion attestation**. The data/promotion
workflow retains `tools/verification/full_suite_attestation.py`, its final-audit
requirements, and the phase-specific gates. Old attestations and checkpoints
keep their original hashes; new reports bind the current source inventory.

The inventory covers maintained code/configuration in `.github/`, `config/`,
`makhos/`, `native/`, `schemas/`, `scratch/`, `tests/`, `tools/`, and `web/`,
plus the listed root launchers/build wrappers. Node module/test files and YAML
workflows are included. Frozen evidence, user games and local artifacts are
not recursively inventoried. A source digest does not prove that a prebuilt
DLL was built from that source: verify its build manifest separately before
using native results as a candidate gate.

## Where changes belong

| Concern | Maintained owner / entry point |
|---|---|
| Rules oracle | `RULESET.json`, `makhos/core.py` — immutable |
| Search and root policy | `makhos/search.py` |
| Engine configuration, resources, clear/cancel/close | `makhos/engine_manager.py` |
| HTTP/GUI adapter and compatibility facade | `makhos/server.py`, `web/` |
| CLI dispatch / command implementation | `makhos/cli.py` / `makhos/cli_handlers/` |
| Native ABI and implementation | `native/`; [dependency map](docs/architecture/NATIVE_ABI_AND_DEPENDENCY_MAP_TH.md) |
| Native builds | `tools/build/build_orchestrator.ps1`; old build commands delegate |
| Test and evidence tools | `tools/verification/`, `tools/arena/`, `tests/tooling/` |
| Benchmarks and frozen observations | `benchmarks/`; [evidence index](docs/architecture/EXPERIMENT_EVIDENCE_INDEX_TH.md) |

Build into separate candidate paths. `-VerifyOnly` checks a build profile without
compiling; inspect the orchestrator's parameters before selecting a profile.
Keep accepted DLL/model identities and all user games/checkpoints intact.
`work/` and `scratch/` still contain compatibility interfaces and evidence;
trace consumers and manifest bindings before relocating anything.

## Verification by change

| Change | Required evidence |
|---|---|
| Documentation | Check active links and consistency with current-state |
| Tooling or application code | Focused regression, then full suite on an idle validation host |
| Native move/state code | Full suite plus Python/native differential and initial-position perft through depth 10 |
| Behavior-preserving search/build refactor | Deterministic move/score/node/PV parity and measured performance |
| Search, evaluation, TT, SMP, timing or model behavior | Correctness gates, controlled benchmarks, and applicable paired/SPRT gates |

For a structural change, describe the resource owner, callers, supported
profiles, compatibility obligations and validation in the PR. Keep one policy
implementation; compatibility facades delegate. A single game, fast benchmark,
or passing tests does not establish an Elo gain.

## CI scope

[Reference CI](.github/workflows/reference-ci.yml) runs the default developer
checks on Windows and Linux with Python 3.11 and 3.14. It deliberately does not
download local production artifacts or run an arena. Windows full native gates
remain separate; a green CI badge must not substitute for those results.

The workflow uses GitHub's documented [checkout](https://github.com/actions/checkout),
[Python setup](https://github.com/actions/setup-python), and
[Node setup](https://github.com/actions/setup-node) actions, pinned to verified
commit identities rather than moving tags. It runs on pull
requests and pushes to `main`, with read-only repository permissions.
