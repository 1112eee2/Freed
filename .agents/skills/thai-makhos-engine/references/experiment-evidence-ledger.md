---
name: thai-makhos-engine
description: >-
  Develop, debug, benchmark, and strengthen the ThaiMakhosEngine project toward
  a world-class Thai Makhos engine. Use for native search, Threads/Hash,
  evaluation, move generation, time management, UCI/UGI, web play, self-play,
  pentanomial SPRT, tablebase integration, or NNUE work in D:\ThaiMakhosEngine.
---

# Thai Makhos Engine

## Mission

Build a Thai Makhos engine that can credibly compete for strongest in the world.
Optimize for playing strength across short and long time controls, not for a
single position, raw NPS, or an attractive GUI number.

Treat “world strongest” as an evidence target. Do not claim it from self-play
alone. Require reproducible internal testing and, eventually, matches against
the strongest available independent Thai Makhos engines and players.

Use `10s + 0.1s` as the primary STC acceptance time control unless the user
sets another standard. Use fixed-depth and shorter-clock runs only as screening
tests; do not treat them as Elo evidence.

## Non-negotiable correctness rules

### Make no mistake — no silent strength regression

Treat this as an acceptance invariant inside the world-class-strength mission,
not as a separate optional task:

- Never run acquisition, corpus generation, tablebase construction, profiling,
  arena, or SPRT workloads concurrently with a user-facing GUI strength test.
  The GUI has absolute priority and must hold the interactive workload lease.
- Bind every strength result to the accepted DLL SHA-256, source/config hashes,
  rules profile, Threads, total Hash, time control, backend, completed depth,
  machine load, and whether runtime isolation was active. An unbound result is
  diagnostic evidence only and cannot establish a regression or promotion.
- A byte-identical accepted DLL protects code identity, not runtime strength.
  Rebaseline after changes to the server, root splitter, process scheduling,
  time management, Threads/Hash allocation, or background workloads.
- Never replace the accepted DLL until correctness, deterministic screening,
  and the applicable paired pentanomial SPRT all pass in an isolated run. A
  single external win, loss, draw, or tactical position never promotes or
  reverts playing code by itself.
- Preserve the last accepted control and reproducible external regression set.
  If results swing, stop unrelated batch work first, reproduce under isolation,
  and classify environment variance separately from search variance before
  changing HCE or heuristics.

- Never edit `RULESET.json`.
- Never edit `makhos/core.py`; keep it as the verified Python rules reference.
- Preserve the Thai king-halt rule, mandatory capture, immediate removal of a
  captured piece, end-of-turn promotion, threefold repetition, and the 80-ply
  no-progress rule.
- Treat native move generation as mutable only behind Python/native randomized
  differential tests and the published initial-position perft sequence through
  depth 10.
- Keep proof/DFPN and tablebase artifacts intact. Do not resume a large builder
  or delete/move tablebase data unless the user explicitly requests it.
- Inspect running engine/tablebase processes before CPU- or RAM-heavy work. Do
  not stop an active user workload without explicit approval.
- Run the full automated suite after every code change. Report failures and
  incomplete verification honestly.

## Current architecture

- `native/makhos_native.c`: authoritative fast bitboard move generator,
  evaluation, iterative-deepening alpha-beta/PVS, quiescence, TT, null move,
  LMR, killers, history, and persistent native-search ABI.
- `makhos/native.py`: ctypes bridge for one-shot and persistent native search.
- `makhos/parallel_native.py`: Python root-split Threads implementation with an
  independent persistent TT partition per worker. This is not shared-TT SMP.
- `makhos/search.py`: engine integration, clocks, exact/tablebase policy, and
  Python reference search.
- `makhos/sprt.py`: paired-game pentanomial SPRT harness.
- `makhos/server.py` and `web/`: local GUI and Threads/Hash settings.
- `build/makhos_native_accepted.dll`: production default for newly started GUI
  and CLI processes. `build/makhos_native.dll` remains the development slot.
  Verify paths, hashes, and loaded process modules before every experiment;
  never infer acceptance or the active DLL from a filename alone.

The full native C search and UCI/UGI integration already exist. Do not follow an
old roadmap that lists either as future work.

## Evidence-first workflow

### 1. Establish the baseline

Before editing search behavior:

1. Read the exact source and tests on the active path.
2. Record candidate and control DLL paths, file hashes, compiler flags, ABI,
   time control, Hash, Threads, opening seed/suite, and test command.
3. Preserve a byte-for-byte control DLL and enough source or patch information
   to reconstruct it.
4. Change one search idea at a time. Do not stack unaccepted heuristics.

### 2. Pass correctness gates

Run targeted tests while iterating, then run:

```powershell
python -B -m unittest discover -s tests -v
```

For native move-generation or state-transition changes also run the native
perft sequence and randomized Python/native differential tests. For TT,
repetition, persistence, or pruning changes include regression positions near
threefold and the 80-ply boundary.

### 3. Measure performance correctly

Use a deterministic suite containing opening, tactical capture, quiet
middlegame, king-heavy endgame, and repetition/no-progress boundary positions.
Record at least:

- completed depth, nodes, elapsed time, and NPS;
- best move, score, and PV stability;
- TT probes, hits, cutoffs, replacements, and collisions when counters exist;
- beta cutoffs by move index and re-search counts;
- worker utilization, effective Hash, and peak memory for Threads tests.

Prefer fixed-depth runs for speed comparisons and fixed-time runs for scaling.
NPS or node reduction alone is not a strength result. Require identical moves
and scores at controlled depths before trusting a speed optimization.

Classify every experiment before choosing its acceptance gate:

- A representation, allocation, telemetry, or other behavior-preserving
  refactor must match the accepted engine node-for-node, move-for-move, and
  score-for-score over the deterministic suite. Reject a repeatable slowdown.
  SPRT is not required when search behavior is proven identical.
- Any change that can alter pruning, ordering, evaluation, time allocation, or
  selected moves is a strength change and must pass paired pentanomial SPRT.
- Threads/Hash changes must additionally report total native allocation at
  1/2/4/8/12 Threads. Treat Hash as a total budget, not a per-worker budget.

### 4. Accept strength changes only through paired pentanomial SPRT

Use color-swapped game pairs from the same randomized opening. Preserve all
five pair-score buckets in order:

`LL, LD+DL, LW+DD+WL, DW+WD, WW`

Use the generalized logistic pentanomial LLR. Do not reconstruct pentanomial
results from aggregate W/D/L and do not call an approximate WDL error bar
Fishtest-style evidence.

Screen a candidate cheaply, then run the project acceptance test at
`10s + 0.1s`, normally with `H0=0 Elo` and `H1=2 Elo`. Continue until PASS,
FAIL, or the declared maximum pairs; do not accept a candidate from a positive
point estimate whose confidence interval still crosses zero.

Use:

```powershell
python -u -m makhos sprt --pairs 10000 --elo0 0 --elo1 2 --time 10 --inc 0.1 --dev-library build\makhos_native.dll --master-library build\makhos_native_baseline.dll
```

Make the test path representative of production. Explicitly test and document
one-shot versus persistent TT behavior instead of silently mixing them.

### 5. Promote or reject cleanly

- Promote a strength change only after SPRT PASS and all correctness gates.
- Promote a behavior-preserving refactor only after deterministic equality,
  representative timing, memory measurements when relevant, and the full
  automated suite all pass.
- Keep the previous accepted binary until the promoted build is reproduced and
  smoke-tested.
- Reject or revert a FAIL before starting the next search idea.
- Treat inconclusive results as inconclusive; retain logs but do not merge the
  idea into the accepted baseline.

## Bottleneck priority order

Work in this order unless new measurements overturn it.

### P0 — Make testing trustworthy and representative

- Keep pentanomial paired outcomes and exact LLR calculations.
- Add a fixed, versioned opening suite plus deterministic seeds.
- Compare the same persistence, Threads, Hash, tablebase, and time-management
  configuration used in actual play.
- Add machine-readable match logs and resume support without losing pair data.
- Add search telemetry before guessing which heuristic needs work.

An optional ABI 6 profiling build now exposes per-search and aggregated
root-parallel telemetry. Compile with `MAKHOS_SEARCH_TELEMETRY=1` and run
`makhos profile-native`; normal production keeps the switch off. The counters
cover qnodes, move generation and ordering load, TT probes/hits/cutoffs/
collisions/stores/replacements, null attempts/cutoffs, beta-cutoff index, PVS
and LMR re-searches. On 96 deterministic depth-15 positions (seed 20260920,
hash power 17), qsearch was 62.11% of 19,185,628 nodes and 17,891,689 move-list
generations produced 104,508,417 moves. First-move beta cutoffs were already
90.13%, null cutoff success 48.91%, TT hits 39.71%, and TT cutoffs 17.80% of
probes. This evidence deprioritizes further generic move-order tuning: profile
qsearch/move-generation waste and positional evaluation next. Instrumentation
matched accepted search node-for-node but added about 0.6% fixed-depth time,
so retain it as a profiling build rather than enabling it in production.

Treat repeated losses to an independent opponent such as GAMEINDY's
`เซียนเฒ่า` as valuable external evidence, but preserve exact games before
tuning. Replay both colours, record both clocks, and compare the accepted move
at 2 seconds, the opponent-like 5 seconds, and a substantially longer analysis
limit. If the long search converges on the opponent move, improve search/time
efficiency; if it continues to prefer the losing plan, prioritize evaluation
and labelled position data. Build a versioned regression suite from positions
before the first strategic divergence, not only the final tactical loss, and
do not overfit evaluation to one opponent. The GUI's `คัดลอกเกม` action exports
`thai-makhos-game-v1` JSON with start/final positions, moves, and engine settings
for this workflow.

When a game record is available, read
`references/positional-diagnosis.md` before tuning. Validate and replay the
record first, then use `makhos analyze-game` to compare isolated search budgets
on the engine-controlled plies. Treat per-ply actor/settings as authoritative;
the final GUI settings are only a fallback for older records. Keep the trace
and analysis formats versioned so regression evidence remains reproducible.

`analyze-game` reports every root move score/PV when Threads is greater than
one. Use those root Multi-PV scores to measure the margin between the short
search choice and the stable longer choice; do not tune only from the winning
move name. Find the first completed depth where the ranking stabilizes, then
measure the wall-time threshold for that depth.

The GUI has separate `project` and `external-no-repetition` rules profiles.
Use the latter only to reproduce external sites that demonstrably play past
threefold; it retains the 80-ply safety limit and is not a claim about the
site's exact current draw counter. Export the selected rules profile with every
game. Historical launch material for GAMEINDY described a separate 25-move
count after both sides reach two pieces, but the current live implementation
still requires direct verification.

### P1 — Reduce hot search memory and wasted work

The 2026-08-13 audit found these concrete issues in the original native design:

- `Move` stores a full child `Position` and occupies 52 bytes.
- `MoveList` reserves 4,096 moves and occupies 212,996 bytes.
- Ninety-six per-ply `MoveList` objects reserve about 19.5 MiB per worker.
- Twelve workers reserve about 234 MiB for move-list workspaces alone, before
  TT, PV, tablebase mappings, and Python overhead.
- A TT entry is 72 bytes because it stores a full `Move`; power 20 consumes
  72 MiB. Keep Python Hash budgeting synchronized with the exact C layout.
- The 96x96 full-`Move` PV table adds about 0.46 MiB per worker and repeatedly
  copies move chains on best-score updates.

ABI 4 replaced the eager 96-list allocation with pointer-stable, lazily
allocated per-ply lists. A representative depth-15 search allocated 21 lists:
about 4.27 MiB of move workspace per worker instead of 19.5 MiB, or about
51 MiB instead of 234 MiB across 12 workers. Preserve node-for-node behavior
and timing neutrality when changing this storage again.

ABI 5 replaced the 52-byte full `Move` inside each TT entry with an exact
24-byte compact path/capture encoding. The TT entry is now 40 bytes instead of
72 bytes. C static assertions, a maximum-length compact-move self-test, and an
exported entry-size check guard Python Hash budgeting against layout drift.
At Hash 64 MiB, 12 workers now receive 1,572,864 total TT entries instead of
786,432 while measured native allocation after a 200 ms start-position search
was about 93.8 MiB including lazy move workspaces.

ABI 5 also precomputes each move-order weight once, then insertion-sorts moves
and a shared 4,096-entry score scratch array together. This preserves the exact
stable ordering while avoiding repeated TT/killer/capture/history scoring in
the inner comparison loop. It adds 16 KiB per worker, matched accepted search
node-for-node on 192 deterministic positions, reduced fixed-depth wall time by
about 10.5-12.0%, and reached one extra completed ply in 500 ms at 1 and 4
Threads. Treat `MAKHOS_PRECOMPUTED_ORDERING=1` as accepted behavior.

The accepted native search also probes TT before materializing a full move
list. It performs the exact lightweight legal-move-existence check only when a
valid TT entry would actually cut off, preserving the old terminal-before-TT
precedence even under a theoretical 64-bit key collision. The helper matched
`generate_moves` on 1,000,000 randomized bitboard positions; the candidate
matched move, score, and nodes on 96 deterministic depth-15 positions over five
repetitions and reduced median fixed-depth wall time by about 2.8% without a
memory increase. Calling the helper at every node instead was about 6.4% slower
and is rejected. Treat `MAKHOS_EARLY_TT_CUTOFF=1` as accepted behavior.

The accepted PV table stores the directly copyable 36-byte path/capture
payload (`MakhosPackedMove`) instead of the 52-byte full `Move`; PV lines never
need the embedded child `Position`. This removes 147,456 bytes per worker, or
about 1.69 MiB across 12 Threads, while preserving complete returned PVs. It
matched move, score, nodes, and PV on 96 deterministic depth-15 positions over
five repetitions; fixed-depth time ratio was 0.9983, so treat the change as
timing-neutral. A more aggressive 24-byte bit-packed PV saved 258,048 bytes per
worker but was repeatably about 0.7-1.2% slower at depth 15-16 and is rejected.
Likewise, using the 36-byte format through a clearing/field-copy helper was
about 4.3% slower; preserve the single contiguous 36-byte copy guarded by the
layout static assertions. Treat `MAKHOS_COMPACT_PV=1` as accepted behavior.

The accepted repetition path now skips history scans entirely when repetition
is disabled, bounds in-search repetition scans by the reversible clock and
same-side parity, and builds an exact open-addressed lookup for game histories
of at least 32 unique positions. Project-rule fixed-depth search matched move,
score, and nodes on 64/64 positions; short-history timing was neutral and a
20..70-ply suite was about 4.2% faster. In the external game ply-21 fixture,
the no-repetition profile reached depth 25 and the stable `27-23` in 5 seconds,
where the former build stopped at depth 24 and chose `25-21`.

Do not merely lower `MAX_MOVES` from 4,096: the observed maximum from random
positions is not a proof of the legal maximum. First derive a safe bound or use
a proven overflow-safe representation.

Prioritize experiments that:

1. Extend compact move storage from the completed TT/PV work to killers.
2. Reduce full-`Move` traffic in generated move lists without changing the
   verified generator or reconstructing child positions redundantly.
3. Measure lazy workspace allocation and total native memory under 12-thread
   timed play so memory regressions are caught before SPRT.

The accepted full-Move TT exposes a subtle separate search behavior: a null
search can replace a direct-map entry while move ordering still points into it.
ABI 5 deliberately preserves that behavior for node equality. Test a stable
local TT-move snapshot only as its own strength experiment with SPRT.

The 2026-08-13 stable-snapshot screen was not promoted. At 0.2s+0.01s,
persistent TT, hash power 17, seed 20260831, it finished 60 pairs as W41 D32
L47 with pentanomial `5/10/35/6/4`, LLR -0.39, and Elo -17.4 +/-41.0 (95%).
The result was INCONCLUSIVE but negative, while fixed-depth power-17 work was
neutral, so do not rerun the same candidate without a new mechanism or evidence.

### P2 — Improve single-thread search quality

Establish a strong one-thread baseline before using extra cores to hide search
inefficiency. Test each item separately:

- aspiration windows with widening fail-low/fail-high recovery;
- depth- and move-index-dependent LMR with full-depth verification;
- better TT replacement and compact generation/age policy;
- internal iterative reduction when no reliable TT move exists;
- capture-aware pruning and move ordering suited to mandatory captures;
- futility or reverse futility only with conservative endgame, promotion,
  repetition, and no-progress guards;
- continuation/countermove history after search telemetry justifies it.

Never copy chess constants blindly. Tune Thai Makhos parameters through SPRT.

Do not repeat these rejected 2026-08-14 experiments unchanged:

- a 64-centipawn aspiration window was about 3.6% slower in the screen and
  changed selective fixed-depth results;
- replacing the narrow passed-man rays with the complete forward reachability
  cone improved one diagnostic move but screened at W5 D27 L8 at 0.05s+0.002s
  and W2 D13 L9 at 0.2s+0.01s;
- a 24-byte signature-only TT was node-identical and about 2.7% faster at equal
  depth, but timed screening finished W6 D20 L14 (about -70 Elo +/-39 at 95%).
  This is evidence of depth/odd-even instability, not grounds to promote the
  representation merely for higher NPS.
- reducing only the second LMR reduction made the external-game ply-21 search
  take about 18 seconds at depth 24 instead of roughly one second and did not
  stabilize the root ranking;
- disabling null move, using a shallower deep null reduction, and using an
  aggressive reduction of four plies all failed the combined speed/stability
  screen.  The aggressive variant reached greater nominal depth but still
  diverged from the stable `27-23` plan at 20 seconds.  Do not equate its depth
  gain with strength.

### P3 — Replace Python root split with native SMP

The current Threads implementation independently searches every root child,
partitions Hash, and cannot share root alpha efficiently. On the audited start
position, 1 Thread completed depth 16 in 400 ms, while 2/4/8/12 Threads reached
depth 14/15/15/15 despite higher aggregate node counts. With seven legal root
moves, 12 configured workers can use only seven for search but all twelve own
memory.

Build native shared-TT SMP only after P1/P2 stabilize. Start with a simple
Lazy-SMP design, shared stop/deadline state, per-thread search stacks/history,
and a shared TT. Measure scaling at 1/2/4/8/12 Threads on multiple positions and
SPRT multi-thread behavior; do not equate aggregate NPS with Elo.

The 2026-08-14 selective-root prototype is not accepted.  It added an optional
fixed-depth persistent API and reserved part of a timed root-split search for
the top candidates, accepting a selective layer only when every shortlisted
move completed it.  Correctness and timeout fallback passed the full 142-test
suite, and the external-game ply-21 fixture found stable `27-23` at one second.
However, match evidence was time-control sensitive: two 50 ms seeds aggregated
to pentanomial `0/5/22/13/0` (about +34.9 +/-34.9 Elo), while two 100 ms seeds
with reserve 0.60 aggregated to `0/6/16/2/0` (about -29.0 +/-38.9 Elo).  A
controlled reserve-0.40 rerun on one negative seed improved decisiveness but
remained negative-inconclusive at `0/2/9/1/0` (about -14.5 +/-48.9 Elo).  Keep
the feature off by default and do not promote or run the 10s+0.1s acceptance
test without a new mechanism that removes shortlist/odd-even instability.

The SPRT CLI now records DLL hashes and can reproduce multi-thread screens with
total Hash, 1..12 Threads, candidate-only selective-root controls, a per-move
screening cap, and sequential colour-swapped games to avoid CPU over-subscription.

The first shared-TT prototype is also not accepted.  A guarded native build
used striped locks and optional 2/3/4-worker TT clusters while the default build
kept independent partitions.  A one-context 64-position depth-15 suite matched
move, score, and nodes in all cases and measured about 0.75% slower.  One TT
shared by 8-12 workers lost throughput to contention; two-worker clusters were
the best scaling variant and reached depth 22 instead of 21 on the ply-21
fixture at 500 ms, but root choices remained unstable.  Two 50 ms seeds
aggregated to pentanomial `0/6/24/9/1` (about +21.7 +/-36.8 Elo), while two
100 ms seeds aggregated to `2/3/15/3/1` (about -14.5 +/-60.6 Elo).  The full
144-test suite passed, but the time-control reversal means this remains an
off-by-default research path.  Do not promote it or combine it with selective
root without a new mechanism and an independent paired screen.

A later nonblocking shared-TT try-lock screen was also rejected and fully
removed. A busy stripe was safely treated as a TT miss/store skip (never an
unlocked 40-byte read), which confirmed substantial contention but produced
unstable leader results: at the 12-thread, 512-MB, one-second Sian-Thao fixture
it selected `27-23` in only 4/10 fresh trials, with the remaining trials spread
across `25-22`, `27-24`, and varying completed depths. Do not retry that exact
try-lock policy; it does not solve the leader-only/root-instability problem.

### P4 — Improve evaluation and data

After search and test infrastructure are trustworthy:

- build a diverse, deduplicated position corpus from accepted-engine games,
  tactical suites, human games, and exact 4/5/6-piece labels;
- tune handcrafted terms from held-out data before declaring saturation;
- introduce an efficiently updatable NNUE-style evaluator only with a scalar
  fallback, deterministic feature specification, quantization tests, and
  self-play SPRT;
- guard against learning only the accepted engine's own blind spots.

The first exact-WDL evaluation corpus is now reproducible. It contains 9,000
deduplicated quiet non-terminal positions sampled evenly from verified 4/5/6-
piece ranked tablebases, with 7,200 train and 1,800 hash-held-out validation
positions and balanced W/D/L labels. The linear fit reduced validation cross
entropy from 0.35957 to 0.32037 and raised decisive-label accuracy from 95.92%
to 98.58%; all five material-signature-held-out folds improved. Treat this as
endgame calibration evidence, not as direct middlegame-strength evidence.

Do not repeat the 2026-08-14 king-term candidates unchanged. Lowering only
the tapered endgame king value from 330 to 204 was positive at 50 ms, near
neutral at 100 ms, then repeated a negative direction in two independent
200 ms seeds. The 200 ms aggregate was W11 D24 L13, pentanomial
`1/5/13/5/0`, about -14.5 +/-53.3 Elo (95%), LLR -0.044, INCONCLUSIVE.
Adding the fitted edge term of +31 repeated a negative direction in two
independent 100 ms seeds: aggregate W13 D18 L17, pentanomial `2/5/13/3/1`,
about -29.0 +/-63.5 Elo, LLR -0.056, INCONCLUSIVE. Neither candidate is
accepted or eligible for a long acceptance run.

The external Sian-Thao ply-21 fixture also shows why coefficient guessing is
the wrong next step. The accepted static evaluator already prefers the
played `27-23` child (-6) over the one-second search choice `25-21` (-24), but
the complete root ranking flips only from depth 24 to depth 25. Prioritize
removing this horizon/search-throughput bottleneck and building middlegame or
game-result-labelled data before changing more handcrafted weights. Never
taper 4/5/6-piece coefficients into the middlegame merely because held-out
tablebase loss improves.

The current highest-value pre-NNUE candidate is a quiescence-only generator
optimization. ``MAKHOS_QSEARCH_CAPTURE_ONLY=1`` enumerates mandatory capture
sequences directly; when there is no capture it uses the existing lightweight
legal-move test to distinguish a quiet leaf from a terminal loss, avoiding
materialization of every quiet move that quiescence would never search. On
64 deterministic positions at depth 15 over three repetitions it matched the
accepted DLL's move, score, and node count in 64/64 cases and reduced total
fixed-depth wall time from 3012.7 ms to 2793.6 ms (0.9273x, about 7.3%
faster). A 12-pair 100 ms screen was W8 D9 L7 (+14.5 +/-63.8 Elo), an
independent seed was W5 D17 L2 (+43.6 +/-73.2 Elo), and the aggregate was
pentanomial `0/3/15/5/1`, LLR +0.099, about +29.0 +/-48.4 Elo,
INCONCLUSIVE. Keep it as a separately reproducible candidate until the
project's long 10s+0.1s acceptance gate is passed; do not overwrite the
accepted DLL from the short screen alone.

The follow-up qsearch candidate removes one redundant scan from that same
path. Once capture-only generation has returned zero moves, the terminality
check now tests quiet mobility directly instead of rescanning every capture
ray. The separate DLL `build/makhos_native_qsearch_capture_quiet_candidate.dll`
preserved move, score, and node count on the deterministic fixed-depth test;
on the same 64-position/depth-15/three-repetition benchmark it was 0.9235x
the first qsearch candidate (2766.8 ms to 2555.3 ms, about 7.6% faster) and
0.8598x the accepted DLL (2987.9 ms to 2569.1 ms, about 14.0% faster), with
64/64 equal-node, equal-score, and equal-move cases. Two independent
four-pair 10s+0.1s pilots were both inconclusive; combined they were W5 D7
L4, pentanomial `0/1/5/2/0`, LLR +0.029, about +21.7 +/-73.6 Elo. Keep this
candidate isolated until a properly sized long gate passes.
Its first 4-pair 10s+0.1s pilot was W3 D3 L2, pentanomial `0/1/1/2/0`,
LLR +0.01, about +43.6 +/-153.2 Elo, INCONCLUSIVE.
The 16-pair follow-up completed W10 D11 L11, pentanomial `0/5/7/4/0`,
LLR -0.02, about -10.9 +/-64.4 Elo, still INCONCLUSIVE. On the external
ply-21 fixture at 1 second it still stopped at depth 24 and selected `25-21`,
so the speed-only change does not yet remove that strategic horizon. Do not
promote it as a strength gain; use the measured throughput only as a future
NNUE/search baseline.

The next qsearch-only candidate replaces the quiet-mobility coordinate loops
with precomputed red/black-man and king adjacency bitboards. It is compiled
as `build/makhos_native_qsearch_fast_quiet_candidate.dll` and leaves the
accepted path unchanged. On 64 deterministic positions at depth 15 over
three repetitions it matched the iterative qsearch candidate's move, score,
and node count in 64/64 cases and measured 0.9962x wall time against that
candidate; against the accepted DLL the same run measured 0.8681x wall time
(15,572,644 equal nodes). The external ply-21 ladder still reached `27-23`
at 1.5 seconds rather than one second, so this is a small throughput
improvement, not a horizon fix. A 12-thread 10s+0.1s, 16-pair screen finished
W8 D9 L15, pentanomial `2/5/7/2/0`, LLR -0.09, about -77.2 +/-78.7 Elo,
INCONCLUSIVE. Keep it isolated and do not promote it without a longer gate;
the short result is not evidence of a real strength loss either.

The original fast-man and fast-king geometry DLLs are historical throughput
screens only, not promotion candidates. The flags were first placed inside
`capture_recursive()`, which is also called by the authoritative
`generate_moves()` path. Thus the old `fast_capture`/`fast_king` binaries
changed normal move generation as well as qsearch, despite the intended scope.
Their 64-position fixed-depth measurements remain useful profiling data, but
they are not sufficient correctness evidence. Never promote those unscoped
binaries.

The corrected implementation keeps `generate_moves()` on a byte-for-byte
coordinate-style `reference_capture_recursive()` path, while
`generate_capture_moves()` alone calls `qsearch_capture_recursive()` with the
precomputed man-jump and Thai king-halt ray tables. The current isolated
candidate is `build/makhos_native_qsearch_fast_capture_exists_candidate.dll`
(compiled with `MAKHOS_QSEARCH_CAPTURE_ONLY=1`,
`MAKHOS_FAST_QUIET_MOBILITY=1`,
`MAKHOS_QSEARCH_FAST_MAN_CAPTURE_GEOMETRY=1`,
`MAKHOS_QSEARCH_FAST_KING_CAPTURE_GEOMETRY=1`,
`MAKHOS_QSEARCH_FAST_CAPTURE_EXISTS=1`, and
`MAKHOS_EXPERIMENTAL_SEARCH_APIS=0`). Its source uses
`native_has_capture()` to return directly from captureless qnodes before a
full `MoveList` allocation, but retains the existing qsearch generator and
ordering whenever a capture exists.

The scoped candidate was tested through native perft depth 10 (ending at
861,842,812 leaves), a 504-position Python/native normal-move differential
(2,575 legal moves plus 10 exact three-piece checks), and a direct qsearch
capture-generator differential on five king/mixed fixtures plus 500 dense
random valid states, comparing complete move paths, captures, promotion flags,
and child states. The full suite passed 167 tests. The rebuilt current
candidate DLL SHA-256 is
`3E072D8ED120D21695A9FA658A4E9B7B0BD3C9F6FB9FB4DA12D2CAB7950E98A0`.
On the deterministic 64-position/depth-15/three-repetition screen it matched
the accepted DLL's move, score, and node count in 64/64 cases (15,572,644
equal nodes) and measured 0.8151x wall time (about 18.5% faster; timing must
always be treated as a range rather than a single guaranteed percentage).

This is still only a throughput candidate. On five fresh 12-thread/512-MB,
1,300-ms external-no-repetition trials of the critical Sian-Thao ply-21
fixture, it reached `27-23` at depth 25 in 3/5 trials; the scoped fast-king
control also reached it in 3/5. The pairwise result was neutral, so it does
not establish a new deadline threshold and does not meet the one-second target.
Keep the accepted DLL unchanged pending a reproducible behavior-preserving
promotion decision or a long production gate.

A compiler-only PGO build of exactly that scoped source is also available as
`build/makhos_native_qsearch_pgo_candidate.dll` (SHA-256
`11B2A761BAEA35264A0B4E6C1C4530C8A2C0B529848CC87C1F985FC8FC95792F`).
It was trained on a deterministic 64-position depth-15 corpus, then evaluated
on a distinct 64-position holdout. Both screens preserved move, score, and
node count in 64/64 cases; the training screen measured 0.9486x and the
holdout 0.9402x the scoped non-PGO candidate's wall time. The PGO executable
also passed perft depth 10 (`861842812`), a 504-position Python/native
differential (2,905 legal moves plus 10 exact three-piece checks), and the
direct qsearch capture-generator differential; the source-suite passed 167
tests. On five fresh 12-thread/512-MB/1,000-ms external trials it still
completed only depth 24 and chose `25-21`. At 1,300 ms it completed depth 25
and chose `27-23` in 10/10 fresh trials, versus 9/10 for the non-PGO scoped
candidate. This is reproducible behavior-preserving throughput evidence, but
it does not satisfy the one-second target or by itself establish Elo gain, so
the accepted DLL remains untouched.

### 2026-08-20 throughput/session update

A later, narrower qsearch-only refinement is available as
`build/makhos_native_qsearch_fast_capture_exists_man_geometry_candidate.dll`
(SHA-256 `06455DD18D8BDC161C3B302A13E4AE777B7BF05193795B0E981DAFA019B3C0A2`).
It replaces only the **man** geometry in qsearch's capture-existence check;
kings retain the coordinate reference scan, and normal move generation is
unchanged. Its PGO build is
`build/makhos_native_qsearch_fast_capture_exists_man_geometry_pgo_candidate.dll`
(SHA-256 `31D7481A118629B84B504F095A3E20C235BDDE0581A874F88769A0C3B74846B9`).
The plain candidate matched the preceding scoped candidate's move, score, and
node count in 64/64 cases at depth 15 and measured 0.9723x on the training
seed and 0.9650x on an independent holdout. The matched-source PGO build then
measured 0.9366x and 0.9391x of that plain candidate on the same two screens,
again with 64/64 equal nodes, moves, and scores. It passed perft depth 10
(`861842812`), the 504-position Python/native differential (2,905 legal moves
plus 10 exact checks), direct randomized qsearch capture-existence tests, and
the 169-test suite. This is behavior-preserving throughput evidence only.

On the critical external-no-repetition Sian-Thao ply-21 fixture at
12 Threads/512 MB/1,000 ms, the PGO/man-geometry candidate still completed
only depth 24 and chose `25-21` in 5/5 fresh trials. It first chose depth-25
`27-23` in 5/10 fresh trials at 1,200 ms. Thus it meaningfully narrows the
deadline but does not meet the one-second requirement and must not replace the
accepted DLL without the normal long strength gate.

Two native iterative-session designs were screened and rejected. An
immediate-start session retained completed ID layers but still returned depth
24/`25-21` at one second; an attempted warm attach after ordinary layers was
worse, returning depth 23/`19-15` in three fresh one-second trials. They are
candidate-only, macro-disabled code and are not production paths. Do not retry
either unchanged: a useful next parallel-search project must preserve the
relevant native context correctly or move to a separately designed native
Lazy-SMP implementation with private worker state and an explicit shared-TT
safety proof.

Two narrow source micro-candidates were also rejected after exactness gates:
a deep persistent-root-PV ordering cache did not improve any of five fresh
1,000-ms or 1,300-ms critical-fixture trials, and a quiet two-square compact
TT-store packing fast path measured 1.0005x against the scoped candidate
despite 64/64 equal node/move/score cases. Do not retry either unchanged; the
next material throughput step needs a genuine native-SMP/search-design
mechanism rather than another root hint or packing micro-optimization.

To measure the optimization on the real production path, the experimental
fixed/window API is now compile-time guarded by `MAKHOS_EXPERIMENTAL_SEARCH_APIS`.
The separate candidate
`build/makhos_native_qsearch_capture_quiet_iterative_candidate.dll` sets that
switch to zero, so both candidate and accepted control report
`fixed_search=false` and `window_search=false` in the paired match. It matched
move, score, and node count on the 64-position depth-15 suite (three
repetitions) and measured 0.8837x wall time (3409.6 ms to 3013.1 ms, about
11.6% faster). On the critical fixture, the candidate reached depth 25 and
`27-23` at 1.3 seconds in the cold ladder while accepted remained depth 24 and
`25-21`; the 1.0-second result is not yet stable. A 16-pair 10s+0.1s pilot
completed W8 D22 L2, pentanomial `0/1/9/5/1`, LLR +0.09, about +65.9 +/-62.1
Elo, still INCONCLUSIVE. Keep the accepted DLL unchanged until either the
behavior-preserving promotion gate is explicitly satisfied or a stronger
production-path result is established.

The replayed external game analysis (18 black plies, 1s and 5s budgets) shows
the iterative candidate is not simply changing every move: most rankings and
scores are identical, while it gains a completed ply at selected positions
(for example ply 37 at 1s). It still chooses `25-21` at the critical ply 21
at 1s and only converges to `27-23` after the deeper layer, so this is useful
throughput/horizon evidence rather than an external-game win claim.

The first middlegame search-stability corpus is now generated by
`makhos build-middlegame-corpus` from the validated external-game analysis.
`corpora/middlegame_search_v1.jsonl` contains 18 deduplicated middlegame
positions from game `374f92e56f20496b`; 13 have the same move at 1s, 5s, and
20s and are marked usable as observational training/regression samples. The
remaining five are explicitly marked as long-horizon divergences or
settings/version mismatches and are not treated as ground-truth best moves.
The `--stable-only` output reproduces the 13-sample subset. This is a data
pipeline and a regression seed, not enough evidence to tune handcrafted
weights or claim a win over Sian-Thao; add independent games before fitting
NNUE or supervised policy targets.

A candidate root aspiration-window patch was also screened and rejected. On
the deterministic 64-position depth-15 fixed-depth comparison it was not a
behavior-preserving replacement for the production iterative path; on the
12-thread, 1-second external ply-21 fixture it completed only depth 23 and
selected `25-22`, versus the non-aspiration candidate's depth 24 and `25-21`.
The patch was reverted, the accepted DLL was never touched, and the full
161-test suite passed after the revert. Do not retry this exact narrow-window
design without a fresh root-search proof and paired strength evidence.

A separate persistent-resume API prototype attempted to avoid restarting each
root child at depth one in the Python root splitter. It was reverted because
the reduced-history/LMR path changed move or score on 7 of 16 deterministic
depth-12 positions and was slightly slower overall (605.9 ms versus 599.7 ms,
8 threads); the critical 12-thread one-second fixture still stopped at depth
24. Do not revive this API without preserving heuristic state or replacing
the Python root split with a native SMP design.

A windowed native-search API and candidate-only root-alpha/PVS experiment are
also present but remain off by default. The first parallel-window version
screened negative-inconclusive (two 100 ms seeds aggregated to `1/5/13/5/0`,
about -14.5 +/-53.3 Elo). A later first-move-full variant did not improve the
critical ply-21 depth and is not an accepted path. Do not combine root-alpha
with selective-root or shared-TT experiments; revisit only with a deterministic
root scheduling design and fresh paired evidence.

A later parallel bound-scout prototype was rejected and completely removed
from `parallel_native.py` before release. Its idea was to scout every root
with a zero window against the prior score minus a margin, then fully re-search
only challengers. On the initial position at depth 10, however, the scout path
returned `25-22` / 0 while the normal full-root path returned `26-23` / +3.
The window probes changed persistent TT/history/heuristic behavior enough that
a subsequent full search was not a reliable exact re-search in this engine.
Do not retry that design, or claim alpha-beta bound proof, without first making
the native search's window/full-search state interaction reproducibly exact.

### 2026-08-20 main-TT key integrity update

`search_position_key()` formerly OR-ed a nonzero salt into the packed
king/turn/reversible-clock state before mixing it. OR masks source bits that
are already one in the salt: 21 king flags and several reversible-clock bits
could therefore produce the exact same main-TT key. The main TT validates a
64-bit key only, so this is a deterministic false hit/cutoff rather than an
ordinary hash collision. Do not dismiss it as a performance-only hash change.

Keep any repair candidate opt-in until its strength and deadline behavior are
measured. It must prove all 256 clock encodings and all individual king flags
distinct, then show that a fresh search and a deliberately warmed former-alias
position agree, including a 72/76-clock pair near the 80-ply rule. The current
strict-identity candidate passes those direct regressions, native perft depth
10 (`861842812`), a 504-position / 2,905-move native differential, and the
172-test source suite. Do not bundle unrelated repetition/exact-table hash
changes: those tables recheck full state and are a separate distribution issue.

A candidate that uses strict state identity for the TT entry key while retaining
the legacy direct-map slot index is a cache-layout/strength experiment, not a
behavior-preserving refactor. Its fresh PGO build matched its non-PGO form's
fixed-depth nodes, moves, and scores in 64/64 training and held-out cases and
measured 0.8804x and 0.9129x wall time respectively. It still completed only
depth 24 / `25-21` on all ten fresh 1,000-ms Sian-Thao ply-21 trials (and five
1,300-ms trials), so it is not accepted and must not replace the GUI DLL.

A qsearch-only bounded capture-history candidate was also rejected and fully
removed. It broke only equal capture-count/equal-captured-king ties and did not
touch quiet history, but its own telemetry found 67,111 first-move q-beta
cutoffs out of 68,492 (about 98.0%), with a total cutoff-index sum of only
1,383. On the held-out fixed-depth screen it expanded 1.0068x as many nodes,
took 1.0396x as long, and changed selective-search moves/scores. Do not revive
this idea without evidence that a new capture class has materially poor
first-move cutoff order.

### 2026-08-23 qsearch transposition census

The next single experiment measured whether capture-only qnodes repeat often
enough to justify a private qsearch TT. The source gained an opt-in
`MAKHOS_QSEARCH_TT_CENSUS=1` shadow table only; it never returns a cached score,
does not alter ordering or pruning, and is disabled in production. It records
only qnodes with at least one mandatory capture, and only when
`repetition_limit=0` (the external-no-repetition profile). The census key uses
the injective XOR state encoding rather than the legacy OR-salt main-TT key, so
false main-TT aliases cannot inflate the result. Each private direct-map table
has `main_TT_entries/16` 16-byte entries.

The control and candidate were built from the same current source with Clang
`-O3 -march=native -std=c17 -Wall -Wextra -Werror -Wno-unused-function
-shared -DMAKHOS_NO_MAIN -DMAKHOS_SEARCH_TELEMETRY=1`; only the candidate added
`-DMAKHOS_QSEARCH_TT_CENSUS=1`. Their SHA-256 hashes are respectively
`DE8F1773DB3367026132B7BC0B4DE74A81B910F380684431E111A9575CFE2CF6` and
`BAC7724F6971DF98325337DC58EE42DC93665E95A43929EB496D6164A325042B`.

On 64 deterministic non-repetition positions (seed 20260920, depth 15), both
DLLs returned identical move, score, depth, and node count on all 64 cases.
At hash power 17 the candidate saw 2,564,816 capture qnodes and 320,044
same-key hits (12.49%); 1,875,259 probes collided with another live slot.
At hash power 20 it saw 2,185,998 capture qnodes and 353,913 same-key hits
(16.18%), with 615,771 live-slot collisions. The census adds no search
behavior, but its key/store instrumentation measured about 2.2% fixed-depth
wall overhead at power 17 and about 7.1% at power 20, so these are an upper
bound on a useful cache's cost rather than a speed claim.

On five fresh one-second runs of the external Sian-Thao ply-21 position at
hash power 20, control and candidate both stayed at depth 21 and chose
`25-22` with score `-46`; candidate capture qnodes were 676,988..711,408 and
same-key hits were 9.87..9.88%. The source smoke build after the patch passed
the full 172-test suite. This is measurement-only evidence, not a promoted
search change. The hit signal is large enough to screen a real private qTT,
but the collision rate and qsearch bound semantics require an exact
alpha/beta-aware implementation; do not treat every hit as a safe cutoff.

The single highest-value next experiment is therefore an opt-in private
qsearch TT candidate with strict keys, bound flags, mate-score ply conversion,
and no caching of stopped or captureless qnodes. If its fixed-depth result is
not exact and its paired screen is not positive, revert it and move to the
next native-SMP/search-stack design rather than enlarging the census table.

The private qTT candidate was then screened and rejected. It used a 16-byte
strict-key entry with exact/lower/upper bounds and `score_to_tt`/`score_from_tt`
conversion, and was compiled separately as
`build/makhos_native_qtt_candidate.dll` (SHA-256
`3FBF755C63910DE46DC5F8A104786E53EE2D53ABE394D4A6E9C6F0779BF53B47`) against
the telemetry control `build/makhos_native_qtt_control.dll` (SHA-256
`438FF2820F41EA27BC93FF7EDC1AFAA76929E8398E8ECF7623C3C6DFA161DAA1`). On the
same 64-position, depth-15, hash-power-17 screen it reduced nodes from
13,567,632 to 13,053,145 and wall time from 3,062.5 ms to 3,058.2 ms, but
changed the selected move or score on 2/64 cases (only 3/64 node counts were
equal). Candidate telemetry recorded 8,007,928 probes, 236,533 hits, 222,571
cutoffs, and 6,322,550 direct-map collisions. The lower node count is therefore
search behavior, not a behavior-preserving speedup.

The production-path deadline test was negative: with 12 Threads, total Hash
512 MiB (power 20 per worker), external-no-repetition, and five fresh 1,000-ms
trials on the Sian-Thao ply-21 fixture, the control completed depth 24 and
selected `25-21` in 5/5 trials. The qTT candidate selected `19-15` at depth 23
in 3/5 and `25-21` at depth 24 in 2/5; it never improved the target plan.
Native allocation rose from about 557.6 MB to 568.3..568.9 MB across the 12
workers. A paired external-no-repetition pilot (0.2s + 0.01s, 8 color-swapped
pairs, seed 20260823, 16 games) ended INCONCLUSIVE but negative at W3 D7 L6,
pentanomial `2/0/5/1/0`, LLR `-0.045`, Elo `-65.9 +/-130.2` (95%). Revert the
candidate; do not run the long 10s+0.1s gate or retry this design unchanged.

The source now retains only the opt-in census instrumentation; the qTT search
path is removed and the accepted DLL remains byte-for-byte unchanged. The
post-revert default smoke build and full source suite passed (`172 tests`).
Given the qsearch cache's deadline loss, the next highest-value experiment is
the low-risk P1 representation step: compact killer moves with exact
node/move/score equality and measured 1/2/4/8/12-thread memory. If that is
neutral, move to a newly designed native SMP root search with private worker
state and an explicit shared-TT correctness proof; do not revive the rejected
lock/try-lock leader designs.

The compact-killer representation step passed and is now the source default
(`MAKHOS_COMPACT_KILLERS=1`). It stores only the 36-byte path/capture payload
for each of the two killers per ply, while matching the existing `same_move`
semantics; the child `Position` is not needed for killer ordering. The separate
production candidate
`build/makhos_native_compact_killer_production_candidate.dll` has SHA-256
`A7F34A3F445978CEAAC3FD1E9C998961095CBE5ED2F020F14522CC559BD180F1`.

Against the byte-preserved accepted control
`build/makhos_native_accepted.dll`, 96 deterministic positions (seed 20260920,
depth 15, hash power 17, project repetition rules) over two repetitions had
zero move, score, node, depth, or PV mismatches. The candidate took 8,973.0 ms
versus 9,021.6 ms for the control (0.9946x in that paired run). A separate
three-repetition external-no-repetition screen over 64 positions also matched
all results and measured 0.9982x; timing variation is within the expected
sub-percent range, not a playing-strength claim.

Persistent allocation measurements at total Hash 64 MiB after a 200-ms
start-position search showed exactly 3,072 bytes saved per worker: 1/2/4/8/12
Threads saved 3,072/6,144/12,288/24,576/36,864 bytes respectively, with the
same TT power at each setting. The source default smoke build and full suite
passed (`172 tests`). This is a behavior-preserving KEEP/PROMOTE at source
level; the accepted DLL SHA-256 remains
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD` and was
never overwritten. The promotion artifact remains isolated until a deliberate
production-binary replacement is scheduled.

The next highest-value experiment is now architecture-level native SMP root
search: retain private worker stacks/history, use a separately proven shared
TT or message-passing result channel, and elect the best fully completed root
iteration instead of returning a leader-only result. It must first pass
1/2/4/8/12-thread scaling, root-result determinism, and timeout fallback tests;
do not combine it with qTT, selective-root, root-alpha, or the rejected
lock/try-lock Lazy-SMP prototypes.

### 2026-08-23 native root-SMP full-window task prototype

The first native root-SMP design was screened as an isolated architecture
experiment. The candidate was compiled from the compact-killer source default
with Clang `-O3 -march=native -std=c17 -Wall -Wextra -Werror
-Wno-unused-function -shared -DMAKHOS_NO_MAIN -DMAKHOS_SHARED_TT=1
-DMAKHOS_NATIVE_ROOT_SMP=1` as
`build/makhos_native_root_smp_candidate.dll` (SHA-256
`01763FFBF3511A4FA12F49269943363C1F1E69084949E43C72F0AC6EEBB99088`). It
assigned every root move to worker threads at each full-window depth, kept
private search contexts, shared the main TT, waited for the complete root layer,
and committed only a fully completed iteration.

The hard determinism gate failed immediately. On eight fixed deterministic
positions (seed 20260920, depth 10, hash power 16, two repetitions), one thread
matched itself on 8/8 cases, while 2, 4, 8, and 12 threads matched on only 1/8
cases each; the other 7/8 results changed in move, score, or PV. This is a
correctness/search-state race, not acceptable parallel variation. A one-thread
target-position depth-12 run was repeatable but differed from the accepted
single-search behavior (`19-16`, score 8, 123,385 nodes versus score 4,
54,257 nodes), so the candidate is not a behavior-preserving scheduler.

The production deadline screen was also negative. With 12 threads, hash power
20 (about 512 MiB total in the ordinary per-worker profile), external
no-repetition, and five fresh 1,000-ms trials on the Sian-Thao ply-21 fixture,
the candidate returned depth/move pairs `21/19-16`, `21/25-22`, `22/27-23`,
`21/27-23`, and `21/27-23`; it never matched the accepted control's stable
depth-24 result and did not establish the target plan within the budget. The
root handle measured about 92.9--94.4 MB at this reduced hash setting, and
several runs stopped with an incomplete root layer. No SPRT was run because the
determinism and timeout gates failed. The source prototype was completely
reverted; the candidate DLL is retained only as an audit artifact.

The post-revert source smoke build passed with warning-as-error flags and the
full source suite passed (`172 tests`). The accepted control
`build/makhos_native_accepted.dll` remains byte-for-byte unchanged at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

Do not retry this shared-TT/root-task design unchanged. The next single
experiment is a deterministic C-side root scheduler with a fixed worker
assignment and private TT per worker, specifically to separate Python root-split
overhead from shared-TT/heuristic races. It must first prove exact 1-thread
parity, 2/4/8/12-thread repeatability, complete-root timeout fallback, and
fixed-depth throughput before any TT-sharing or strength screen is considered.

### 2026-08-23 deterministic private-TT root scheduler

The follow-up native-SMP experiment implemented that fixed-assignment design as
an opt-in candidate. Each root move was assigned by `index % active_threads`,
each worker kept a private TT/search context, the root move list was copied and
sorted with the Python `(path, captures)` order before workers started, and a
depth was committed only when every assigned root task completed. The candidate
was compiled with Clang
`-O3 -march=native -std=c17 -Wall -Wextra -Werror -Wno-unused-function
-shared -DMAKHOS_NO_MAIN -DMAKHOS_NATIVE_PRIVATE_ROOT_SMP=1` as
`build/makhos_native_private_root_smp_candidate.dll` (final SHA-256
`EE52D1DF4C26F2E429C3F2B86EDEF2B0F82B39495A49DA41844A358600A549B9`).

Correctness gates passed for the mechanism itself: the 1-thread path matched a
same-source ordinary-search control on 8/8 deterministic depth-10 positions
(move, score, and node count); a separate fixed-depth depth-8 repeatability
screen matched on 8/8 positions for each of 1/2/4/8/12 threads; and 1/5/10/25
ms timeout-edge trials always returned status 0 with a legal move. These gates
do not prove playing strength because the multi-thread root searches use a
different private-history/TT schedule than the ordinary root search.

The fixed-depth behavior gate failed to preserve the control. On 64
deterministic positions (seed 20260920, depth 12, 12 threads, power-17 private
TT), 35/64 cases changed the selected move or score and 63/64 changed the node
count versus the same-source Python root splitter; all completed the requested
depth. The candidate was about 0.8974x the Python wall time (1,371.2 ms versus
1,528.0 ms), so the speed signal is real but is not behavior-preserving.

The critical external-no-repetition Sian-Thao ply-21 ladder was neutral rather
than a horizon improvement. With 12 threads and power-20 per-worker TT, fresh
trials returned depth 24/`25-21` at 1,000, 1,200, and 1,300 ms, matching the
control; at 1,500 ms both candidate and control reached depth 25/`27-23`.
The candidate's five 1,000-ms trials were stable at depth 24/`25-21` while
using about 553 MB, and its native timing was roughly 30--35 ms below the
Python wrapper's total call time. This does not meet the short-term one-second
`27-23` target and supplies no strength evidence, so no SPRT was run.

The candidate source was completely reverted after the gates; the isolated DLL
remains only as an audit artifact. The warning-as-error source smoke build and
the full source suite passed again (`172 tests`). The accepted control remains
byte-for-byte unchanged at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

The next single experiment is now the strongest measured pre-NNUE path rather
than another SMP architecture: run the properly sized production-path gate for
the existing qsearch capture-only/quiet-terminal candidate
`build/makhos_native_qsearch_capture_quiet_iterative_candidate.dll` (the
`MAKHOS_EXPERIMENTAL_SEARCH_APIS=0` build). It already has equal-node fixed-depth
evidence, about 11.6% measured throughput improvement, and a positive but
inconclusive 16-pair 10s+0.1s pilot. Reproduce its correctness/critical ladder
first, then run paired pentanomial SPRT with the accepted DLL; do not combine it
with private/shared SMP changes or promote it from short pilots alone.

### 2026-08-23 qsearch capture-only production-path gate

The qsearch capture-only/quiet-terminal candidate was reproduced as an isolated
production-path binary and passed the targeted candidate tests (`2/2`). On the
64-position deterministic depth-15 screen (three repetitions, seed 20260931,
hash power 18), candidate and accepted control matched move, score, and node
count on all `64/64` cases. The total wall time was `3037.7 ms` versus
`3445.7 ms`, a reproducible `0.8816x` ratio (about `11.8%` faster) with no
fixed-depth search-behavior change.

The fresh external-no-repetition Sian-Thao ply-21 ladder used 12 Threads and
512 MiB total Hash. At 1,000 ms both binaries were stable at depth 24 and
`25-21` in `5/5` trials. At 1,300 ms the accepted control remained depth 24 /
`25-21` in `5/5`, while the candidate reached depth 25 / `27-23` in `4/5`
trials (one run stayed at depth 24). This is a useful deadline/horizon signal,
but it does not meet the one-second target and is only one external position.

The paired color-swapped production SPRT then used candidate SHA-256
`BB4C9E8003FE44FD51079A9A94BBDE127E50339FF9688462592B65779415EC20` against
the byte-preserved accepted SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`, ABI 5,
12 Threads, 512 MiB Hash, persistent search, 8 opening plies, 10s + 0.1s,
seed 20260933, and one game at a time. The 100-pair / 200-game screen ended
`INCONCLUSIVE`: W61 D84 L55, pentanomial `3/20/49/24/4`, LLR `+0.09`, and
`+10.4 +/- 28.9` Elo (95%). Therefore the candidate has a measured speed and
deadline advantage but no promotion-grade general-strength evidence yet. The
accepted DLL was not overwritten and the source defaults remain unchanged.

The next single experiment is an expanded, independently seeded production
SPRT of this same candidate (no code changes) until a meaningful boundary or a
minimum 500 paired games is reached. This is higher value than starting another
heuristic while the only behavior-preserving speed candidate remains
statistically unresolved. Promote only if the expanded gate supports strength;
otherwise retain the speed measurement as a baseline and move to the next
measured single-thread bottleneck.

The expanded independent seed (20260934) completed the planned 250 pairs / 500
color-swapped games under the same ABI-5 production settings. It finished
`INCONCLUSIVE` at W163 D189 L148, pentanomial `12/45/120/62/11`, LLR `+0.19`,
and `+10.4 +/- 19.2` Elo (95%). The sign and point estimate are consistent with
the first 200-game screen, but the interval still crosses neutral and the LLR
is far below the `+2.94` promotion boundary. This is reproducible
throughput/deadline evidence, not promotion-grade general-strength evidence.
The candidate and accepted hashes, 12-thread/512-MiB configuration, persistent
search, 8 opening plies, 10s + 0.1s time control, tablebases, and one-game
parallelism were unchanged; the accepted DLL and source defaults remain
untouched.

The qsearch candidate therefore remains an isolated, behavior-preserving speed
candidate. Do not promote it from the two inconclusive screens or infer that
the Sian-Thao threshold result generalizes to every middlegame. The next single
experiment is a diverse fixed-time horizon/stability audit over the existing
`corpora/middlegame_search_v1.jsonl` positions at 1,000 and 1,300 ms, comparing
candidate versus accepted depth, move, score, node count, and elapsed time with
fresh searches. This measures whether the deadline gain survives away from the
single fixture before spending another long match gate or changing HCE/search
behavior.

### 2026-08-23 diverse fixed-time qsearch horizon audit

The production qsearch candidate and accepted control were compared on all 18
positions in `corpora/middlegame_search_v1.jsonl`, with three fresh repetitions
at each of 1,000 ms and 1,300 ms (216 searches total). Each position cleared
the 12-worker, 512-MiB total-Hash persistent search before the next trial; the
control/candidate order was alternated by repetition. The corpus is still from
one external game, so this is a search-stability audit rather than independent
game evidence.

At 1,000 ms the candidate and control selected the same move in `54/54` pairs,
the same score in `52/54`, and the same completed depth in `52/54`. The candidate
completed a deeper layer in only `2/54` pairs (control `0/54`), while expanding
`1.1064x` as many nodes at the same time budget; native elapsed-time ratio was
`1.0002x`. Thus the fixed-depth 11.8% speedup does not generally turn into a
one-second extra ply.

At 1,300 ms the candidate completed a deeper layer in `18/54` pairs (control
`0/54`), with same depth in `36/54`, same move in `45/54`, and same score in
`42/54`. It expanded `1.1370x` as many nodes at the same budget and had a
`1.0001x` elapsed-time ratio. Six corpus positions produced the deeper layer
in all or most repetitions; the Sian-Thao target was among them and again
returned depth 25 / `27-23` versus control depth 24 / `25-21`. The other
changed positions include both same-move score shifts and two move changes, so
the candidate is a time/strength change in the timed setting even though it is
node-identical at fixed depth.

This confirms a useful but budget-sensitive horizon effect and does not justify
promotion or another long match gate from this single-game corpus. The next
single experiment is the measured P1 representation step: an opt-in compact
ordering-index candidate that avoids copying full `Move` structs during
insertion ordering while preserving the authoritative generated moves. It must
first pass perft/differential tests, exact fixed-depth move/score/node parity,
and 1/2/4/8/12-thread memory measurements; reject it if the index storage or
ordering changes are not a net throughput win.

### 2026-08-23 compact ordering-index candidate

The P1 ordering experiment was implemented as an opt-in
`MAKHOS_COMPACT_ORDER_INDEX=1` build. It keeps generated `Move` objects
authoritative and stores a 16-bit permutation per workspace so insertion
ordering does not copy full structs. The first implementation failed exactness
because iterative root ordering in the accepted engine intentionally carries
the previous physical order into the next depth; preserving the permutation
across depths and resetting it only after a fresh generation repaired that
issue. The final candidate
`build/makhos_native_compact_order_index_candidate.dll` has SHA-256
`8424B4D8D9ECF452027FF31C2967B7C68CCAE1CE372A112B131C626EF1DECD5C`.

Against a same-source control on 64 deterministic positions, depth 15, three
repetitions (seed 20260931, hash power 18), the repaired candidate matched
move, score, and node count in `64/64` cases. It took `3466.7 ms` versus
`3427.6 ms`, a repeatable `1.0114x` slowdown. The candidate also adds exactly
8,192 bytes per allocated `MoveList`; at a 64-MiB Hash / 200-ms start-position
measurement the structural overhead was 180,224 / 311,296 / 655,360 /
1,130,496 bytes at 1/2/4/8 Threads for 22/38/80/138 workspace lists. The
12-thread run reached a different depth and allocated three extra lists, so its
1,794,060-byte delta is not a pure layout comparison. No strength SPRT was
run because the behavior-preserving speed gate was negative. The candidate is
rejected and retained only as an audit artifact.

The source was fully reverted to the 174,808-byte production form; the
warning-as-error smoke build and full suite passed again (`172/172`), and the
accepted DLL SHA-256 remains
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.
Do not retry this permutation/index design unchanged. The next single
experiment is a narrower qsearch waste reduction: an opt-in path that skips
`order_search_moves()` when qsearch has exactly one legal capture, where
ordering cannot change the result. It must prove exact fixed-depth parity,
perft/differential correctness, and a net speedup before any timed strength
screen is considered.

### 2026-08-23 qsearch single-capture ordering skip

The narrower qsearch waste candidate was compiled from the current production
qsearch path with `MAKHOS_QSEARCH_CAPTURE_ONLY=1`, fast quiet mobility,
precomputed man/king capture geometry, and fast capture-existence checks. The
control used the same source and flags with
`MAKHOS_EXPERIMENTAL_SEARCH_APIS=0`; the candidate added only
`MAKHOS_QSEARCH_SKIP_SINGLE_ORDER=1`. Candidate SHA-256 is
`4D52236D9E53E5EB33FAAF50CECAD56754B781446F25B36A9701C8394B27E0A5` and
control SHA-256 is
`7A94626F018C37E212C756D14B81E9A3B1C4DF4F590CA8D6CAB69F61A03F9C65`.

On the 64-position deterministic depth-15 screen (three repetitions, hash
power 18), the candidate preserved move, score, and node count in `64/64`
cases. It was `0.9919x` on seed 20260931 (2718.1 ms versus 2740.2 ms) and
`0.9943x` on the independent seed 20260932 (2600.7 ms versus 2615.6 ms), a
small sub-one-percent signal. The fresh 12-Thread / 512-MiB external-
no-repetition ladder was neutral: at 1,000 ms both candidate and control
returned depth 24 / `25-21` in `5/5`; at 1,300 ms both returned depth 25 /
`27-23` in `5/5`. Memory and allocated workspace lists were identical in the
paired runs (about 555.5 MB / 224 lists at 1.0 s and 558.7 MB / 239 lists at
1.3 s).

This is a behavior-preserving micro-speed signal without a deadline or
horizon gain. The source opt-in was removed, restoring the exact 174,808-byte
production source; the warning-as-error full suite passed `172/172`, and the
accepted DLL remained byte-for-byte unchanged. Retain the two DLLs only as
audit artifacts and do not promote or stack this skip into production.

### 2026-08-23 qsearch PVS screen

Because telemetry still attributes about 62% of search nodes to qsearch, a
separate current-source candidate enabled `MAKHOS_QSEARCH_PVS=1`: the first
capture is searched with the full window and later captures use a null window,
with a full-window re-search only on a possible principal-line improvement.
The production API was held at `MAKHOS_EXPERIMENTAL_SEARCH_APIS=0`; no other
macro changed. The same-source control SHA-256 is
`32CC79B1573BE000A50186DFE72782BA438EDF95846AB8E26AF70D772CC84914` and the
candidate SHA-256 is
`A9952B6F78FFD667166EC50EBA3FC6BC2B8AEEE5F5A4FD981D912D8FA1FA28F7`.

The candidate preserved the selected move and score on both 64-position,
depth-15, three-repetition screens, but not exact node behavior: equal-node
cases were `16/64` on seed 20260931 and `15/64` on seed 20260932. The first
screen measured `0.9955x` wall time (3471.8 ms versus 3487.5 ms) with a
`1.0000308x` node ratio; the holdout reversed direction to `1.0079x` (3296.0
ms versus 3270.2 ms) with a `1.0000267x` node ratio. Since the behavior is not
node-identical and the timing sign is not stable, no timed ladder or SPRT was
justified. Reject this PVS candidate and do not retry it unchanged.

The source itself was unchanged (the macro remains disabled by default), the
post-revert source suite remained `172/172`, and the accepted DLL SHA-256 is
still `FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.
The next single experiment is a conservative history-update screen using the
existing telemetry-supported quiet-move ordering path: enable the opt-in
history-gravity update, compare it with an identical current-source control
at fixed depth on two seeds, and proceed to a short paired screen only if the
candidate shows a reproducible node/time or stability advantage. Do not
combine it with qsearch or SMP changes.

### 2026-08-23 history-gravity screen

The opt-in `MAKHOS_HISTORY_GRAVITY=1` update was screened against an identical
current-source control with `MAKHOS_EXPERIMENTAL_SEARCH_APIS=0`. Candidate
SHA-256 is
`BFA38228756AA5F7572D787BC7A65779AFE1E49C102C863E74227E61613663ED` and
control SHA-256 is
`5220E54B33F9346239C6E5374760D20E43363AFF509A088A84B878E3B4D1ED1A`.

The candidate materially changed search behavior. On the 64-position,
depth-15, three-repetition screen (hash power 18, seed 20260931), it matched
the control move on `53/64` and score on `47/64`, reduced nodes to `0.9725x`,
and measured `0.9382x` wall time (3259.9 ms versus 3474.7 ms). The independent
seed 20260932 reversed the signal: moves matched `56/64`, scores `41/64`,
nodes rose to `1.0152x`, and wall time was `1.0048x` (3304.3 ms versus
3288.3 ms). This is neither a stable speed improvement nor a controlled
strength result. No timed ladder or SPRT was run; reject this history-gravity
parameter unchanged and leave the production default at zero.

The source was not modified, so the prior warning-as-error full suite remains
`172/172` and the accepted DLL is still byte-for-byte unchanged at
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`. The next
single experiment is a separate TT-policy screen for
`MAKHOS_TT_KEEP_DEEP_STALE_SAME_KEY=1`, motivated by the high TT-hit rate and
the existing direct-map replacement policy. It must first show reproducible
fixed-depth behavior/throughput on two seeds; do not combine it with history,
qsearch, or SMP changes.

### 2026-08-23 deep-stale TT policy screen

The opt-in `MAKHOS_TT_KEEP_DEEP_STALE_SAME_KEY=1` policy was compared with an
identical current-source control, both using the production API
(`MAKHOS_EXPERIMENTAL_SEARCH_APIS=0`). Candidate SHA-256 is
`414885BB2161A016FB2F2E9EACA9808439E7ABE6ABBCBAF03D5FC513C638A0BA` and
control SHA-256 is
`48FBE59B692388EA655AF7F1C68FA8A7F341132A96EF4EA1374A27598C45E3BE`.

The candidate was exactly node-, move-, and score-identical on both
64-position depth-15 screens (three repetitions, hash power 18): `64/64`
equal cases on seeds 20260931 and 20260932. Timing was not a reliable win:
seed 20260931 measured `1.0015x` (3449.2 ms versus 3444.0 ms), while the
holdout measured `0.9852x` (3268.8 ms versus 3318.0 ms). The decisive timed
gate was negative. At 12 Threads / 512 MiB total Hash under the external-
no-repetition profile, the candidate returned depth 23 / `19-15` in all five
fresh 1,000-ms trials and all five 1,300-ms trials; the control returned depth
24 / `25-21` in all ten trials. Candidate memory was about 555.5 MB / 224
workspace lists versus control about 557.2 MB / 232 lists, so the small memory
saving did not compensate for the horizon loss.

Reject this TT policy unchanged. The source remains at its default value, the
warning-as-error suite remains `172/172`, and the accepted DLL is still
byte-for-byte unchanged at
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`. The next
single experiment is now the highest-evidence HCE path: an opt-in **full
fitted endgame term set** using the existing held-out exact 4/5/6-piece WDL
fit, gated only to the verified endgame region. It must not taper those fitted
coefficients into the middlegame, and it must pass integer-evaluation
regressions, fixed-depth screens, and a paired strength gate before any source
promotion.

### 2026-08-23 fitted endgame HCE screen

The opt-in `MAKHOS_FITTED_ENDGAME_EVAL=1` candidate applies the complete
logistic fit from `build/exact_wdl_eval_fit_v1.json` only when the position has
at most six pieces. It uses fixed-point integer weights rounded from the fit;
the production/default evaluator is unchanged for seven or more pieces and
the macro remains disabled by default. Candidate SHA-256 is
`C2361A9375FB1F82329ACDABF8972A76247B21D4EC6E8BB844E2FE91EB38AE90` and the
same-source control SHA-256 is
`322820AD182CEA75299E300188947FA5B221BC39511A78F859379ABD09FD54C9`.

Correctness gates passed: the candidate's integer evaluation differed from
the Python fitted feature score by at most one centipawn on 10,000 randomized
valid 4/5/6-piece states (no error exceeded two), and the warning-as-error
source suite passed `172/172`. On all 9,000 exact-WDL corpus samples the
candidate's static validation metrics were cross-entropy `0.320295`, Brier
`0.023843`, and decisive accuracy `98.58%`, versus control `0.359571`,
`0.036803`, and `95.92%`; these reproduce the held-out fit evidence and are
not independent playing-strength results.

On a deterministic validation subset of 96 tablebase positions (32 each from
4/5/6 pieces), depth-12 native search selected a move preserving the exact
tablebase WDL in `96/96` candidate cases. The control preserved WDL in `94/96`
(28/28 loss, 30/32 draw, 36/36 win); its two errors were draw positions that
the selected move turned into a tablebase win for the opponent. This is useful
endgame-domain evidence, not a full-game promotion gate.

The general fixed-depth screen was mixed because the candidate intentionally
changes low-piece positions. On 64 positions at depth 15, three repetitions,
hash power 18, candidate/control had seed-20260931 node ratio `0.99298`, time
ratio `0.99872`, same move `58/64`, and same score `51/64`; the independent
seed-20260932 ratios were `1.02351` nodes and `1.00701` time, with same move
`59/64` and same score `42/64`.

A cheap paired pentanomial screen was run with tablebases disabled so this HCE
could actually affect play: 32 pairs / 64 colour-swapped games, 0.2 s + 0.01
s, 12 Threads, 512 MiB total Hash, persistent search, eight opening plies,
one game at a time, seed 20260823. It ended `INCONCLUSIVE` and slightly
negative at W27 D8 L29, pentanomial `2/4/21/4/1`, LLR `-0.04`, and
`-10.9 +/- 47.8` Elo (95%). Do not promote or run the long 10s gate from this
negative short screen; leave the source macro off and retain the candidate
only as a reproducible data-backed audit artifact. The result also reinforces
that exact endgame fit quality does not by itself prove general middlegame
strength.

The next single experiment is therefore data, not another coefficient guess:
build a versioned `middlegame_search_v2` corpus by validating and merging all
available independent-budget analysis reports, keeping per-source observations
and conflict/stability labels. Use it to expand regression coverage before
another HCE/search candidate; do not start NNUE or tablebase builders.

### 2026-08-23 middlegame corpus v2 merge

The available analysis reports were merged into the new, non-destructive
`corpora/middlegame_search_v2.jsonl` (the v1 corpus was not overwritten). The
builder validated 23 `thai-makhos-analysis-v1` reports and wrote 26
deduplicated positions with 23 source observations. Only six positions have a
stable last-two-budget move; 17 are explicitly marked as conflicting search
labels. Every source currently has the same external game id
`374f92e56f20496b`, so this is broader budget/build/regression coverage, not
independent-game diversity and not supervised ground truth. The output has 26
samples / 27 JSONL lines and is reproducibly loadable.

The next single experiment is a holdout fixed-time audit of the existing
qsearch production-path speed candidate against the accepted control over all
26 v2 positions at 1,000 and 1,300 ms. This tests whether the prior v1
deadline/horizon signal survives the newly merged positions before any more
qsearch code or strength gate is attempted. Keep the accepted DLL unchanged
and treat the v2 labels as search-stability observations only.

### 2026-08-23 qsearch candidate v2 fixed-time audit

The existing production-path qsearch candidate
`build/makhos_native_qsearch_capture_quiet_iterative_candidate.dll` was
compared with the byte-preserved accepted DLL on all 26 positions in
`middlegame_search_v2`, with two fresh repetitions at each 1,000-ms and
1,300-ms budget, 12 Threads, 512 MiB total Hash, external-no-repetition, and
alternated candidate/control order (104 paired searches per budget). At
1,000 ms the candidate completed a deeper layer in `7/52` pairs (control
`0/52`), selected the same move in `51/52`, and had the same score in `46/52`;
mean/median node ratios were `1.1283x`/`1.1087x` while mean/median native
elapsed ratios were `1.0001x`/`1.0000x`. At 1,300 ms it completed a deeper
layer in `13/52` pairs (control `0/52`), selected the same move in `46/52`,
and had the same score in `44/52`; node ratios were `1.1468x`/`1.1456x` and
elapsed ratios `1.0000x`/`1.0000x`. The target Sian-Thao position again reached
depth 25 / `27-23` for the candidate while control stayed at depth 24 /
`25-21` at 1,300 ms in both repetitions; at 1,000 ms both stayed on the
shorter plan. This strengthens the deadline/horizon evidence beyond v1, but
the corpus is still one game and cannot replace game-level strength evidence.

The accepted DLL SHA-256 remains
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`; the
candidate remains isolated because the independent 500-game production SPRT
was previously inconclusive. The new v2 holdout is sufficient new mechanism-
independent evidence to justify one more independently seeded production SPRT
of this same candidate before starting another heuristic: use 250 pairs / 500
games at 10 s + 0.1 s, 12 Threads, 512 MiB total Hash, persistent search,
eight opening plies, one game at a time. Promote only on the generalized
pentanomial boundary; otherwise keep the speed baseline and move on.

### 2026-08-23 qsearch production SPRT closure and telemetry refresh

The independently seeded production-path gate completed all 250 pairs / 500
colour-swapped games for
`build/makhos_native_qsearch_capture_quiet_iterative_candidate.dll` against
`build/makhos_native_accepted.dll`. The settings were unchanged from the
previous production gate: 10 s + 0.1 s, 12 Threads, 512 MiB total Hash,
persistent search, eight opening plies, one game at a time, production
tablebases, seed `20260935`. Candidate SHA-256 was
`BB4C9E8003FE44FD51079A9A94BBDE127E50339FF9688462592B65779415EC20`; the
accepted control remained
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

The final result was `INCONCLUSIVE`: W153 / D194 / L153, pentanomial
`10/62/103/68/7`, LLR `-0.02`, and Elo `-0.0 +/- 19.2` (95%). There was no
promotion-grade strength evidence, so the candidate stays an isolated speed
artifact and the accepted DLL was not overwritten. Together with the earlier
500-game gate (`+10.4 +/- 19.2` Elo, also inconclusive), this establishes a
repeatable deadline/throughput effect without a demonstrated general playing-
strength gain; do not spend another long SPRT on this unchanged qsearch path.

As a fresh bottleneck measurement, the current source was built separately as
the ABI-6 telemetry library
`build/makhos_native_current_production_telemetry_20260823.dll` (SHA-256
`09132EB2ED7CF0C86A9E945375773ABBC4359123195DFC98A153EC936F755431`). On 96
deterministic positions at depth 15, seed `20260920`, hash power 17, it
recorded 19,185,628 nodes, of which 11,916,146 (62.11%) were qnodes. There
were 17,891,689 move-list generations producing 104,508,417 moves (5.841 per
generation), 9,095,939 ordering calls covering 35,912,920 moves (3.948 each),
90.13% first-move beta cutoffs, 48.91% null-move cutoff success, 39.71% TT
hits, 17.80% TT cutoffs per probe, 18.43% TT collisions, 22.98% replacements
per store, 439,332 PVS re-searches, and 59,512 LMR re-searches. The existing
qsearch candidate keeps the same node/search telemetry but reduces generated
move payloads to 40,171,063 (2.245 per generation); its neutral 500-game gate
shows that this already-targeted qsearch saving is not sufficient by itself.

The next single experiment is a low-risk, behavior-preserving normal-search
ordering screen: an opt-in `MAKHOS_SKIP_SINGLE_MOVE_ORDER=1` path that skips
`order_search_moves()` only when a fully generated legal list has exactly one
move. It cannot change ordering or scores in that case, but can remove a
measurable fraction of the 9.1 million ordering calls. Require perft and full
suite correctness, exact fixed-depth node/move/score parity on two seeds, and
an independent timing win before considering any further strength gate. Do not
combine it with qsearch, HCE, or SMP changes.

### 2026-08-23 normal-search single-move ordering screen

The opt-in `MAKHOS_SKIP_SINGLE_MOVE_ORDER=1` path skipped
`order_search_moves()` only for generated lists with exactly one legal move in
normal search and the iterative root/session paths. The source warning-as-error
suite passed `172/172` before the isolated builds. The same-source ABI-5
control SHA-256 was
`40114F73D7DAB24915FAF655129183D3594BAC19C55AE4832EA2829F583C4A87`; the
candidate SHA-256 was
`175F169582CBDBC08597B14831ED414DF770C5589ADB3890B8BE56A9C32D617C`.

On both deterministic 64-position depth-15 screens (three repetitions,
hash power 18), the candidate preserved nodes, scores, and moves in `64/64`
cases. It was nevertheless slower: `1.00152x` on seed `20260931`
(3441.9 ms versus 3436.7 ms) and `1.01473x` on independent seed `20260932`
(3302.0 ms versus 3254.1 ms). ABI-6 telemetry explains that the branch did
skip exactly `1,634,207` ordering calls: ordering calls fell from 9,095,939
to 7,461,732 and ordered moves from 35,912,920 to 34,278,713, while all
node/search counters stayed identical. The extra per-node branch and code-path
cost outweighed the saved insertion-order work. Reject this candidate and
remove the opt-in code; do not run a strength gate or retry the same singleton
branch unchanged.

The next single experiment is a structural TT replacement screen motivated by
the measured 18.43% direct-map collision rate and 22.98% replacement/store
rate. An opt-in two-entry-per-bucket TT will keep the same total entry budget
and memory, probe both ways for an exact key, and replace the shallower/older
slot on a miss. It must first pass TT/perft/search correctness and fixed-depth
parity diagnostics, then show a reproducible collision/cutoff or horizon
benefit at both hash-power 17 and the production 12-thread/512-MiB profile.
Do not combine it with qsearch, HCE, SMP, or another ordering change.

### 2026-08-23 two-way TT pilot

The opt-in `MAKHOS_TT_TWO_WAY=1` candidate keeps the same total TT entry
budget but uses two entries per bucket, probing both for an exact key and
replacing the shallower/older slot on a miss. Candidate SHA-256 is
`291A3925D7C4008A84CF0F953330919F7ADDC5EFABEDA4897B831B41CB942346`; the
same-source control is
`89E26F455BC3CFBF4CC329583D96CE2E11DA3FCD623553609844D3EE5A960CDB`.

Correctness gates passed: the candidate executable's native differential
covered 204 positions / 1,149 legal moves plus 10 exact three-piece states,
and the two-way layout kept `40`-byte TT entries and identical measured
per-worker memory. The deterministic depth-15 screen was intentionally
search-changing: on seed `20260931` candidate/control total nodes were
13,779,721 / 13,621,939 (candidate ratio `1.00708x`, with 20 control-fewer
node cases) and time ratio `1.00535x`, with same move `50/64` and same score
`35/64`; on the
holdout seed `20260932` candidate node ratio was `0.95976x`, time ratio
`0.88089x`, same move `53/64`, same score `32/64`. These mixed fixed-depth
results are not sufficient alone.

Telemetry on 96 depth-15 positions at hash power 17 showed the intended
mechanism: collisions fell from `18.43%` to `10.50%`, TT hits rose from
`39.71%` to `42.28%`, replacements/stores fell from `22.98%` to `13.32%`,
and candidate nodes fell from 19,185,628 to 17,916,237 on that seed. The
critical external-no-repetition 12-thread / 512-MiB ladder was stable in
five fresh trials: control was depth 24 / `25-21` at 1,000 ms and depth 25 /
`27-23` at 1,300 ms; candidate was depth 25 / `27-23` at 1,000 ms and depth
26 / `27-23` at 1,300 ms. This is the first candidate to meet the short-term
one-second target on the critical position, but it changes search behavior.

A 1s + 0.1s production pilot with tablebases, persistent search, 12 Threads,
512 MiB total Hash, eight opening plies, one game at a time, and seed
`20260824` completed 100 pairs / 200 colour-swapped games `INCONCLUSIVE` at
W69 / D72 / L59, pentanomial `2/20/49/24/5`, LLR `+0.15`, and Elo
`+17.4 +/- 28.8` (95%). Do not promote from this pilot; run the independent
10s + 0.1s 250-pair production gate next, with the same accepted control and
without combining any other candidate.

The independent production gate completed all 250 pairs / 500 colour-swapped
games with seed `20260825`, 10 s + 0.1 s, 12 Threads, 512 MiB total Hash,
persistent search, eight opening plies, one game at a time, and production
tablebases. Candidate SHA-256 was
`291A3925D7C4008A84CF0F953330919F7ADDC5EFABEDA4897B831B41CB942346` and the
same-source control was
`89E26F455BC3CFBF4CC329583D96CE2E11DA3FCD623553609844D3EE5A960CDB`. The
final result was `INCONCLUSIVE`: W149 / D203 / L148, pentanomial
`10/54/124/49/13`, LLR `-0.01`, and Elo `+0.7 +/- 19.0` (95%). The candidate
therefore has no generalized strength evidence and is not promoted; its
isolated DLLs remain available for audit, while the source experiment is
closed and the accepted DLL remains byte-preserved.

Production-scale ABI-6 telemetry explains why the attractive small-hash
screen did not transfer. On 47 non-terminal deterministic positions at depth
15 with 12 Threads and 512 MiB Hash (requested; 480 MiB allocated by the
power-rounded layout), control/candidate had respectively 14,852,724 /
14,468,650 TT probes, 236,539 / 16,118 collisions (1.59% / 0.11%),
6,519,009 / 6,414,451 hits (43.89% / 44.32%), and 221,142 / 15,305
replacements (2.00% / 0.14%). Candidate qnodes and generated moves fell only
to 0.972x and 0.973x of control, while elapsed time was 4.684 s versus
4.725 s (0.991x); memory was 559.7--560.4 MB with 244--247 workspace lists.
At hash power 17 the collision reduction was much larger, so that earlier
result is a small-hash mechanism diagnostic rather than production strength
evidence. Do not promote or rerun this two-way replacement unchanged.

The next single experiment is a corpus-groundwork gate: construct a
versioned, non-destructive middlegame regression corpus from every independent
game record available to the project, and explicitly report source-game
diversity, stable/conflicting labels, and usable positions. The current v2
corpus still contains only game id `374f92e56f20496b`; no HCE/search candidate
should be judged from it as if it were diverse general-strength data.

### 2026-08-23 accepted-selfplay corpus v3 and support-term screen

Because the workspace contained no additional Thai Makhos records (the other
game files found on D: were chess PGN files), eight deterministic accepted-
selfplay games were generated with six random opening plies per seed and the
accepted DLL (`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`)
for the remaining moves. Each record is explicitly tagged
`accepted-selfplay-synthetic` and `regression-search-stability-only`; it is
not human data or a supervised best-move label. Three-budget analysis at
100/300/1,000 ms, four Threads, and 128 MiB Hash produced the non-destructive
`corpora/middlegame_search_v3.jsonl`: 64 deduplicated positions from eight
source game ids, with 12 `stable`, 12 `long-horizon-divergence`, one
`short-search-divergence`, and 39 `settings-or-version-mismatch` labels. There
are 32 `usable_for_supervised_training` flags, but they remain search-derived
and must not be treated as ground truth.

The companion `build/middlegame_hce_audit_v1.json` measured a useful HCE
diagnostic without changing production code. On the 32 usable samples, the
current static evaluator selected the stable/long move as top static choice in
only `4/32`; leave-one-term-out support removal raised that diagnostic to
`11/32` (stable-only `5/12` versus current `3/12`). This is mechanism evidence,
not strength evidence; the corpus is accepted-selfplay and the labels are
search-stability observations.

The opt-in `MAKHOS_SUPPORT_WEIGHT=0` screen was then compared with a same-source
weight-8 control. Candidate SHA-256 was
`3916B10A235813E411E380896D9A04DC347B92CC12593417D1A47C6282DA0C22`; control
was `B98138BC7DDDDDF252AD5C2C475D6095C06AE2D89CDE621D14320A8732D20406`.
The candidate native differential passed 204 positions / 1,149 legal moves /
10 exact three-piece states, and the default source suite passed `172/172`.
At depth 15 over two 64-position, three-repetition screens (hash power 18),
candidate node/time ratios were `0.9589x/0.8783x` on seed `20260931` and
`0.9178x/0.7990x` on holdout `20260932`, with same moves `42/64` and `52/64`
and same scores `16/64` on both. The critical external-no-repetition ladder
did not improve: control and candidate both stayed depth 24 / `25-21` in
five fresh trials at both 1,000 and 1,300 ms (scores -57 / -58).

A required short production gate (1 s + 0.1 s, 12 Threads, 512 MiB total
Hash, persistent search, eight opening plies, production tablebases,
seed `20260850`) completed 64 pairs / 128 colour-swapped games
`INCONCLUSIVE`: W45 / D38 / L45, pentanomial `5/15/26/11/7`, LLR `-0.00`,
and Elo `-0.0 +/- 46.0` (95%). The support-removal candidate is not promoted:
its speed gain changes search substantially, it misses the one-second horizon
target, and the strength gate is neutral. Keep the isolated artifacts only
for audit and do not rerun support removal unchanged.

The next single experiment is a conservative, new mechanism suggested by the
same audit: an opt-in **phase-tapered support term** that keeps the existing
support bonus in low-piece positions but disables it only above a measured
midgame piece-count threshold. Screen one threshold at a time against the
accepted control; do not combine it with TT, qsearch, or another HCE change.

### 2026-08-23 phase-tapered support threshold-12 screen (REVERTED)

The phase-taper candidate added one opt-in compile-time boundary,
`MAKHOS_SUPPORT_MAX_PIECES`, so the accepted support bonus remained unchanged
through the selected piece count and was disabled only above it. The screen
used threshold `12` against a same-source threshold-`32` control; it did not
combine TT, qsearch, SMP, or another evaluation term. Candidate SHA-256 was
`9D773B1F1246D37DFFAC5428D9AF679C2C7BBCCD071A669C89C756D1B98961BF` and
control SHA-256 was
`32F05413658A7FFD0C7FCD47C5E8D685B9631089EAD34D4C5428AB34A63492EF`.

Correctness gates passed: the candidate executable differential covered 204
positions / 1,149 legal moves / 10 exact three-piece states, and the default
source suite passed `172/172`. On deterministic depth-15 screens at hash power
18 (64 positions, three repetitions), candidate/control total node and time
ratios were `0.9805x/0.9159x` on seed `20260931` and
`0.9461x/0.8694x` on holdout seed `20260932`; same moves were `47/64` and
`54/64`, with same scores `38/64` on both. This is a real search-changing
throughput signal, not a behavior-preserving refactor.

The critical external-no-repetition Sian-Thao ply-21 position was then run in
five fresh paired trials at 12 Threads, 512 MiB total Hash, and both 1,000- and
1,300-ms budgets. Both candidate and control completed depth 24 and selected
`25-21` in all ten budget/trial cells; neither reached the depth-25 `27-23`
plan. The threshold leaves the 12-piece critical position unchanged, so this
negative horizon result is also a useful mechanism boundary rather than a
claim about all positions.

The required paired production gate used 1 s + 0.1 s, 12 Threads, 512 MiB
total Hash, persistent search, eight opening plies, production ranked/native
tablebases, one game at a time, and seed `20260851`. All 64 pairs / 128
colour-swapped games completed `INCONCLUSIVE`: W37 / D51 / L40, pentanomial
`4/17/24/16/3`, LLR `-0.18`, and Elo `-8.1 +/- 41.7` (95%). The candidate has
no generalized strength evidence and did not meet the short-term horizon
target, so it is **REVERTED**; its isolated DLLs and critical/gate reports are
retained for audit, but the threshold must not be rerun unchanged.

The opt-in macro and source condition were removed after the gate. The
post-revert full suite passed `172/172` in 64.548 s. The accepted control
`build/makhos_native_accepted.dll` was never overwritten and remains
byte-preserved at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.


### 2026-08-23 support-weight-4 screen (REVERTED)

The follow-up HCE candidate changed only the support bonus from `+8` to `+4`
through an opt-in `MAKHOS_SUPPORT_WEIGHT` macro. The production-path binaries
were compiled with `MAKHOS_EXPERIMENTAL_SEARCH_APIS=0`: candidate SHA-256 was
`7640A302B8DAC632A3A5A5FC742BBDD5C09D689E6AF6F56B0E5E110893F82C47` and
same-source control was
`5F242C6DB32DC523FFF03C120803D3CCCC62632877CB17D10642DBC87D8CA04F`.
An earlier six-game pilot accidentally used the default experimental API path;
it was stopped and is not counted as evidence.

The production candidate passed the native differential (204 positions,
1,149 legal moves, and 10 exact three-piece states). On deterministic
depth-15 screens at hash power 18 (64 positions, three repetitions),
candidate/control node and time ratios were `0.9762x/0.9445x` on seed
`20260931` and `0.9691x/0.8711x` on holdout seed `20260932`; same moves were
`41/64` and `51/64`, with same scores `17/64` and `19/64`. The candidate
therefore changes evaluation/search behavior and is not a refactor.

Five fresh external-no-repetition critical ladders at 12 Threads and 512 MiB
Hash found no horizon improvement. At both 1,000 and 1,300 ms every candidate
trial completed depth 24 and selected `25-21`, while every control trial also
completed depth 24 and selected `25-21`; candidate score was consistently
`-82` versus control `-57`.

The correctly configured paired production SPRT used 1 s + 0.1 s, 12 Threads,
512 MiB total Hash, persistent search, eight opening plies, production ranked
and native tablebases, one game at a time, and seed `20260852`. All 64 pairs /
128 colour-swapped games were `INCONCLUSIVE`: W43 / D39 / L46, pentanomial
`4/14/31/11/4`, LLR `-0.19`, and Elo `-8.1 +/- 40.3` (95%). The candidate has
no generalized strength evidence and misses the one-second target. It is
**REVERTED**; do not rerun this weight unchanged, and keep its binaries only
as isolated audit artifacts.

The opt-in macro was removed and the source returned to the accepted `+8`
term. The post-revert full suite passed `172/172` in 64.598 s. The accepted
DLL was never overwritten and remains byte-preserved at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

With support-0, phase-taper, and weight-4 variants all failing to show a
general strength or critical-horizon gain, the next single experiment is a
measurement-only **production cutoff/move-generation telemetry audit** on the
accepted source over the deterministic corpus and v3 middlegame positions.
It will report qnode share, generated/ordered moves, first-move beta-cutoff
rate, cutoff index, LMR re-searches, TT collision/hit rates, and forced-capture
coverage. Only one new search candidate may follow from a measured dominant
waste; do not add another HCE constant or revive a rejected qTT/TT/SMP design
without a new mechanism signal.

### 2026-08-23 accepted production telemetry v4

The accepted source was built only with ABI-6 telemetry enabled as the isolated
measurement DLL
`build/makhos_native_accepted_telemetry_v4.dll` (SHA-256
`D3E4FB773DA3904151764C39CDEAD3E20CD438C98E87712241D322FDC2F580A`). On 96
deterministic depth-15 positions (seed `20260920`, hash power 17, one native
worker), the counters reproduced the established baseline: 19,185,628 nodes,
11,916,146 qnodes (`62.11%`), 104,508,417 generated moves across 17,891,689
move-generation calls, 90.13% first-move beta cutoffs, average cutoff index
`0.219`, 13.55% LMR re-searches, 39.71% TT hits, 18.43% TT collisions, and
22.98% replacements/stores.

The production-shaped v3 audit used all 64 deduplicated positions from
`corpora/middlegame_search_v3.jsonl`, depth 15, 12 Threads, and requested
512 MiB total Hash. It measured 90,486,526 aggregate nodes and 57,133,740
qnodes (`63.14%`), 489,059,592 generated moves over 84,761,703 generation
calls, average 5.770 moves per generation and 3.745 per ordering call, with
90.81% first-move beta cutoffs and average cutoff index `0.206`. LMR
re-searches were 12.45% of PVS re-searches. At this production Hash size TT
collisions were only `1.56%`, hits `42.63%`, and replacements/stores `1.92%`;
the aggregate native allocation was 507,759,840 bytes for the 12 workers.
Only one root position had a forced capture, so the signal is predominantly
middlegame rather than a tactical-suite artifact.

The measured dominant cost remains qsearch/move generation, while move ordering
is already highly effective and production TT collisions are low. The next
single experiment is therefore an opt-in **qsearch single-capture fast path**:
when mandatory capture generation returns exactly one move, recurse through the
existing first-move alpha/beta path without sorting or materializing an
ordering pass. It must prove exact move/score/node/PV equality against a
same-source control, then show a reproducible fixed-depth time benefit on both
seeds before any timed strength screen. Do not combine it with qTT, capture
history, HCE, or SMP changes.

### 2026-08-23 qsearch single-capture fast path (source-level PROMOTE)

The isolated candidate guarded only the qsearch `moves->count == 1` case. It
skipped `order_search_moves()` when there was no ordering decision to make and
left capture generation, recursion, alpha/beta windows, PV handling, and all
terminal rules unchanged. Production-path candidate SHA-256 was
`DD0673C7D83E310E875C3E4A6C245BB4144C58ADED2691F03AF6931B3D94F4EA`; the
same-source control was
`55F0DE47DCE4CA32894B39C39AF096F1D49A969E3595B38D78EE43ACA109C4D4`.

Correctness gates passed: the candidate differential covered 204 positions /
1,149 legal moves / 10 exact three-piece states; the default source suite
passed `172/172`; and deterministic depth-15 comparisons at hash power 18
matched move, score, and node count in `64/64` cases on both seeds
`20260931` and `20260932`. The three-repetition screens measured time ratios
`0.9955x` and `0.9955x`. A larger five-repetition, 96-position hash-power-17
holdout matched all moves/scores/nodes in `96/96` cases and measured
`0.9928x` on seed `20260920` and `0.9856x` on seed `20260921`.

ABI-6 telemetry confirmed the mechanism without a search change: on the
96-position seed `20260920` screen, nodes and all search counters were
identical, while ordering calls fell from `9,095,939` to `6,023,474` and moves
ordered from `35,912,920` to `32,840,455`. This is a small but reproducible
behavior-preserving throughput gain. Five fresh 12-thread / 512-MiB critical
trials at both 1,000 and 1,300 ms remained depth 24 / `25-21` for candidate and
control, so it is not a one-second horizon fix.

Because equality is exact and the timing signal repeats on independent seeds,
the fast path is **PROMOTED at source level** by changing its default compile
flag to `1`. The named production build
`build/makhos_native_qsearch_single_move_promoted.dll` has SHA-256
`B068FDAA454D7039F4986662CB51B755F8509DCB472FE1C49DE09FCC6C354903`, and its
executable passed the same native differential. The post-promotion source
suite passed `172/172` in 78.195 s. The accepted DLL remains untouched and
byte-preserved at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

The next single experiment is **middlegame corpus v4 expansion**: add at least
24 independently seeded accepted-selfplay games with the promoted source,
retain the explicit search-stability-only provenance, and analyse each at the
same 100/300/1,000-ms budgets. Report game/position diversity, piece-count
coverage, stable versus conflicting labels, and duplicate rate before fitting
or changing another HCE/search term. This is required to avoid treating the
small synthetic v3 corpus as general strength evidence; do not start NNUE or
revive rejected qTT/TT/SMP candidates during this data-groundwork step.

### 2026-08-23 middlegame corpus v4 expansion

Twenty-four additional deterministic accepted-selfplay games were generated
with independent seeds `20261001..20261024`, six random opening plies, and the
promoted single-capture fast-path source. Every file is explicitly tagged
`accepted-selfplay-synthetic` and `regression-search-stability-only`; it is not
human data and its long move is not a proven best-move label. Each game has 40
plies (34 engine plies after the opening) and eight analysed positions at
100/300/1,000 ms, four Threads, and 128 MiB Hash.

The non-destructive
`corpora/middlegame_search_v4.jsonl` contains 192 unique positions from 24
source games (zero duplicate positions in this batch), SHA-256
`113D80FA86DC4E910E47FBDC9FBA67EDB812D3D20E6AD935EEBEA1338BBF180D`. Piece
counts are 12:17, 13:14, 14:53, 15:7, and 16:101; this is useful middlegame
coverage but does not replace late-endgame data. Labels are 40 stable,
103 long-horizon-divergence, 29 short-search-divergence, and 20
settings-or-version-mismatch. The corpus builder marks 81 samples usable for
search-stability analysis and 111 not usable; there were no conflicting source
labels. These labels remain observational only and must not be used as
supervised ground truth.

The next single experiment is a **fixed-time v4 holdout** of the promoted
single-capture path against the byte-preserved accepted DLL at 1,000 and
1,300 ms, external-no-repetition and production 12-thread / 512-MiB Hash. It
will measure depth, move, score, PV stability, and per-position timing across
the 192 diverse positions. If timed move behavior differs, treat it as a
strength change and run paired pentanomial SPRT; if it remains identical, keep
the source-level promotion as a measured throughput improvement. Do not fit
HCE or start NNUE from v4 labels alone.

### 2026-08-23 v4 fixed-time holdout (NEUTRAL)

The required v4 holdout compared the promoted single-capture path with the
byte-preserved accepted DLL on all 192 unique positions, using external
no-repetition rules, production-shaped 12 Threads, and 512 MiB total Hash.
At 1,000 ms the candidate and control selected the same move in 185/192
positions and the same score in 173/192; at 1,300 ms they selected the same
move in 181/192 and the same score in 178/192. Depth matched in 170/192 and
174/192 positions respectively. Mean elapsed-time ratios were 0.999906x and
1.000228x, with mean node ratios 1.002122x and 0.996035x. The differences are
small, mixed, and are not strength evidence; no paired SPRT was warranted.

The source-level promotion therefore remains **KEPT as a behavior-preserving
throughput change**, but the candidate has no generalized playing-strength
evidence. The accepted DLL remains byte-preserved at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

The next highest-value work is a **reproducibility/diagnostic gate for GUI
game records**: records must carry the native DLL SHA, actual depth/nodes,
elapsed time, rules profile, and engine mode so a loss can be attributed to a
specific build and search budget. Do not treat a human game without that
provenance as evidence for an HCE or search change; replay it against the
accepted control first, then run targeted deeper analysis of the earliest
non-forced divergence.

### 2026-08-23 supplied human-game diagnostic

The attached `thai-makhos-game-v1` record was replayed successfully: 44 plies,
engine black moving first, human red, project rules, and a legal terminal final
state `B:RM2,19:RK20` with black to move and no legal move. The record reports
2 seconds, 12 Threads, and 512 MiB Hash, but it does not record the native DLL
SHA, depth, node count, or actual elapsed time. Its per-move metadata also
switches `mode` from `best` to `win` at plies 23--29 and back to `best`, while
the top-level record says `best`; this is a provenance warning, not proof that
the policy caused the loss. The analysis artifacts are retained as
`build/lost_game_analysis_accepted_2s_5s.json`,
`build/lost_game_key_accepted_2s_5s_20s.json`,
`build/lost_game_ply13_2s_5s_20s_60s.json`, and
`build/lost_game_ply25_2s_5s_20s_60s.json`.

Against the byte-preserved accepted DLL, fresh-TT re-searches found the first
large, reproducible horizon failure at recorded ply 13 (`28-24`). At 2 s it
completed depth 22 and chose `28-24` with score `-12`; at 20 s it completed
depth 25, chose `22-18` with score `-5`, and scored the played move `-57`; at
60 s it completed depth 26, chose `23-19` with score `-15`, while `28-24`
remained `-57`. The exact best PV is still horizon-sensitive, but the played
move is consistently much worse than the alternatives. Recorded ply 15
(`23x14`) is not a separate tactical blunder: at depth 29 both `23x14` and
`22x15` scored `-8` and their PVs transpose after the forced exchange. Recorded
ply 19 (`25-22`) was the best root move at 20 s (score `+9`). A second stable
mistake is ply 25 (`27-23`): at both 20 s and 60 s the engine chose `31-26`
(`-48`) while the recorded move scored `-74` at depth 26. By plies 37--43
the scores are already mate-like (`-999981` and below), so those late moves are
consequences, not the cause.

This game therefore supports a search-horizon/time-budget diagnosis, not an
HCE constant change: the critical plan needs roughly depth 26 on this line,
well beyond the roughly depth 22 reached at 2 s. Because the record lacks
build/runtime provenance, it must not be used as a strength result until a
sequential replay is captured with DLL SHA, mode, rules profile, depth, nodes,
elapsed time, and PV for every engine move.

### 2026-08-23 GUI search-provenance gate (PROMOTE)

The GUI/server game-record path now carries an explicit per-search provenance
contract, `search-v1`, so a reported loss can be tied to the code and runtime
that actually searched it. `makhos/search.py` records whether the result came
from native search, the Python fallback, or a forced single legal move;
`makhos/parallel_native.py` exposes the loaded worker ABI; and
`makhos/server.py` snapshots the configured DLL path, SHA-256, and ABI when the
engine is loaded. The `/api/bestmove` response now returns the requested clock,
depth limit, actual depth/common depth/selective-root status, nodes, elapsed
time, score/PV/WDL/tablebase hits, actual Threads/Hash allocation, rules
profile, engine mode, search backend, DLL identity, ABI, and any native error.
Engine replacement and server shutdown also close native search and tablebase
resources instead of leaking loaded DLL or mapped-file handles.

`web/app.js` freezes settings at request start and writes response-backed
provenance into each engine move rather than trusting mutable GUI controls. A
record receives top-level `provenance_version: search-v1` only when every
recorded engine move has the server-issued contract; this intentionally avoids
mislabeling games if a new static page is temporarily paired with an old
already-running server. The JSON schema now validates the exported position
history and all optional provenance fields. `makhos/game_analysis.py` and the
`analyze-game` CLI report missing fields separately from actual replay
mismatches; a DLL/ABI/settings/budget/backend contradiction is classified as
`settings-or-version-mismatch` instead of being treated as a search or HCE
failure.

Correctness gates passed: the focused game-analysis/server/GUI suite passed
`28/28`, and the full source suite passed `177/177` in 81.445 s. An isolated
runtime smoke server on port 8001 returned `search-v1`, backend
`native-root-split`, accepted DLL ABI 5 and SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`
for a two-thread search; a forced-move position correctly returned backend
`forced`. The smoke server was stopped afterward, while the user's existing
port-8000 process was left untouched. A legacy-record CLI smoke correctly
reported incomplete provenance plus Threads/Hash/requested-budget mismatches,
rather than inventing build identity. The byte-preserved accepted DLL remains
unchanged at the same SHA-256.

This diagnostic infrastructure is **PROMOTED**. It does not change search
strength, so no paired SPRT is warranted. The next single experiment is a
**selectivity/horizon attribution audit** on diverse middlegames plus the two
earliest human-game divergences: use deterministic single-thread fixed-depth
root-move ladders and isolated null-move/LMR measurement ablations to determine
whether the depth-22 to depth-26 plan shift is primarily pruning horizon,
qsearch boundary, or static-evaluation horizon. This is a measurement gate,
not permission to promote an ablation. Only the mechanism supported across the
holdout may become a one-concept candidate, followed by correctness,
deterministic throughput, and paired pentanomial SPRT. Do not retry a rejected
heuristic unchanged, tune to the single human position, or start NNUE/DFPN.

### 2026-08-23 selectivity/horizon attribution audit

The measurement-only audit is reproducible with
`scratch/horizon_attribution_audit.py`; its complete JSON is
`build/horizon_attribution_audit_20260823.json` (SHA-256
`9950D5255480AE2A3903AAC6C8E47E4A560D58315511E0BE17DE49764782C6C7`).
It sampled 48 deterministic v4 positions, 12 from each of stable,
long-horizon-divergence, short-search-divergence, and
settings-or-version-mismatch, at single-thread depth 15. All three ABI-6 DLLs
were built from the same current source: control SHA-256
`F0012ACBBC55989628122C97A8D3A1E29E5D7ABFA4E32230D889E9940006C791`,
null-move-disabled SHA-256
`85F9AA901EDD209A0E6F61893B7348B5EAE4181F9941B5DF4473344662362E9F`,
and second-LMR-reduction-disabled SHA-256
`C083A0802B0B3F52C6F1267BDB63EC71F13D3C41EEB70D08233B243F89FF1F78`.
The two ablations are controls for attribution only; they remain rejected
search candidates.

Disabling null move changed the selected move in 21/48 positions, matched the
control score in only 5/48, expanded `2.54x` as many nodes, and took `2.64x`
as long. On human-loss ply 13 it did find `22-18` at depths 18--22, but depth
22 took 15.196 s single-thread; the 12-thread root splitter failed to complete
depth 22 within 30 s after 414,864,566 nodes. This is excessive brute-force
de-selectivity, not a viable horizon fix. Reducing only the second LMR
reduction changed 15/48 moves, expanded `1.18x` nodes, and took `1.17x` as
long. At root-split depth 22 it still chose the recorded bad `28-24` on ply 13.
The old rejections are therefore reinforced; do not retry either candidate.

The dominant new signal is the root architecture. On the same 48 positions,
the production-shaped 12-thread/512-MiB root splitter disagreed with ordinary
single-thread search on 19/48 moves and 38/48 scores at equal depth 15. It
expanded `4.32x` as many nodes and took `1.60x` wall time despite parallelism;
qnodes remained about 63.4% in both, so this is not a qsearch-boundary-specific
effect. On human-loss ply 13 with the recorded reversible clock, ordinary
single-thread control changed from `27-24` at depth 18 to `22-18` at depth 20
in 723 ms and retained `22-18` at depth 22 in 1.060 s. The 12-thread root
splitter instead completed depth 22 in 1.105 s and reproduced the losing
`28-24` / -12. This directly attributes that recorded error to independent
root-search state/alpha loss at least as strongly as to nominal depth. Human
ply 25 also differed: single-thread depth 22 chose `31-26` / -48 while the
root splitter chose `19-16` / -2.

This audit changes no production search and requires no SPRT. The next single
experiment is a **root-architecture quality gate**: on the same stratified
holdout, create a stable deeper single-thread reference from two completed
depths, then compare ordinary single-thread and the actual 12-thread root
splitter at equal 300/1,000-ms clocks. Report which architecture alone matches
the deeper stable move, completed depth, nodes, and human-ply behavior. The
deeper result is still observational, not solved ground truth. Only if the
diverse holdout supports the human-game signal may a one-concept routing or
new native-SMP candidate be designed; do not revive the rejected shared-TT,
private-root scheduler, root-alpha, selective-root, or leader-only Lazy-SMP
implementations.

### 2026-08-23 root-architecture quality gate

The reproducible harness is
`scratch/root_architecture_quality_audit.py`; the complete result
`build/root_architecture_quality_audit_20260823.json` has SHA-256
`A73FF15E21AFDF634CE099428C519D28228F305088DBC93C8C0E7CDA7B6F3A52`.
It reused the same stratified 48-position v4 holdout and current-source control
DLL. A position became an observational reference only when ordinary
single-thread searches completed both depth 17 and depth 19 and selected the
same move. This yielded 36/48 stable references. These are deeper-search
stability labels, not solved best moves.

At an equal fresh-TT 300-ms clock with 512 MiB requested per engine,
single-thread search matched 32/36 stable reference moves, versus 21/36 for the
actual 12-thread root splitter. Single alone matched 13 positions, root split
alone matched two, both matched 19, and neither matched two. Single-thread mean
completed depth was 17.78 versus 16.44 for root split, while expanding
39,733,248 nodes versus 135,234,249. The signal remained at 1,000 ms:
single-thread matched 32/36, root split 20/36; single alone matched 14, root
split alone two, both 18, and neither two. Mean depth was 20.47 versus 19.17,
and nodes were 131,115,008 versus 464,174,630. Single-thread matched every
stable short-search-divergence and stable-class reference at both budgets; the
root splitter was particularly weak on the short-search-divergence subset
(4/9 at 300 ms and 3/9 at 1,000 ms versus single 9/9).

The one-shot human timing samples were horizon-sensitive, as expected: at
1,000 ms ply 13 single completed depth 21 / `27-24`, while root split completed
depth 21 / `22-18`; the fixed-depth gate above had single depth 20 and 22 both
on `22-18` but root-split depth 22 on the losing `28-24`. Do not use one timed
sample as a routing rule. The diverse result nevertheless establishes that the
current Threads implementation spends roughly 3.4--3.5x the nodes yet reaches
less depth and less often agrees with the stable deeper move. More root-split
nodes are duplicated independent-root work, not effective search throughput.

This gate changes no production behavior and needs no strength claim yet. The
next single experiment is a **same-source paired architecture SPRT**. Extend the
SPRT harness so candidate and baseline may use different explicit Threads
counts, keep source bytes, total Hash, rules, tablebases, time control, and
openings identical, and compare ordinary Threads=1 against root-split
Threads=12. First require parser/config/factory tests and a short paired pilot;
continue only if the signal warrants it. A positive result would justify an
explicit safe-routing candidate while a new native SMP design is developed; it
would not justify silently ignoring the GUI Threads setting or promoting an
untested architecture.

### 2026-08-23 same-source architecture SPRT pilot (Threads=1 PASS at STC)

The SPRT CLI now accepts optional `--dev-threads` and `--master-threads`
overrides while preserving the existing `--threads` default for both sides.
Its preflight, engine factories, effective persistent-search state, and emitted
configuration all use and disclose the per-side values. Parser tests cover the
fallback and mixed-thread cases. The six focused SPRT tests passed, a one-pair
mixed 1-versus-12 smoke emitted the correct configuration and completed, and
the full source suite passed `177/177` in 83.415 s.

To remove source/build confounding, candidate
`build/makhos_native_accepted_architecture_twin.dll` is a byte-identical copy
of the accepted DLL; both sides have SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD` and ABI 5.
The only match difference was candidate Threads=1 versus baseline Threads=12.
Both used 512 MiB total Hash, persistent search, production 3/4/5/6-piece
tablebases, eight opening plies, one game at a time, and colour-swapped pairs.

The fresh seed `20261031` SPRT used 0.2 s + 0.01 s, maximum 200 plies, and
H0/H1 `-10/+10` Elo. It crossed **PASS** after 52 pairs / 104 games at W48 D32
L24, pentanomial `0/6/25/12/9`, LLR `+2.99`, and `+81.6 +/-45.6` Elo (95%).
The exact result is
`build/root_architecture_sprt_seed20261031.json` (SHA-256
`648BC85068332B0C511CD11BECA19268B519795040DFEFA7638D1411BA28A1D8`).
This independently supports the fixed-time corpus finding that the current
root splitter is a strength regression, despite using twelve cores.

Do not silently reinterpret Threads or replace production from this STC result
alone: the early-game clock allocation is roughly 50 ms, shorter than the
user's 1--2-second GUI target. The next single experiment is an independent
longer-time architecture gate with the same byte-identical DLLs and settings,
fresh seed, 10 s + 0.1 s and a 1,000-ms per-move cap. Start with a bounded
paired pilot and extend only if its signal supports the STC/corpus result. If
confirmed, implement an explicit, provenance-visible safe routing option while
native SMP is redesigned; do not pretend Threads=12 were used when the actual
backend searches one thread.

### 2026-08-23 independent longer-time architecture pilot (NEUTRAL)

The predeclared longer-time pilot kept the same byte-identical ABI-5 DLLs,
512-MiB total Hash per engine, persistent search, production tablebases, eight
opening plies, colour swaps, and one-game parallelism. Fresh seed `20261032`
used 10 s + 0.1 s with a 1,000-ms per-move cap, H0/H1 `-10/+10` Elo, and a
fixed 32-pair bound. Its early allocation is roughly 475 ms and can grow to the
cap, making it materially closer to the GUI's 1--2-second target than the STC
screen.

The result was **INCONCLUSIVE/NEUTRAL**: 32 pairs / 64 games, W19 D27 L18,
pentanomial `1/6/16/9/0`, LLR `+0.19`, and `+5.4 +/-46.6` Elo (95%). The
machine-readable result is
`build/root_architecture_ltc_pilot_seed20261032.json` (SHA-256
`4B13129FE0B7B9B991F345020BA69015CF50072AF1C89C87F5AD9BE069EEAC3E`),
and the full pair log has SHA-256
`1285409A10F4BB8FB076CA6DD18455734A174E71033421677095336A0524A3DF`.
The run moved from an early negative point estimate back to exact balance near
pair 24, demonstrating why it must not be truncated based on direction.

Together, the STC PASS and longer-time neutral result are a **time-control
reversal**. Reject a global “force Threads=1” routing change: it is strongly
supported only at the shortest allocation and has no longer-time promotion
evidence. Also do not interpret neutral Elo as proof that root split is
efficient; the deterministic corpus still shows lower depth, 3.4--3.5x more
nodes, and much weaker alignment with stable deeper moves.

The next single experiment is an isolated-state root-scout mechanism that
directly addresses the old root-alpha failure: scout other roots in their
private contexts, but clear a fail-high worker's scout TT/history before its
full re-search so the scout cannot contaminate the exact result. Keep it opt-in
and use same-source experimental-API DLLs. First require deterministic selected
move/score parity against full root split on a diverse fixed-depth holdout; if
that fails or loses the deadline, REVERT without SPRT. Do not combine it with
shared TT, selective root, session resume, qsearch, HCE, or any accepted DLL
replacement.

### 2026-08-23 fail-high re-search clear candidate (REJECTED)

The isolated candidate added one opt-in behavior to the old root-alpha path:
after every scout completed, a reported fail-high worker had its private
TT/history/killers/root cache cleared before the ordinary full re-search. The
same current-source experimental-API DLL had SHA-256
`5C9E276133A12F3FF645C2BD2C0FCC3FBC574B359C4E59DC4C9D5E8B3DD5C1D3`.
The candidate was deterministic against itself on all four stratified smoke
positions at depth 8, including exact move, score, and node count.

It failed the required control-parity gate immediately. Versus full root split
it matched only 1/4 selected moves, 3/4 scores, and 0/4 node counts. One case
returned `1-5` / +2 instead of `9-14` / +10. The complete four-position result
is `build/isolated_root_scout_audit_smoke.json` (SHA-256
`4E45EB37EA089210D05A555A6D5BB3B712AE79A9C6762ADB4B8AA2194B3202E8`).
No larger holdout, deadline test, or SPRT was justified.

Root-result inspection identified the mechanism: the null-window scouts often
returned the current root bound for nearly every move. In the failing +10
case, the scout reported +2 and therefore never entered the `> root_bound`
full-research set. Clearing only after fail-high cannot repair a challenger
that stale bound/search state suppresses before detection. The candidate code
and harness were fully reverted; only the DLL/result artifact remain. The
focused seven tests passed after revert, the full source suite passed `177/177`
in 82.124 s, and the accepted DLL remains untouched.

Do not retry this re-search-only clear. The next single experiment, if root
scouting is pursued, must use **dedicated fresh scout contexts** that never
share TT/history/killers with the persistent full-search workers. A scout is
cleared before every null-window probe; only a detected challenger is searched
by its untouched ordinary worker. First run a four-position depth-8 proof and
abort on any selected-score mismatch, then expand to the 48-position fixed-
depth gate. Track added memory and do not proceed to timed/SPRT work unless the
exactness gate passes.

### 2026-08-23 dedicated fresh-scout candidate (REJECTED)

The follow-up candidate used twelve additional private scout contexts at TT
power 16 (30 MiB aggregate TT). They never shared TT/history/killers with the
twelve persistent full-search workers and were cleared before every
null-window probe. Scout results were internally marked as bounds, so only the
exact first root and fully re-searched challengers were eligible to win. The
four-position depth-8 proof passed selected-score parity 4/4, repeatability
4/4, and equivalent-best-move 4/4; one selected move differed only on a +26
control tie. It reduced nodes to `0.7224x`, but its small-sample wall ratio was
already `1.3524x` and memory rose from 535,660,492 to 589,237,976 bytes.

The predeclared 48-position depth-12 gate then failed. Candidate
repeatability remained exact 48/48, but versus full root split it matched only
30/48 selected scores and 36/48 moves/equivalent moves. Nodes fell to
`0.7207x`, while wall time worsened to `1.5554x` (2,641 versus 1,698 ms).
After deeper workspace allocation, memory was 629,281,224 bytes versus
553,978,148 for control, an added 75,303,076 bytes. The proof artifact SHA-256
is `1C34BCE4A88140DEE38DD4B3C2EB91689B0A3F99F13F28525F95FC91767183AE`;
the full gate artifact
`build/fresh_root_scout_audit_20260823.json` has SHA-256
`D3F8713E17E75025C54FA8C8A7BE1FB2D91C3AFC017C244DDD223FC4AAB78564`.

This is deterministic but neither score-preserving nor fast. It is
**REJECTED** without timed search or SPRT, and all Python candidate code/harness
was reverted. Do not retry root scouting through the current fixed-window API:
separate contexts remove state contamination but not the iterative/full-root
semantic mismatch, and the extra contexts erase the node saving in wall time.

The next single experiment returns to measured P2 single-thread quality rather
than another parallel scheduler. Add behavior-preserving census instrumentation
for deep normal nodes that lack a valid TT move, split by full versus null
window, then measure the 96-position deterministic corpus and the two human
divergences. Only if missing-TT deep nodes are a material share may an isolated
internal-iterative-reduction candidate be screened. Do not add IIR merely
because chess engines use it, and do not combine it with LMR/null/qsearch/HCE.

### 2026-08-23 deep missing-TT / IIR census (PROMOTE diagnostic infrastructure)

The measurement-only `MAKHOS_IIR_CENSUS` path now counts normal nodes only
after they survive the TT-cutoff and terminal-move checks, which is the exact
point where an IIR candidate could act. It excludes root and depth below four,
then partitions eligible nodes by full/null window, forced capture/quiet,
TT-move presence, and missing-TT depth 4/5/6+. The flag defaults off. The
Python bridge discovers the optional API by exported symbol, so accepted and
ordinary DLLs retain their existing ABI and behavior.

The reproducible audit is `scratch/iir_census_audit.py`. Same-source builds
used Clang `-O3 -march=native -std=c17 -Wall -Wextra -Werror
-Wno-unused-function -shared -DMAKHOS_NO_MAIN`; the census candidate added only
`-DMAKHOS_IIR_CENSUS=1`. The control SHA-256 is
`6928F2078D0B2AAF7AE1608264A909E5DC37760157E129D73C14CE6BEDE513BF` and
the census DLL SHA-256 is
`E5B48B9BFC52AE88669157B53047D3326D6C6C37FB1AE08DA308C2DF96E31E22`.
On 96 deterministic positions, seed 20260920, depth 15, TT power 17, two fresh
repetitions per DLL, control and census builds matched move, score, node count,
and PV in 96/96 cases; both were repeatable 96/96. Median-time sums were
4,527.416 versus 4,577.102 ms (`1.010974x`), confirming that the diagnostic
counter overhead is small but must not be treated as a speed candidate. The
full source suite passed 178/178 in 78.037 s. The accepted DLL remained
byte-preserved at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

Across the 96-position census, 922,896 of 5,964,065 post-TT normal nodes were
eligible (15.4743%). Of those, 303,269 lacked a TT move (32.8606%). Missing-TT
incidence was 300,009/888,614 at null windows (33.7615%) but only 3,260/34,282
at full windows (9.5094%). It was similar for forced-capture and quiet nodes
(32.3410% and 33.0735%). The missing-depth split was 142,005 at depth 4,
78,657 at depth 5, and 82,607 at depth 6+; depth 6+ therefore supplies a
material 27.2389% of missing-TT nodes without relying on the shallowest layer.

The two supplied-game divergences were also checked at reproducible fixed
depth 22 with exact control parity. Ply 13 had 466,867/664,532 missing TT
(70.2550%), including 168,560 at depth 6+ (36.1045%); ply 25 had
912,149/1,421,738 (64.1573%), including 337,019 at depth 6+ (36.9478%). The
artifact `build/iir_census_audit_20260823.json` has SHA-256
`996A4F8D39D90CC0687C5AF98E47D799AADE742F077433E371164336758113C4`.

This is material general scope, so the next single behavioral experiment is
an isolated one-ply IIR at non-root null-window nodes with no TT move and
depth at least six. Screen the conservative quiet-node form first to avoid
shortening mandatory tactical capture chains. Require legal/deterministic
correctness, then fixed-depth 96-position move/score/node evidence and the two
human ladders. Run paired pentanomial SPRT only if the deterministic gate shows
real node or time relief without broad instability. Do not combine this test
with LMR, null move, qsearch, evaluation, or root-parallel changes.

### 2026-08-23 conservative quiet non-PV IIR candidate (SEED 1 INCONCLUSIVE)

The first behavioral candidate reduced depth by one only after the null-move
probe at non-root null-window nodes with no TT move, original depth at least
six, no mandatory capture, `allow_null=true`, and no repetition dependency.
No LMR, null-move, qsearch, evaluation, or root code was otherwise changed.
The deterministic artifact `build/iir_quiet_candidate_audit_20260823.json`
has SHA-256
`A08DE1F386DD5142546D9A9B0B07FFE580181C6D2A4E877727DEE64829AEB1C3`.
On 96 positions at depth 15, seed 20260920, TT power 17, two repetitions, both
builds were deterministic and legal 96/96. The candidate matched 78/96 moves
and 49/96 scores, searched 16,385,815 versus 19,185,628 nodes (geometric ratio
`0.925862`) and measured `0.860481x` wall time. The broad score differences
mean this is selective-search behavior, not a throughput-only speedup.

At fixed depth 22 in the supplied-game diagnostics, the candidate cut the
ply-13 search from 9,908,456 to 6,874,734 nodes but changed `22-18/-12` to
`27-24/-8`; at ply 25 it retained `19-16/-2` while cutting 18,237,224 to
5,017,703 nodes. Under a 5-second cap on the external Sian-Thao ply-21 fixture,
both candidate and control completed only depth 20 and chose `27-24`; this
candidate did not reveal the stable depth-25 `27-23` plan sooner.

The same-source no-IIR control matched the byte-preserved accepted DLL in
move, score, and nodes on 96/96 depth-15 cases. A production-surface candidate
was therefore rebuilt with `MAKHOS_EXPERIMENTAL_SEARCH_APIS=0`; it matched the
measurement candidate move/score/nodes on 96/96 cases and has SHA-256
`2D00316AE539D14104FD7D457C2961251434A52E151A951A223148401AE275EB`.
An earlier five-pair seed was discarded because preflight showed the
experimental API-surface mismatch; it is not strength evidence.

The clean paired STC seed 20260924 used accepted master directly, one Thread
per engine, 512 MiB Hash each, persistent search, production 3/4/5/6-piece
tablebases, 0.2 s + 0.01 s, eight opening plies, and colour-swapped pairs. It
reached the 64-pair cap INCONCLUSIVE: W42 D41 L45, pentanomial
`3/14/32/13/2`, LLR `-0.47`, and `-8.1 +/- 36.6 Elo` (95%). The result artifact
is `build/iir_quiet_production_sprt_seed20260924.json`; do not promote from
fixed-depth savings. Run one independent 64-pair STC replication. Aggregate
the two seeds; if they still do not support a positive direction, reject and
fully revert this IIR mechanism without spending an LTC run.

The independent seed 20260925 was also INCONCLUSIVE but positive: W41 D55
L32, pentanomial `0/13/32/16/3`, LLR `+1.74`, and `+24.5 +/- 33.8 Elo`.
Aggregating the two identical-setting seeds gives 128 pairs / 256 games,
W83 D96 L77, pentanomial `3/27/64/29/5`, LLR `+1.00598`, and
`+8.14 +/- 24.97 Elo`. This is a weak positive direction, not promotion
evidence. The per-seed and aggregate artifacts are
`build/iir_quiet_production_sprt_seed20260925.json` and
`build/iir_quiet_production_stc_aggregate_20260924_20260925.json`.

Before any LTC pilot, rerun the external ply-21 1.0/1.2/1.3-second cold ladder
with `repetition_limit=0`; the earlier 5-second target gate accidentally used
project repetition semantics and is not comparable to the documented
depth-25 target. Only if the corrected ladder is neutral or favorable may the
aggregate STC justify a bounded LTC pilot. A regression at the critical target
overrides the weak aggregate point estimate and rejects the candidate.

The corrected cold ladder used the accepted and production-surface candidate
directly, TT power 20, depth cap 64, no-progress 80, `repetition_limit=0`,
fresh TT, five trials each, and alternated run order. At 1,000, 1,200, and
1,300 ms the accepted engine completed depth 21 in all 15 trials and chose
`19-15`; the candidate completed only depth 20 in all 15 trials and chose
`27-24`. Neither found `27-23`, but the candidate's consistent one-ply loss is
a direct regression on the phase's critical horizon target. The artifact
`build/iir_quiet_critical_ladder_20260823.json` has SHA-256
`C7430DBCC80C4DA16B0FCC1C7BC37013DFE8F01CE4F9D3CFBBCF55197F708C4C`.

The conservative quiet non-PV IIR candidate is therefore **REJECTED** without
LTC despite its weak-positive aggregate STC point estimate. Its selective
depth reduction lowers fixed-depth work but does not convert that saving into
reliable timed depth at the critical position. The candidate macro and search
block were fully reverted; retain the census instrumentation and result DLLs/
artifacts only for reproducibility. Do not retry IIR at depth 6+ without a new
verification mechanism that explains and prevents the timed-depth regression.

### 2026-08-23 current-production PGO screen (REJECT strength promotion)

The next isolated experiment changed no source-level search behavior. It built
the current production-equivalent source with Clang profile-guided optimization
and `MAKHOS_EXPERIMENTAL_SEARCH_APIS=0`. The ordinary same-source control is
`build/makhos_native_current_production_control.dll` (SHA-256
`CACF2DE046B37CD7F76BAC28AFA91E9EB24442EC52C109F255FB9B64C4806528`), the
instrumented training DLL is
`build/makhos_native_current_production_pgo_instrumented.dll` (SHA-256
`EE56FA9190CC29B3739C60B41DA552CB9633C4D75FEBEBE81F064881ACDBB184`), and
the PGO candidate is
`build/makhos_native_current_production_pgo_candidate.dll` (SHA-256
`33315162E8C3B4F3E206B82184F983EF33B2600327EDE3E2C7D02FB7A5DD64F5`).
All builds used Clang `-O3 -march=native -std=c17 -Wall -Wextra -Werror
-Wno-unused-function -shared -DMAKHOS_NO_MAIN`; production surfaces added
`-DMAKHOS_EXPERIMENTAL_SEARCH_APIS=0`, instrumentation added
`-fprofile-instr-generate`, and the candidate used
`-fprofile-instr-use=build/pgo/current_production_20260823/training.profdata
-Wno-profile-instr-unprofiled`.

The profile was collected on 96 deterministic positions, seed `20260920`,
depth 15, hash power 17, one repetition, then merged to
`build/pgo/current_production_20260823/training.profdata` (SHA-256
`E4477FFF5286F874730E2F156BA0C6E68365F86B70019A83ADEBCEB67E15FD6D`).
Two independent 96-position holdouts at depth 15 and three repetitions proved
exact behavior preservation: candidate/control move, score, and node count
matched 96/96 on both seeds. Seed `20260921` measured `0.892634x` wall time;
seed `20260922` measured `0.900072x`. The ordinary same-source control also
matched the byte-preserved accepted DLL move/score/nodes in 96/96 cases on seed
`20260922` and measured a neutral `1.003237x`, proving that the roughly 10%
speed signal comes from PGO rather than a source mismatch. The holdout logs are
under `build/pgo/current_production_20260823/`.

The cold critical ladder used 12 Threads, 512 MiB total Hash,
`repetition_limit=0`, and five fresh trials per 1,000/1,200/1,300-ms budget. At
1,000 and 1,200 ms both accepted and PGO builds completed depth 24 and chose
`25-21` in 5/5. At 1,300 ms accepted remained depth 24 / `25-21` in 5/5, while
PGO completed depth 25 and chose the stable `27-23` plan in 4/5 trials (one
depth-24 `25-21`). The artifact
`build/current_production_pgo_critical_ladder_20260823.json` has SHA-256
`DBB9488F1E3B01EC87B7DC3EE2F73625157BE045E464811E7747D6F974739259`.
This narrows the horizon but still does not meet the one-second target.

A production paired screen then ran the PGO candidate directly against the
accepted DLL for 100 colour-swapped pairs / 200 games, seed `20260936`, 10 s +
0.1 s, 12 Threads per side, 512 MiB total Hash per side, persistent search,
eight opening plies, one game at a time, production 3/4/5/6-piece tablebases,
and `H0=-10`, `H1=+10`. It exhausted the declared cap **INCONCLUSIVE** at W51 /
D85 / L64, pentanomial `4/31/43/18/4`, LLR `-1.78`, and `-22.6 +/- 30.5 Elo`
(95%). The complete log
`build/current_production_pgo_sprt_seed20260936.log` has SHA-256
`74B20D6512EBA934D0E992F7D70AE362741FE1B5393AF71ABD86B883DB985057`.

The PGO build is therefore **REJECTED for production-strength promotion**. The
fixed-depth throughput and critical 1.3-second result are real, but the paired
match does not support an Elo gain and points negative; do not replace the GUI
or accepted DLL with it. There is no source behavior to revert. Retain the PGO
DLL/profile/logs only as reproducible compiler-throughput artifacts. The
accepted DLL remains untouched at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

LLVM profile counts now identify square/coordinate geometry as the next broad
representation target: `bit_at`, `coord_to_index`, `index_to_coord`, and
`reference_capture_recursive` are among the highest-count production routines,
while prior telemetry already attributes about 63% of nodes to qsearch and
move generation. The next single experiment is therefore an opt-in,
behavior-preserving **precomputed square-geometry primitive** screen. Replace
only the repeated 32-square index/coordinate and valid dark-square conversion
arithmetic with immutable lookup tables; preserve generated move order and do
not reuse the rejected unscoped fast-capture implementation. Require the
published perft through depth 10, randomized Python/native move differential,
full source suite, exact 96-position move/score/node/PV parity on two seeds, and
a repeatable fixed-depth timing win before any source promotion. Revert without
timed search or SPRT if the lookup loads/code size are neutral or slower.

### 2026-08-23 precomputed square-geometry primitive (REJECTED)

The opt-in `MAKHOS_PRECOMPUTED_SQUARE_GEOMETRY=1` candidate replaced the
variable shift in `bit_at`, square-to-row/column arithmetic, and validated
row/column-to-square arithmetic with immutable 32/64-entry lookup tables. It
changed no move-generation branch or move order. The production-surface
same-source control was
`build/makhos_native_square_geometry_control.dll` (SHA-256
`9C893FFE4A62C2923CBE3EA3ECF764D8699BD7550CB2AFEA8B5399087C6103BF`); the
candidate was `build/makhos_native_square_geometry_candidate.dll` (SHA-256
`FE8E899DF6F1ECA0E2A176F3BBC690BF8461CD8A5433FB9F2993D88FFCC13C8A`).

Correctness passed before performance measurement: the candidate executable
matched the official initial-position perft sequence through depth 10, ending
at `861842812`, and the randomized Python/native differential passed 1,004
positions / 5,495 legal moves plus 10 exact three-piece states (seed
`20260940`). On 96 deterministic positions, depth 15, hash power 17, three
repetitions, candidate/control move, score, and node count matched 96/96 on
both independent seeds. Despite exact behavior, the candidate was repeatably
slower: seed `20260941` measured `1.028505x` wall time (5,313.919 versus
5,166.642 ms), and seed `20260942` measured `1.030895x` (4,878.744 versus
4,732.531 ms). Logs
`build/square_geometry_bench_seed20260941.log` and
`build/square_geometry_bench_seed20260942.log` have SHA-256
`EA08F8427E0AD739CACFCB21B457FFFAD127A8ACE62A889ECF4AC9C98B497382` and
`A164DBB417DAE4C5921997CD81B7CF2E0665E3BE111C51A9818D583D9025BA99`.

The lookup candidate is therefore **REJECTED** at its behavior-preserving speed
gate; no timed search or SPRT was run. Table loads/code layout cost more than
the compiler's shift/divide-by-four arithmetic. The macro, tables, and branches
were fully removed, and the post-revert suite passed 178/178 in 77.672 s. Do
not retry these global lookup primitives unchanged. Candidate binaries/logs
remain only for reproducibility; the accepted DLL remains byte-preserved.

The next single experiment is measurement-only **repetition-scan census**
instrumentation. LLVM counts put `same_history_entry` and
`search_repetition_count` near the hottest move-generation routines, but block
counts are not elapsed-time proof. Add default-off counters for normal/qsearch
calls, initial-history linear entries, hash-table probes, in-line entries
scanned, identity matches, draw hits, and scan-span buckets. Require exact
move/score/node/PV parity before trusting the census. Measure the deterministic
96-position corpus and the supplied human-game divergences under project
repetition rules. Only if line/history scans are a material per-node cost may a
packed-key or incremental-count candidate follow; preserve full-state collision
verification and explicit threefold/80-ply boundary tests.

### 2026-08-23 repetition-scan census (PROMOTE diagnostic infrastructure)

The default-off `MAKHOS_REPETITION_CENSUS=1` path now counts repetition checks
without changing comparison, history, cutoff, or TT behavior. It partitions
normal versus qsearch calls; linear initial-history entries; hashed-history
probes; initial hits; in-tree line entries/matches; actual repetition draw hits;
and zero/1--4/5--16/17+ line spans. The optional
`makhos_search_repetition_census` symbol is discovered by the Python bridge, so
ordinary and accepted DLLs keep their existing ABI and behavior. The targeted
counter/clear test passes, and the post-instrumentation suite passed 179/179 in
78.693 s.

The same-source control
`build/makhos_native_repetition_census_control.dll` has SHA-256
`D3C57F87C142099D795EDAABBD871376EEF4E084EE902124E7075BA6545EA54B`; the
census DLL `build/makhos_native_repetition_census_candidate.dll` has SHA-256
`EDB1EF378F9E3838F7B3A890A47CDE80FF0E039DA33AB81881D7FE3CEAAAD3D2`.
On 96 deterministic positions, seed `20260920`, depth 15, hash power 17, and
two fresh repetitions, both builds were repeatable and matched move, score,
node count, and PV in 96/96 cases. The two supplied human positions also
matched exactly at depth 22. Median-time sums were 4,611.481 versus 4,653.593
ms (`1.009132x`), so the small diagnostic overhead must not be treated as a
speed result. The artifact `build/repetition_census_audit_20260823.json` has
SHA-256
`FF79BEBD3C22894E8318B11A93F5A8F77342219A58A24389FF7C34067C9FCE0`.

The general corpus made 19,185,628 repetition-count calls, exactly matching
search nodes; 11,916,146 (`62.1098%`) were qsearch calls. The current linear
initial-history path handled 18,918,707 calls and inspected 234,923,643 entries,
or `12.417532` entries per call. In contrast, the existing >=32-entry hash path
handled 266,921 calls at only `0.356637` occupied probes per call. Across both
paths only 86 initial-history matches and 108 actual draw cutoffs occurred.
The in-tree line scan inspected 42,994,934 entries (`2.240997` per call); 88.02%
of calls had spans 1--4 and none exceeded 16. The two human positions had no
initial history, only `1.751076` and `1.973158` line entries per call, and no
repetition cutoff. Thus the broad production waste is the small-history linear
threshold, not the human fixtures or long search-line spans.

This measurement-only infrastructure is **PROMOTED**. The next single
behavior-preserving experiment is an opt-in **small-history hash lookup** that
changes only `prepare_history_lookup()` eligibility from 32 entries to any
non-empty history. Keep the existing collision key plus complete red/black/
kings/turn verification and first-duplicate semantics. Add direct equivalence
tests for 1/2/31/32-entry histories, duplicates, threefold at the root and in
the search line, and reversible clocks 79/80. Then require exact fixed-depth
move/score/node/PV parity on two seeds and a repeatable timing win before a
critical ladder or source promotion. This is a representation optimization;
do not combine it with self-match skipping, pruning, qsearch, or HCE changes.

### 2026-08-23 small-history hash lookup (REJECTED)

The opt-in `MAKHOS_SMALL_HISTORY_HASH=1` candidate changed only
`prepare_history_lookup()` eligibility so any non-empty initial history used
the existing open-addressed lookup instead of reserving it for 32+ entries.
The stored mixed key, full red/black/kings/turn collision verification, and
first-duplicate behavior were unchanged. The production-surface control
`build/makhos_native_small_history_hash_control.dll` has SHA-256
`74070A26C84022B0D1C8E0BA0BE0EB77B17D411C255112C36B6E0673BC97CEF7`; the
candidate SHA-256 is
`0B967547FE9281A5CE4BBF123ECA53A2A9E4F31FC9C33563B34A99395A0F78B0`.

Four direct correctness tests passed. Candidate and control matched exactly
with 1/2/31/32-entry histories; raw duplicate arrays `(3,1)` and `(1,3)` kept
the first entry; root and in-line threefold cases matched; and reversible-clock
79/80 boundary behavior matched. Both 96-position depth-15/hash-power-17/
three-repetition screens then preserved move, score, and nodes in 96/96 cases.
However, the candidate was slower on both seeds: `1.019466x` on `20260920`
(4,665.805 versus 4,576.715 ms) and `1.008663x` on `20260921` (4,760.488
versus 4,719.601 ms). Logs
`build/small_history_hash_bench_seed20260920.log` and
`build/small_history_hash_bench_seed20260921.log` have SHA-256
`3134EFE33BC9E9C217C63D1602C0562E6691AE91038A5E1DAD575E1865842CA2` and
`5BABF54BCD3E8901DB71B8F8546BADA7FE22A9D43495F33EA100891D47742D31`.

The hash path is therefore **REJECTED** at the speed gate without timed search
or SPRT. Its per-node `search_mix64` cost exceeds the cheap early-out field
comparisons even when linear history scans inspect many entries. The macro and
eligibility branch were fully reverted; the post-revert suite passed 183/183 in
77.331 s. Retain the candidate tests/binaries/logs for boundary reproducibility,
but do not retry a small-history table using the same mixed key unchanged.

The census still identifies one cheaper, proof-local opportunity: every
in-tree repetition call compares `line[ply]` with the current position and gets
a guaranteed match. Those 19,185,628 self matches account for roughly 45% of
42,994,934 line entries. The next single behavior-preserving experiment is an
opt-in **current-line self-match skip**: when `ply >= line_begin`, initialize the
in-tree occurrence count to one and scan from `ply-2`; retain the existing root
case with external history (`ply < line_begin`) unchanged. Do not alter initial
history or hashing. Reuse all duplicate/threefold/79--80 tests, require exact
two-seed move/score/node/PV parity and a repeatable speed win, and reject before
timed search if either gate fails.

### 2026-08-23 current-line self-match skip (REJECTED)

The opt-in `MAKHOS_REPETITION_SKIP_CURRENT_LINE=1` candidate replaced the
guaranteed `line[ply] == current position` comparison with one initial in-tree
occurrence and began the backward scan at `ply-2`. The external-history root
case (`ply < line_begin`), all older line entries, initial-history handling, and
draw thresholds were unchanged. Production-surface control SHA-256 was
`5715A0E0E8B640B29A1AEE765B533E71A6713F2164E571EE804611EDDA6ECDA7`; candidate
SHA-256 was
`753DDEDAF07D01BC8647F5CCB90E8743D0B4DF9539C6B460775D152225845D12`.

The shared 1/2/31/32-entry, duplicate-first-entry, root/in-line threefold, and
reversible-clock 79/80 tests all passed. Four independent 96-position depth-15
screens matched move, score, and nodes in 96/96 cases. Three-repetition timing
ratios were `0.984986x` on seed `20260920` but `1.001590x` on `20260921`.
The bounded five-repetition replications were only `0.997327x` on seed
`20260922` and `0.995571x` on `20260923`. Complete logs and SHA-256 hashes are:

- `build/current_line_skip_bench_seed20260920.log` —
  `A636726E8925306AADCCE545D52C126ED090350DD05717F92B5E6D78541E4E1B`;
- `build/current_line_skip_bench_seed20260921.log` —
  `66ADD66F9D6C0CA17CF4CC7FAAEE62A2DF0F8886FEA6398872368DF5C680536E`;
- `build/current_line_skip_bench_seed20260922.log` —
  `E5555198485CA32B4AE44ADDC205BE5BF33E2599E8856B3A2F2D4192AB2734C6`;
- `build/current_line_skip_bench_seed20260923.log` —
  `7CA4846BB7DC2CD450EB774C41A7070D9B15C06A57D02685B21A86A20990C349`.

The small speed direction justified a critical check but not promotion. At 12
Threads, 512 MiB total Hash, and five cold trials each at 1,000/1,200/1,300 ms,
candidate and control both completed depth 24 and chose `25-21` in every trial;
neither found `27-23`. The artifact
`build/current_line_skip_critical_ladder_20260823.json` has SHA-256
`91766B72E654E3D0198C1B36A415852618DDAB4520A42F40B0A47DC9A754F340`.

The candidate is therefore **REJECTED** without SPRT. Its replicated sub-0.5%
gain does not move the critical horizon and matches the project's prior
rejection standard for neutral micro-speed paths. The macro and scan shortcut
were fully reverted; the post-revert suite passed 187/187 in 78.700 s. Keep the
boundary tests and artifacts, but do not retry this exact self-match skip.

Repeated qsearch/TT/SMP/IIR/root/repetition micro-candidates now show clear
classical-search diminishing returns, while the accepted evaluator still lacks
independent middlegame labels. The next single experiment moves to HCE/data: a
measurement-only **middlegame tuning-readiness audit** over corpus v4 plus the
human divergences. Split by source game (never by position), inventory every
current HCE feature's coverage/variance/correlation, report stable-versus-
conflicting long-search labels and piece-count/phase gaps, and test whether the
existing samples support a well-conditioned train/holdout fit. Do not change a
weight unless the audit proves sufficient independent coverage; otherwise
produce a concrete corpus-v5 acquisition plan instead of overfitting 192
synthetic positions.

### 2026-08-23 middlegame HCE tuning-readiness audit (INSUFFICIENT)

The measurement-only audit is reproducible with
`scratch/hce_tuning_readiness_audit.py` (SHA-256
`901CFCC55029705B29AA2B2211750A27B296D34079143A47CC14FABEB16FC659`). Its
complete result is `build/hce_tuning_readiness_audit_20260823.json` (SHA-256
`A5D564FAE0AC627C2CA56E212ED01B5B2F0E5D8E031A7A955C91489FA0CC4D90`); a second
run reproduced the artifact byte-for-byte. Whole source games were assigned by
a salted SHA-256 split, yielding 18 train games and six holdout games. The
corpus still has 192 positions from 24 games, but only 69 positions from 23
games pass the stricter label gate: the last two searches agree and the class
is either `stable` or `short-search-divergence`. This excludes 12 nominally
usable `settings-or-version-mismatch` rows rather than laundering incomplete
provenance into a target. The strict split contains 52 train positions and 17
holdout positions; there are zero conflicting source labels, but every label
remains accepted-self-search stability rather than ground truth.

The nine-term move-ranking basis is not identifiable from these data. The
position-global `simplification` term is deliberately excluded from this gate
and must remain fixed until separate outcome/value labels identify it. The 399 train
chosen-versus-alternative pairs exercise only `man_pst`, `support`,
`back_rank`, `passed_men`, and `king_mobility`, for rank 5/9. The 107 holdout
pairs exercise only `man_pst`, `support`, and `back_rank`, for rank 3/9.
`men`, `kings`, `king_pst`, and `king_edge` are identically
zero in the train pair deltas; several of the nominally active terms occur in
only one or two train games. The active train submatrix itself has condition
number 1.7402, so the problem is missing feature/phase coverage rather than
numerical instability among the five observed columns. Ridge regularisation
could manufacture a solution but cannot identify absent coefficients or the
separate outcome-only simplification term.

Phase coverage confirms the cause: piece counts are limited to 12--16, plies
7--18, with only 17 positions in the 9--12 band, zero positions at 5--8
pieces, and 191/192 positions containing no king. The current static evaluator places
the stable search move in its best-score tie in only 20/69 positions (29.0%)
and uniquely first in 15/69 (21.7%). On the game-held-out subset those figures
fall to 4/17 and 2/17. Pairwise current-static margins are positive in only
280/506 comparisons (55.3%). These are diagnostic correlations with the
engine's own deeper search, not evidence that fitting those labels will improve
playing strength.

The two human-game divergences remain out-of-sample regressions, not training
rows. On ply 13 the present HCE scores deeper alternatives `22-18` and `23-19`
19 and 27 cp below the recorded losing `28-24`; on ply 25 it scores the stable
deeper `31-26` 15 cp below the losing `27-23`. The first deltas are dominated
by support and man-PST, while the second is a man-PST delta; none identifies a
safe coefficient change because the same corpus lacks phase and independent
labels. This refines the diagnosis: search horizon exposed the mistakes, but
the leaf evaluator currently points in the wrong static direction too.

The audit verdict is **INSUFFICIENT -- do not fit or change HCE weights**. No
playing code or weight changed, so no SPRT was warranted. Evaluator/corpus
correctness tests passed 10/10, and the byte-preserved accepted DLL remains
unchanged at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

The next single experiment is **middlegame-search corpus v5 acquisition**, not
a coefficient guess. Lock complete games into a 48-train/16-holdout manifest;
target at least 64 games, 512 strict stable positions, and at least 128 samples
at 5--8 pieces, 256 at 9--12 pieces, 256 at 13--16 pieces, and 128 mixed-king
positions. Vary opening
length as well as seed, cap samples per game, stratify by phase/king/capture/
branching, and deduplicate position plus reversible clock. Use the
byte-preserved accepted DLL for identity and deterministic deeper
single-thread analysis as the observational teacher because the production
root splitter is a measured weaker teacher. Preserve all budgets, root scores,
PVs, depths, nodes, and provenance; reserve human/external games as independent
regressions. Rerun this audit before considering one HCE candidate, and do not
start NNUE/DFPN or change weights while the coverage gates fail.

### 2026-08-23 middlegame-search corpus v5 acquisition pilot (PROMOTE PIPELINE)

The resumable acquisition harness is
`scratch/middlegame_v5_acquire.py` (SHA-256
`070555F24E7E41BBF0BF7C6CBE008EAE992DF827D24527509F2422A570F7A9AB`). It
hard-fails unless the teacher is the byte-preserved accepted DLL, keeps whole
games in one split, drops any position-plus-clock duplicate crossing the split,
and checkpoints every generated game and analysis. Generation varies random
opening length over 2/4/6/8/10/12 plies and explicitly tagged exploration over
5/10/20/30%, then uses accepted single-thread fixed-depth-10 play. Selection is
capped at 16 positions per game and stratified across 13--16, 9--12, and 5--8
pieces, preferring mixed-king coverage. Teacher analysis is fresh-TT accepted
single-thread search at 100/500/2,000 ms with 128 MiB Hash; all PVs, completed
depths, nodes, scores, static child traces, rules, history clocks, and DLL
identity are retained. Labels remain search-stability observations, not proven
best moves.

The eight-game pilot used seeds `20262801..20262808` and locked six complete
games to train and two to holdout. Its config SHA-256 is
`739D7D82198589D1CEE3B4CE2A13FB78ECB48CC1B09CA255014EB60B966550C9`; the
selection manifest SHA-256 is
`6220E3036D958ECE44B49B94BF589DAE31606A6D094240BBCD4CDE71239048A0`. One
cross-split duplicate was dropped before analysis and there were no remaining
within-split duplicates. The resulting 120 unique positions contain 33 at
13--16 pieces, 37 at 9--12, 50 at 5--8, and 64 with at least one king. This
directly repairs the phase failure measured in v4 rather than merely adding
more opening positions.

The pilot corpus is
`build/middlegame_v5_generation_pilot/corpus.jsonl` (SHA-256
`D22A1C4E19D822EF4A73E0BE7D89DCBD7AE3391A00C029930F67862659ABE216`); its
summary SHA-256 is
`81655D6138F49B3E3AB69DC6C92642712D4F798A06427584A94B325112D09361`. Search
classifications are 101 stable, seven short-search-divergence, and 12
long-horizon-divergence. Thus 108/120 positions (90.0%) pass the strict last-two
budget agreement gate, including 80/90 train and 28/30 holdout. A complete
resume/rebuild reproduced config, manifest, corpus, and summary byte-for-byte.
The game-analysis/corpus correctness suite passed 15/15. No evaluator/search
behavior changed, no SPRT was warranted, and the accepted DLL remains SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

The locked-manifest readiness rerun is
`build/middlegame_v5_generation_pilot/hce_readiness.json` (SHA-256
`A329374E4E2A153EC465F4202A1679FE6A198F5F8E60C186651FCF2C5F32C3CE`). Unlike
v4, the pilot train matrix exercises all nine move-ranking terms and is full
rank 9/9 with condition number 8.8472. The holdout contains every term but is
rank 8/9 on only two games; `men` and `kings` are strongly coupled in this
small sample. `simplification` remains intentionally outside the pairwise
basis because sibling moves ordinarily share that position-global phase term.
The pilot therefore proves that the sampler repairs feature identifiability,
but it remains below the predeclared sample/game/holdout and phase-count gates;
it is not permission to fit weights yet.

The pipeline is **PROMOTED for data acquisition only**. The next single
experiment scales the exact locked protocol to 64 fresh games (48 train, 16
holdout), using the default seeds `20262001..20262064`. Require zero
cross-split leakage after dropping duplicates, at least 512 strict positions,
the predeclared phase/king targets, and the accepted DLL identity. Then rerun
the HCE readiness audit against the locked acquisition manifest. Do not fit a
weight merely because the pilot label yield is high; search self-labels still
lack independent outcome evidence.

### 2026-08-23 middlegame-search corpus v5 full acquisition (PROMOTED DATA)

The current resumable acquisition harness, including a locked early-phase
supplement path, is `scratch/middlegame_v5_acquire.py` (SHA-256
`A69CE0D74F336C41888C98B8617872992692700B7A551A6380EA1B607F2F0AA0`). The
64-game config SHA-256 is
`6DAB4ADB3CA34B62F294D05E995A329C15D05142AAD172FB581E1D6B31A9EC95`; the
48-train/16-holdout selection manifest is
`391BE15664E3BEEF4036691DB23227FF8E6E03541611B388ACAE0B7AF34DF41F`.
The main selection produced 948 unique positions after dropping five
cross-split duplicates and one within-split duplicate. Because it yielded only
244 of the predeclared 256 early-phase positions, the target was not relaxed:
a locked nine-train/three-holdout supplement added 12 unique 13--16-piece
positions from the same already-split games. Its manifest SHA-256 is
`996662F80F18834585DBBBEC5C19BAF8AAE6E0F2E9001A3566B7F7568D209D47`.

The final `corpora/middlegame_search_v5.jsonl` has SHA-256
`E6EAE12866243FDA30AC06A71BE47A7AF57AEC295C601E66FF67EF4007D8D3CB`;
`build/middlegame_v5/summary.json` has SHA-256
`9E521422338B6F3577381451AC0C796EFD5043CC23FC6DB4A81EFE99D88CF356`.
It contains 960 unique positions: 256 at 13--16 pieces, 367 at 9--12, 337 at
5--8, and 473 with at least one king. Classifications are 733 stable, 115
short-search-divergence, and 112 long-horizon-divergence, with zero conflicting
source labels. Thus 848/960 positions pass strict last-two-budget agreement,
including 636 train and 212 holdout positions. A no-argument resume/rebuild
reproduced the config, both manifests, corpus, and summary byte-for-byte.

The locked-manifest HCE audit is `build/middlegame_v5/hce_readiness.json`
(SHA-256
`B71698FBC4F7F843FDD5107C73DADCD7227668A54AE6ACCB3756F0494049BDBD`) and was
also reproduced byte-for-byte. Two strict positions containing an immediate
terminal child were conservatively excluded from a linear fit, leaving 635
train and 211 holdout positions. The nine-feature pairwise train matrix has
4,210 comparisons, rank 9/9, and condition number 19.8725; holdout has 1,422
comparisons, rank 9/9, and condition number 17.8635. Every pairwise feature is
present in at least five train games and in holdout. All predeclared size,
phase, king, support, rank, and conditioning gates pass.

The current HCE still agrees poorly with its own stable deeper teacher: it puts
the teacher move in the best static tie in only 225/846 positions (26.6%) and
uniquely first in 159/846 (18.8%). Holdout is similar at 54/211 (25.6%) and
38/211 (18.0%); current pair margins are positive in only 779/1,422 holdout
comparisons (54.8%). This generalises the two human-game wrong-direction
static margins and establishes real fitting headroom rather than one-position
overfitting.

Corpus v5 and the acquisition pipeline are **PROMOTED as data/regression
infrastructure**. The audit verdict is only `sufficient-for-measurement-fit`:
the sole failed promotion gate is an independent non-self-search label source.
No playing code or weight changed, no SPRT was warranted, focused evaluator/
game/corpus tests passed 21/21, and the accepted DLL remains SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

The next single experiment is a **measurement-only grouped pairwise HCE fit**.
Keep `simplification` fixed, weight complete source games/positions equally,
select regularisation only by game-grouped cross-validation inside the 48
train games, and open the locked 16-game holdout once. Report logistic loss,
pair accuracy, top-move rank, coefficient stability, phase/class breakdown,
and the two human-game margins. Do not edit native/Python weights or build a
candidate unless train-CV and locked holdout both improve without pathological
material/sign changes. Even then, strength promotion still requires a separate
one-concept candidate, correctness/deterministic gates, and paired pentanomial
SPRT against the accepted DLL.

### 2026-08-23 grouped pairwise HCE fit (CANDIDATE JUSTIFIED)

The measurement-only fitter is `scratch/hce_pairwise_fit_audit.py` (SHA-256
`2A41355042083E6AB6747E5C9ABBC7B350BD47F4DD557550175CB3ECFED77FE5`). Its
complete, byte-reproduced result is
`build/middlegame_v5/hce_pairwise_fit.json` (SHA-256
`BCBACE00F959B3DD0D2CBE1A2D5BC153EC7BD086FE5857C2AD437C9DD7A94083`). It
fits only the nine move-ranking terms and keeps `simplification=6` fixed.
Every source game has equal aggregate weight, every position within a game is
equal, and every alternative within a position is equal. A six-fold split of
the 48 train games used a fixed hashed manifest. The regularisation grid was
locked before holdout; the conservative one-standard-error rule selected
ridge `1.0`, not the minimum-loss `0.03` fit.

At selected ridge, float and integer-rounded fits improved logistic loss in
5/6 train folds. Mean rounded validation improvement was `0.00497445`. Fold
coefficients retained the same expected sign in every fold. The rounded vector
is: men `99`, kings `332`, man-PST `1`, king-PST `1`, support `6`, back-rank
`16`, passed-men `1`, king-edge `-5`, and king-mobility `2`; simplification
remains `6`. All predeclared sanity gates pass: men and king values remain
positive with king > man, positional/support/back-rank/passed/mobility terms
remain non-negative, and king-edge remains non-positive.

The locked 16-game holdout was opened only after ridge selection. Rounded
game/position-equal logistic loss improved from `0.6781641` to `0.6705243`.
A deterministic 20,000-resample source-game bootstrap gives candidate-minus-
current loss delta `-0.0076204`, 95% interval `[-0.0117107, -0.0036896]`.
Best-static-tie agreement increased only from 53/211 to 56/211; unique-best
fell from 38 to 37 and raw positive pair count fell from 778 to 777. The loss
improvement appears in every phase (`13--16`, `9--12`, and `5--8`) but the
top-tie gain is concentrated in 5--8-piece king positions. This is a modest,
regularised signal, not a solved policy.

The external human regressions do not overclaim success. On ply 13, static
margins for deeper alternatives improve from `-19/-27` to `-15/-21` cp but
remain on the wrong side; ply 25 stays `-15` cp. The fit therefore generalises
some evaluator direction without fixing either reported mistake by itself.

The fit passes the predeclared **candidate-build gate**, but no playing source
or weight changed in this experiment and no strength promotion is justified.
The next single experiment is one opt-in rounded-vector HCE candidate. Implement
the exact vector in both a diagnostic Python evaluator and a separately built
native DLL while leaving defaults and the accepted DLL unchanged. Require
randomized Python/native evaluation parity, full rules/search correctness,
fixed-depth/fixed-time diverse benchmarks including the critical target and
both human positions, then paired pentanomial SPRT against the byte-preserved
accepted DLL. Reject/revert the vector if correctness, deterministic quality,
or strength evidence fails; do not tune a second vector against the opened
holdout.

### 2026-08-23 rounded grouped-pairwise HCE candidate (REJECTED)

The one-concept candidate used exactly the predeclared rounded vector: men `99`,
kings `332`, man-PST `1`, king-PST `1`, support `6`, back-rank `16`, passed-men
`1`, king-edge `-5`, king-mobility `2`, with simplification fixed at `6`. It was
implemented behind an opt-in native macro and a diagnostic Python evaluator;
production defaults and the accepted DLL were not touched. An initial build
accidentally exposed experimental fixed/window search APIs, was caught by the
SPRT preflight, and all results from that build were discarded. The valid
production-surface builds used `MAKHOS_EXPERIMENTAL_SEARCH_APIS=0`: same-source
control `build/makhos_native_hce_pairwise_control.dll` has SHA-256
`B320EAC70CB70FA699316595E82A53AD17728F83E3A909EFE23FA27AF40D0B9F`; candidate
`build/makhos_native_hce_pairwise_candidate.dll` has SHA-256
`AD2EF6CF26062F902128BD968518D10E45E54614D84F2DAB139397DC020BE7BB`.
Both report ABI 5 and no fixed/window/shared search entry points.

Correctness passed before strength testing: randomized Python/native evaluator
parity on 1,000 positions, 188/188 full tests, perft depth 10 = `861842812`, and
native differential verification on 1,004 positions, 5,581 legal moves, plus
ten exact three-piece cases. Against the production control on 96 deterministic
depth-15 positions (seed `20260951`, hash power 17), the candidate changed search
substantially: only 75/96 moves and 23/96 scores matched. Geometric node ratio
was `0.9716539`, but aggregate nodes increased from 20,765,592 to 20,829,870 and
time ratio was `0.9996745`; there was no throughput improvement.

The critical-target ladder is
`build/hce_pairwise_critical_ladder_20260823.json` (SHA-256
`3B690AB0EE63B7A971BE8FFBB0B0C6C927EDD988E61F76E8A060865F9A3D57E5`). Across
five cold 12-thread/512-MB trials at 1,000, 1,200, and 1,300 ms, the accepted DLL
always chose `25-21`, the candidate always chose `25-22`, both completed depth
24, and the candidate never found `27-23`. It therefore fails the explicit
short-term target. Evidence on the earlier human-loss game was mixed: at ply 13
the candidate still chose the shallow mistake `28-24` at 2 s but found `23-19`
at 5/20 s; at ply 25 it changed to `27-23`, contradicting the accepted 20/60-s
teacher preference for `31-26`. The reproducible artifact is
`build/lost_game_hce_pairwise_2s_5s_20s.json` (SHA-256
`5B36400CBF6B06B6A930929A11C509A304AC46843B6DC5F0412906A7F4DCF40D`).

The new เซียนเฒ่า loss was also analysed rather than treated as a tuning target.
Accepted analysis is `build/siantao_loss_20260823_accepted_analysis.json`
(SHA-256
`23FEEEEECB521D2775956D4CAFBAE685C65782E0C68A66B845231F013A1FB8E5`); candidate
analysis is `build/siantao_loss_20260823_hce_pairwise_analysis.json` (SHA-256
`82BEA168791577811038FD0A18F72B38A8FBF619AEBEFDCF88914D279EC81FDC`). Moves
`4-8` at ply 14 and `8-11` at ply 16 remain the long-search best choices. The
first clear loss of value is red ply 20 from
`R:BM22,23,27,30,31,32:RM1,6,9,10,11,15`: the recorded `9-14` is about 80--112
cp worse than the long-search alternatives. Accepted chooses `10-14` in a clean
1-s replay and `1-5` at 20 s; the recorded timed run chose `9-14`. The candidate
does choose `1-5` at 1 s, so it fixes this external position, but that isolated
success is not promotion evidence. The position is now the external regression
`sian-thao-win-red-ply20` in `corpora/positional_regressions.json`, including
every legal root score and a timed ladder.

Two independent paired STC runs used one thread per engine, 512 MB each,
persistent sessions, production 3/4/5/6-piece tablebases, `0.2+0.01`, opening
depth 8, 200-ply cap, and pentanomial SPRT H0/H1 `-10/+10` Elo. Seed `20260953`
(`build/hce_pairwise_stc_sprt_seed20260953.json`, SHA-256
`A13B172C50EFFD31675F0931D4B4D05E4ABD77A76E9ADED72E6D1808E15C912B`) gave
pentanomial `[7,8,29,17,3]`, W/D/L `42/45/41`, LLR `+0.11`, Elo
`+2.7 +/- 43.1`. Seed `20260954`
(`build/hce_pairwise_stc_sprt_seed20260954.json`, SHA-256
`35602439AFD4B66B5F412F16F66E7644CCBDA6F26109E6EFC21B88ACD0EE81E5`) gave
`[4,14,27,16,3]`, W/D/L `38/52/38`, LLR approximately zero, Elo
`0.0 +/- 40.7`. The byte-reproduced aggregate
`build/hce_pairwise_stc_aggregate_20260953_20260954.json` (SHA-256
`CDB55F2845AE108B4AD7844493D833FE0747CC42347DAF46B72AFE139347866D`) is 128
pairs/256 games, `[11,22,56,33,6]`, W/D/L `80/97/79`, exact LLR `0.114735`,
Elo `+1.357 +/- 29.572`: **INCONCLUSIVE and practically neutral**. Because the
candidate misses the critical target, has contradictory regression evidence,
and shows no general playing-strength signal, it is **REJECTED**. No LTC or
12-thread SPRT is warranted.

The candidate branches were removed from Python, native source, and tests.
Post-revert production-surface DLL
`build/makhos_native_hce_pairwise_post_revert.dll` has SHA-256
`E526FC437AE57934EF9B6743B1629A901623510DAB2012AAF48E926C03A9977E`; it matches
the accepted DLL on move, score, and node count in all 96/96 depth-15 cases.
The post-revert full suite passes 187/187. The accepted DLL remains byte-for-byte
unchanged at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

Reusable infrastructure from the experiment is **PROMOTED**: `makhos sprt`
now has an atomic `--output` JSON result containing settings, API preflight,
DLL/tablebase hashes, pentanomial counts, and result; and
`scratch/aggregate_sprt_results.py` (SHA-256
`0051721351B5F3B3C4D79B095522603DD41AAD076919A6FCBB0AF54401230013`) validates
compatible independent runs and aggregates exact pentanomial evidence. The
external regression and its timed-ladder schema are also retained.

### 2026-08-23 classical phase completion checkpoint

Stop classical candidate work at this checkpoint. The measured search program
now shows clear diminishing returns: qsearch, move generation, repetition,
root/SMP, TT, IIR/selectivity, geometry, PGO, and time-routing paths have been
profiled or tested, but the recent high-plausibility candidates either lose
throughput, miss the horizon target, or remain neutral in paired play. The first
regularised, leakage-controlled HCE refit improves self-teacher loss yet is also
neutral in 256 paired games. Reopening the same holdout or stacking another
hand-tuned heuristic would be overfitting, not evidence-driven progress.

The correctness and testing pipeline is mature enough for the next phase:
byte-preserved accepted control, 187-test regression suite, perft/differential
gates, deterministic fixed-depth/fixed-time harnesses, machine-readable paired
SPRT with exact multi-seed aggregation, and external positional regressions.
Data is sufficient to design (not yet train or promote) a serious NNUE pipeline:
`corpora/exact_wdl_eval_v1.jsonl` contains 9,000 exact endgame examples, while
`corpora/middlegame_search_v5.jsonl` contributes 960 diverse, game-split
middlegames with 848 strict stable labels and phase/king coverage. The external
game regressions expose real one-second horizon failures independently of the
self-search corpus.

Per the phase boundary, **do not begin NNUE automatically**. The highest-value
next work is an NNUE design roadmap, followed only after explicit user approval
by a data-acquisition/label-quality experiment. The design must freeze the
accepted classical engine as control, predeclare representation and model size,
split by source game before augmentation, keep exact WDL and deeper-search
targets distinguishable, add external/outcome labels to limit teacher bias,
measure C inference cost before training at scale, require Python/native parity,
and promote only through the same paired pentanomial SPRT pipeline.

### 2026-08-23 NNUE readiness audit and roadmap (DESIGN ONLY)

The requested post-classical roadmap is now concrete and reproducible, but no
NNUE model, trainer, inference path, or playing candidate has been started.
`NNUE_ROADMAP.md` has SHA-256
`25C843F5EAADC261626BB5A0916DA4E759AB696BF507220E8AC498F784C5A869`. The
measurement-only auditor `scratch/nnue_readiness_audit.py` has SHA-256
`B93C59395CF80DB0F50E18DC3D2462DEAF6B4C1488FA0321FB87953F30569AB2`; two
independent executions reproduced `build/nnue_readiness_v1.json` byte-for-byte
at SHA-256
`3C7D91F78A7834762355CC3DFFF99F135E3600A70D0FD71A4AD1EEC1AB010BA7`.

The audit binds the accepted DLL hash and validates the actual label coverage.
The exact corpus has 9,000 unique quiet 4--6-piece samples, evenly split across
WIN/DRAW/LOSS, but every reversible clock is zero. V5 has 960 unique positions
from 64 games: 909 quiet roots, 848 usable search-stability labels, and only 708
that are simultaneously quiet/usable with last-two score delta at most 50 cp.
The score-delta median/p90/p95 is 4/59/115 cp. V5 has balanced turns (476 Black,
484 Red), 473 mixed-king positions, and real clock coverage to 39 plies, but no
game-outcome field. Its HCE holdout was already opened and is not a fresh NNUE
test set. The two external regressions remain diagnostics, with zero proven
best-move labels. Verdict: **design-ready-data-not-training-ready**.

The roadmap locks an initial Thai-specific scalar evaluator rather than copying
chess HalfKP or adding a policy head. Each of two perspective accumulators uses
one shared 137-input feature table: four relative piece categories times 32
canonical squares, plus nine reversible-clock buckets. Red squares rotate by
`31-square`; side-to-move is represented by concatenation order. The single
predeclared v1 shape is `137 sparse -> 128x2 -> 32 -> 1`, with int16
accumulators, int8 dense inference, int32 accumulation, a scalar C oracle, and
an AVX2 candidate path. No mobility/threat/handcrafted features enter v1 without
new evidence. The proof/WDL/tablebase and terminal layers remain authoritative.

The highest-value next experiment is the roadmap's **quiet-leaf scalar-label
acquisition pilot**, and it still requires explicit user authorization because
the user prohibited automatically starting NNUE. It trains no model and changes
no playing code: 256 fresh source games, game-hash 80/10/10 split before
sampling, accepted one-thread persistent teacher at 100/500/2000 ms, at least
8,000 unique quiet positions, and retention only when the last-two score delta
is at most 50 cp. It must preserve game outcomes separately, never label
truncations as draws, bind all teacher hashes, meet turn/phase/king coverage,
show zero symmetry leakage, and reproduce all manifests/corpus summaries
byte-for-byte. Do not begin a trainer experiment before at least 100,000
broad-phase quiet scalar labels and a fresh unopened test split exist.

### 2026-08-23 second 2-second Sian-Thao loss and adaptive-root route (REJECTED)

The new external game record has content SHA-256
`58794DA9C5814560B78606818F47313BA5A69714B3EDDE3D811C27FCAD61C6E0`
and stable game ID `1981eb3c4686b78a`. Replay is legal through all 64 plies,
the final position and reversible clock match, and every engine ply has complete
`search-v1` provenance. Black was the accepted engine at 2,000 ms, 12 Threads,
512 MiB Hash, project rules, and accepted DLL SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

Accepted 2/5/20-second analysis of every non-forced Black ply through ply 21 is
`build/siantao_2s_loss_20260823_opening_analysis.json` (SHA-256
`8BDF52ED8C8339C57788B2C80CE0F9B7FEF663BDC570A0151975E912D30C473F`).
At 20 seconds the recorded moves through ply 19 lose only 0--7 cp against the
observed root best. The first clear loss of value is therefore Black ply 21 at
`B:BM14,20,22,23,27,31,32:RM2,3,5,7,11,13,15`: recorded `32-28` was only
depth 21 / 14,901,245 nodes / `+120`, but the opponent's `2-6` made the next
engine score collapse to `-129`. Fresh accepted searches choose `27-24` at
2/5/20 seconds; the 20-second depth-26 root score is `-14` for `27-24` versus
`-169` for `32-28`, a 155-cp loss. The child-static HCE also scores `27-24`
at `+21` and recorded `32-28` at `-3`. This loss is not evidence that HCE
preferred the blunder; it is a root-search/time-horizon failure.

Cold repeat ladders refine the mechanism. At 2,000/2,001 ms and 512 MiB, the
12-thread splitter chose `27-24` in 10/10 searches at depth 23--24, while
ordinary one-thread search chose it in 10/10 at depth 27 using only about
7.5--7.8 million nodes. Reducing the one-thread TT to a 40-MiB root-worker
partition made it choose the losing `32-28` in 10/10 depth-26 searches. A
160-MiB one-thread TT restored `27-24` in 6/6 depth-27 searches. Thus both
duplicated independent-root work and Hash partitioning matter; merely reusing
one existing root worker is not a valid fix.

One new mechanism was screened rather than changing HCE: a predeclared
Hash-budgeted adaptive route used a 160-MiB ordinary search at roots with at
least eight legal moves and retained root splitting below eight. The reproducible
measurement harness is `scratch/adaptive_root_hash_routing_audit.py` (SHA-256
`FE5598B0401636FC4E49EA13E13807C1C29B85F69F537F1A93FB37A33144A94A`);
the rejected wrapper is isolated at `scratch/adaptive_native_candidate.py`
(SHA-256
`6EAA206B5314AE1ABAFFA24B5A3C0158BDDC00EEE23D5E1B16BA55B4B93EF4EB`).
The audit artifact
`build/adaptive_root_hash_routing_audit_20260823.json` has SHA-256
`0C5C7E2EBB353B0B3E5869210EB70CE5FFC48050DD111E6F0E31C3A30E237A95`.
On the locked 48-position v4 selection, 36 positions had stable depth-17/19
observational references. At a fresh 1,000-ms clock the actual adaptive wrapper
matched 27/36 versus 21/36 for the accepted 12-thread root splitter, reached
mean depth 20.083 versus 19.222, and searched 186,862,450 versus 486,162,653
nodes. It allocated 440 MiB total, below the 512-MiB budget. On the new external
ply 21 it chose `27-24` in 5/5 fresh 2-second trials at depth 27.

Correctness passed before match testing: the focused candidate/parser tests and
the then-current full suite passed 188/188. Two independent production STC
screens used byte-identical accepted DLLs, 12 Threads, 512 MiB Hash, persistent
search, production 3/4/5/6-piece tablebases, `0.2+0.01`, eight opening plies,
one-game concurrency, and H0/H1 `-10/+10`. Seed `20261041` produced
`[5,8,25,19,7]`, W/D/L `48/47/33`, LLR `+1.40`; seed `20261042` produced
`[2,10,30,16,6]`, W/D/L `43/56/29`, LLR `+1.78`. Their exact aggregate
`build/adaptive_root_sprt_aggregate_20261041_20261042.json` (SHA-256
`452EB5DE2742DE747520BF86CBE472287BA807DD01DEAA4B50CBC5D815A5F536`)
crossed **PASS** at 128 pairs / 256 games: `[7,18,55,35,13]`, W/D/L
`91/103/62`, LLR `+3.11362`, and `+39.53 +/- 30.38 Elo` (95%). Individual
artifacts have SHA-256
`65E2AD4B594EB416964C239CB5CC6703BFD901677A235F082E3FF2EFC220AC5D` and
`6E87188D43740DF8770818E81DB51FB9B421D1EA4FF4A3A9C163BAF5B973C849`.

The required closer-to-GUI gate reversed that signal. Two fresh 32-pair pilots
used `10+0.1` with a 1,000-ms move cap and otherwise identical production
settings. Seed `20261043` gave `[0,8,14,7,3]`, W/D/L `20/29/15`, LLR
`+0.76`; seed `20261044` gave `[1,12,15,3,1]`, W/D/L `14/27/23`, LLR
`-1.20`. Their aggregate
`build/adaptive_root_ltc_aggregate_20261043_20261044.json` (SHA-256
`7523F45E1A5FFC08260AFED540CD0290F7E8B2911382A6833E38BDDC89330630`)
is INCONCLUSIVE/neutral-negative at 64 pairs / 128 games:
`[1,20,29,10,4]`, W/D/L `34/56/38`, LLR `-0.56195`, and
`-10.86 +/- 37.71 Elo`. The seed artifacts have SHA-256
`E46A9C06B8792616F3890E786F42B609C25E2DC0BF547CAE57B37A1D118C7C30` and
`7DC4940D6DA8685BCBE0F9215E9F04FFF414E98098218D697E860C1740F92973`.

The adaptive route is therefore **REJECTED for production promotion** despite
fixing this external position, improving the diverse one-second observational
gate, and passing aggregate STC. It repeats the measured time-control reversal:
the advantage does not survive the closer-to-use clock. All playing-module,
CLI, and test branches were removed; only scratch reproduction code and result
artifacts remain. Post-revert focused tests passed 17/17 and the full suite
passed 187/187 in 77.817 s. The accepted DLL and server/GUI path remain
untouched.

This external game strengthens the existing conclusion rather than reopening
HCE coefficient tuning: the immediate failure is the Python independent-root
architecture under a deadline, while the last grouped HCE vector remains
neutral in paired play. Do not retry global/branch-count one-thread routing or
change HCE weights from this game. The next credible classical search project
requires a materially new native root-PVS/SMP design with one authoritative
full-root result, private per-worker heuristic state, and a proven-safe helper
communication/TT mechanism. That is an architecture change, not another small
candidate; keep the classical phase checkpoint and do not start it or NNUE
without explicit direction.

### 2026-08-24 native authoritative root-PVS/SMP architecture (PLAYING PATH REJECTED; DIAGNOSTICS KEPT)

The explicitly authorized architecture experiment is fully recorded in
`NATIVE_ROOT_PVS_SMP_ROADMAP_TH.md` (SHA-256
`C2AE374FC7FB713F2415AA3C9E0A04A073FFC35139C47AA6F3FDCF683BD811E5`).
The retained default-off implementation is behind
`MAKHOS_NATIVE_ROOT_PVS_SMP=1`: one authoritative native main search owns the
returned move, score, PV, depth, and node count; up to eleven fixed Win32 helper
threads have private TT/history/killers/workspace and run root null-window
scouts. Requested Hash is a total TT budget. At 12 Threads / 512 MiB the
allocator gives the main a power-23 TT (320 MiB) and eleven power-18 helper TTs
(10 MiB each), 430 MiB total. The Python ABI reports requested/effective
threads, both hash powers and allocation, main/helper nodes, task readiness,
fail-high/abort/failure counts, and main barrier wait.

The final source is `native/makhos_native.c` SHA-256
`EA987C0CD625E6AF2B376269474202686265F6AE35E61291DF0DA0E6B2C07E2C`;
the bridge is `makhos/native.py` SHA-256
`90FFF834D3F20553F6255BFA204853F71261E623A04C86E0DF003709F3C88A34`.
The same-source control
`build/makhos_native_root_pvs_shadow_control.dll` has SHA-256
`B66D65B8887ACFC19E833C868782B922ABCFFCFFD711954F7160CA21806127BD`;
the shadow DLL
`build/makhos_native_root_pvs_shadow_candidate.dll` has SHA-256
`00AF95C588132716E4BBB245406D98D6D2DA3AD38AE436C7DA2C9EBD889C4BDA`.
Both used clang 21 with `-O3 -march=native -std=c17 -Wall -Wextra -Werror
-Wno-unused-function -Wno-unneeded-internal-declaration -shared
-DMAKHOS_NO_MAIN -DMAKHOS_EXPERIMENTAL_SEARCH_APIS=0`; only the candidate added
`-DMAKHOS_NATIVE_ROOT_PVS_SMP=1`.

The deterministic shadow audit at seed `20261061`, 96 positions, depth 12,
12 Threads, and Hash 512 MiB preserved move/score/PV/depth/nodes in 96/96
cases. Helpers searched 2,977,805 nodes versus 4,806,695 main nodes. They
completed 5,910/6,066 tasks (97.4283%), and 4,646 completed scouts were ready
before main reached the root (78.6125%); 621 ready scouts failed high, 265 were
above current main alpha, worker failures were zero, and main waited only
5.56 ms. Shadow/control wall-time ratio was `1.05250x`. The raw artifact is
`build/root_pvs_shadow_audit_20260824.json` SHA-256
`732C8EBC9A35793D5C6472E54B438AADFB5D517C58831ACE8B4C6552E92BF86A`.
At one thread, 96 positions times three repetitions preserved exact result and
nodes in 288/288 cases with only `1.00598675x` wall-time ratio; artifact
`build/root_pvs_shadow_1t_overhead_20260824.json` SHA-256
`ABE914362A023D830310FF19E7B4CD2C035FC052210D8E900293F14A0DEA08B3`.
Keep this coordinator/worker/Hash/telemetry infrastructure as a diagnostic
checkpoint; it is not a playing-strength promotion.

Two predeclared bound-use gates were **REJECTED before SPRT**. Directly using a
ready private fail-low to skip the corresponding main root changed fixed-depth
results in 4/4 initial cases. It reduced main node ratio to `0.8779x`, but the
result mismatch makes that saving invalid. Reproduction is
`build/root_pvs_bound_failure_20260824.json` SHA-256
`6FF3A2C3D9D34D509E17839BB52649A20DC66D5D55CB46FF3D34D49454EEC11F`.
The one allowed protocol fix disabled null move and LMR throughout helper
scouts before consuming their fail-low. It still changed move/score/PV in 4/4
cases, used 108 ready fail-lows, reduced main nodes only to `0.925450x`, and was
slower at `1.134760x`. Its raw proof is
`build/root_pvs_verified_bound_proof_20260824.json` SHA-256
`57F68FDFDDE1C8518E4EB79A500ECF46F022319B43CB8D9FCE67D02FAB61C028`;
the isolated rejected DLL is SHA-256
`9C2A889FAEFFB017C5DCD7EE251BEAFB706F579F45BE68F11964CE6404F76ED7`.
Skipping an otherwise losing root also removes the main context's subtree
history/killer/TT updates, which changes later selective null-move/LMR behavior;
therefore a conservative private bound alone does not preserve authoritative
main behavior. All bound-consuming code and helper-pruning changes were
reverted. Do not retry private-root fail-low skipping or loosen its parity gate
without a materially new mechanism that preserves main heuristic state.

Post-revert gates passed: focused root-PVS tests 5/5; full suite 192/192 in
84.809 seconds; candidate executable perft depths 1--10 ended at `861842812`;
and seed `20261061` native/Python differential passed 1,004 positions, 5,402
legal moves, and ten exact three-piece cases. The accepted production DLL and
server/GUI paths were untouched; accepted SHA-256 remains
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

This triggers the roadmap architecture stop condition: shadow proved useful
work is available, but both the direct protocol and the single permitted sounder
scout protocol failed the fixed-depth gate. Do not run SPRT on either rejected
candidate. Classical candidate work remains at diminishing returns. The
highest-value next phase remains the already-designed quiet-leaf scalar-label
acquisition pilot in `NNUE_ROADMAP.md`; per the user's phase-completion rule,
stop and present that roadmap rather than starting NNUE automatically.

### 2026-08-24 quiet-leaf acquisition preflight (256-GAME CAPACITY REJECTED; V2 AUTHORIZED)

After the user explicitly authorized the architecture phase, the data-only
quiet-leaf acquisition harness was implemented at
`scratch/nnue_quiet_leaf_acquire.py` (SHA-256
`FBBE50891C3AED9BF08BE164112D0F647D44C85D18FE60435E1DA2A7D03CADA2`).
It locks the accepted DLL, one thread, persistent search, 100/500/2000-ms
budgets, source-game hash split before sampling, color-rotation/reversible-clock
identity, real terminal outcomes, explicit truncation, and tablebase
provenance. Focused tests in `tests/test_nnue_quiet_leaf_acquire.py` passed 7/7;
the full suite passed 199/199 in 77.550 seconds. No playing code changed and
the accepted DLL remains SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

The locked 256-game source set produced 9,065 selected quiet positions (phase
counts 3,340 / 2,477 / 3,248) after symmetry deduplication. Its game split is
210/27/19 train/validation/test and all games ended naturally. A deterministic
12-game teacher preflight analyzed 474 positions; 300 passed (63.2911%), 107
were mate-like, and 67 exceeded the 50-cp last-two-score delta. Required
retention was 88.2515%; projected yield is only 5,737. The signed-off artifact
`build/nnue_quiet_leaf_pilot_v1/preflight_summary.json` has SHA-256
`5F013826CAE23EF22405DE75FDA941512F100DBC592053FDDAFAD7530268CA39`.
Even selecting every quiet position from the same games gives only 9,163 raw
candidates, so the 256-game pilot is **REJECTED on capacity**. Do not finish
that expensive labeling run, lower the 50-cp gate, admit mate-like labels, or
mislabel truncations to force a pass.

The highest-value next experiment is the predeclared v2 repair: 512 fresh
source games with identical teacher/search/quality gates, plus deterministic
metadata-only coverage sampling to exactly 8,000 published labels. The sampler
must enforce both turns at 45--55%, every phase at least 20%, and king positions
at least 30%; it may not inspect teacher score or game outcome. All eligible
labels remain in per-game analyses for audit. Complete v2 labeling, reproduce
the corpus byte-for-byte on resume, then update this skill with the final
PASS/FAIL. Passing this pilot validates acquisition only and does not authorize
NNUE training before the roadmap's 100,000-label gate and fresh unopened test
split.

### 2026-08-24 quiet-leaf v2 preflight (COVERAGE CAPACITY RISK; DO NOT RUN FULL)

The 512-game v2 repair used an entirely fresh seed range beginning `20264001`.
All games are terminal and none is truncated. The locked manifest contains
16,991 unique quiet candidates, split 13,417 / 1,993 / 1,581 across
train/validation/test, with phase counts 5,902 / 5,213 / 5,876 and 6,047 king
positions. Config SHA-256 is
`76ACC4D39A1C833DA19F5F782BD70243FEFD1DB275C0AADEDB742AE315F0AAD6`;
manifest SHA-256 is
`D1FC5DD62F6787A77A6318F53A176AA4B11C98577CC97046EAACE6D29F72D013`.

The accepted one-thread teacher then analyzed a fresh deterministic 12-game
preflight: 269/418 labels passed (64.354%), 101 were mate-like, and 48 failed
the 50-cp stability gate. Stratified projection is 10,772 labels overall but
only 2,403 with kings and 1,972 from 5--8 pieces. Those are too close to final
minima 2,400 and 1,600 to justify a long full run. Artifact
`build/nnue_quiet_leaf_pilot_v2/preflight_summary.json` has SHA-256
`D3756EC65D1947CDED5BB77A0F356AB2568899030F61A924E838575140CA6BE2`
and verdict **COVERAGE_CAPACITY_RISK**. Do not finish v2 labeling and do not
weaken coverage or teacher-label gates.

The acquisition preflight now locks a 1.25x safety margin: at least 10,000
projected total, 3,000 projected king, and 2,000 projected labels in every
phase before a full run. The highest-value next experiment is v3 with 768
wholly fresh source games, the same accepted DLL, one thread, 100/500/2000 ms,
50-cp/mate exclusion, game split, symmetry identity, and deterministic
metadata-only coverage sampler. First run a 12-game v3 preflight. Continue full
labeling only if the artifact says `READY_FOR_FULL_LABELING`; otherwise stop
and use its failed stratum as the next evidence.

### 2026-08-24 third Sian-Thao loss, engine first (MIXED POSITIONAL/SEARCH EVIDENCE)

The supplied `thai-makhos-game-v1` record has content SHA-256
`CF23379CBB83C2F0243CA90F49AACA3AAC6599F557E56A50E112A4C8CEFD8EBA`
and stable game ID `50c2e37c4239346c`. Replay is legal through all 68 plies;
the final position and reversible clock match, Red wins by no legal Black move,
and every engine ply has complete `search-v1` provenance. Black was the accepted
engine at 2,000 ms, 12 Threads, 512 MiB Hash, project rules, and accepted DLL
SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

The first reproducible loss of root value is Black ply 19 at
`B:BM22,23,24,25,26,28,30:RM1,3,7,10,11,13,15` with reversible clock 8.
The game played `25-21`. Fresh accepted 12-thread searches choose `24-20` at
2/5/20 seconds; at 20 seconds and depth 26, `24-20` scores -4 while `25-21`
scores -31, a 27-cp loss. After the opponent's `10-14`, ply-21 long search
scores the recorded continuation `23-18` at -145, exposing a further roughly
100-cp horizon swing relative to the ply-19 PV. In contrast, the static HCE
scores the child after `24-20` only 3 cp above `25-21`; it does not represent
the positional urgency well. The failure is therefore mixed: a broad
positional-evaluation blind spot plus deadline/depth instability in the
independent-root 12-thread search, not proof that one HCE coefficient caused
the loss.

Reproducible artifacts are
`build/siantao_loss_black_opening_12t_screen_20260824.json` (SHA-256
`70FC855322A5DDDF8B0E378D211B4EED9CB9C0B67156D3C0E0D1877B1E788CBE`),
`build/siantao_loss_black_ply19_12t_long_20260824.json` (SHA-256
`FEFE944464B8ADA2F2923F041576D7F1A6A1BDB0404A9E3C39D2FBF0FC8A11E7`),
and one-thread ply-21/25 analysis
`build/siantao_loss_first_black_1t_analysis_20260824.json` (SHA-256
`2BC121B6D78E056A0087875ABBDB75E81E8E676C29944ADEC2AC3B702EE3DA82`).
The ply-19 case is retained in `corpora/positional_regressions.json`; it is an
external regression, not a proven best-move or training label. Focused corpus
and replay tests passed 12/12. Do not tune weights to this single game. Use the
broad, game-disjoint quiet-leaf acquisition experiment to measure whether the
same positional weakness generalizes.

### 2026-08-24 quiet-leaf v3 identity failure (REJECTED)

The v3 capacity preflight passed, but the full acquisition was stopped after a
coordinator audit found 768 generated files contained only 766 content-stable
game trajectories. Game ID `9bbc855319e407f8` appeared under three seed files.
Because the old analysis path keyed only by `game_id`, workers could overwrite
the same result and the finalizer required an impossible 768 unique IDs. The 52
partial v3 analyses are stale failure evidence and must not be finalized or
used for training.

The repaired acquisition path deduplicates source trajectories before split
and sampling, records kept/dropped source hashes, binds every analysis to a
`selection_sha256`, rejects stale manifests, and makes the finalizer separately
verify 768 generated files and 766 unique analyses. Harness SHA-256 is
`7650DDA319A5640DDEFF78FF935B500530FB67059A335F12B978FD075F554CA9`;
focused-test SHA-256 is
`27874ED749E7A02D489504E22A132D21C24423555396E60B6B16AD3624723D0B`.
Focused acquisition tests passed 10/10, focused finalizer tests passed 2/2,
and the full suite passed 204/204 in 89.851 seconds. No playing code changed.

### 2026-08-24 quiet-leaf v4 preflight (READY; FULL LABELING AUTHORIZED)

The repaired v4 manifest retains 766 unique trajectories from the same 768
locked generated files, split 620/63/83 train/validation/test. It selects
24,734 quiet positions, including 8,983 with kings and phase counts
8,775 / 7,708 / 8,251. Config SHA-256 is
`F0C50CE1E59C10F7F8596087690B97AF3147B70F95B9AD2699D8A258980EBED7`;
selection-manifest SHA-256 is
`3F5330B745BD30369E371B58203858994832260FBF1C583A6EE4600394DCF1B4`.

The bound 12-game preflight retained 204/301 labels (67.774%): 64 mate-like
and 33 unstable-score exclusions. Stratified projection is 16,508 total,
3,417 with kings, and 8,169 / 5,445 / 2,894 by phase. Every 1.25x margin passes;
`build/nnue_quiet_leaf_pilot_v4/preflight_summary.json` has SHA-256
`7C9A7AF0432FA333BF24E154CD8F580209C04AB4B7AD0CF7F18D17CEBB38B633`
and verdict **READY_FOR_FULL_LABELING**. This authorizes completing v4 teacher
label acquisition only, not NNUE training. Run four whole-game shards with one
accepted persistent teacher thread each at 100/500/2000 ms and Hash 256 MiB.
Require empty stderr, 766 unique bound analyses, one successful finalization,
and a second byte-identical resume finalization before declaring the pilot PASS.

### 2026-08-24 quiet-leaf scalar HCE-gap audit (PARTIAL MEASUREMENT ONLY)

The measurement-only audit `scratch/quiet_leaf_hce_gap_audit.py` (SHA-256
`E7692E4E1AA1881D40F097BA4BAED2BA07D7D31A5923942B61D7331965E208BD`)
validates selection bindings, game/position uniqueness, teacher DLL hashes and
budget ladders before comparing the static handcrafted score with the accepted
100/500/2000-ms quiet-leaf teacher. It defaults to train only, does not expose
the test split, and refuses an incomplete acquisition unless the caller records
`--allow-partial`. Focused tests (SHA-256
`9AEE8E03D76A1341131B61ACDCB3929EB8F45955B5458E46E40DBD9731324672`)
passed 3/3; the full suite passed 207/207 in 117.836 seconds while the four
BelowNormal acquisition workers remained active.

The partial 62-analysis checkpoint is
`build/nnue_quiet_leaf_pilot_v4/hce_gap_checkpoint.json` (SHA-256
`A047F42750740C9A572C9FDA4C500DFB8AFF24F330767D01C69334787DA22817`).
On 1,033 eligible train rows, current HCE versus the 2,000-ms teacher has
Pearson 0.6843 and MAE 94.45 cp. The 13--16-piece band is strongest at Pearson
0.7833 / MAE 48.17 cp; 9--12 pieces is weakest at Pearson 0.5765 / MAE
181.66 cp; 5--8 pieces is Pearson 0.7481 / MAE 129.90 cp. The same phase
ordering is already visible against the 100-ms search, but teacher scores still
contain tactical/search effects. This checkpoint supports broad evaluator data
rather than one coefficient change; it is not a fit, candidate, promotion, or
final corpus result. After v4 finalizes, rerun without `--allow-partial`, bind
the final artifact hash, and use only aggregate train/validation evidence when
designing the next data-scale experiment.

### 2026-08-24 Make-no-mistake runtime gate and cold-start repair (PROMOTED WORKFLOW)

An apparent user-facing strength regression occurred while four continuous
one-thread v4 label workers were pinned to logical processors 0/2/4/6. The GUI
was tested at 1,000--2,000 ms, 12 Threads and 512 MiB on the same six-core CPU.
BelowNormal priority did not isolate physical cores or shared cache, so those
external games are valid gameplay evidence but not a controlled before/after
strength comparison. The accepted DLL was verified byte-for-byte unchanged at
SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

All four workers and the old finalizer were stopped without touching the GUI
server; 100 atomically completed v4 analyses remain preserved and resumable.
`makhos/workload_isolation.py` (SHA-256
`FC80019852ADAC635909740399F3826AFA7173FD32D1E50F28FEAAE78658E402`)
now provides a crash-safe named interactive-priority event plus file-range
leases. The GUI owns the complete range. Instrumented batch workers own one
slot, checkpoint between generated plies/label positions, and yield before the
GUI can search. A cross-process test proves a live worker drains and releases
its slot when interactive priority is asserted. Never resume v4 while a live
server owns this lease.

The old first-request path synchronously created or replaced a native
three-piece tablebase whose measured initialization cost was 16--17 seconds
and roughly 640 MiB. Threads/Hash reconfiguration therefore rebuilt unrelated
endgame state before a middlegame search. `makhos/server.py` now keeps the same
Engine/ranked-tablebase objects, swaps only the native search resource when
Threads/Hash change, does not build TB3 during opening/middlegame live play,
and reports request/setup time and isolation provenance. To avoid a silent
endgame-strength loss, the exact TB3 oracle is loaded synchronously once only
when a searched position actually has at most three pieces. `/api/state` now
returns a round-trippable position string. A clean-process
12-thread/512-MiB/1,000-ms
benchmark in `build/server_cold_start_12t_512mb_20260824.json` (SHA-256
`0FD90DE44722F6B123DBF6061F97DEFE7EC6D60F5F670FA6876820EFD421EA58`)
reached HTTP readiness in 1,610.002 ms and completed the first request in
1,015.322 ms: 1,003 ms engine time, 10.544 ms setup, native-root-split, accepted
DLL, and no competing TB3 builder. This is a workflow/startup promotion, not a
playing-strength promotion.

Under isolated repeated 1-second searches, the external ply-19 regression
initially alternated between `25-21` and `24-20` only when the same persistent
GUI context re-searched the identical root without a new-game clear. The
follow-up fresh-state audit
`build/gui_strength_stability_1s_20260824.json` (SHA-256
`4955E41879BE72048E015191898CEFA7C5BB1693B9DA499322999987F21613C0`)
held the batch isolation lease, cleared each backend before every trial, and
ran five 1,000-ms trials per backend on all three external regressions. Both
single-thread and 12-thread results were move/depth stable 5/5 in every case.
The GUI new-game API already clears persistent TT/history, so there is no
reproduced cross-game stale-state bug.

The controlled weakness remains search horizon/quality, not run-to-run
randomness: at one second the 12-thread path missed the longer-search move 5/5
on the first two cases and matched 5/5 on the newest ply-19 case. Single-thread
also missed the first two and matched the third. This three-case regression is
diagnostic only; the existing broader architecture gates remain authoritative
and their rejected routing/scout candidates must not be retried.

The GUI now persists the user's time/Threads/Hash/mode/rules settings across a
refresh, labels Threads greater than one as experimental root split, and
exports request/setup timing, tablebase readiness, and runtime-isolation status
with every engine move. Focused GUI/server/isolation tests passed 25/25; the
full suite passed 215/215 in 52.556 seconds. The next strength change must use
the completed broad HCE/data evidence or a materially new search mechanism,
then pass the normal deterministic and paired-SPRT gates. Do not reinterpret a
single Sian-Thao game as an engine-version regression when the accepted DLL is
byte-identical and the environment/settings are not paired.

### 2026-08-25 quiet-leaf v4 completion (PASS DATA PIPELINE; NO TRAINING YET)

The interactive GUI was closed only after its request stream had been idle,
then the locked v4 acquisition resumed from 100 atomically preserved analyses.
The reproducible coordinator `scratch/nnue_pilot_resume.py` has SHA-256
`10D582DA7C5E9F11A263D2836B3B06FA3EC76F22142F04F9B395F2B06E8F7FC5`.
It revalidated every existing analysis plus the accepted/config/selection/
preflight/finalizer/isolation hashes before launching four BelowNormal,
single-thread whole-game shards on logical processors 0/2/4/6. Its focused
tests passed 14/14 together with the acquisition/finalizer tests; the full
suite passed 217/217 in 52.854 seconds before the batch launch. No playing code
or accepted DLL changed.

All 766 unique selected trajectories were analyzed from the 768 locked source
files. Eight worker stderr logs (the original and resumed four-shard runs)
contain zero bytes in aggregate, every analysis binding and teacher hash
validated, and all recorded workers/finalizer exited. Finalizer status
`build/nnue_quiet_leaf_pilot_v4/finalizer_status.json` has SHA-256
`1AA24990D30FEAD535B749C15CDC6DDD55B536BDB2AD6123E27C5027F0C1345D`
and state **PASS**. The published 8,000-row corpus
`corpora/nnue_quiet_leaf_pilot_v4.jsonl` has SHA-256
`4C90796735DFC5AC1667906E2DB4F9EAEBBB4C5B10DA0CAF543249444FD4FB24`;
the PASS summary has SHA-256
`AA610533E6CAB3D8D720789F9B0A8DFA37F321F0B8000EBAECF769EA4C56BFE4`.
A separate resume reproduction preserved both hashes byte-for-byte.

The final corpus is split 6,496 / 611 / 893 by whole source game across
train/validation/test. It is exactly 4,000 Black-turn and 4,000 Red-turn rows,
contains 2,610 king positions (32.625%), and has 3,522 / 2,454 / 2,024 rows in
the 13--16 / 9--12 / 5--8 piece bands. It includes 1,003 independently exact
WDL labels, zero position/symmetry leakage, and zero truncated game mislabeled
as a draw. Before deterministic coverage sampling, 15,393 labels passed the
unchanged mate/stability gates. This validates the label schema and resumable
pipeline only; 8,000 labels remain far below the 100,000-label trainer gate.

### 2026-08-25 full quiet-leaf HCE-gap audit (REPRODUCIBLE MEASUREMENT)

The completed audit uses current script SHA-256
`EE8B46766F078E9BA40B7C0F9422A20BC8E7617B5A01AEF2B8F6298E87BEBF82`.
It validated all 766 analyses without `--allow-partial`, used only train and
validation aggregates, and never opened the test split for model selection.
The 12,510-row train artifact
`build/nnue_quiet_leaf_pilot_v4/hce_gap_audit.json` has SHA-256
`6C46BE7B3DA6DF37D38A0EBA05E44270302D332877F88FEB68CC42BC341D16F4`;
the 1,225-row validation artifact
`build/nnue_quiet_leaf_pilot_v4/hce_gap_validation_audit.json` has SHA-256
`CE04F79529A181E96BD9F0D88EA6CDD764E38A5DF38988864894B36AC02E42EE`.
Both reproduced byte-for-byte on an independent rerun.

Against the accepted 2,000-ms quiet-leaf teacher, aggregate train/validation
are Pearson 0.7681 / 0.7379 and MAE 98.43 / 103.77 cp. The opening-heavy
13--16-piece band is much easier at validation Pearson 0.8044 and MAE 44.68 cp.
The broad weaknesses are 9--12 pieces (Pearson 0.7489, MAE 171.73 cp), 5--8
pieces (Pearson 0.6656, MAE 154.32 cp), and positions with kings (Pearson
0.7275, MAE 178.53 cp versus 88.31 cp without kings). Black/Red validation MAE
is similar at 103.38 / 104.17 cp, so the evidence does not support a side-to-
move-specific patch. Teacher convergence remains measurable: validation mean
absolute score change is 27.41 cp from 100 to 500 ms and 13.32 cp from 500 to
2,000 ms. These search-contaminated scalar gaps justify broad phase/king data,
not one HCE coefficient change or a playing-code promotion.

The single highest-value next experiment is a deterministic **NNUE scaling-
capacity audit**, still with no model training. Use only v4 train/validation
source-game units (never its test rows) to compute reproducible conservative
yield bounds for total, king, phase, and turn strata. Size a wholly fresh
game-level 80/10/10 acquisition so the train pool clears a 1.25x margin over a
100,000-row training sample, including 30,000 king rows, 20,000 rows per phase,
and 45--55% per turn, while reserving a fresh sealed test manifest that cannot
select architecture or checkpoints. The audit must output the required source-
game count, runtime/storage projection, and predeclared stop gates before any
large generation run starts. Do not train NNUE, weaken the current label gate,
or guess a corpus size before this audit is reproducible.

### 2026-08-25 NNUE scaling-capacity audit (PROMOTE SIZE; HARNESS PREFLIGHT NEXT)

The deterministic whole-game audit
`scratch/nnue_scaling_capacity_audit.py` has SHA-256
`12BB81BEB90B66E31BA1B4A225370853C4FF87B3D278B330D3CF7BAEAB2D8FD7`.
It validated and bootstrapped 683 v4 development games (620 train plus 63
validation), explicitly read zero analysis files from the 83-game v4 test
split, and used 20,000 fixed-seed resamples at the source-game unit. Focused
NNUE pipeline tests passed 20/20; after adding the audit, the full suite passed
220/220 in 49.147 seconds. The report
`build/nnue_scaling_capacity_audit_v1.json` reproduced byte-for-byte at SHA-256
`9F27BCEAADA11695E1049D4F68A34D26ACAF509E25DFDF1D914E9AA74E360C59`.

Observed eligible labels per unique development game average 20.1098 total,
3.7570 with kings, 10.4817 / 5.7745 / 3.8536 by the three phase bands, and
10.0278 / 10.0820 by turn. Conservative 1% bootstrap lower bounds are 19.2782
total, 3.2313 king, 10.0571 / 5.3089 / 3.3075 by phase, and 9.6003 / 9.6574 by
turn. The 766/768 unique-trajectory observation is separately discounted to a
99% Wilson lower bound of 0.98678.

The locked train-pool requirements apply a 1.25x margin: 125,000 total,
37,500 king, 25,000 per phase, 56,250 per turn, plus at least 10,000 validation
and 10,000 sealed-test labels. King yield is the binding constraint at 14,701
fresh source files; rounding to a 1,024-file scheduling boundary gives
**15,360 fresh source files**. Conservative projection at that size is 233,759
train labels, including 39,182 king, 121,948 / 64,374 / 40,105 by phase, and
116,409 / 117,101 by turn, plus about 29,220 labels in each validation/test
pool. This is a pool-size contract, not permission to select rows using the
future test split.

Measured v4 resume throughput was 92.22 worker-seconds per new analysis. Six
single-thread whole-game workers therefore project about 64.7 wall-clock hours
for teacher analysis, excluding generation. Projected source/analysis storage
is about 373 MB / 1.53 GB. Because generation throughput and race-free sealing
are not yet measured at this scale, the 15,360-game full run is not authorized
yet and NNUE training remains forbidden.

The single next experiment is a **96-game fresh-seed scalable-harness
preflight**. Build disjoint six-shard source generation and development-label
analysis, then let one coordinator deduplicate/split only after all source
files exist. Freeze a 10% whole-game test manifest and expose only its hash and
counts; development workers must read zero test analysis files. Use fresh seeds
`20270001..20270096`, the accepted one-thread teacher and unchanged
100/500/2000-ms, 50-cp/mate/quiet gates. Require exactly-once atomic source
writes, disjoint shard manifests, empty stderr, crash-safe resume, GUI-priority
yield, and measured generation/teacher throughput. Passing this bounded run
authorizes the 15,360-game acquisition only; it still does not authorize model
training until the full train pool and sealed test artifact pass their gates.

### 2026-08-25 96-game scalable-harness preflight (PASS; ACQUISITION AUTHORIZED)

The six-shard coordinator `scratch/nnue_scaling_preflight.py` has SHA-256
`A84497F1418D1E19B4871A361D29939951AE95092A3BBD02918FEB298AA9C7A1`;
the extended acquisition worker `scratch/nnue_quiet_leaf_acquire.py` has
SHA-256
`C5E5DD007B3566741466229099120C3BD0FD11783576251A9964B08C853D49D5`.
The harness locks configuration and provenance, uses six BelowNormal
single-thread workers pinned to logical processors 0/2/4/6/8/10, generates
disjoint index shards, seals the whole-game test partition before teacher
analysis, restricts analysis to train/validation, yields to interactive GUI
priority, and validates existing source/analysis files before resume. The
preflight tests passed 3/3 after the initial status-directory startup defect
was fixed. A subsequent GUI-priority audit added safe-boundary checkpoints to
existing source/analysis validation, coordinator selection replay/ownership,
and artifact hashing; it also removed a redundant second read of every analysis
hash. Focused acquisition/isolation tests passed 21/21 and the complete
correctness suite passed **227/227 in 49.088 seconds**.

Fresh seeds `20270001..20270096` produced 96/96 unique source trajectories in
36.128 seconds. Coordinator-only partitioning locked 84 development games and
12 sealed-test games containing 402 selected test positions. The development
manifest SHA-256 is
`F461D2EB37531607C795E7DEC73207180766E72C42CFE9CB5CF92CF1553E6F0D`;
the sealed-test manifest SHA-256 is
`4822A8C93CBA458175375209CCEBAD18432CEF5E2A7EF3F98FBB73B720EA7997`.
Development workers read **zero** test analysis files.

Teacher analysis completed 84/84 development games in 2,150.808 wall-clock
seconds with zero stderr bytes and zero temporary artifacts. It retained 1,991
eligible labels: 398 with kings, 1,042 / 618 / 331 by the 13--16 / 9--12 /
5--8 phase bands, and 990 / 1,001 by turn. The six first-pass shard durations
sum to 7,600.256 worker-seconds, or 90.479 worker-seconds per development game,
which independently agrees with the earlier 92.22 estimate. At six workers
this projects about 57.9 hours for the initial 90% development partition of a
15,360-game run, or 64.3 hours if all games are eventually labeled; generation
projects about 1.6 hours. The small preflight's hash shards held
13/13/24/13/11/10 games and therefore exposed a 35.85-minute tail, but this is
sample-size load variance rather than missing work. Do not add work stealing
without full-scale imbalance evidence; monitor per-shard counts and tail time.

Automatic generation and analysis resume reproduced every source file,
development analysis, development manifest, and sealed-test manifest
byte-for-byte. A second completed-state coordinator run again passed and kept
the deterministic summary byte-identical at
`build/nnue_scaling_preflight_v1/preflight_summary.json`, SHA-256
`58C4A1AFBF1FDF90590AACF0B02109A085FC3A1D3271E586CA5036E3702D94FC`.
All nine summary gates are true; the accepted DLL remains untouched at SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

This PASS authorizes **data acquisition only**. The single highest-value next
experiment is to lock and test a resumable full-run launcher for 15,360 wholly
fresh games, then start the six-shard generation/development-label acquisition
under the same accepted-teacher, split-sealing, atomic-write, and GUI-priority
contract. Freeze a non-overlapping seed range and full-run config before the
first source file. NNUE training, test-label opening, architecture selection,
and production playing-code changes remain forbidden until the completed
corpus passes its coverage, provenance, reproduction, and sealed-test gates.

### 2026-08-25 locked 15,360-game supervisor (GENERATION ACTIVE)

`scratch/nnue_scaling_full_run.py` (SHA-256
`F3E7E7457B521253E0A893F5F89D89048D662324CAA3FE24B81109159B048AA9`)
is the fail-closed production acquisition supervisor. It accepts only the exact
15,360-game contract, fresh seeds `20280001..20295360`, six shards pinned to
0/2/4/6/8/10, depth-7 generation, 200-ply games, 64 selected positions per
game, one thread and 256 MiB Hash per teacher, and 100/500/2000-ms labels. It
binds the accepted DLL, capacity audit, PASS preflight, config, worker,
coordinator, workload-isolation, and its own source hashes before launch. It
fails closed on any later binding drift, keeps sealed test labels unopened,
and automatically waits/drains/resumes across interactive GUI sessions.

Supervisor tests passed 6/6; the combined acquisition/isolation focus passed
27/27. After repairing a parent-PowerShell false-positive in duplicate-process
detection, the complete suite passed **233/233 in 49.196 seconds**. That first
launch attempt failed closed before a manifest, source, worker, or analysis was
created. The full-run config was created with zero source and zero analysis
files. It contains
15,360 unique schedule indexes and seeds, first/last seeds 20280001/20295360,
and has SHA-256
`B42B9369ED6CD40C7D19843674F191CCEE4E22BC137FD28F94C99B57177FA8A4`.
At config lock the D drive had 407.87 GiB free, no GUI priority event, and no
live acquisition process.

The repaired supervisor started successfully on attempt 1. Its locked
`build/nnue_scaling_full_v1/full_run_manifest.json` has SHA-256
`8EBB797FF547162791E4CEF4A1C8D4CF5FBD8335D1A0586DE061D99ABC70C787`.
The manifest timestamp precedes the first atomic source file by 2.73 seconds.
At the first live audit generation had completed 145 source games, with zero
analysis files and zero stderr bytes; a later check reached 409. The coordinator
plus six workers were live, every worker was BelowNormal and pinned exactly to
logical processors 0/2/4/6/8/10, and each used roughly 419--425 MiB resident
memory. Continue monitoring source/development-analysis counts, per-shard tail,
stderr, GUI pauses, and disk use. Completion of generation and development
labeling is still a data-pipeline result, not NNUE training or playing-strength
promotion.

Generation subsequently completed 15,360/15,360 atomic source files on the
same first attempt with zero stderr. Coordinator replay/dedup retained 15,335
unique trajectories and dropped 25 duplicate trajectories, consistent with
the conservative dedup bound. The frozen whole-game partition contains 13,802
development games and 1,533 sealed-test games with 41,698 selected test
positions. The development manifest SHA-256 is
`C359269C7858D042BFE0B41EEA5D98CC6F03DBDBBADE7ACAC9B13D1E90FACDD2`;
the sealed-test manifest SHA-256 is
`B1F2350607A95ACF3F04B5667236EE10B7D2ABCF0DE3EB7FA737E72D96338115`.
The commitment keeps `test_analysis_files_may_be_read=false`. Six development
teacher workers then entered provenance replay and began analysis with zero
test analyses and zero stderr. Do not alter bound pipeline sources while this
supervised stage is active.

The first supervisor process later hit a Windows-only status-publication race:
a read-only PowerShell monitor held `full_run_supervisor_status.json` at the
instant `Path.replace` ran, causing `PermissionError: WinError 5`. The
coordinator and all six teacher workers remained live and clean; source,
development/test manifests, accepted DLL, config, and teacher pipeline were
unchanged. Stop any polling reader that opens the volatile supervisor status
file while its writer is active.

The status-only helper `scratch/nnue_pilot_resume.py` now retries transient
`PermissionError` replacement up to 100 times at 0.05 seconds and still fails
closed after five seconds. Focused status/supervisor/isolation tests pass 14/14.
Because teacher workers are live, defer the complete suite until no teacher
worker is active. The locked recovery addendum
`build/nnue_scaling_full_v1/supervisor_runtime_recovery.json` has SHA-256
`16CB8DD35BE65FA27E95F867FE718BD594EE2D0CF1B97DDC794CC33EFE876D48`.
It binds the original full-run manifest/config/accepted hashes, records
`data_pipeline_changed=false`, and arms a process-handle watcher: after the
current coordinator exits for PASS, GUI pause, or failure, launch the unchanged
bound supervisor, which imports the retry-hardened status writer. At recovery
arming the teacher count was 29/13,802 with six live workers and zero stderr.
The sole stale `.tmp` was the failed supervisor's obsolete 5,016-source status
payload (SHA-256
`D943C3DB9ECA0C098377C074A695985971F42F8CB169AFAB6FE85FFEA61CC674`),
not a source or analysis artifact. It was inspected and removed; the temporary-
artifact count returned to zero while six workers continued normally.

### 2026-08-25 reproducible early development checkpoint (PASS; NON-GATING)

The read-only checkpoint audit
`scratch/nnue_scaling_checkpoint_audit.py` has SHA-256
`4937829284EEEEAEDB2A701F34C121821CD1B95BFA2A6526941E20829A219A0D`.
Its focused tests pass 2/2. The first invocation locks the exact completed
development-analysis filename set and hashes; later invocations ignore newly
completed analyses and recompute only that locked set. It validates the
accepted DLL, one-thread persistent teacher, 100/500/2000-ms budgets, split
and per-position provenance, while never opening the sealed-test manifest or
any test analysis.

The locked 71-game artifact
`build/nnue_scaling_full_v1/checkpoint_early_development.json` reproduced
byte-for-byte on an immediate rerun at SHA-256
`A1C657184EB63D68548DF1E14CCF0A82D4D346EBA4BE1ECD4C622DF41E797C64`.
All gates are true: 64 train plus 7 validation games, 2,130 selected positions,
1,419 eligible (66.619718%, 19.985915/game), 351 eligible king positions,
phase counts 596/419/404 for 13--16/9--12/5--8 pieces, turn counts 698/721,
173 exact-WDL positions, zero incomplete-search rejections, zero stderr,
zero temporary artifacts, and zero test-analysis reads. Rejections were 230
last-two-score-delta and 481 mate-like-score positions.

This checkpoint is deliberately **non-gating**: completed filenames are an
early ordered prefix of asynchronous acquisition, not a random or full-corpus
sample. It proves current pipeline health and reproducibility only. Do not use
its coverage percentages to choose architecture, loss, corpus weighting, or a
model checkpoint, and do not start training. Continue the unchanged acquisition
until all 13,802 development analyses finish, then run the full reproduction,
coverage/provenance, and sealed-test gates before authorizing a trainer.

### 2026-08-28 post-acquisition full-suite attestation v2 (PROMOTE TOOLING)

Hypothesis: the trainer gate's prose/JSON requirement for a full-suite PASS was
not sufficient because no official producer independently proved completed
health, idle workers, GUI priority, exact discovery, immutable source/tests,
and protected-data isolation. A fail-closed producer plus independent gate-side
inventory recomputation should remove that evidence gap without touching engine
behavior or running the full suite during acquisition.

`scratch/nnue_full_suite_attestation.py` (SHA-256
`4109D973F7200A3EC61ABC262F93CC3820D1B3F59B1EA2F34F8CDE21690AADB9`)
implements attestation schema v2. It requires
`COMPLETE_PENDING_FINAL_GATES` before/after, no pipeline process, no GUI, and an
exclusive 32-slot workload lease; checks GUI priority around every discovered
test; guards production analyses, sealed manifest, test analyses, and volatile
status; binds accepted DLL, final audit, runner/result, and before/after
source/test inventories; and writes nothing on failure. Outputs inside the
acquisition or source/test trees are rejected.

The hardened trainer gate now has SHA-256
`FB99AE3DC546D4B3FC1B4E1CFDD6025439FA4C2A72787E43460FD968D4FBBA31`;
its test SHA-256 is
`B3B4977926F7CC8B2E6B5E66182179646E474033D47DC08F960C057E611F386D`.
It binds the v2 source-inventory and runner hashes in the frozen contract and
recomputes the current 114-source/41-test inventories instead of trusting the
attestation. The reviewed pre-attestation inventory hashes were
`9F169F4980DB0E0B32D803E6658379B80E40565E094B9879A114656AF7F6D2D8`
for source and
`6D86FA4635D01E16DEB36706FDF3BD7031ACF0D2FEF77D122CCA01E0F0C795AE`
for tests. Runner tests
`B1C255946AE68822BDE10ECCF5F7C1782C478435A996884F42CCE0E9033DC653`
pass 11/11; gate tests pass 10/10, including stale source, wrong runner,
protected read, incomplete discovery, invalid time, live pipeline, GUI/lock,
and output-tree rejection. The combined runner/contract/inventory/health/final
focused stack passes **41/41 in 4.232 seconds**.

Verdict: **PROMOTE TOOLING**, not an engine-strength or data-completion
promotion; no SPRT applies. The real full suite was deliberately not run and no
attestation was created because acquisition remains active. Next: finish all
13,802 analyses, obtain coordinator PASS, reproduce the final audit twice, then
run this producer while fully idle.

### 2026-08-28 acquisition external-process-loss recovery (RECOVERED)

All six workers were externally terminated together at 1,734 analyses with
exit `0x40010004`, while worker stderr remained zero. The coordinator's 705-byte
traceback was preserved at SHA-256
`1FCD0ACEF58F11A8E29B5AF126580798DDD897B9599370D0F1541E22103F9EF1`
under `build/nnue_scaling_full_v1/incident_logs/`; it was not deleted or called
a data failure. There were no extra analyses or `.tmp` files. The accepted DLL,
bound scripts, config, full/development manifests, authorization, and sealed
commitment all revalidated. With no GUI or duplicate process, only the locked
supervisor was relaunched as a hidden detached Windows process with separate
launcher logs.

Recovery verification observed exact 1/1/6 supervisor/coordinator/worker roles,
six BelowNormal workers pinned to 0/2/4/6/8/10, forward progress from 1,734 to
1,768 analyses, zero new stderr/tmp/extra analyses, and `RUNNING_HEALTHY`; protected read
counters remained zero. Accepted artifacts and playing code were unchanged.

### 2026-08-28 executable NNUE v1 feature oracle (PROMOTE TOOLING)

Hypothesis: the locked 137-feature prose/schema was not enough to prevent a
future trainer, scalar native evaluator, refresh path, or AVX2 path from silently
assigning different indices or deltas. A pure executable oracle, single-sourced
into the trainer-contract gate and exercised by symmetry and transition tests,
would close that implementation risk without changing search or training.

The new `makhos/nnue_features.py` is a standard-library-only oracle for
`thai-makhos-shared-137-v1`: four relative piece categories over 32 canonical
squares plus nine reversible-clock buckets, side-to-move/opponent concatenation,
and fixed-perspective parent/child remove/add deltas. It is not imported by the
playing path. Its SHA-256 is
`EAEB36EDBF09476F36958AAD7C78ED28B02A2B5EE178622D44BC331ABE30A30E`.
`tests/test_nnue_features.py` has SHA-256
`F57B620F6B5407F2EA6BD0E388B521673BFF2DB61E2273235078A8A08B498A2B`.
`scratch/nnue_trainer_contract_gate.py` now obtains the expected feature
payload from the oracle; its SHA-256 is
`DF502CFADDC6B220E141AD1350D838FB62D3A26DFE1D039A93EB2E7D4D1D35C8`.

Correctness evidence: the oracle and existing gate stack passed 53/53 in
3.984 seconds. The new tests cover exact machine-readable indices and active
counts, both-perspective rotation/color-swap symmetry, all 0--79 clock values
and rejection of 80, quiet/capture/promotion/multi-capture deltas, bucket-only
clock changes, and 300 random legal transitions. `py_compile` passed and the
import graph confirms the oracle is referenced only by its tests and the
trainer-contract gate. Current discovered inventories are 116 source files and
42 test files with hashes
`2C184EDE7B55D22BCCA2AF5C425768B0C77EFD503979980C2F4D2F67B92E37E2` and
`CA8FBE3877940A8E91E9BB2C4277DD014AA7C405441E944AD5D6D26E6BB6DFFC`.

The accepted control remains byte-identical at
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`. Bound
acquisition files remain unchanged. No playing code, native DLL, model, or
training data changed; acquisition health was `RUNNING_HEALTHY` at 1,835/13,802
when the experiment was recorded and reached 1,858/13,802 on the final
read-only snapshot, with exact 1/1/6 roles, zero stderr/tmp/extra artifacts,
and zero protected reads. No SPRT applies because this is behavior-preserving
tooling.

Verdict: **PROMOTE TOOLING**. This does not authorize training or imply a
strength gain. Next single experiment: after acquisition reaches its final-data
gates, freeze and preflight the deterministic trainer contract using this oracle
as the only feature source; until then continue the locked supervisor and do
not create placeholder trainer evidence.

### 2026-08-28 deterministic trainer-contract freezer (PROMOTE TOOLING)

Hypothesis: once the final-data gates pass, hand-assembling the frozen trainer
contract leaves avoidable room for stale hashes, omitted choices, test leakage,
or platform-dependent bytes. A builder that requires every dynamic evidence and
train-only choice explicitly, injects the locked feature/network/policy
sections, and writes canonical bytes should make the next authorization step
reproducible without reading production payloads during development.

Added `scratch/nnue_trainer_contract_freezer.py` (SHA-256
`B0E26673291AB92882CE48051F9C487E244E33EB64FE5A9B744A2ECEEB721273`) and
`tests/test_nnue_trainer_contract_freezer.py` (SHA-256
`3F8F0D841E19E9E4420195A243E4215B0690FD25DBC822F19FD8EAD286FDD17F`). The
freezer deep-copies explicit evidence/dataset/target/optimizer/reproducibility
choices, rejects missing/extra or test-dependent values, binds the locked
development manifest/accepted DLL/ruleset, supplies the executable feature
oracle and one-time sealed-test policy, and rejects source/acquisition output
trees. Its writer uses canonical LF bytes and refuses a differing locked file.
It never opens analysis payloads or sealed-test data and never authorizes a run.

Correctness evidence: freezer tests pass 10/10; the combined focused stack
(`features`, full-suite attestation, trainer gate/freezer, inventory, health, and
final audit) passes **63/63 in 4.355 seconds** in the experiment run and
**63/63 in 4.139 seconds** on the final rerun. `py_compile` passes, and the
import graph shows the freezer/oracle reachable only from tooling/tests, not
the playing path. Current discovered inventories are 118 source files and 43
test files with hashes
`B0F9A0EE4A174160E03958EC9E511DCE2D782C8159A3BBBAD59BECB9A0AA34DC` and
`1170853627E8DE3ADE9FE390E79C3B6E46293B9F8DA7BDA7EA2EF795EF442EC0`.

The accepted control remains
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`; all
bound acquisition hashes remain unchanged. The live acquisition snapshot
reached `RUNNING_HEALTHY` at 1,901/13,802 with exact 1/1/6 roles, zero
stderr/tmp/extra artifacts, zero protected reads, and about 407 GiB free. No
model/training/playing code changed, so no SPRT applies.

Verdict: **PROMOTE TOOLING**. Do not create a real contract until acquisition
completion, two final-audit reproductions, idle full-suite attestation, and the
actual tiny-fixture preflight exist. The next gated action is to invoke this
freezer with those real train-only inputs, then pass both byte-identical outputs
through the existing authorizer.

### 2026-08-28 deterministic tiny-fixture trainer preflight (PROMOTE TOOLING)

Hypothesis: before any production trainer reads a row, an executable synthetic
preflight should catch overfit, repeat/resume, serialization-checksum, and
protected-path failures that static contract checks cannot prove. The harness
must stay non-authorizing and must not inspect production or sealed data while
the locked acquisition is active.

Added `scratch/nnue_trainer_preflight.py` (SHA-256
`157BF19A3E77D760F3B9B94D747F9CC314C55481A714A245ABE04A2C43019CF2`) and
`tests/test_nnue_trainer_preflight.py` (SHA-256
`7432CACD5FC9C6DBE1BCB7E458DF6873CA5550C4BB990E78C9C1007AB156A411`). It
uses only the explicit `thai-makhos-nnue-trainer-fixture-v1` synthetic linear
fixture plus frozen contract/audit/source identities; fixture weights are
discarded. Protected-read auditing rejects production analyses, test analyses,
the sealed-test manifest, and volatile supervisor status. The artifact schema
is byte-locked and explicitly records that it cannot authorize training.

The first direct-file CLI smoke exposed a launch-only defect: executing the
script by path did not put the repository root on `sys.path`, so imports failed
before the preflight began. The fix moves the root-path bootstrap ahead of the
tooling imports and adds a regression test; it does not change the feature
oracle, training logic, or playing path.

Correctness evidence: focused preflight tests pass **7/7**; the combined
low-resource NNUE gate stack (`features`, full-suite attestation, trainer
gate/freezer/preflight, inventory, health, and final audit) passes **70/70 in
4.766 seconds** on the latest rerun; `py_compile` passes. Current discovered
inventories are 120 source files and 44 test files with hashes
`A069013B5ABAD25F2D4935E394BE804573A3E0C24E1BB4A06C27AA54A3259B65` and
`007A14891C6592AA0DA49F1E6BE16980248BD80E7970969738E5C6346B655437`.

The accepted control remains
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`; the
locked acquisition hashes remain unchanged. The latest read-only health audit
reports `RUNNING_HEALTHY` at 2,041/13,802 development analyses (11,761
remaining), shard counts 336/348/346/325/341/345, exact roles coordinator=1,
supervisor=1, worker=6, unknown=0, zero stderr bytes, zero temporary/extra
analysis artifacts, and zero protected reads; 51 stderr log files are present
but empty, and free disk is about 407 GiB. No production contract, model,
training, sealed-test read, playing-path change, or SPRT evidence exists.

Verdict: **PROMOTE TOOLING**. This closes the synthetic trainer-preflight gap
without authorizing training. The next single gated action is, only after
acquisition completion and the Phase-1 exit gates, to freeze the real contract,
run the real preflight on exact train/validation inputs, and pass two
byte-identical copies through the existing authorizer. Until then continue the
locked supervisor and do not create placeholder trainer evidence.

### 2026-08-31 out-of-band root aspiration retry (REJECT and clean revert)

An external tool reintroduced a default-off narrow root aspiration window with
initial delta 25 and widening by four. Although the candidate compiled, its
reported 19--25% depth-12--16 saving came only from selected initial-position
depths. Reproduction showed depth 12/13 used 28.5%/24.0% more nodes; depth
14/15/16 saved 16.5%/23.4%/19.5% while changing moves or scores.

On the deterministic 64-position depth-15 corpus, seed 20260931, two repeats,
the aspiration DLL `509A9E43919BE980BFF0AAB6181A075CCC48FBBFCBF7270AA1BF6DE56C76AA1A`
had geometric node ratio 0.99244 but total nodes 15,627,796 versus 15,572,644,
neutral time ratio 0.99957, only 45/64 same moves, and only 25/64 same scores.
The existing tests did not load this candidate, so the external 73-test claim
was not candidate correctness evidence. No SPRT was warranted after the
deterministic gate repeated the already-recorded mechanism failure.

The aspiration source was removed. Post-revert DLL
`4E2148B29DEF246CC0CD0BB532EF5E0BA9320A324B05047AE7306C082267A901`
matched the pre-revert macro-off control node/move/score on all 64/64 cases at
depth 15, two repeats. Accepted DLL remained
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.
Verdict: **REJECT and clean revert**. Do not stack futility on this candidate.

### 2026-08-31 native scalar full-refresh oracle (KEEP measurement only)

Hypothesis: a standalone default-off `MKNNUE1` loader and scalar full-refresh
implementation can become the bit-exact correctness oracle and quantify whether
direct scalar search integration is viable before incremental/AVX2 work.

`native/makhos_nnue_scalar.c` SHA-256 is
`D95CE674EE9180EDCAAFAD08F2D42C4FAD20212374F94A45A32460251EF93704`.
It validates magic/version/dimensions/scales, feature/rules/source identities,
payload length/SHA, and conservative feature/hidden/output integer bounds;
truncated, corrupt, incompatible, wrong-source, invalid-index, and
checksum-valid-but-unsafe artifacts fail closed. The reproducible builder
`build_nnue_scalar.ps1` SHA-256 is
`C77A4890D75A16ED6FAF9801C1BD4BE90EC7F43C23E3D89A8F52CC204D4E4C00`.
Two `/Brepro` builds are byte-identical at scalar DLL SHA-256
`2D071F91EC9551FD82EB8793F4E651BD1FA87A9B14C1EA3A6A4B3588B248634C`.

Real KEEP-model parity is 1,152/1,152 with zero mismatches: 640 structured
2/6/10/16-piece, both-turn, clock-0--79 cases plus 512 seeded random legal
positions. Parity report SHA-256 is
`3E206D0C2A6F9A142006BA0ADBD9A83C2DB6FF62A942B34F0C95D36D11106D82`.
The source-bound v9 complete suite passed 351/351 in 67.777 seconds, zero
protected/sealed reads, attestation SHA-256
`E8CE7B0E33FB10E05B29D97D499F128E896B7AFA9D93B1A14826E4E52A7F1DDB`.

The BelowNormal hot-cost screen on Ryzen 5 5600H measured full-refresh scalar
at 2,355.643/1,978.304/1,981.276/1,431.463 ns for 16/10/6/2 pieces versus
accepted HCE at 21.088/15.286/12.232/8.329 ns: scalar is 111.7x--171.9x
slower. Model allocation is 43,684 bytes. Raw-cost report SHA-256 is
`4F301866CBB4FE3FC96CFAF26E39C6A7D230BC84E138D1881306EFC1C88A4E1D`.

Verdict: **KEEP as measurement-only correctness oracle**. Direct full-refresh
search integration is rejected. The next one-concept experiment is a standalone
scalar incremental accumulator with full-refresh/parent-child/undo bit-exact
parity; AVX2 and playing-path integration remain separate later gates.

### 2026-08-31 scalar incremental accumulator (KEEP MEASUREMENT ONLY)

`native/makhos_nnue_incremental.c` SHA-256
`CD2575527528B0B96D924A867A64B9EBEFC9BB8363FB7CC127BF6ED08CF0FFC9`
wraps the validated scalar model with fixed RED/BLACK int16 accumulator sums,
active-feature bitsets, atomic candidate commits, and model-instance
invalidation. It changes no playing code. The reproducible builder SHA-256 is
`BFACF797F9FB18DDA484260DBD75D606E9A2DE32D8FB47B963DC93B46EF86DB2`;
two `/Brepro` builds are byte-identical at DLL SHA-256
`E455B708423F4B8B8B126263DB7A5F7BD5E7645DDF300114DC07EAB8B01C0CE7`.
Build-manifest SHA-256 is
`D2AB902408102C2858A5F22ACA64386FFF937974ED485313AA67592F870F50A6`.

Final-artifact parity has zero mismatches over 640 structured refresh states,
4 targeted quiet/capture/promotion/multi-capture forward/undo transitions, all
8 explicit clock-bucket boundaries, resets from all 9 buckets, 300 seeded random
forward/undo/reapply transitions, a requested 64-ply deep stack, invalid state,
and model reload. Focused tests pass 5/5; test SHA-256 is
`1A652D00AE1952C47A9E90044BA0E81B99AF3F7DCBC1467907262F256A515BBB`.
Parity-report SHA-256 is
`8241D1FC5CA34A6E81AE3CF5FB00444CD7952B7BC5925D732B0D545885B25475`.

The BelowNormal alternating-order screen used 500,000 iterations per run and
three repetitions on 16/10/6/2-piece cases. Dense scalar evaluation medians were
769.266/761.443/789.101/780.758 ns; forward remove/add updates across both
perspectives were 637.942/629.348/629.898/437.547 ns. Dense evaluation is
1.833x--3.062x faster than Phase 5 full refresh but still 36.479x--93.740x
slower than accepted HCE; update plus evaluation is 66.730x--146.273x slower.
Raw-cost report SHA-256 is
`FB6E74281A570249ADCB7B6DF4CDBFA9838D9FF121C9FB602B3EAB1D8E6F3456`.
The wrapped model uses 43,704 bytes and each accumulator 584 bytes.

Source-bound full-suite attestation v11 passed 356/356 in 68.252 seconds with
zero protected/sealed reads; SHA-256 is
`760FE2EB829EA7C269A9B220EF4B96DCF74E5DC0144E3FE06875A2FE43D84C1C`.
Accepted DLL remains
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

Verdict: **KEEP as the scalar incremental correctness oracle, never as a
playing path**. No SPRT applies. The next one-concept experiment is AVX2 only
for clipped activation/dense evaluation over the proven scalar accumulator;
scalar delta updates and playing-path integration remain unchanged/pending.

### 2026-08-31 AVX2 dense evaluation (KEEP MEASUREMENT ONLY)

`native/makhos_nnue_avx2.c` SHA-256
`2137BC4BB4DBB8E85CE2F38F93B3C529C20A497E7C7E3A078F04EBB765D84568`
adds only clipped activation and dense AVX2 kernels over the proven scalar
accumulator. The DLL is compiled baseline x86-64; only annotated functions
target AVX2, and an explicit runtime gate prevents unsupported execution. The
reproducible builder SHA-256 is
`D1610418400145193215B6985B20015D5B220F0754E90898AC3A5361436FF157`;
two `/Brepro` builds are byte-identical at DLL SHA-256
`EA6B6A1C47671CC1050E9FC861D3BF403E2AD6FCB6D07A7B24BE62E41B8C250A`.
Build-manifest SHA-256 is
`0C657B4A6408F0EF2C5720BB2D41CE8F125577043FAA60415263CB13D3463DCD`.

Final-artifact parity has zero mismatches over the complete Phase 6A corpus.
The target reports AVX2; a forced-unsupported build returns failure without
modifying output. Focused tests pass 7/7; test SHA-256 is
`AFDBB15B27958577D769FF4D8B020351D7B6A96792493F4EF6D526B0E5468198`.
Parity-report SHA-256 is
`E3529A12455BE179EAF557FD086216CC3E18A0CD1F9921D6E15C38B67F6C2F92`.

The BelowNormal alternating-order screen used 1,000,000 calls per run and three
repetitions on 16/10/6/2-piece accumulators. AVX2 dense medians were
154.062/158.872/159.664/157.358 ns, a 4.793x--4.993x speedup over the Phase 6A
`-march=native` scalar control. The same-DLL baseline scalar comparison is only
a diagnostic, not the primary control. Dense AVX2 is 7.306x--18.893x HCE
latency; projected unchanged-update plus AVX2-eval cost is 594.905--792.004 ns,
or 37.557x--71.426x HCE. Raw-cost report SHA-256 is
`80DCD2FA5F889CB54C2163FDB8EF1E6B199F806B8E4A4068769A3B073C07B6C9`.

Source-bound full-suite attestation v12 passed 363/363 in 71.191 seconds with
zero protected/sealed reads; SHA-256 is
`4D9FCA24A27015D32E0B1D1827A673E6937A084823405664CE98711E0F329687`.
Accepted DLL remains unchanged.

Verdict: **KEEP as the standalone AVX2 dense oracle, never as a playing path**.
No SPRT applies. Scalar delta updates now dominate the combined cost; the next
one-concept experiment vectorizes only the post-validation accumulator
remove/add arithmetic while preserving bitsets and commit semantics.

### 2026-08-31 AVX2 accumulator delta updates (KEEP MEASUREMENT ONLY)

`native/makhos_nnue_avx2_update.c` SHA-256
`6A236861A185D6C6DAD8DA785F10C92D680D26823C4A534F5733E56651FD182C`
reuses the validated model, accumulator, bitset, validation, atomic commit, and
AVX2 dense paths while vectorizing only the post-validation 128-lane int16
remove/add arithmetic in checked int32 lanes. The reproducible builder SHA-256
is `F4E4C74855BA45B0BE5A82FE2CB77F3D9F30FB515A2EF5076D3E80EBF2DFF21C`;
two `/Brepro` builds are byte-identical at DLL SHA-256
`64C862F3FC2AB99ACFE2AEE04966401E05B48849FF61EAE14A5F5208C5873095`.
Build-manifest SHA-256 is
`57A31A0841BF50DEFEFFE9FA74722868AF9296056F6FBE900C7D8310C27841B1`.

Final-artifact scalar/AVX2 parity has zero mismatches for quiet 1/1,
clock-boundary 2/2, capture 3/2, multi-capture 4/2, promotion 2/2, all clock
transitions/resets, 300 seeded random forward/undo/reapply transitions, the
deep stack, invalid delta classes, model reload, and forced-unsupported
fail-closed behavior. Focused tests pass 10/10; test SHA-256 is
`51B2D699B9B146F7B26AB31E42534C85DEB8B3966EBFD2BE2C3C2F93C8E0988F`;
parity-report SHA-256 is
`E95821C2027F6E2EC7AD04366C0DFDFA3D3B90FA09B377ADD44ECF582962D680`.

BelowNormal alternating-order native scalar/AVX2 medians are 435.974/87.427,
645.616/121.573, 713.805/134.418, 818.830/138.179, and 640.350/121.884 ns
for quiet/boundary/capture/multi-capture/promotion. AVX2 speedups are
4.987x--5.926x. Combining each update with the 158.115-ns Phase 6B dense
reference estimates 245.542--296.294 ns; this is not measured search NPS.
Raw-cost report SHA-256 is
`51A0B35066B7A4F3065628EB77E92A6E330B4BB5E9EB2C7E2A8D6F23A042E930`.

Source-bound full-suite attestation v13 passed 373/373 in 82.544 seconds with
zero protected/sealed reads; SHA-256 is
`7E7F1BBB1D1AB73BC76B0C02C8228C4C6540322766BD659E28D540D5549F2964`.
Accepted DLL remains
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.

Verdict: **KEEP as the standalone AVX2 update oracle, never as a playing
path**. No SPRT applies. All pre-search NNUE inference gates are complete; the
next one-concept experiment is a separate opt-in candidate that integrates the
KEEP NNUE into native search while preserving terminal/proof/tablebase rules.

### 2026-08-31 Phase 7 opt-in NNUE search candidate (PRE-GAME PASS)

Candidate DLL/model SHA-256 values are
`32C323026A7F78CCD9C4013FC3067422A564EE3D0A6ADE4F1CE5C62356747E79` and
`07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C`.
The implementation uses a root refresh, lazy per-ply accumulator stack, direct
changed-square AVX2 deltas, and NNUE only for non-terminal static evaluation.
The exact recursive parity guard, 256-state Python/native evaluation parity,
perft depth 10 (`861842812`), randomized 504-position/2,660-child differential,
20 exact endgames, time-stop, forced move, 12 Threads/512 MiB, and model-aware
GUI provenance all pass.

Pre-game audit SHA-256 is
`E8AE7AF5E91AF29CB393591E21BA3C26108FEB71DCDD547F39EAD4D75A9D3C7D`.
Fixed-depth candidate/accepted total nodes are 2,115,317/2,308,721 while total
time ratio is 1.812515x. At 250 ms median depths are 18.5/19 and candidate nodes
are about half. The model-aware arena pipeline smoke is operational but its one
truncated pair is `INCONCLUSIVE` and not strength evidence. Full-suite v16
passes 379/379 at SHA-256
`BB991A79B4A9459BE1A28A05CE65B0A322A3C09D7F64063E283F4E1EB713F61E`;
accepted remains byte-identical and sealed labels remain unopened.

Verdict: **freeze for Phase 8/9 gates; no promotion**. Next build and test the
resumable one-time sealed evaluator, then open/report the frozen test partition
without model selection before any real STC/SPRT.

### 2026-08-31 Phase 8 sealed-test opening (RUNNING; model selection forbidden)

The resumable evaluator/test SHA-256 values are
`EAAEF8129A8DAA49F1A482B564B96CEAF3FC1DFC78E72F571135B02AB131CC55` and
`E0C36DF684546A137FE2049762FA035F35E08AA89585B8932F9822B97A144A10`.
Its focused tests pass 4/4, including a guard that fails if preflight reads the
sealed manifest. Source-bound full-suite v17 passes 383/383 at SHA-256
`275F6B29BEBE989B95669EDD981C6C0C7443A3C165E9C9C637F8BEFCF0FD5326`.

Preflight authorization SHA-256 is
`01666818F1613ABDBBB4BD452280A75F60E79F68142A88B42609F30AEA4CA23A`.
The partition was then opened once under commitment SHA-256
`8F00BB6341B271D379BA48B406199B3C5AE50C75037CA2AEFB54AAE9AFEFB44E`,
binding 1,533 test games / 41,698 selected positions, the exact accepted teacher,
frozen candidate/model/feature ABI, and `model_selection_forbidden=true`.
Six BelowNormal workers on logical CPUs 0/2/4/6/8/10 now write whole-game
analyses under GUI-priority checkpoints; stderr was zero after startup.

Verdict: **RUNNING, not strength evidence**. Completion requires every shard
PASS and one immutable final report; resume the same shards after interruption,
never create a second opening.

### 2026-09-07 GitHub Gate C evidence-integrity review (KEEP TOOLING ONLY)

Base commit: `f45f7ab388025e91d6fad9442a0566ee84af4e74`.
Hypothesis: the lifecycle monitor can accept mathematically impossible W/D/L
totals despite matching pair counts and score mass; it also needs to reject
invalid consecutive log deltas and unfinalized checkpoints already at the cap.
The baseline accepted four draws for buckets `1/0/0/0/1` (LL + WW). The updated
validator rejects it. Independent exhaustive outcome enumeration through three
pairs verifies both acceptance of realizable totals and rejection of impossible
ones. Live checks cover the bounded observed tail, not a full journal audit.

Changed code: `work/nnue_gate_c_control.py` and its separate lifecycle tests.
Added read-only `preflight`: checks local prerequisites, leaves result/manifest
payloads and large tablebases unopened, and always reports runtime state as
unknown. Exit 2 reports blockers; even prerequisites-present is not launch or
promotion authorization. It diagnoses LF checkout versus frozen CRLF contract
bytes without rewriting files or weakening the exact contract check.

Read/hashed all 216 tracked files (32,792,306 bytes), parsed Python ASTs and all
JSON/JSONL records, and manually reviewed the relevant plans and lifecycle code.
This is not a claim of manual line-by-line review of every source/data file.
Accepted HCE/model hashes match the immutable identities above. Candidate DLL,
three tablebases, five bound evidence files, both Gate C results and the active
manifest are absent. The original host's current 2000ms verdict remains unknown.

Validation: lifecycle **25/25**, fixture preparation **5/5**, no failures/errors/
skips in those focused checks; skill validator and diff check PASS. The Linux
full-suite attempt discovered 355 cases including failed-import placeholders,
ran 312 in 61.436s, and ended with **6 failures, 25 errors, 51 skips**. Seven
imports failed for absent `psutil`; other failures/errors reflect missing native
fixtures, Windows DLL/clang requirements and Windows-specific workload locking.
This is **not** a complete-suite PASS or production attestation. Original
Windows validation remains required; no test was disabled or altered to pass.

Frozen source inventory: 153 files,
`E8F223128CA34BAFD7AF5E3E93F58D56777D0647A1D279B7C13A3BF20DC383A0`.
Frozen test inventory: 52 files,
`FE123C50E916829F8AA735E4862E726595F89BB8AE03BEF47403B2FFF1E8281B`.
Both still match the contract exactly. No playing source, rules, model, DLL,
search setting or frozen test changed; no strength experiment was launched.

Reproduction commands and exact tool/log hashes are in
[validation.json](../../../../work/gate_c_evidence_integrity_20260907/validation.json),
with the actual full-suite log and preflight report beside it.
Verdict: **KEEP tooling only; HCE remains production default**. Next action is
original-host Gate C manifest/evidence verification, followed by the unchanged
2000ms continuation only if resumable under all existing gates. Independent
PASS at both controls precedes production smoke/reversible promotion review.

### 2026-09-07 offline thread-audit reporting (KEEP PREPARATION ONLY)

Base: `252b06116a7f7a140c5c81a5e007ae8f9ca4648a`, including the user's Windows
newline correction to the prior lifecycle test. The user reports verified
2000ms resume on the original host (PID 20288, from pair 282, LLR +1.461).
These are user-reported snapshot values, not a new process probe. The existing
match remains under its frozen stop/isolation conditions.

Hypothesis: the already prepared thread matrix needs an offline result
contract that catches missing/duplicated observations, mixed runtime identities,
incorrect total Hash accounting and unavailable telemetry before comparison.
Inspection found that the iterative-session root splitter deliberately exposes
no per-layer telemetry delta; missing measurements must remain null.

Added `work/nnue_thread_audit_report.py`, focused tests and the recording guide.
The tool reproduces the unchanged preparation (96 cases x 6 thread counts x
2 budgets x 5 repetitions = 5,760 observations), validates header/row identity
bindings and sequential indices, replays move/PV legality, checks actual private
TT allocations, and summarizes each budget/thread/position stratum separately.
Complete data enables matched case/repetition/budget comparisons against 1T
and five-run move stability. Partial schedules/tails withhold these comparisons.
Fallback/errors/nonfinite data fail validation. No configuration recommendation,
native execution, strength gate or promotion is implemented by the reader.

Focused validation: **25/25 PASS**, zero failures/errors/skips, 5.143s,
56,284 KiB peak RSS on Linux/Python 3.12.13; guarded native loading and subprocess
call counts both zero. This comprises 20 new reporting tests and five unchanged
fixture tests. Cases include mixed identities, Hash overflow, illegal PVs,
recording gaps/duplicates, partial tails, LF/CRLF equivalence, missing telemetry,
and matched comparison keys. Skill validation and documentation links pass.
No full suite, native benchmark, training, match or external workload was run.

The complete demo contains fabricated data only, with 36 summary groups and
30 paired-comparison groups. Re-reading its 5,760-row stream reproduced the
report byte-for-byte: SHA-256
`1423C7D9D4979ECF72F23FA77F14278A4C82A00ECABBF49623650ACBB5C3718B`.
All eleven optional telemetry fields are explicitly unavailable in the demo;
profile coverage stays incomplete despite a complete schedule. Demo values
must not be cited as measured speed, scaling, correctness labels or strength.

Frozen source/test inventories still match the Gate C contract exactly:
153 source files `E8F223128CA34BAFD7AF5E3E93F58D56777D0647A1D279B7C13A3BF20DC383A0`,
52 test files `FE123C50E916829F8AA735E4862E726595F89BB8AE03BEF47403B2FFF1E8281B`.
Playing source, model, DLLs, rules, frozen tests and preparation remain unchanged.

Exact tool/evidence hashes and reproduction commands:
[validation.json](../../../../work/nnue_thread_report_evidence_v1/validation.json).
Verdict: **KEEP offline tooling/preparation only**. The next engine milestone
remains completion of the unchanged Gate C, then production smoke/reversible
review. After those gates, implement/verify the native collector, run the
approved matrix and select one measured bottleneck for an isolated experiment.

## Build and smoke commands

Build the full native tool set with:

```powershell
.\build_native.ps1
```

For an engine-only candidate, reproduce the compiler and flags used by the
control build and write to a separate DLL. Never overwrite the only accepted
baseline before tests finish.

Run the GUI with:

```powershell
python server.py
```

Use the GUI for behavior checks, not strength acceptance. Flipping the board
must not change the human side. A requested think time is a clock budget, while
forced/single legal moves may return immediately by design.

## Completion standard

At the end of each engine change, report:

- exactly what changed and which files changed;
- correctness tests and their results;
- fixed-depth/fixed-time benchmark deltas with the test positions;
- SPRT settings, pentanomial buckets, LLR, Elo confidence interval, and status;
- RAM/Threads/Hash behavior when relevant;
- whether the candidate is accepted, rejected, or still inconclusive;
- the single highest-value next experiment.

Do not declare the mission complete merely because the GUI works, the engine is
fast, or an internal candidate passes one SPRT. Completion requires sustained
external competitive evidence and a reproducible development pipeline.

### 2026-09-09 endgame request latency Phase 1A (KEEP_DIAGNOSTICS)

User authorized implementation of the phased architecture plan, starting with
latency profiling. Baseline is main `ec26c5e`; work is on
`codex/endgame-latency-phase1`. No search/evaluation/TT/time-allocation change.

`makhos/server.py` now partitions successful request time into validation,
engine-lock wait, engine setup, TB3 preparation, search, provenance and response
preparation. Resource metadata is captured under the search lock. Optional
`profile_request` uses `makhos/search_profile.py` only on the calling thread;
native internals/helper execution and IO wait are explicitly unmeasured.
`benchmarks/endgame_latency.py` uses the production release/HTTP handler under an
exclusive batch lease, retains raw observations, and checks fixed-depth parity.

619 observations: 560 unprofiled timed, 56 fixed-depth and three cold-process
requests. At requested 12T/512 MiB, TB3--6 use Python capacity 1; native7 uses
root split capacity 12. Cold TB3 preparation was 11,920.661 ms and 11,204.566 ms;
the pilot cold request consumed 11,671.875 ms process CPU and added 679,141,376
RSS bytes. Warm 1s/2s handler overshoot group P95 maxima were 8.79/9.60 ms.
The 2s run entered at four pieces without loading TB3, so it is a distinct oracle
readiness condition, not a matched 1s-versus-2s comparison. OS cache was not
flushed. Python movement/state self time was about 56--63% on warm BEST endgames.

Profile on/off parity passed 28 pairs. Old/new handler parity at depth 1/2/3
passed 48 cases, including repetition, clocks, draw defence and native7.
Final discovered suite: 434/434 PASS, zero failures/errors/skips, 97.582 seconds;
source/test inventories unchanged; protected-open attempts zero. An earlier
verification invocation stopped at Python 3.14 namespace test discovery after
parity passed; final invocation corrected discovery and completed all tests.
RULESET/core/accepted-DLL SHA-256 stayed unchanged. The frozen 6T/12T SPRT
checkpoint was neither opened nor resumed. This is diagnostic verification, not
a new release attestation or strength promotion; no new SPRT was run.

Review `docs/architecture/ENDGAME_LATENCY_PHASE1_TH.md` and
`benchmarks/results/endgame_latency_phase1/summary.json`. Compressed raw reports,
the executed verification snapshot, baseline parity and full-suite log are bound
by raw/gzip SHA-256 in that summary. Next experiment: loadable TB3 artifact and
readiness/deadline design, followed by native WDL-bound integration; do not retry
rejected SMP while the measured cold-build and Python movement costs dominate.

## 2026-09-09 — Phase 1B loadable TB3 candidate (Windows acceptance pending)

Base `ceb25bc`; branch `codex/endgame-latency-phase1b`. KEEP as a candidate,
not production promotion. Offline export reuses the unchanged C exact solver.
The 410,452-byte artifact expands to 2,838,446 bytes (1,447 clock vectors), with
52,731,648 dense slots verified by round-trip. GUI loads/checks it in a background
service; requests only attach ready bytes. Missing/corrupt/late loads fail visibly
without live building. Forced moves keep their bypass. Search/history/bound code,
rules/core, accepted DLL/model and the paused 27-pair experiment remain unchanged.

Linux final verification: 48,600 probes match the legacy oracle, 144 fixed-depth
search comparisons match nodes/moves/scores/bounds/PV, 20 new TB3 tests pass and
Node lifecycle passes 16/16. Load P95 8.956 ms, max 9.205 ms over 20 loads versus
12,958.814 ms legacy initialization; OS cache uncontrolled. The reference native
library is a separately compiled Linux .so, not the Windows accepted DLL.
HTTP BEST/WIN 1s/2s smoke passes. Full discovery is 454, with 411 tests run:
8 failures, 18 errors, 64 skips reproduce by name on unchanged `ceb25bc` (434
discovered/391 run). This is not a Windows full-suite PASS attestation.

See `docs/architecture/TB3_ARTIFACT_PHASE1B_TH.md`, `data/tb3_np80.manifest.json`
and `benchmarks/results/tb3_phase1b/summary.json`. Next: Windows 454-test suite,
accepted-DLL parity, startup <50 ms and production HTTP smoke at 1s/2s before
merge/promotion. Earlier attachment during 4->3 is an availability change;
preloaded-oracle fixed-depth parity alone is not a whole-GUI strength claim.


## 2026-09-09 — Phase 1C: native TB3 implementation milestone

KEEP experimental/default-off; C1 remains incomplete pending TB4–6.
Added native owned TB3 image, C17 versioned probe API and ctypes bridge.
48,600 raw Python/native probes match (seed 20260909); full Windows suite
461/461 PASS, zero skips/failures/errors in 150.154 s. Inventories unchanged;
protected production opens zero; rules/core/accepted DLL hashes unchanged.
Evidence: `benchmarks/results/endgame_c1_tb3/summary.json`; implementation
notes: `docs/architecture/ENDGAME_NATIVE_C1_TB3_TH.md`. No GUI routing change
or search performance/Elo claim. Next gate: native TB4–6 mapped readers with
139-signature differential and opened-file provenance before C2 integration.
