# NNUE ancestor delta v1 — isolated preparation

Status: STAGED ONLY. Not compiled, not benchmarked, not promoted.
Current gate/run identity is recorded in
`../../.agents/skills/thai-makhos-engine/references/current-state.md`.
Gate B is completed; Gate C takes priority. Do not build or run native tests or
benchmarks here while an arena or interactive GUI workload runs. The v21
bindings below are historical; a future experiment needs an explicit fresh
rebaseline record, not an edit to its original evidence.

## Hypothesis

The frozen NNUE pre-game timed audit recorded 11,111,810 child updates for
5,431,285 evaluations (2.0459 updates/evaluation). Current ensure logic
recursively materializes every missing intermediate ancestor. A direct net
feature delta from the nearest valid ancestor may avoid some work. This is not
proof of a speedup: fewer updates can mean more features per update and less
sibling reuse. No Elo gain is established.

## Isolation and single change

`control/native` is an untouched snapshot of the repository native sources.
`candidate/native` differs only in accumulator materialization scheduling.
Build candidate explicitly with `-DMAKHOS_NNUE_ANCESTOR_DELTA=1` through
`makhos_native_nnue.c`. The switch defaults off. Do not build into repository
`build/nnue_search_v1_r5` or overwrite accepted DLLs. Checked update arithmetic,
model identity checks, features, weights, evaluation, and search rules remain.
The original main source SHA-256 at snapshot was
`7D14358AA5D45EE96B19F90810168EFF7C73A620E23CFDB1BB71744F88466E8B`.

## Required gates after the machine becomes idle

1. Revalidate the current frozen artifact/source identities and workload lease.
2. Reproducibly build snapshot control, candidate-off, candidate-on, and guarded
   candidate-on separately. Never invoke test classes that rebuild live DLLs.
3. Exact integer accumulator/full-refresh parity: quiet moves, captures,
   multi-captures, promotion, clock bucket changes/reset, terminal clock 80,
   null moves, deep lines, PVS retries and sibling-slot invalidation. Test
   invalid ancestry and existing overflow/model-corruption rejection too.
4. Verify control versus candidate-off parity; run candidate-on with the
   existing recursive full-refresh guard. Run applicable full correctness gates.
5. Diverse deterministic fixed-depth comparison: exact move, score, nodes and
   PV; include the existing regression corpus, not only the initial position.
6. Isolated repeated paired timing/profile: count features changed as well as
   materializations/evaluations; include one-thread and production settings.
   Reject if throughput is not consistently improved or parity fails.
7. Predeclare a separate paired strength experiment for fixed-time effects;
   never merge it into the frozen Gate C. No promotion without applicable
   benchmark/strength and production evidence.

Any prepared fixture check is only a feature-algebra preflight. It does not
prove native execution, stack validity, overflow behavior, or playing strength.

## Preparation evidence — 2026-09-05

Command: `C:\Python314\python.exe -B work\nnue_ancestor_delta_v1\preflight.py`
from the repository root. Exit 0: 3,832 perspective/direction checks across
eight seeded random trajectories and explicit quiet/capture/promotion/multiple
capture fixtures. The fixture includes two promoting moves, two capturing
moves (one multi-capture), and clock bucket boundaries. This does not exercise
the native implementation; native terminal/null/sibling tests remain pending.

The preflight also verified all original native files equal the control
snapshot, all other candidate source files equal control, and the accepted
DLL/frozen NNUE DLL/model hashes match their locked identities. Repository
source and test inventory hashes remain the full-suite v21 identities:

- Source: `BE1F791F157E17775BAFB17A56F2E461FC14A66F4B973E733F4FCE9BA09367FB`
- Tests: `E461DD8FFF212682C0D12DA158A8E0E0B25A0B2AF5A64695D362D64F6BA3629D`
- Staged modified native source:
  `FED2B2B9CCD9190547BF9E91CCDFA37F82BAD21ECDCF8C2803661D0506CC7BA2`

Historical preparation next action: prepare native parity fixtures. The active
forward plan now requires completion of Gate C and the post-promotion scaling/
profile audit before selecting this candidate. Execute its native sequence only
if that evidence supports it and workload isolation permits. No performance or
Elo claim is made.
