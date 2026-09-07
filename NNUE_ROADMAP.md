# Thai Makhos NNUE roadmap

Status routing (reviewed 2026-09-07): the frozen NNUE candidate has completed
training, inference/search pre-game gates, one-time sealed reporting and Gates
A/B. Gate C 1000ms is complete PASS; the unchanged 2000ms match is the active
experiment. Production default remains HCE until both controls and production
smoke/rollback gates pass.

[Current state](.agents/skills/thai-makhos-engine/references/current-state.md)
is the single current-state record; verify its live manifest/results before
acting. [DEVELOPMENT_PLAN_TH.md](DEVELOPMENT_PLAN_TH.md) owns the approved
forward sequence. This document owns v1 feature/model/data contracts and
historical evidence. Dated evidence and old next-action text below are history,
not launch instructions. The opened sealed partition cannot select a model.

## Objective and boundary

The first neural phase targets a Stockfish-style **scalar evaluation network**
that replaces `native_evaluate()` inside alpha-beta/qsearch. It does not add a
policy head and does not replace the separate proof-guided `PolicyValueModel`
contract. Proven WDL/tablebase/proof tiers, repetition, the 80-ply no-progress
rule, terminal scores, and move legality remain above the neural evaluator and
must never be weakened by it.

The production control stays
`build/makhos_native_accepted.dll`, SHA-256
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`, until a
candidate passes every gate below. No experiment may overwrite it.

## Historical evidence snapshots (non-routing)

The reproducible measurement-only audit is
`scratch/nnue_readiness_audit.py`; its current output is
`build/nnue_readiness_v1.json`.

- Exact corpus: 9,000 unique quiet 4--6-piece positions, balanced 3,000 each
  WIN/DRAW/LOSS, but every clock is zero and the coverage is endgame-only.
- Middlegame corpus: 960 unique positions from 64 source games and all 5--16
  piece bands; 909 are quiet roots, 848 have stable last-two move labels, and
  708 are simultaneously quiet, marked usable, and have last-two score delta
  at most 50 cp. It contains no game-outcome field.
- The v5 train/holdout split is useful development data, but its holdout was
  already opened for the HCE fit. It cannot become the final NNUE test set.
- The two เซียนเฒ่า regressions are independent external diagnostics, not
  proven best-move labels and not training data.
- The native evaluator is called primarily at quiet qsearch leaves after all
  mandatory captures have been resolved. Training distribution must therefore
  prioritize quiet positions with scalar targets, not arbitrary policy roots.
- The target host is an AMD Ryzen 5 5600H (6 cores/12 threads); the current
  native compiler exposes AVX2, AVX, and SSE4.2 under `-march=native`.

Historical readiness verdict: **superseded by completed float training**. The subsequent completed inference/search/strength milestones are recorded in
current-state.md. This old readiness snapshot does not reopen a finished gate.

### 2026-08-31 AVX2 accumulator-update evidence (KEEP measurement only)

The isolated update DLL is byte-reproducible at SHA-256
`64C862F3FC2AB99ACFE2AEE04966401E05B48849FF61EAE14A5F5208C5873095`.
Scalar/AVX2 parity has zero mismatches for all targeted delta shapes, every
clock transition/reset, 300 seeded random transitions, the deep stack, invalid
deltas, reload, and forced-unsupported behavior. Focused tests pass 10/10 and
the parity-report SHA-256 is
`E95821C2027F6E2EC7AD04366C0DFDFA3D3B90FA09B377ADD44ECF582962D680`.

AVX2 medians are 87.427--138.179 ns by delta shape, a reproducible
4.987x--5.926x speedup over the scalar update control. The Phase 6B dense
reference plus update projects 245.542--296.294 ns per update+eval, which is an
integration-planning estimate rather than search NPS. Full-suite attestation
v13 passed 373/373 at SHA-256
`7E7F1BBB1D1AB73BC76B0C02C8228C4C6540322766BD659E28D540D5549F2964`.
No playing path changed and no SPRT applies.

### 2026-08-31 native scalar full-refresh evidence (KEEP measurement only)

The reproducible builder produced two byte-identical standalone oracle DLLs at
SHA-256 `2D071F91EC9551FD82EB8793F4E651BD1FA87A9B14C1EA3A6A4B3588B248634C`.
The real KEEP model matched Python quantized inference on all 1,152 cases across
2/6/10/16 pieces, both turns, all clocks 0--79, and 512 seeded random legal
positions. The loader rejects corrupt, truncated, incompatible, wrong-source,
invalid-feature, and checksum-valid but overflow-unsafe inputs. Parity report
SHA-256 is `3E206D0C2A6F9A142006BA0ADBD9A83C2DB6FF62A942B34F0C95D36D11106D82`.

The 43,684-byte model allocation measured 1,431--2,356 ns per hot full-refresh
evaluation versus 8.329--21.088 ns for accepted HCE on the Ryzen 5 5600H. The
111.7x--171.9x latency gap rejects direct full-refresh search integration and
justifies the predeclared incremental-then-AVX2 sequence. Raw-cost report
SHA-256 is `4F301866CBB4FE3FC96CFAF26E39C6A7D230BC84E138D1881306EFC1C88A4E1D`.
Full-suite attestation v9 passed 351/351 with SHA-256
`E8CE7B0E33FB10E05B29D97D499F128E896B7AFA9D93B1A14826E4E52A7F1DDB`.
No sealed label, playing path, or accepted DLL changed, so no SPRT applies.

### 2026-08-31 scalar incremental evidence (KEEP measurement only)

The fixed-perspective scalar accumulator is byte-reproducible in the standalone
DLL at SHA-256 `E455B708423F4B8B8B126263DB7A5F7BD5E7645DDF300114DC07EAB8B01C0CE7`.
Final-artifact parity has zero mismatches on 640 structured states, 4 targeted
quiet/capture/promotion/multi-capture forward/undo transitions, all 8 explicit
clock-bucket boundaries, resets from all 9 buckets, 300 seeded random
forward/undo/reapply transitions, a requested 64-ply deep stack, invalid state,
and model reload. Parity-report SHA-256 is
`8241D1FC5CA34A6E81AE3CF5FB00444CD7952B7BC5925D732B0D545885B25475`.

The 43,704-byte wrapped model and 584-byte accumulator measured scalar dense
evaluation at 769.266/761.443/789.101/780.758 ns and two-perspective move updates
at 637.942/629.348/629.898/437.547 ns for 16/10/6/2-piece cases. Dense evaluation
is 1.833x--3.062x faster than Phase 5 full refresh but remains 36.479x--93.740x
slower than accepted HCE; update plus evaluation is 66.730x--146.273x slower.
Raw-cost report SHA-256 is
`FB6E74281A570249ADCB7B6DF4CDBFA9838D9FF121C9FB602B3EAB1D8E6F3456`.
Full-suite attestation v11 passed 356/356 with SHA-256
`760FE2EB829EA7C269A9B220EF4B96DCF74E5DC0144E3FE06875A2FE43D84C1C`.
No sealed label, playing path, or accepted DLL changed, so no SPRT applies.

Verdict: retain scalar incremental as the parent/child/undo oracle only. The
next one-concept experiment vectorizes clipped activation/dense evaluation while
reusing scalar accumulator updates unchanged; AVX2 delta updates and search
integration remain later, separately measured decisions.

### 2026-08-31 AVX2 dense evidence (KEEP measurement only)

The standalone baseline-x86-64 DLL uses an AVX2 function target behind an
explicit runtime capability gate; a forced-unsupported build fails closed before
touching output. Two `/Brepro` builds are byte-identical at SHA-256
`EA6B6A1C47671CC1050E9FC861D3BF403E2AD6FCB6D07A7B24BE62E41B8C250A`.
AVX2/scalar final-artifact parity has zero mismatches over the complete Phase 6A
corpus. Parity-report SHA-256 is
`E3529A12455BE179EAF557FD086216CC3E18A0CD1F9921D6E15C38B67F6C2F92`.

BelowNormal alternating-order medians were 154.062/158.872/159.664/157.358 ns
for 16/10/6/2-piece dense evaluations, a 4.793x--4.993x speedup over the Phase 6A
native scalar control. Dense AVX2 remains 7.306x--18.893x slower than HCE. With
the unchanged scalar update cost, projected update+eval is 594.905--792.004 ns,
or 37.557x--71.426x HCE latency. Raw-cost report SHA-256 is
`80DCD2FA5F889CB54C2163FDB8EF1E6B199F806B8E4A4068769A3B073C07B6C9`.
Full-suite attestation v12 passed 363/363 with SHA-256
`4D9FCA24A27015D32E0B1D1827A673E6937A084823405664CE98711E0F329687`.
No sealed label, playing path, or accepted DLL changed, so no SPRT applies.

Verdict: retain AVX2 dense as a standalone oracle. Scalar delta updates now
dominate the measured combined cost; the next isolated experiment vectorizes
only the validated 128-lane remove/add arithmetic.

## Why the first network is not chess HalfKP

Stockfish's design demonstrates the useful principles: sparse inputs, small
changes between positions, two perspective accumulators, low-precision integer
inference, and search-stack accumulator state. Its king-anchored HalfKP/HalfKA
feature family is chess-specific. Thai Makhos has no unique royal king square,
so copying that anchor would add artificial state and expensive refreshes.

The upstream references are:

- <https://github.com/official-stockfish/nnue-pytorch/blob/master/docs/nnue.md>
- <https://github.com/official-stockfish/Stockfish/blob/master/src/nnue/nnue_accumulator.h>
- <https://github.com/official-stockfish/Stockfish/blob/master/src/nnue/nnue_architecture.h>

They are design references, not justification to copy a heuristic or current
Stockfish network size without Thai-Makhos evidence.

## Locked v1 feature specification

Maintain two accumulators, one for each player's perspective, using one shared
feature-weight table.

For perspective `p`:

1. Canonical square is the physical square for Black and `31 - square` for Red.
2. Piece category is relative to `p`: own man, own king, opponent man, opponent
   king.
3. Piece feature index is `category * 32 + canonical_square`, giving 128 sparse
   piece-square inputs.
4. Add one of nine reversible-clock features: exactly zero, 1--9, 10--19,
   20--29, 30--39, 40--49, 50--59, 60--69, or 70--79. Positions at 80 are
   terminal before evaluation.

Total input dimensions: `128 + 9 = 137`. A legal position activates exactly
`piece_count + 1` inputs in each perspective.

At inference, concatenate the side-to-move accumulator first and the opponent
accumulator second. Side to move is therefore represented without a feature
whose weight must change globally every ply.

### Executable feature ABI oracle (2026-08-28, PROMOTED TOOLING)

`makhos/nnue_features.py` is the executable, pure-Python oracle for this
contract. It is deliberately not imported by the playing path. Its SHA-256 is
`EAEB36EDBF09476F36958AAD7C78ED28B02A2B5EE178622D44BC331ABE30A30E`, and its
focused tests `tests/test_nnue_features.py` have SHA-256
`F57B620F6B5407F2EA6BD0E388B521673BFF2DB61E2273235078A8A08B498A2B`.
The trainer-contract gate now obtains its expected feature payload from this
oracle; the updated gate SHA-256 is
`DF502CFADDC6B220E141AD1350D838FB62D3A26DFE1D039A93EB2E7D4D1D35C8`.

The oracle tests prove the exact machine-readable contract and both-perspective
rotation/color-swap symmetry, enumerate all 80 legal clock values while
rejecting terminal clock 80, and reconstruct quiet, capture, promotion,
multi-capture, and 300 random legal parent/child deltas. Before the contract
freezer was added, the low-resource NNUE gate stack passed 53/53 in 3.984
seconds; the freezer experiment stack passed 63/63 in 4.355 seconds. This is a tooling
promotion only:
there is no model, native inference, playing-path change, or SPRT result.
Future trainer, scalar-C, refresh/incremental, and AVX2 implementations must
match this ABI exactly before any candidate is allowed into search.

### Deterministic trainer-contract freezer (2026-08-28, PROMOTED TOOLING)

`scratch/nnue_trainer_contract_freezer.py` assembles the first frozen trainer
contract only from explicit post-gate evidence and train-only choices. It
injects the executable feature ABI, locked network shape, split identity,
one-time sealed-test policy, and authorization boundary; it rejects missing or
extra evidence, test-dependent fields, duplicate/invalid seeds, and protected
source/acquisition output paths. It writes canonical LF byte-locked JSON but
does not authorize training.

The freezer SHA-256 is
`B0E26673291AB92882CE48051F9C487E244E33EB64FE5A9B744A2ECEEB721273` and its
focused tests SHA-256 is
`3F8F0D841E19E9E4420195A243E4215B0690FD25DBC822F19FD8EAD286FDD17F`.
The freezer tests pass 10/10; at the freezer checkpoint the combined
low-resource NNUE gate stack passed 63/63 in 4.139 seconds on the final rerun
(experiment run: 4.355 seconds). The latest stack including preflight is
recorded below. The existing fail-closed
`nnue_trainer_contract_gate.py` remains the final authority after two real final
audits, exact inventories, idle full-suite attestation, and tiny-fixture
preflight exist. No production contract, model, or playing-path change has
been made.

### Deterministic tiny-fixture trainer preflight (2026-08-28, PROMOTED TOOLING)

The new `scratch/nnue_trainer_preflight.py` is a standard-library-only harness
for the trainer's last development gate. It runs solely on an explicit
synthetic `thai-makhos-nnue-trainer-fixture-v1` tiny linear fixture and the
frozen contract/audit/source identities; it never reads production analyses,
test analyses, the sealed-test manifest, or volatile supervisor status. It
proves fixture overfit, byte-identical deterministic repeat, byte-identical
checkpoint resume, a non-tautological checkpoint checksum round-trip, and
fail-closed protected-path/sealed-test guards. Fixture weights are discarded,
and every emitted result is explicitly non-authorizing.

The preflight SHA-256 is
`157BF19A3E77D760F3B9B94D747F9CC314C55481A714A245ABE04A2C43019CF2`; its
focused tests SHA-256 is
`7432CACD5FC9C6DBE1BCB7E458DF6873CA5550C4BB990E78C9C1007AB156A411`.
The focused preflight tests pass 7/7, including a direct-file CLI smoke; the
complete low-resource NNUE gate stack passes 70/70 in 4.766 seconds on the
latest rerun, with `py_compile` also
passing. The current discovered inventory is 120 source files / 44 test files,
with hashes
`A069013B5ABAD25F2D4935E394BE804573A3E0C24E1BB4A06C27AA54A3259B65` and
`007A14891C6592AA0DA49F1E6BE16980248BD80E7970969738E5C6346B655437`.

This is tooling only: there is still no real trainer contract, preflight
artifact, production model, native inference, playing-path change, or training
authorization. A real preflight is permitted only after acquisition completion,
two byte-identical final audits, idle full-suite attestation, exact
train/validation inventories, and a real frozen trainer contract.

Do not add mobility, capture maps, support cones, handcrafted PST values, or
history/repetition features to v1. They either change non-locally, duplicate
search rules, or lack measured justification. The network can infer material,
phase, square relations, and promotion geometry from the sparse occupancy
features. Search continues to handle history-dependent repetition explicitly.

### Incremental update contract

The position stack must hold both accumulator vectors. Use the authoritative
bitboard difference between parent and child to remove/add piece features in
both perspectives. This naturally handles:

- quiet start/end changes;
- every captured piece in a multi-jump;
- immediate captured-piece removal;
- man-to-king promotion as a category replacement; and
- a reversible-clock bucket change or reset.

Undo restores the parent's stored accumulator; it must not apply inverse
floating-point updates. A full refresh is required only at root/model load or
after a failed validity check, not because a king moved.

## Locked v1 network shape

Start with a single architecture, not a post-hoc sweep:

```text
137 sparse inputs
  -> shared 128-wide int16 accumulator for each perspective
  -> concatenate side-to-move/opponent (256)
  -> clipped ReLU to int8
  -> affine 32 + clipped ReLU
  -> affine 1 scalar score
```

This is approximately 26,000 learned weights and remains small enough for this
laptop's caches. It supplies nonlinear piece interactions without importing the
much larger chess network. A size change is a later independent experiment and
requires an offline learning-curve or inference bottleneck that identifies
capacity as the limiting factor.

### Quantization and model identity

- Float training must simulate the intended clamps/scales before export.
- Feature-transformer weights/accumulators use int16; dense activations/weights
  target int8 with int32 accumulation and biases.
- A scalar C implementation is the correctness oracle. An AVX2 path is required
  for a strength candidate; scalar inference is not promoted merely because it
  is easier.
- Clamp the neural scalar inside a non-terminal range (initial design bound
  `[-30000, 30000]`) so it cannot collide with mate/tablebase scores.
- The binary format must start with a versioned `MKNNUE1` header and bind feature
  specification, dimensions, quantization scales, ruleset SHA-256, payload
  length, and payload checksum. Every benchmark/SPRT result records the model
  SHA-256 in addition to the DLL SHA-256.
- Loading an incompatible/corrupt model fails closed to an explicitly selected
  classical fallback. It must never silently use partially loaded weights.

## Label contract

The NNUE output is a scalar from the side-to-move perspective. Keep three label
sources distinct in every record:

1. `teacher_score`: longest completed accepted-control search score, excluding
   mate-like/incomplete layers.
2. `game_outcome`: actual WIN/DRAW/LOSS; truncated games have no outcome label.
3. `exact_wdl`: tablebase result when independently available.

Do not convert a search-stable move into a proven best-move label. Do not turn a
time cap into a draw. Do not copy a game result to positions after a repetition
or no-progress history has been discarded without retaining that history flag.

The eventual trainer may interpolate teacher-eval and outcome loss, as the
official NNUE training documentation describes, but its mixing coefficient is
selected only inside training games. The locked test split and external
regressions cannot select architecture, scale, loss, epoch, or checkpoint.

Exact 4--6-piece WDL prevents endgame blindness but must be stratified so its
balanced artificial distribution does not dominate normal 8-vs-8 play.

## Data split and leakage rules

- Assign the **source game** to train/validation/test before selecting positions
  or applying symmetry; initial rule is deterministic 80/10/10 by game-id hash.
- Every position, color-rotated copy, clock variant from the same trajectory,
  and relabelled version remains in that game's split.
- Deduplicate by canonical position plus reversible clock across all splits;
  cross-split duplicates are dropped, never reassigned.
- Existing v5 data is development-only. Create a fresh locked test manifest for
  NNUE and do not open it until the model/checkpoint rule is frozen.
- User/เซียนเฒ่า games remain external regression data unless the user explicitly
  creates a separate training pool. A reported loss never becomes a one-position
  tuning target.

## Historical first experiment after authorization (completed)

Name: **quiet-leaf scalar-label acquisition pilot**. It changes no playing code
and trains no model.

Protocol:

- 256 fresh source games with locked seeds and controlled opening diversity.
- Byte-locked accepted DLL, one thread, persistent search, production rules and
  tablebases.
- Analyze quiet positions at 100/500/2000 ms; retain a scalar-training candidate
  only when the last two completed scores differ by at most 50 cp and no
  mandatory capture exists.
- Minimum 8,000 unique quiet positions after deduplication.
- Split 80/10/10 by source-game hash before sampling.
- Store full provenance, all budgets/depths/nodes, teacher/model DLL hash,
  position, reversible clock, game outcome or explicit truncation, and exact WDL
  where available.

Pilot gates:

- zero canonical/symmetry leakage across splits;
- every teacher hash equals the accepted control;
- Black/Red each 45--55% of samples;
- each 13--16, 9--12, and 5--8 piece band at least 20%;
- at least 30% of positions contain a king;
- no truncated game labelled draw;
- generation/resume reproduces config, manifests, corpus, and summary
  byte-for-byte.

The pilot only validates label yield and schema. It does not authorize training.
Before a trainer experiment, accumulate at least 100,000 broad-phase quiet
scalar labels and reserve a fresh unopened test split. Dataset-size escalation
after that follows a predeclared learning curve, not an arbitrary claim that a
small corpus is enough.

### 2026-08-24 acquisition preflight result and capacity repair

The first 256-game source set was generated and locked, but its label-capacity
preflight is **REJECTED as too small**, not as a reason to weaken the label
contract. The locked config and selection manifest are
`build/nnue_quiet_leaf_pilot_v1/config.json` (SHA-256
`1228B7E2B742D0EAA2CBF49077DC50A6FCD14CD50A9A526F6345DBF26CCCFE19`)
and `build/nnue_quiet_leaf_pilot_v1/selection_manifest.json` (SHA-256
`6817A208675DF7F29D5E84C7F1CB811694E7840D5994F3AFE5D712E13BCB56F2`).
All 256 games completed by a real terminal condition; the game-hash split is
210 train / 27 validation / 19 test. After symmetry deduplication the locked
manifest contains 9,065 quiet positions: 3,340 in the 13--16-piece band,
2,477 in 9--12, and 3,248 in 5--8. Exhausting every quiet position from those
same games raises capacity only to 9,163, so increasing the per-game selection
cap cannot repair the pilot.

The accepted one-thread persistent teacher analyzed a deterministic 12-game
preflight (474 positions) at 100/500/2000 ms. Only 300 labels passed: 63.2911%
retention versus the 88.2515% required to obtain 8,000 labels from 9,065.
There were 107 mate-like exclusions and 67 last-two-score-delta exclusions.
Retention by phase was 145/159 (91.195%) for 13--16 pieces, 83/126 (65.873%)
for 9--12, and 72/189 (38.095%) for 5--8. The honest projection is 5,737
eligible labels. The reproducible artifact is
`build/nnue_quiet_leaf_pilot_v1/preflight_summary.json` (SHA-256
`5F013826CAE23EF22405DE75FDA941512F100DBC592053FDDAFAD7530268CA39`),
with every contributing analysis hash recorded. This is enough evidence to
stop the 256-game labeling run early; completing it would spend hours without
being able to pass the declared 8,000-label gate.

The single permitted repair is **v2 capacity scaling to 512 fresh source
games**, with all other teacher and quality gates unchanged. The 50-cp score
gate, mate-like exclusion, one-thread accepted teacher, 100/500/2000-ms
budgets, game-level split, symmetry deduplication, and truncation semantics are
locked. Every eligible analysis remains stored. The published pilot corpus is
then selected deterministically to exactly 8,000 samples while enforcing at
least 30% king positions, at least 20% from each phase band, and 45--55% from
each side to move. This is coverage sampling, not label cherry-picking: it uses
only position metadata and canonical IDs, never scores or outcomes. The
acquisition harness is `scratch/nnue_quiet_leaf_acquire.py` (SHA-256
`FBBE50891C3AED9BF08BE164112D0F647D44C85D18FE60435E1DA2A7D03CADA2`),
and the focused tests are `tests/test_nnue_quiet_leaf_acquire.py` (SHA-256
`02693C6BA7A76AB91F241DCB1CCDB6E215EF6DAAAEA9391C5F8E0950931D17F3`).
Focused tests passed 7/7 and the full suite passed 199/199 in 77.550 seconds.
No playing code or accepted DLL changed.

The 512-game v2 repair was then generated from a wholly fresh seed range
starting at `20264001`. Its locked config and manifest are
`build/nnue_quiet_leaf_pilot_v2/config.json` (SHA-256
`76ACC4D39A1C833DA19F5F782BD70243FEFD1DB275C0AADEDB742AE315F0AAD6`)
and `build/nnue_quiet_leaf_pilot_v2/selection_manifest.json` (SHA-256
`D1FC5DD62F6787A77A6318F53A176AA4B11C98577CC97046EAACE6D29F72D013`).
All 512 games are terminal, none is truncated, and the split is 406 train / 59
validation / 47 test. It supplies 16,991 unique quiet candidates: 5,902 / 5,213
/ 5,876 across the three phase bands and 6,047 containing kings.

A fresh 12-game v2 preflight analyzed 418 positions and retained 269 (64.354%):
101 mate-like and 48 unstable-score exclusions. Stratified projection is
10,772 labels overall, but only 2,403 with kings and only 1,972 in the 5--8
piece band. Those barely cover the final minima of 2,400 kings and 1,600 per
phase, with no acquisition safety margin. The locked preflight artifact is
`build/nnue_quiet_leaf_pilot_v2/preflight_summary.json` (SHA-256
`D3756EC65D1947CDED5BB77A0F356AB2568899030F61A924E838575140CA6BE2`)
and its verdict is **COVERAGE_CAPACITY_RISK**. Do not spend the full labeling
budget on v2.

The preflight now requires a 1.25x capacity margin before a full labeling run:
10,000 projected total labels, 3,000 projected king labels, and 2,000 projected
labels in every phase. The next and only capacity repair is v3 with 768 wholly
fresh source games and unchanged label/search gates. At v2's measured
stratified yield this projects about 16,158 total, 3,605 king, and 2,958 late
phase labels. Run a locked v3 preflight first; only a
`READY_FOR_FULL_LABELING` verdict authorizes completing every teacher analysis.

The original v3 run is **rejected as acquisition evidence** despite its passed
capacity preflight. A coordinator audit found that 768 generated files contained
only 766 content-stable game trajectories: one trajectory appeared under three
different seed filenames. The old selector keyed analyses only by `game_id`, so
two workers could overwrite the same analysis and the finalizer simultaneously
required an impossible 768 unique IDs. The run was stopped before completion;
its 52 partial analyses remain only as failure evidence and must not enter a
corpus.

The repaired harness deterministically keeps one source file per content-stable
trajectory before split/sampling. Selection manifests record every duplicate
group and bind each game analysis to a `selection_sha256`; stale or duplicate
manifests are rejected. The finalizer separately verifies 768 generated files
and 766 unique analyses. Harness SHA-256 is
`7650DDA319A5640DDEFF78FF935B500530FB67059A335F12B978FD075F554CA9`;
focused-test SHA-256 is
`27874ED749E7A02D489504E22A132D21C24423555396E60B6B16AD3624723D0B`.
Focused acquisition tests passed 10/10, focused finalizer tests passed 2/2,
and the full suite passed 204/204 in 89.851 seconds. No playing code or accepted
DLL changed.

The repaired v4 manifest reuses the same locked 768 generated source files and
teacher gates, but deduplicates them to 766 trajectories before splitting:
620 train / 63 validation / 83 test. It selects 24,734 quiet positions, including
8,983 with kings and 8,775 / 7,708 / 8,251 across the three phase bands. Config
SHA-256 remains
`F0C50CE1E59C10F7F8596087690B97AF3147B70F95B9AD2699D8A258980EBED7`;
selection-manifest SHA-256 is
`3F5330B745BD30369E371B58203858994832260FBF1C583A6EE4600394DCF1B4`.

The fresh bound 12-game v4 preflight retained 204/301 labels (67.774%): 64
were mate-like and 33 exceeded the 50-cp delta. Stratified projection is 16,508
labels, with 3,417 containing kings and 8,169 / 5,445 / 2,894 by phase. Every
1.25x capacity gate passes. Artifact
`build/nnue_quiet_leaf_pilot_v4/preflight_summary.json` has SHA-256
`7C9A7AF0432FA333BF24E154CD8F580209C04AB4B7AD0CF7F18D17CEBB38B633`
and verdict **READY_FOR_FULL_LABELING**. Full v4 teacher acquisition is
authorized; model training remains unauthorized. Run four whole-game shards,
require empty stderr and 766 unique bound analyses, finalize once, then rerun
the finalizer to prove the corpus and summary are byte-identical on resume.

A train-only scalar HCE-gap audit now accompanies acquisition. The audit
validates every analysis binding and reports HCE-versus-teacher MAE, RMSE,
correlation, residual quantiles, phase, king, turn, and search-budget deltas.
It refuses partial data by default and never uses the test split for model
selection. The current checkpoint is explicitly partial; rerun it only after
the v4 corpus has passed both finalization/reproduction gates before using its
aggregate result to design corpus scaling or evaluator experiments.

The v4 run resumed only after the interactive server was idle and closed. A
hash-binding coordinator revalidated the preserved 100 analyses, then launched
four BelowNormal whole-game shards under the workload lease. The acquisition
completed all 766 unique analyses; all eight old/resumed worker stderr logs are
empty, every teacher hash equals the accepted DLL, and the finalizer state is
**PASS**. Interactive work still has absolute priority for every future batch.

The final deterministic corpus contains 8,000 rows from 15,393 eligible labels:
6,496 train, 611 validation, and 893 test; 4,000 rows per side to move; 2,610
king rows; and 3,522 / 2,454 / 2,024 rows across 13--16 / 9--12 / 5--8 pieces.
There are 1,003 exact-WDL rows, zero symmetry/position leakage, and zero
truncation-to-draw errors. Corpus SHA-256 is
`4C90796735DFC5AC1667906E2DB4F9EAEBBB4C5B10DA0CAF543249444FD4FB24`;
summary SHA-256 is
`AA610533E6CAB3D8D720789F9B0A8DFA37F321F0B8000EBAECF769EA4C56BFE4`.
A separate resume reproduction preserved both files byte-for-byte. The
accepted DLL remains byte-identical at
`FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`.
This completes the label-pilot gate only and does not authorize training.

The full non-partial HCE-gap audit validated all analyses and remained
byte-identical on rerun. Train has 12,510 eligible rows (Pearson 0.7681, MAE
98.43 cp versus the 2,000-ms teacher); validation has 1,225 (Pearson 0.7379,
MAE 103.77 cp). Validation MAE is 44.68 cp at 13--16 pieces, 171.73 cp at
9--12, 154.32 cp at 5--8, and 178.53 cp with kings versus 88.31 without kings.
Black/Red MAE is nearly equal, so the general gap is phase/king coverage rather
than a side-specific constant. Train/validation artifact SHA-256 values are
`6C46BE7B3DA6DF37D38A0EBA05E44270302D332877F88FEB68CC42BC341D16F4`
and `CE04F79529A181E96BD9F0D88EA6CDD764E38A5DF38988864894B36AC02E42EE`.

The next experiment is a deterministic scaling-capacity audit using only v4
train/validation source-game units. It must derive conservative lower bounds
for total, king, phase, and turn label yield; project runtime/storage; and size
a wholly fresh 80/10/10 acquisition whose train pool has a 1.25x margin over
the 100,000-row trainer target and its coverage strata. The future test
manifest is sealed and unopened until architecture, loss, and checkpoint rules
are frozen. No large generation run or NNUE trainer starts before this sizing
artifact is reproducible.

That capacity audit is now complete and byte-reproduced. It read 683
train/validation source-game units and zero v4 test analysis files. Its 1%
bootstrap lower-bound yields are 19.2782 eligible labels per unique game,
3.2313 with kings, 10.0571 / 5.3089 / 3.3075 by phase, and 9.6003 / 9.6574 by
turn; the unique-trajectory rate is separately discounted to a 99% Wilson
lower bound of 0.98678. Artifact SHA-256 is
`9F27BCEAADA11695E1049D4F68A34D26ACAF509E25DFDF1D914E9AA74E360C59`.

King coverage is the binding 1.25x gate. Raw sizing needs 14,701 source files;
the locked scheduling size is **15,360 fresh files**. Conservative projection
is 233,759 train labels, 39,182 with kings, 121,948 / 64,374 / 40,105 by phase,
and about 29,220 validation plus 29,220 sealed-test labels. Six teacher workers
project 64.7 hours from measured v4 throughput, excluding generation; projected
source plus analysis storage is about 1.9 GB. These are planning bounds, not
training evidence.

The 96-game fresh-seed harness preflight on `20270001..20270096` is now complete
and PASS. It generated 96 unique trajectories in 36.128 seconds, locked 84
development games plus 12 sealed-test games (402 selected test positions), and
analyzed 84/84 development games while reading zero test analysis files. The
development and sealed-test manifest SHA-256 values are
`F461D2EB37531607C795E7DEC73207180766E72C42CFE9CB5CF92CF1553E6F0D` and
`4822A8C93CBA458175375209CCEBAD18432CEF5E2A7EF3F98FBB73B720EA7997`.
There were zero stderr bytes and zero temporary artifacts.

Teacher work totaled 7,600.256 worker-seconds for 84 development games, or
90.479 worker-seconds per game, closely reproducing the previous 92.22 sizing
estimate. Six workers project about 57.9 hours for the initial 90% development
partition at 15,360 games (64.3 hours if every game is later labeled), while
generation projects about 1.6 hours. The 96-game sample's hash-shard counts
were 13/13/24/13/11/10, so its measured 2,150.808-second wall time includes a
small-sample tail; monitor full-run balance before adding scheduler complexity.

Generation resume, analysis resume, the development manifest, and the sealed
test manifest all reproduced byte-for-byte. A separate completed-state rerun
kept `build/nnue_scaling_preflight_v1/preflight_summary.json` unchanged at
SHA-256
`58C4A1AFBF1FDF90590AACF0B02109A085FC3A1D3271E586CA5036E3702D94FC`;
all nine gates are true, and the full suite passes 227/227. Worker resume
validation plus coordinator replay/hash loops now checkpoint GUI priority at
safe item boundaries, and validation no longer hashes each analysis twice.
This authorizes the
15,360-game acquisition only. Next lock a resumable full-run launcher and a
fresh non-overlapping seed range, then start six-shard generation and
development labeling under the same accepted-teacher and GUI-priority
contract. Training and opening test labels remain locked until the full corpus
passes coverage, provenance, reproduction, and sealed-test gates.

The locked full-run supervisor is now implementation-ready at
`scratch/nnue_scaling_full_run.py`, SHA-256
`F3E7E7457B521253E0A893F5F89D89048D662324CAA3FE24B81109159B048AA9`.
It hard-rejects drift from 15,360 games, fresh seeds
`20280001..20295360`, six one-thread/256-MiB workers, and the accepted
100/500/2000-ms teacher. It rechecks every source/config/authorization binding
before each automatic post-GUI resume. Supervisor tests pass 6/6 and the full
suite passes 233/233. The locked config has SHA-256
`B42B9369ED6CD40C7D19843674F191CCEE4E22BC137FD28F94C99B57177FA8A4`,
contains 15,360 unique indexes and seeds, and was created before any source or
analysis file. The supervisor is now active. Its locked full-run manifest has
SHA-256
`8EBB797FF547162791E4CEF4A1C8D4CF5FBD8335D1A0586DE061D99ABC70C787`
and predates the first source file by 2.73 seconds. The first two live audits
observed 145 then 409 source games, zero analysis files, zero stderr, and all
six BelowNormal workers pinned to 0/2/4/6/8/10. This remains acquisition only,
not training.

Generation is now complete at 15,360/15,360 source files with zero stderr.
Global replay retained 15,335 unique trajectories (25 duplicates dropped),
then froze 13,802 development games and 1,533 sealed-test games containing
41,698 selected test positions. Development and sealed-test manifest SHA-256
values are
`C359269C7858D042BFE0B41EEA5D98CC6F03DBDBBADE7ACAC9B13D1E90FACDD2` and
`B1F2350607A95ACF3F04B5667236EE10B7D2ABCF0DE3EB7FA737E72D96338115`.
The commitment forbids reading test analysis files. Development-only teacher
analysis is active under the same six-worker supervisor; training remains
locked.

The first supervisor process exited on a Windows status-file replacement race
while a read-only monitor held the destination. The coordinator and six teacher
workers were unaffected and remained error-free. The status helper now retries
transient replacement denial for up to five seconds, with focused
status/supervisor/isolation tests passing 14/14; the full suite is deferred
until teacher workers are idle. A locked recovery addendum at SHA-256
`16CB8DD35BE65FA27E95F867FE718BD594EE2D0CF1B97DDC794CC33EFE876D48`
binds the unchanged acquisition artifacts and arms a process-handle watcher to
restart the unchanged supervisor after the current coordinator exits. This is
runtime supervision hardening only; no data pipeline, model, or playing code
changed. The one stale supervisor-status `.tmp` from the failed replacement was
verified as an obsolete volatile payload and removed; the temporary-artifact
gate is again zero while teacher workers remain live.

A development-only early checkpoint is now locked and reproducible. The audit
script `scratch/nnue_scaling_checkpoint_audit.py` has SHA-256
`4937829284EEEEAEDB2A701F34C121821CD1B95BFA2A6526941E20829A219A0D`
and its focused tests pass 2/2. It freezes the exact completed analysis-file
set on first use, validates accepted-teacher/budget/split/per-position
provenance, and never opens the sealed-test manifest or test analyses.
`build/nnue_scaling_full_v1/checkpoint_early_development.json` contains 71
games (64 train, 7 validation), 2,130 positions, and 1,419 eligible labels;
it reproduced byte-for-byte at SHA-256
`A1C657184EB63D68548DF1E14CCF0A82D4D346EBA4BE1ECD4C622DF41E797C64`.
All health gates pass, including zero stderr, temporary artifacts, incomplete-
search labels, and test-analysis reads. Because this is an early ordered
asynchronous prefix rather than a random/full-corpus sample, it is a pipeline-
health checkpoint only. It cannot select architecture, loss, weighting, or a
model checkpoint and does not authorize training.

An isolated fresh-state 1-second rebaseline was completed before pausing this
workflow. Five trials per backend on all three external regressions were
move/depth stable when each backend was cleared between trials. This rules out
a reproduced cross-game stale-state defect; it does not make the longer-search
labels solved truth. The two older horizon cases remain missed at one second,
so the data pilot continues to target broad evaluation/search gaps rather than
one external move. GUI exports now bind runtime-isolation and request/setup
timing so future games can be admitted or rejected as controlled evidence.

### 2026-08-28 safe live acquisition health audit (PROMOTED TOOLING)

After a second Windows reboot cleanly preserved 697 atomic analyses but stopped
all ephemeral watcher/supervisor processes, the locked supervisor was rehashed
and resumed without changing any acquisition input. The read-only monitor
`scratch/nnue_scaling_health_audit.py` has SHA-256
`A3B76458174DB59A9226E38A36EB990F32384614C729B2EF194DA6241A7DDEBE`;
its focused test file has SHA-256
`6D349E73E84D367DF7DAF97A4986BC3FE461465C40E2A56346418D8FFC343739`.
Focused tests pass 5/5.

The monitor validates the locked non-test bindings and inspects only filenames,
log sizes, temporary artifacts, disk space, and exact live Python entrypoint
tokens. A guard test fails if it opens an analysis payload, sealed-test
manifest, or volatile supervisor status file. It classifies duplicate/excess
pipeline processes, unexpected analyses, non-empty stderr, and `.tmp` artifacts
as unhealthy; a clean stopped state is explicitly marked safe for the locked
supervisor resume rather than confused with PASS.

The post-hardening real snapshot was `RUNNING_HEALTHY` at 734/13,802 analyses,
with shard counts 117/126/124/117/125/125, one supervisor, one coordinator,
six workers, zero unknown processes, zero stderr bytes, zero temporary files,
no extra analyses, and zero reads of payload/test/sealed/volatile files. The
observed 725 -> 729 -> 734 sequence proved resumed forward progress. This is
monitoring infrastructure only: it does not finalize data, authorize training,
or replace the full reproduction/coverage verifier.

A later external process loss terminated all six workers together at 1,734
completed analyses with exit `0x40010004` and zero worker stderr. The 705-byte
coordinator traceback was hashed at
`1FCD0ACEF58F11A8E29B5AF126580798DDD897B9599370D0F1541E22103F9EF1`
and preserved under `build/nnue_scaling_full_v1/incident_logs/` with the
1,734-artifact recovery record. All locked bindings still matched, with no
extra analyses or temporary files. Only the locked supervisor was relaunched
as a hidden detached Windows process. The post-recovery snapshot returned to
`RUNNING_HEALTHY` at 1,768 analyses with exact 1/1/6 process roles, six analysis
workers pinned to 0/2/4/6/8/10 at BelowNormal priority, zero new stderr/tmp, and
zero protected reads.

A third Windows reboot at 2026-08-28T09:08:56.5000000Z again removed the
non-persistent supervisor/process handles without damaging atomic data. The
recovery audit preserved 2,173/13,802 development analyses and all 15,360
source games, found zero stderr/tmp/extra artifacts and zero protected reads,
revalidated every accepted/bound hash, confirmed no GUI/server, and reported
`safe_to_resume_locked_supervisor=true`. Only the locked supervisor was
relaunched hidden/detached. The coordinator replayed six completed generation
shards before restoring six BelowNormal analysis workers pinned to logical CPUs
0/2/4/6/8/10. Forward progress to 2,177 analyses returned health to
`RUNNING_HEALTHY`; training remains unauthorized. The immutable incident record
is `build/nnue_scaling_full_v1/incident_logs/20260828_reboot_090856Z_resume.md`
(SHA-256 `5BDEC14A002CAEFB4BE5DBD2615429CF0C8B4811CA797685F6EA7813123D3DC0`).

### 2026-08-28 full-suite attestation runner (PROMOTED TOOLING)

The fail-closed runner `scratch/nnue_full_suite_attestation.py` has SHA-256
`4109D973F7200A3EC61ABC262F93CC3820D1B3F59B1EA2F34F8CDE21690AADB9`;
its focused test file has SHA-256
`B1C255946AE68822BDE10ECCF5F7C1782C478435A996884F42CCE0E9033DC653`.
Focused tests pass 11/11. At this earlier tooling checkpoint the complete
focused gate stack passed 41/41 in 4.232 seconds.

The v2 runner is gated on completed clean acquisition health, no live pipeline
process, no GUI event, and an exclusive lease over all 32 workload slots. It
checks GUI priority around every discovered test, rejects incomplete/failed
discovery, guards production analysis/sealed/status paths, verifies accepted
DLL and final-audit immutability, and binds exact before/after source and test
inventories plus runner/result hashes. It writes only after PASS and only
outside acquisition/source/test trees. The trainer authorizer independently
recomputes the current inventories, so stale or fabricated hashes fail closed.

This is tooling promotion only. The active acquisition correctly blocks the
real full suite, so no production attestation has been generated.

### 2026-08-28 trainer-contract authorization gate (PROMOTED TOOLING)

The fail-closed authorizer `scratch/nnue_trainer_contract_gate.py` has SHA-256
`FB99AE3DC546D4B3FC1B4E1CFDD6025439FA4C2A72787E43460FD968D4FBBA31`;
its focused test file has SHA-256
`B3B4977926F7CC8B2E6B5E66182179646E474033D47DC08F960C057E611F386D`.
Focused tests pass 10/10; at this earlier tooling checkpoint the complete
focused gate stack passed 41/41 in 4.232 seconds.

The authorizer requires byte-identical reproduction of both the final-data audit
and frozen trainer contract. It independently checks the development manifest,
requires disjoint train/validation inventories that reconstruct the audited
analysis-set hash, binds the v2 post-acquisition full-suite PASS and independently
recomputes its current source/test inventories, and requires a tiny-fixture
preflight proving overfit,
deterministic repeat/resume, checkpoint checksum, and sealed-test guards. It
does not open analysis payloads, the sealed-test manifest, or test analyses.

This is gate infrastructure only. The active partial acquisition cannot satisfy
it; there is no real frozen contract, trainer preflight, authorization artifact,
or trained model. Placeholder evidence is forbidden. Continue acquisition to
13,802 development analyses, pass finalization/reproduction/full-suite gates,
then make train-only calibration choices and exercise this gate.

### 2026-08-28 trainer-input inventory builder (PROMOTED TOOLING)

The deterministic builder `scratch/nnue_trainer_input_inventory.py` has SHA-256
`B33B7ACACB0F5C0F5374B27D7289A6061CF40C77F969F93552CB34E0B8330C5E`;
its focused test file has SHA-256
`1932F769B6AB7406E2E7CFA5E97FECA296424305F60072A06FBC51C673AFF211`.
Focused tests pass 9/9; at this earlier tooling checkpoint the complete focused
gate stack passed 41/41 in 4.232 seconds.

The builder is deliberately gated on the real final-audit PASS and coordinator
PASS. It maps each locked development game to the coordinator-verified analysis
hash, emits exact disjoint train/validation inventories in deterministic game-id
order, reconstructs the final audit's analysis-set SHA-256, preflights both
locked outputs, and refuses to write inside the acquisition directory. It opens
no analysis payload, sealed-test manifest, or test analysis.

This is Phase-1 tooling only. The inventory report explicitly leaves training
unauthorized, and no production inventory was created from the active partial
run. After acquisition completes, reproduce the final audit first, then build
the inventories outside the locked run directory and pass them to the separate
trainer-contract authorizer.

## Implementation and promotion sequence

1. **Readiness audit — complete.** Its old training-not-ready verdict was later
   superseded by completed acquisition gates.
2. **Label pilot — complete PASS.** Reproducible schema/pipeline evidence only.
3. **Corpus scaling and frozen test manifest — complete PASS.** Development and
   sealed partitions remain separated; test labels were later opened once only
   after model/contract freeze, as recorded in step 12.
4. **Trainer contract/preflight/authorization — complete PASS.** The real inputs
   and deterministic resume/checksum/sealed guards passed before training.
5. **Float trainer experiment — complete KEEP.** All 8 learning-curve runs
   completed and seed 20280002 won under the frozen validation rule.
6. **Quantized export/parity — complete KEEP.** A/B is byte-identical and all
   frozen parity/overflow/corruption gates pass.
7. **Native scalar refresh path — complete KEEP measurement only.** Real-model
   bit-exact parity passes, but full refresh is far too slow for search.
8. **Scalar incremental accumulator — complete KEEP measurement only.**
   Full-refresh, parent/child, undo, multi-capture, promotion, every clock
   boundary/reset, reload, and invalidation parity pass.
9. **AVX2 dense-evaluation path — complete KEEP measurement only.** Bit-exact
   parity, capability/fail-closed gates, and reproducible raw speedup pass.
10. **AVX2 accumulator delta updates — complete KEEP measurement only.** Exact
   parity, capability/fail-closed gates, and reproducible raw speedup pass.
11. **Search candidate — pre-game PASS, not promoted.** Separate opt-in DLL/model, the complete currently
   discovered correctness suite,
   perft/differential checks, raw-eval benchmark, fixed-depth/time diverse corpus,
   qsearch NPS/evals-per-second, critical `27-23`, and both external games.
12. **One-time sealed test — complete, not promoted.** Six shards passed all
   1,533 games / 41,698 selected positions; the immutable report SHA-256 is
   `BF5166F7BF2B5B5311C138321E5CF97AB8ECE8AC3DB3AF7E1F215A3E7AFD1077`.
   It contains 23,097 eligible rows and forbids model selection.
13. **Strength gates.** Gates A/B and Gate C 1000ms are complete PASS. Run or
   resume only the frozen 2000ms control according to its current run manifest,
   exact config/hash bindings and completed-pair checkpoint. Both independent
   Gate C controls must PASS before production smoke and reversible promotion.
   See current-state.md and DEVELOPMENT_PLAN_TH.md for current identities,
   statistics and failure routing; historical preparation text is not current.
14. **Production and further Elo work.** Follow the approved forward guide:
   verified GUI NNUE release/rollback -> thread-scaling/profile audit including
   physical-core 6T -> one measured optimization -> fresh-data/model iterations.
   More threads, offline loss and NPS are separate from playing-strength proof.

No offline loss, one tactical position, deeper reported depth, or single SPRT
alone promotes the network. Only reproducible general playing-strength evidence
against the byte-preserved accepted control does.

Before step 4 starts, freeze the separate machine-readable trainer contract
defined in `DEVELOPMENT_PLAN_TH.md`: target normalization, teacher/outcome/
exact-WDL loss mixture, source-game/position/phase weighting, optimizer and
seeds, deterministic resume, learning-curve sizes, checkpoint/early-stop rule,
and the one-time sealed-test opening policy. The final development-data audit
proves corpus readiness but deliberately does not authorize those choices.

## Success definition

The first NNUE phase succeeds only when a quantized, incremental native network:

- preserves every rules/proof/tablebase invariant;
- has exact Python/scalar/AVX2 and refresh/incremental parity;
- stays inside a measured CPU/RAM budget on the target laptop;
- improves diverse fixed-time decision quality, including but not limited to the
  external regressions; and
- earns a statistically supported paired playing-strength promotion.

This is a milestone toward Stockfish-like Thai Makhos strength, not evidence that
the complete long-term objective has already been achieved.
