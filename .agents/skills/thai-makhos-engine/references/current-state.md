# Current ThaiMakhosEngine state

Updated 2026-10-14. This file owns the current scope and the next action. It is
kept short on purpose: historical commands and counters are evidence, not launch
instructions, and detail that is no longer current lives in the snapshots below.

- Full text before the 2026-10-13 update:
  [history/20261013-current-state-before-director-loop-update.md](history/20261013-current-state-before-director-loop-update.md)
  (this includes the long 2026-09-25 narrative, the PR #28/#31/#32 notes and the
  per-candidate detail that is condensed here).
- Earlier snapshots: [history/20260925-current-state-before-no-loss-track.md](history/20260925-current-state-before-no-loss-track.md).
- The director-loop section below was first committed in `748ac0c` on branch
  `docs/current-state-director-loop-20261013`.

## Director-loop status (2026-10-14)

Updated 2026-10-14 00:05 local time from `w1_live_status.ps1 -Once` and the
`sprt.json` of NULL_EVAL_01. Earlier text was written from the process inventory,
the `build/runs/` trees and local git refs on 2026-10-13. For strength work it supersedes the 2026-09-25 text. The
BASELINE_HORIZON_01 gate named there was not re-checked in this session.

**Scope.** NNUE V2 became a main track beside the no-loss track on 2026-10-08
(owner approval, recorded in the handoff). Search candidates run one concept at
a time through four stages:

1. **Screen:** 1T, 2s+0.02s, no tablebases, H0=0/H1=+5, cap 2,000 pairs,
   control = strict TT key (`8b82fef8…`).
2. **W1:** 1T, 10s+0.1s, TB4–6 plus the C4 endgame library, H0=0/H1=+2,
   cap 4,000 pairs.
3. **W2:** 12T/512 MiB, fixed 1 s, 1,000 pairs. It needs the owner's go-ahead
   and an idle machine; the owner asked for it to run at night.
4. **Integrated candidate and full suite.** Gains from separate candidates are
   not assumed to add.

Nothing below is promoted. Production, the accepted DLL, `RULESET.json` and
`makhos/core.py` are unchanged. Screen intervals are wide and screen results
are not promotion evidence.

| Candidate (branch) | Result so far | Now |
|---|---|---|
| STRICT_KEY_02 | Linux screen PASS, +15.9 ± 9.3 Elo. **W1 INCONCLUSIVE at the 4,000-pair cap** (2026-10-14 ~11:40 local): 8,000 games, W 2,606 / D 2,989 / L 2,405, pentanomial 195/783/1891/888/243, LLR +2.40 (bound +2.94), +8.7 ± 5.0 Elo; `complete: true`, stderr empty, result SHA-256 `e1e9c5af…bae23`. Per the decision rules: no W2, no rerun on a new seed. | Run history: stopped at 1,909 pairs (+9.5 ± 7.3, LLR +1.21), cause not recorded; **W1 resumed** 2026-10-13T07:05Z, pid 25052, seed 20261004. Stopped again at 3,962/4,000 pairs (+8.6 ± 5.0 Elo, LLR +2.35) at the same moment as LMR_LOG_01; **resumed** 2026-10-14 ~10:53 local, pid 19116, logs `build/strict02/resume-20261014/`. Finished at the cap. Pre-resume checkpoint SHA-256 `F0D3DCD8…7FFE`, kept as `build/strict02/sprt-w1-1t-10s.pre-resume-20261013.json`. Output `build/strict02/sprt-w1-1t-10s.json`, logs `build/strict02/resume-20261013/` |
| LMR_LOG_01 (`lmr-log-01`, PR #35 per the handoff) | Screen PASS, 967 pairs, +21.4 ± 11.1 Elo (screen seed 20261006). **W1 PASS** 2026-10-14 12:20 local at 2,284 pairs (4,568 games, W 1,524 / D 1,753 / L 1,291, pentanomial 99/424/1045/577/139), LLR +2.95, +17.7 ± 6.6 Elo; `complete: true`, stderr empty, result SHA-256 `60333f36…bcac3` | Interrupted once at 2,054 pairs (2026-10-14 ~02:39 local, app update) and resumed with `--resume` (pid 25220). Result `build/runs/lmr_w1/build/lmr01/sprt-w1-20261013/sprt.json`. **W2 not started**: it needs an idle machine and the owner's go-ahead |
| NULL_EVAL_01 (`null-eval-01`, pushed to origin 2026-10-14, based on an older `main`) | Screen PASS, 486 pairs, +42.0 ± 15.8 Elo, LLR +2.95 (seed 20261009) | **W1 PASS** at 824 pairs (1,648 games, W 634 / D 608 / L 406, Ptnml 18/115/388/227/76), LLR +2.94, +48.4 ± 10.8 Elo, `complete: true`, process exited, stderr empty. Result in `build/runs/nullev_w1/build/nullev01/sprt-w1-20261013/sprt.json`. **W2 not started**: it needs an idle machine and the owner's go-ahead |
| HISTORY_MALUS_01 (`history-malus-01`) | Screen PASS, 1,021 pairs, +20.1 ± 10.6 Elo, LLR +2.95 (seed 20261013); QA tests 5/5 and reproducible build per the handoff | W1 not started |
| ITER_PARTIAL_01 (`iter-partial-01`) | **INCONCLUSIVE** at the 2,000-pair cap: +5.5 ± 7.1 Elo, LLR +1.14 (seed 20261012). Raw result in `build/runs/iterpartial_l1w`; only the declaration is committed on its branch | Do not rerun with a new seed; a changed rule is a new hypothesis |
| NNUE2_LABEL_PILOT_01 (`nnue2-label-pilot-01`) | Part 1: NNUE depth-10 labels cost about 12 ms against about 2.6 s per position; 223,473 rows relabelled, no sealed test. Part 2: the NNUE-label model beat the HCE-label model, PASS at 1,563 pairs, +14.2 ± 8.7 Elo, LLR +2.96 (seed 20261017; arms `B956045E…` vs `EE2B86F8…`). One seed per arm, screen settings | Next: freeze the stage-2 data contract. No compute while W1 runs |

**Decision rules.** W1 PASS → W2. FAIL → REJECT as declared. Cap → INCONCLUSIVE,
with no rerun on a new seed. LMR_LOG_01 and NULL_EVAL_01 are both measured on
top of the strict key, so if STRICT_KEY_02 fails W1 or W2 their results are
conditional on it. STRICT_KEY_02 W1 ended INCONCLUSIVE (not a FAIL), so the strict
key is neither promoted nor rejected; any later promotion of LMR_LOG_01 or
NULL_EVAL_01 must either bring the strict key with it as part of an integrated
candidate that passes its own gates, or be re-measured on the production key.

**Identities bound to the W1 runs.** Control `8b82fef8…`; LMR candidate
`7cef50eb…`; NULL candidate `e4d7b0d3…`; NNUE v1 model `07b9ab0f…`; C4 endgame
library `eb8af045…`; TB4/5/6 header FNV `89459baa…`, `c9e825ce…`, `7102f551…`.
The two new run trees are copies of the screen trees. They lack `build/tb*` and
`build/native_endgame_c4`, so their commands pass `--ranked-tablebase` with
absolute paths and `--native-endgame-library`. Without those options `sprt`
silently skips absent default tablebase files and fails later on the missing
endgame library. The first launch attempt failed at startup for that reason, with
no game played. Its logs are kept as `sprt-w1-20261013-attempt1-failed-no-endgame-lib`.

**Monitoring.** `build/runs/_status/w1_live_status.ps1` is read-only. It reads
only `stdout.log` and process identity (PID plus creation time), never a running
match's `sprt.json`. `sprt` prints only when a pair finishes, so the "now playing"
line is inferred.

**Open items.**

- The BASELINE_HORIZON_01 gate, which an older owner review set before any W1/W2
  start, is not verified. The owner told this session on 2026-10-13 to start W1
  and to resume STRICT_KEY_02 W1.
- Untracked in the main checkout: `scratch/profile_smp_scaling.py`, which no
  file references and which is the only copy. `.claude/` is now in `.gitignore`.
  The nested checkout `ThaiMakhosEngine/` was removed on 2026-10-13 after it was
  verified clean and at `origin/main`.
- No relay or automated play against Invincible 2 (2026-09-25 decision), so the
  external baseline can only be gathered by hand.
- The review of game `6ef62f9998d12db4` was only read from the existing log: at
  ply 10 the played move scored -119 against -59 for the best move at 5 s, and at
  ply 12 -291 against -172 at 10 s. It is not concluded and no cause is assigned.

## Self-play baseline, safety mode and stage-2 data (2026-10-14)

Owner goal for the short term: the production engine should draw (not lose to)
itself in as many openings as possible. These items serve that goal. None changes
production, the accepted DLL, `RULESET.json` or `makhos/core.py`. Training-related
branches stay local, per the owner.

- **SELFPLAY_BASELINE_01 part A: COMPLETE (2026-10-14 23:17 local).** Branch
  `selfplay-baseline-01` (local; contract
  `benchmarks/selfplay_baseline01/contract_part_a.json`, declared before the first
  game). Production NNUE v1 against itself, 1T, 10s+0.1s, TB4–6 and the C4 library,
  all 1,225 distinct positions after 4 plies, 2 games each (part1 613 openings, part2
  612). It is a measurement: no pass/fail, no rerun for a better number. Run tree
  `build/runs/selfplay_baseline01/`, report
  `report/part_a_report.json` (made with `tools/arena/selfplay_report.py
  --opening-plies 4`). stderr empty; all 2,450 game records replay legally.
  **Result:** draws 1,028 of 2,450 = **42.0% (95% CI 40.0–43.9%)**; black won 749,
  red won 673. Ended by no legal move 1,422, repetition 1,027, no progress 1. Per
  opening: 231 both games drawn (18.9%), 692 the two games differ (56.5%), 302 the
  same colour won both (24.7%: black 170, red 132). Decisive games: median 81 plies;
  the loser's score first dropped by 150 cp at a median of ply 25 (quartiles 21/25/30;
  336 by ply 20, 953 at 21–40, 133 later). Reading: at this time control the
  engine is far from a 100% draw rate against itself; many losses start in the
  opening and early middlegame, and 57% of openings give different results to two
  games of the same engine (search nondeterminism). The 302 same-colour openings are
  the first candidates for the loss-finding loop. Parts B (time-control curve) and C
  (12T) are not declared yet.
- **Part A loss analysis (2026-10-15, read-only on the game records; no engine search
  ran beside the W2).** Files in `build/runs/selfplay_baseline01/report/`
  (`loss_positions_v2.json`, `same_colour_sudden_drops.json`, `analysis_scripts/`).
  - *Moves get about 0.3 s each.* The 10s+0.1s clock gives a median 312 ms per move
    (median depth 14), so part A measures blitz-speed play, not 10 s a move.
  - *The first move matters.* Over all openings black won 42% of games after 25-22
    and red 21%; after 27-24, 26-22 and 25-21 red won more (35%, 33%, 31% against
    26%, 23%, 24%). Draws are 35–45% for every first move. The 2-ply prefixes with
    the most draws (60–67%) have only 12–30 games each and are not conclusions.
  - *The loser usually sees it late.* Of 1,422 decisive games, 781 have a sudden
    collapse (the loser's own score falls by at least 100 cp to -150 or worse in
    one search) and 641 a gradual one. The collapse follows a move played at ply
    20–29 in 52% of cases and ply 10–29 in 76%; the previous search had a median
    score near 0 and median depth 19. In 80% of collapses the reply is a quiet
    move, not a capture. Moves from the back row (red squares 1–4, black 29–32)
    are about 25% more frequent among collapse moves than among the same side's
    other moves at plies 9–31 (weak evidence).
  - **Defect found: 159 engine moves (0.08%) in 138 of 2,450 games were played by
    the Python fallback at depth 0** (first legal move, no search). Cause,
    reproduced on the part A positions: the native PV is read back from the
    transposition table and can end in a stale move (seen as a king move carrying
    `promotes=True`), and `Engine._native_result` threw the whole native result
    away on one illegal PV move. A side that played such a move lost 96 of 148
    games (65%) against 29% overall; these moves precede 44 of the 781 collapses.
    It explains a small share of the losses (about 50 of 1,422), not the main
    cause. Fix `fix-native-pv-truncate` (`dc74f5b`, Python only), **merged into local
    `main` on 2026-10-15 with the owner's approval, not pushed**:
    compare moves by path and captures, keep the legal PV prefix, count
    truncations. With it, 120 reruns of the failing positions (real DLL, 1T) fell
    back 0 times; before, 3 of 60 did. 4 new tests. Not SPRT-tested: the effect is
    too small for an SPRT. It changes the production `Engine`. The 12T `ParallelNativeSearch`
    path validates its PV through the same function; no fallback appeared in the 3
    real saved games, which is not proof. The same strict check exists in
    `_native_endgame_result` and was not changed.
- **Paused 19:48 and resumed 21:06 local (2026-10-14, owner request).** Part A and
  the W2 watcher were stopped at part1 274 / part2 277 pairs (clean checkpoints,
  equal to the `games` directories) and resumed with `--resume` through
  `build/runs/selfplay_baseline01/relaunch_resume_paused.py` (detached, BelowNormal;
  pids 32584 and 32636; earlier logs kept as `*.paused-20261014.*`). The W2
  watcher was restarted (pid 23852).
- **NULL_EVAL_01 W2 is INTERRUPTED at 145 of 1,000 pairs** (started by the watcher
  2026-10-14 23:17 local, pid 33244, 12T/512 MiB, fixed 1 s, owner-approved; run dir
  `build/runs/nullev_w1/build/nullev01/sprt-w2-20261014`). Last checkpoint 2026-10-15
  03:57:47: W 126 / D 83 / L 81, Ptnml 8/17/62/38/20, LLR +0.43 (bound +2.94),
  +54.4 ± 29.8 Elo, INCONCLUSIVE, `complete: false`, stderr empty. The Windows event
  log shows the machine restarted for Windows Update at 03:59 (MoUsoCoreWorker) and
  04:02 (TrustedInstaller) and shut down at 08:12, back up at 14:33; the process did
  not survive. **Resumed 2026-10-15 14:37 local (owner request)** with `--resume`,
  detached, BelowNormal, pid 23048, through
  `build/runs/nullev_w1/relaunch_w2_resume.py`; the run tree carries its own copy of
  `makhos/`, so the later `main` fixes do not affect it. Checkpoint before the resume
  kept as `sprt.pre-resume-20261015.json`; earlier logs as `*.interrupted-20261015.*`.
  The first resumed pair was 146 (LLR +0.43). Do not run other heavy work beside it.
  LMR_LOG_01 W2 is not queued yet.
- **NNUE V2 stage-2 data contract** is **frozen** (owner, 2026-10-14):
  `benchmarks/nnue2_stage2/data_contract_v1.json`, branch
  `nnue2-stage2-data-contract` (local). v1 development games are excluded.
  Generator and row extractor are in `tools/nnue2/` with tests. **B1 done
  2026-10-15** (branch commits `5747714`, `96979e3`): the extractor fills
  `exact_wdl` from TB4-6 (side to move; a sign check on 400 random TB4 positions
  agreed with their children), and `tools/nnue2/regen_check.py` is the determinism
  gate. A 100-game dry run at the contract settings
  (`build/runs/nnue2_b1_dryrun/`) passed coverage, leakage and 15/15 byte-identical
  regenerations, at about 250k labels per worker-hour. **Blocking finding:** games
  average 56 plies (about 30 train rows per train game), so the contract's
  100,000-seed range gives about 2.4M train rows, not 10M; about 430,000 games are
  needed. Rows with 2-3 pieces get no exact WDL (TB4-6 do not cover them).
  **Contract v2 approved 2026-10-15** (owner chose to widen the seeds):
  `benchmarks/nnue2_stage2/data_contract_v2.json` on the branch, seeds
  2026200000-2026999999, everything else as v1; v1 kept as the record. B2
  (acquisition, about 11 hours on 5 workers) is ready but never runs beside a gate.
- **Safety-first move choice** (branch `safety-mode-01`, local, `ddbb79d`): opt-in
  and default-off. After the normal search it re-checks the root moves within a
  margin of the best score (default 40 cp, up to 3, +2 plies, 10 cp to switch,
  30% of the move time) with a deeper child search and prefers the best worst case.
  It never overrides a mate-band score and never picks an unverified move. Code in
  `makhos/safety_mode.py` and the `Engine(safety_policy=...)` hook; candidate-only
  `sprt` flags `--candidate-safety-mode`, `--safety-*` (needs a byte-identical DLL
  copy for the candidate). 14 new unit tests pass. **Not strength-tested**: a
  screen (+5, 1T, 2s) is queued behind part A and the W2 gates.
- **Opening book** (branch `opening-book-01`, draft only, local): entries would be
  labelled "deep-search verified at depth/time", never "proven"; parameters wait for
  part A. The branch holds a plan only.
- `selfplay-baseline-01`'s `sprt` changes (`--openings-file`, `--play-all-pairs`)
  and the report tool are not yet in `main`.

## Tech-debt changes (2026-10-13, merged into `main`)

Each change was a branch off main `664e981`. They are merged into `main` with `--no-ff` and the branches are deleted. Focused tests only, with no full suite while the W1 matches run. None touches `RULESET.json`, `makhos/core.py`
or the accepted DLL.

| Former branch | Change |
|---|---|
| `tech-debt/sprt-fail-closed-tablebase` | `sprt` raises when a default `build/tb{4,5,6}_np80.compact.bin` is absent (it used to skip silently) |
| `tech-debt/hermetic-build-tests` | tracks the pinned `quantization_contract_v2.json` so orchestrator tests pass in a fresh checkout |
| `tech-debt/sprt-game-record-schema` | `schemas/thai-makhos-match-game-v1.schema.json` for `--games-dir` records, validated in tests |
| `tech-debt/sprt-gate-launcher` | `tools/arena/launch_sprt_gate.py`: hash/argument preflight, live-owner check, `launch.txt` with PID and creation time |
| `tech-debt/immutable-artifact-manifest` | `config/immutable_artifacts.json` and `tools/verification/verify_immutable_artifacts.py` |
| `tech-debt/native-flag-registry` | generated `docs/architecture/NATIVE_COMPILE_FLAGS.md` and a drift test |

Backups (untracked, `build/backups/`): a git bundle of the local-only branches
and a checksummed copy of the small critical artifacts. Known remaining debt:
`tests/test_sprt.py::test_command_sprt_attaches_c4_endgame_to_factories` needs
the untracked `build/nnue_sprt_6t_vs_12t/makhos_native_6t.dll`.

**Why the matches stopped (2026-10-14).** Both processes stopped between 02:39:28 and 02:39:54 local, with empty stderr and fresh checkpoints. Windows logged the Claude desktop app package servicing (AppX deployment, `CoworkVMService` restart) at 02:39:59–02:40:01, so the app update most likely killed the child processes. This is an inference; no process exit record was found. The earlier unexplained STRICT_KEY_02 stop at 1,909 pairs may have the same cause. Long matches should therefore be started detached from the app, or the app's auto-update should be avoided while they run.

## Next action

0. **Approved 2026-10-15 (owner: Q1–Q4 as recommended; no separate W2 for LMR_LOG_01
   and HISTORY_MALUS_01, control = production, no SMP unless DP3, near-continuous
   BelowNormal batch work):**
   [STRENGTH_PHASE_01 plan](../../../../docs/architecture/STRENGTH_PHASE_01_PLAN_TH.md),
   a target of at least +50 Elo against production (RC-2 = integrated search
   candidate + the better NNUE), with pre-declared gates G1–G7. It now owns the
   sequencing; the steps below are its first items.
1. **A1 done: NULL_EVAL_01 W2 PASS** (2026-10-16 15:53 local) at 874 pairs:
   W 725 / D 575 / L 448, Ptnml 33/111/378/250/102, LLR +2.95, **+55.5 ± 11.4 Elo**
   (null-eval guard on top of the strict key, 12T/512 MiB, fixed 1 s, TB4-6 + C4).
   Evidence on branch `null-eval-01` (`56315b4`,
   `benchmarks/null_eval01/sprt_w2_20261014/`). Interrupted twice and resumed with
   `--resume` (Windows Update at 145 pairs, owner pause at 307); stderr empty. The
   pop-up watcher died around 14:15 without a pop-up (no reboot since 2026-10-15
   14:33; probably ended with the Claude app), so a watcher started as a child of the
   app is not reliable. The machine is free of gates now.
2. **A3 (built 2026-10-15):** local branch `search-int-01` (worktree
   `.claude/worktrees/search-int-01`, merge `fd1daf6`) = `main` + `null-eval-01` +
   `lmr-log-01` + `history-malus-01`. The build orchestrator now takes
   `-NullEvalGuard -LogLmr -HistoryMalus` together. SEARCH_INT_01 DLL (strict key +
   null-eval guard + log LMR + history gravity/malus), two byte-identical builds,
   SHA-256 `5ed1fe18…eac9`, copied with its manifest to
   `build/search_int01/candidate/`. 33 focused tests pass (null-eval, LMR, history
   malus, build orchestrator, PV validation). The diff changes search only, not move
   generation or state; perft 10, the differential and the full suite still run once
   W2 ends, before A4.
3. **A3 checks done 2026-10-16** (branch `search-int-01`, now `fc30ace`): a native exe
   with the same five -D flags gave perft 1-10 ending at `861842812`; `verify-native`
   seed 20261016 passed 1,004 positions / 5,917 moves / 10 exact 3-piece cases; full
   suite 556 passed, 103 skipped, 7 failed, of which 6 need untracked `build/` files
   absent from the worktree (they pass in the main checkout) and 1 was a stale
   `NATIVE_COMPILE_FLAGS.md`, regenerated in `fc30ace`.
   **A2 running:** HISTORY_MALUS_01 W1 started 2026-10-16 17:59 local (pid 30116,
   BelowNormal, detached via WMI, `build/runs/histmalus_l1w/launch_w1.py`, run dir
   `build/histmalus01/sprt-w1-20261016`, seed 20261016, same settings as NULL_EVAL_01
   W1). Completion pop-up: Windows scheduled task `ThaiMakhos run watcher`
   (`build/runs/run_watcher.py RUN_DIR NAME`, at-logon trigger, writes
   `watcher_notified.txt` after its one pop-up); re-point it at each new run.
   Then A4 (SEARCH_INT_01 vs production, W1 H1 +5, then W2); B2 and the C1 labels
   need gate-free gaps. The owner declined shortcuts (2026-10-16): one RC-2 with
   everything that passes.
4. Not queued: STRICT_KEY_01's gates are withdrawn; TBDRAW_01 needs a
   scope-specific instruction; RFP_01 ended INCONCLUSIVE (see below).

## Standing scope: practical no-loss track against Invincible 2

On 2026-09-25 the user approved the
[practical no-loss track](../../../../docs/architecture/PRACTICAL_NO_LOSS_TRACK.md)
as the active strength scope. The goal is zero losses against Invincible 2 in a
large, frozen, colour-balanced match, reported with a 95% upper bound on the loss
rate and never as "proven perfect". It excludes proof/DFPN work, tablebases of 7
or more pieces, and any Lazy SMP redesign. The track is in Phase 0; no production
default, rules file, model or accepted artifact has changed under it.

Decisions of 2026-09-25 (still in force unless the owner changes them):

- The owner confirmed the F1 form: extract only what the track needs from PR #25
  and keep the Lazy SMP PRs open.
- A game that reaches a `project` draw that Invincible 2 does not declare is
  reported non-comparable. There is no external rules profile and `RULESET.json`
  is unchanged.
- No relay or automated play against Invincible 2, and no permission request for
  now.
- If PR #29 merges, the frozen NNUE-v1 tools stay blocked rather than re-bound.
  Promotion gates then compare plain `unittest discover` failure IDs with `main`'s.

Findings of the 2026-09-25 review, checked against source on that date and not
re-verified since:

- The root safety policy in `search.py` (`_choose`/`_safety_rank`) runs only on the
  native-endgame route and on the Python paths. The production 12T middlegame uses
  `ParallelNativeSearch._choose`: the highest score wins, with no WDL bound or mode.
  PR #31 (F2) centralized the root choice without a policy change, so a safety-first
  policy (Phase 2) is still to be designed.
- The F3 schema work is partly done: PR #30 aligned `thai-makhos-game-v1` with the
  GUI's records. `sprt --games-dir` records still fail that schema (the top-level
  `match` key, the per-move engine `role`, missing engine fields). They are
  replay-validated only and not gate evidence until the recorder is aligned.
- Invincible 2 reportedly has a database of 10 or fewer pieces and a 300M-position
  book. The page confirms none of this. Its script declares threefold repetition a
  draw only at 10 or fewer pieces, has no no-progress limit and declares one king
  each a draw, so our TB4–TB6 draws, which assume the 80-ply limit, are not
  guaranteed draws against that service (track §3.5).
- The staged review of game `6ef62f9998d12db4` needs Windows, an idle GUI, the game
  DLL `32c32302…`, NNUE v1 `07b9ab0f…` and the gitignored saved game. The frozen
  matrix is `BASELINE_HORIZON_01` in
  [PR #27](https://github.com/1112eee2/ThaiMakhosEngine/pull/27).

## Default-off candidates (before the director loop)

| Candidate | State |
|---|---|
| STRICT_KEY_01 | **REJECT_AS_DECLARED / NOT_PROMOTED.** The depth-20 screen met its declared falsifier, a repeatable fixed-depth slowdown (1.147× and 1.037× total time). It remains correctness evidence: the legacy key made 20.3% and 4.3% of TT cutoffs false, strict none. Linux match stopped at 344 pairs, +19.7 ± 17.8 Elo, INCONCLUSIVE; do not resume. Windows gates withdrawn. ([README](../../../../benchmarks/strict_tt_key/README.md)) |
| STRICT_KEY_02 | The same flag under a paired-play hypothesis. Linux screen PASS 2026-09-26: strict `73aef947` against control `4178a8f7`, 1T, no tablebases, 2s+0.02s, seed 20261003, H0=0/H1=+5, stopped at 1,281 pairs (945/789/828), pentanomial 83/199/623/270/106, LLR +2.96, +15.9 ± 9.3 Elo. W1 status is in the director-loop table. ([README](../../../../benchmarks/strict_tt_key/README.md)) |
| TBDRAW_01 | Main search returns 0 at non-root nodes on an exact tablebase DRAW. INCONCLUSIVE / NOT_PROMOTED; on `main` since PR #28, default-off, 8 tests, default build byte-identical, no paired result. ([README](../../../../benchmarks/tb_frontier/README.md)) |
| RFP_01 | Reverse futility at guarded shallow null-window nodes with 11 or more pieces, margin 48. **RFP_01-L1: INCONCLUSIVE / NOT_PROMOTED** at the 2,000-pair cap: 1,414/1,219/1,367, pentanomial 163/393/849/424/171, LLR +0.49, +4.1 ± 7.9 Elo. No rerun with a new seed. ([README](../../../../benchmarks/rfp01/README.md)) |

Tooling on `main` since PR #28, each default-off: `sprt --games-dir`
(replay-validated only), `bench-native --candidate/--baseline-nnue-model` and
`analyze-game --nnue-model`.

## Repository and PR state

- `origin/main` is at `f67f9a9` (2026-10-13), which holds the six tech-debt merges and the
  docs state. Before that it was `664e981`. Since `a0f7964` (PR #17) these merged:
  #28 (no-loss track docs, match tooling, STRICT_KEY_01 evidence, TBDRAW_01),
  #30 (game schema), #31 (root-choice refactor, no policy change), #32 (RFP_01),
  #33 and #34 (the STRICT_KEY_02 declaration and its Linux screen evidence).
  Production 12T/C4 defaults, the model and the accepted DLL are unchanged.
- Open and unmerged as of 2026-09-25 (not re-listed since; this machine has no
  `gh`): #18–#20, #22, #24 and #26 (the Lazy SMP G2 evidence stack), #25 (the Lazy
  SMP candidate, marked `REJECT_FOR_PERFORMANCE / NOT_PROMOTED` by #26), #21 (the
  self-drive loop), #27 (the strength-loop handoff) and #29 (a draft Linux lease
  fix). None of them changes production. The Lazy SMP design document is a
  reviewed proposal, not a backend.
- Local branches with work not in `main` were pushed to origin on 2026-10-14
  (`null-eval-01`, `history-malus-01`, `iter-partial-01`, `nnue2-label-pilot-01`,
  `local/strict-key-acceptance-a0f7964`, `r4liveness`, `selfdrive`, and the docs branch).
  `lmr-log-01` and `pr29-lease` were fast-forwarded onto their existing remote branches.
  No force push was used.
- The tech-debt roadmap (Phases 0–3, PRs #7–#16) is complete; see
  [the roadmap](../../../../docs/architecture/TECH_DEBT_ROADMAP_TH.md).

## Latest accepted correctness change

[PR #6](https://github.com/1112eee2/ThaiMakhosEngine/pull/6) merged as
`e975d6843ee23e9fe42a3662f5d802516293796e`: native C4 admission now covers legal
multi-captures from more than 6 pieces into 6 or fewer. It was merged under a
correctness-only exception limited to that PR, so no Elo improvement is
established. See its [transition record](../../../../docs/architecture/ENDGAME_TRANSITION_COVERAGE_TH.md).

## Production and stopped experiments

- The GUI profile is NNUE v1 with the C4 native endgame enabled and 12T/512 MiB
  defaults. Runtime provenance, not a merge, is authoritative for the process
  actually serving the GUI.
- The pointer is `config/gui_release.json`, with release manifest
  `releases/nnue-v1-20260908/manifest.json`. Roll back with
  `--no-native-endgame` or `--release-profile hce`. Keep the manual resource
  controls.
- Experiment A (C4, 1000 ms): the user stopped it at 539 pairs; it remains
  INCONCLUSIVE with LLR -0.3364. Keep 12T. The 2000 ms run is deferred, and
  neither checkpoint may be resumed from old launch prose.

| Immutable artifact | SHA-256 |
|---|---|
| `RULESET.json` | `77528addc0e08b17217346c511c7c4084bad4af48789955c3ec85ef76a64871f` |
| `makhos/core.py` | `03152e513bd360e6c2c97ecdf08dc58a290dca0ae6e28889ae70585a381292ab` |
| `build/makhos_native_accepted.dll` | `feedd39cf16e5f5abc236452be897abe1ecf26b8ba7adcda4a25022b868c3ddd` |
| NNUE v1 `model_a.mknnue` | `07b9ab0f83e253cb74b2acd2bd5291f5f91eb086e042790f33ea0a8c0914164c` |
| Historical 27-pair checkpoint | `09cffee749b485c1a742f921d89a173c86defbd5f15bc1a7f1f2a1b84b3de06f` |
| C4 539-pair checkpoint | `66d67efc5ec10ab60f19ff1ef24789ec212c69de8e6d2d7f8400846471cb0c9c` |

## Evidence routing

- [Practical no-loss track](../../../../docs/architecture/PRACTICAL_NO_LOSS_TRACK.md):
  the active plan.
- [Development plan](../../../../DEVELOPMENT_PLAN_TH.md): history and sequencing.
- [NNUE roadmap](../../../../NNUE_ROADMAP.md): data and model contracts.
- [Evidence ledger](experiment-evidence-ledger.md): search a mechanism here
  before retrying it.
- Previous current-state snapshots are listed at the top of this file. Do not
  execute their old next-action instructions.
- Rejected Root-PVS/SMP, large DFPN and tablebase expansion remain deferred.
