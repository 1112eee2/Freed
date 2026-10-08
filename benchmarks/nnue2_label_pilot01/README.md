# NNUE2_LABEL_PILOT_01: is NNUE v1 a better teacher than HCE?

Status 2026-10-08: **declared, offline pilot.** No playing path, production
default, accepted DLL, model or rules file changes. Nothing here is promoted.

The owner approved NNUE V2 as a main track next to the practical no-loss
track on 2026-10-08 ("ได้", in reply to the question whether to start NNUE V2
with this pilot). The research behind it is `build/plans/nnue_v2_plan_draft.md`
(local, not tracked).

## Question

NNUE v1 (`07b9ab0f…` on DLL `32c32302…`) beats the accepted HCE that labelled
its training data by 80–94 Elo, and v1's learning curve still improves with
more data. If a cheap fixed-depth NNUE v1 search is at least as good a
training label as the HCE 2000 ms label, NNUE V2 can scale its data about 100
times more cheaply. This pilot tests only the **label source**. Positions,
feature ABI, network shape and quantization stay as in v1.

## Data

Only the v1 **development** games are read: the 13,802 analyses in
`build/nnue_scaling_full_v1/analyses/`, split by the v1 manifest into train
and validation. The v1 sealed test (`build/nnue_sealed_test_v1/`) is never
read. Rows are v1's eligible rows: 199,923 train and 23,550 validation, each
with the HCE 2000 ms teacher score, the game outcome when the game was not
truncated, and exact WDL where v1 recorded it. `extract_rows.py` writes them
to `build/nnue2_pilot01/v1_rows.jsonl.gz`.

All new labels come from one search per position on a cleared context, one
thread, hash power 20, project rules, and a single-entry history.

## Part 1: depth choice (validation positions only)

A fixed sample of 4,002 validation rows, 1,334 from each of the three
phase bands (13–16, 9–12, 5–8 pieces) by a seeded draw over sorted sample
IDs (seed 20261014), is labelled with:

- NNUE v1 at fixed depth 8, 10, 12 and 14;
- the reference R1: NNUE v1 for 8,000 ms.

Scores map to `tanh(clip(cp, ±2000) / 600)`, the v1 target scale; mate
scores clip to ±2000.

**Rule, declared before any label is computed:** the chosen depth `d*` is the
smallest of 8, 10, 12, 14 whose mean absolute error to R1 is at most the HCE
2000 ms label's in every phase band and in both the king and no-king strata.
If no depth qualifies, the pilot reports that and `d*` is 14.

R1 is an NNUE search, so this comparison favours NNUE labels. Part 1 only
chooses the depth. Part 2 decides whether NNUE labels are better. Agreement
with game outcome and exact WDL is reported for every label but decides
nothing.

## Part 2: retrain and play (the decision)

Every v1 train and validation row is relabelled with NNUE v1 at `d*`. Two
arms are trained with `train_pilot.py` and an identical frozen configuration:

- **arm H:** the HCE 2000 ms label;
- **arm N:** the NNUE `d*` label.

Everything else is shared: rows, features, the v1 shape
(137 → 2×128 → 32 → 1), seeds 20261015 and 20261016, the loss mix, the
weighting and a fixed epoch count with no early stopping, so neither arm's
checkpoint is chosen by its own label. The configuration is
[`train_config.json`](train_config.json).

The first seed of each arm is quantized with the unchanged v1 exporter and
paired against the other:

- arm N against arm H, same search DLL code, 1 thread, no tablebases,
  2s+0.02s, 6 random opening plies, seed 20261017, two parallel games;
- pentanomial SPRT, H0 = 0, H1 = +5 Elo, capped at 2,000 pairs.

Decision:

- **PASS:** NNUE fixed-depth labels are the V2 label source; V2 scales data
  with them.
- **FAIL:** keep HCE-quality labels; V2 tries deeper or mixed labels before
  any scaling.
- **cap:** INCONCLUSIVE; report Elo and interval; prefer the cheaper source
  only with owner agreement.

No rerun with a new seed to chase a PASS. Nothing in this pilot opens a sealed
test, so its models are development models and cannot be promoted.

## Part 1 result (2026-10-09): `d*` = 10

[`part1_report.json`](part1_report.json). MAE to the 8,000 ms reference
(mean depth 22.7), in tanh(cp/600) units:

| Stratum | Rows | HCE 2000 ms | NNUE d8 | d10 | d12 | d14 |
|---|---:|---:|---:|---:|---:|---:|
| 13–16 | 1,334 | 0.1459 | 0.1114 | 0.0969 | 0.0835 | 0.0702 |
| 9–12 | 1,334 | 0.1463 | 0.1488 | 0.1304 | 0.1164 | 0.0978 |
| 5–8 | 1,334 | 0.1427 | 0.1436 | 0.1256 | 0.1079 | 0.0900 |
| kings | 1,161 | 0.1399 | 0.1354 | 0.1173 | 0.0985 | 0.0793 |
| no kings | 2,841 | 0.1470 | 0.1343 | 0.1178 | 0.1043 | 0.0888 |

Depths 10, 12 and 14 qualify, so the declared rule picks **d10**, which costs
12.3 ms per position against about 2.6 s of HCE search per eligible v1 label.
On the independent check, exact WDL (571 rows, 5–6 pieces), d10's MAE is
0.372 against HCE's 0.373 (d12 0.356, d14 0.340); game-outcome MAE is
0.670–0.672 for every label.

The labels and the 4,002-row sample were computed with DLL `32c32302…` and
model `07b9ab0f…`; part 1 took 150 s for the depths and 8,018 s for the
reference on 4 Idle-priority workers. Stderr was empty.
