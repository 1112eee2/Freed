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
  part A. The branch holds a plan only. **Owner 2026-10-19:** V2 ships without a
  book; the book is built later with the final V2 engine and released as a separate
  add-on.
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

## Owner decision 2026-10-22: no V2 release; V2.1 then V3

The owner cancelled the public V2 release ("ยกเลิกการปล่อย release V2 เราจะข้ามไป V3 เลย"): the playing
quality seen in real games (GameIndy) is not good enough yet. V2.1 (search and borrowed ideas that pass
SPRT, measured against RC-2) and V3 (NNUE architecture) are done back to back, locally; the V2 launch
checklist (README, topics, announcements, packaged text protocol) moves to the first public release after
this. Do not push, tag or release V2. Local main `a2044fb` = RC-2 (2.0.0) + learned-loss avoid list.
Real-game results (GameIndy W/D/L by colour, Invincible 2 W/D/L) are reported beside SPRT. Open owner
questions: the version label on local main, and whether V2.1 is released on its own. Suggested order and
branch map: `handoff.md` in the 2026-10-22 session (quality suite from the GameIndy trap, the G1 collapse
corpus and the TB-win suite; Track D1-D3, E1-E2, SEARCH_INT_02, SPSA, C4 repetition fix; then V3 data
contract and architecture).

## Owner decision 2026-10-22 (evening): everything goes into V2

The owner replaced the V2.1-then-V3 split the same evening ("ทำต่อให้เสร็จงานเลย เราจะรวมทุกอย่างเข้าไว้ในV2
ผมอยากทำให้มันแกร่งที่สุดเท่าที่จะเป็นไปได้"): all strength work (search Track D/E, SEARCH_INT_02, SPSA,
the C4 repetition fix, NNUE data and architecture) goes into one V2, made as strong as possible before any
release. Still no push, tag or release of V2 until the owner says so. Each concept is measured against RC-2
(paired SPRT) plus the quality suite: branch `quality-suite-01` (`6760b8a`), run tree
`build/runs/quality_suite01` (G1 collapse corpus 120 positions, 500 TB-win openings, 3 GameIndy traps;
RC-2 baseline chain started 2026-10-22 17:52). Local main `1c1a68f` adds 4 learned-loss entries from the
two GameIndy Black losses of 2026-10-22 (culprits 25-21 at ply 17 and 23-19 at ply 13, both scored by Freed
as its best move). First concept: the C4 slow-kill fix (TB WIN band, `build/runs/rc2_g1/slow_kill_pair964.md`).

### V2 strength queue (2026-10-22 19:00, all local, nothing promoted)

Each concept is one default-off compile switch on its own branch from `v2-dev`
(main + quality suite + C4 band + `--parallel-games`), built with the RC-2 switches plus its own;
with its switch off every branch rebuilds RC-2 `D253F275` byte for byte. Each runs screen
(1T 2s+0.02s, no TB, H0 0/H1 +5, cap 2000) and, only on a screen PASS, W1 (1T 10s+0.1s, TB4-6 + C4,
H0 0/H1 +2, cap 4000) against RC-2, 6 parallel games. Contracts in `benchmarks/<slug>/contract.json`,
run trees `build/runs/<slug>`; `gate_chain.py` (corr-hist-01 `fdf4177`) runs them one after another.

| Order | Concept (branch, commit) | Candidate DLL |
|---|---|---|
| 1 | C4_BAND_01 conversion (500 TB-win pairs) + no-regression SPRT (`c4-band-01`) | C4 `B3636BC7` |
| 2 | RC-2 TB-win baseline (`build/runs/quality_suite01`, measurement only) | RC-2 |
| 3 | CORR_HIST_01 correction history, D2 (`corr-hist-01` `25f688b`) | `D77AF85D` |
| 4 | CONT_HIST_01 continuation history 1+2 ply, D3 (`cont-hist-01` `2d400e4`) | `51E20871` |
| 5 | FORCED_EXT_01 single-move extension, E1 (`forced-ext-01` `c24ac7b`) | `9B4CBD3E` |
| 6 | NULL_VERIFY_01 verified null move at depth >= 6, E2 (`null-verify-01`) | `9AD48B1C` |
| 7 | TIME_STAB_01 best-move stability time stop, D1 (`time-mgmt-01`) | `F9410E04` |
| 8 | SELFPLAY_MINING_01: RC-2 runs + labels (12T, 10 s) on the 4 self-play suites (`selfplay-mining-01` `ea81213`) | RC-2 |
| 9 | SPSA_01: 800 iterations x 6 pairs, 5 parameters (LMR base/div, deep null reduction/depth, history bonus), then a screen of the tuned values vs RC-2 (`spsa-01` `57534c8`) | `8B3D3485` + `.tune` |

Passing concepts go into one integrated V2 candidate (SEARCH_INT_02), measured again as a whole.

### Owner 2026-10-22 (night): everything in V2, opening book included

"ใช่ ตอนนี้เราจะรวมทั้งหมดเลย แผนที่เราคิดไว้ลองให้หมด (ทำให้มันเก่งกว่านี้อีก ผมยังรู้สึกไม่ค่อยพอใจกับผลลัพธ์เท่าไหร่)":
every planned idea is tried for V2, and the opening book now ships in V2 (this replaces the 2026-10-19
"V2 without a book" decision). Order (all local, nothing promoted without its gate):

1. Search concepts D1-D3, E1-E2 and the C4 band (queue above).
2. **Self-play losses and bad draws** (`selfplay-mining-01` `ea81213`): `mine_games.py --any-side` on
   RC-2's G4 self-play (1,226 games): 523 losses = 324 collapses + 199 lost from the opening
   (`bad_start`, input for the book), plus 255 bad draws (a side reached +150 and ended below +50).
   Four suites (568 active positions) in `build/runs/selfplay_mining01`; labels (12T, 10 s) and RC-2 runs
   queued after TIME_STAB_01.
3. SEARCH_INT_02: the concepts that pass, integrated, measured against RC-2 plus all quality suites.
4. SPSA on the integrated candidate's search parameters.
5. NNUE: new data round labelled by the integrated engine, with positions around the collapse,
   bad-draw and GameIndy 10-piece positions; a new data contract frozen before generation; then
   architecture work (buckets / threat inputs) against the new data.
6. **Opening book** (`opening-book-02` `d96632e`): `makhos.book` (root lookup, never over a learned
   loss, bound to the verifying DLL + model hashes), `sprt --dev-opening-book`,
   `tools/book/build_book.py` (1,527 positions up to 4 plies; 1/4 and full-time searches must agree
   within 40 cp). Built with the final V2 engine (about 30 h at 60 s, 12T), then measured.
7. Final V2 candidate: SPRT against RC-2, quality suites, GameIndy and Invincible 2 W/D/L.

### Queue 2026-10-24/25: restart, screens first, NNUE data v4 drafted

- **Queue down 2026-10-23 14:27 to 2026-10-24 22:37:** the machine went down (rebooted 17:43 on 10-24)
  and every chain died. Before that the C4 chain and the baseline chain had waited on each other from
  10-22 20:00 to 10-23 11:41 (`baseline_chain.py` was on gate_chain's busy list; removed, v2-dev
  `6cee0cb`). `tools/arena/queue_status.py` now flags a chain that logs nothing for 15 minutes as DEAD,
  and `tools/arena/keep_awake.py` holds ES_SYSTEM_REQUIRED while any chain runs (v2-dev `d7702d1`).
- **C4_BAND_01: gate 1 FAIL as declared.** No TB-win game drawn, but p90/max plies from the first WIN
  bound to the win 8/16 against RC-2's 8/10 (it needed lower). From a large advantage it wins faster
  (median 28 vs 42, p90 40 vs 114) - not the declared metric. Gate 2 stopped at pair 1116 (LLR +1.25)
  and the band is parked: it adds about 0 Elo. Fresh TB-win openings for a possible C4_BAND_02:
  `build/runs/c4_band02/tb_win_openings_g4.txt` (504 positions from RC-2 G4, sha `cefedfd8`).
  The RC-2 TB-win baseline (measurement only) is skipped.
- **Order now (owner 2026-10-24: maximum strength first):** the five screens back to back, then W1 only
  for passing screens. **CORR_HIST_01 screen FAIL** (912 games, W224 D401 L287, -24.0 Elo, LLR -2.95):
  rejected, no W1.
- **NNUE data contract v4 DRAFT** (`nnue2-data-v4` `96b39a5`, local, from v2-dev + the nnue2-b3-prep
  tools; native file unchanged): labels from RC-2 (D253F275 + v2b) at depth 10 instead of production +
  v1; seeds 2027000000-2027999999; split salt `nnue2-stage4-split-v1` (fresh sealed); 10% of games start
  from one of 1,637 positions (`build/nnue2_data_v4/start_lines_v4.txt` `5c875469`: 449 RC-2
  collapses, 255 bad draws, 933 external-opponent positions); otherwise as v3 (10M train rows, same
  gates). `selfplay.py --start-lines` (no file = byte-identical v3 games), contract chosen by seed range
  in `extract_rows.py`/`regen_check.py`, 71 tooling tests pass. The dry run (100 games, regen 15/15)
  is queued between the NULL_VERIFY_01 and TIME_STAB_01 screens (`build/runs/nnue2_v4_dryrun`);
  the freeze waits for the owner.

- **2026-10-25 owner: freeze v4 if the dry run passes** (regen 15/15, throughput reported) and generate
  right after the screens, before the W1 gates. Contract FROZEN with that condition (`nnue2-data-v4`
  `7e8043a`). `tools/nnue2/acquire.py` (`9b29e4e`) generates 50,000-game chunks from seed 2027000000 and
  stops after the first chunk at which the extractor's own stop-rule count (`StopCounter`) reaches 10M.
  Chain `build/runs/nnue2_v4_acq` (src `ff3b89f`): check the dry run's regen.json, acquire into
  `build/nnue2_data_v4/raw`, extract with TB4-6 into `rows/`, regen 20 per split. The TIME_STAB_01 screen
  and every W1 wait for it. **CONT_HIST_01 screen FAIL** (3,488 games, -4.2 Elo): rejected.
  FORCED_EXT_01 screen at 1,314 pairs: +10.1 +/- 7.8 Elo, LLR +2.37.

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
   **A2 done: HISTORY_MALUS_01 W1 PASS** (2026-10-17 11:00 local) at 2,751 pairs:
   W 1809 / D 2107 / L 1586, Ptnml 113/501/1337/650/150, LLR +2.97, **+14.1 ± 5.8 Elo**
   (candidate 5d1445ac vs strict control 8b82fef8, 1T 10s+0.1s, seed 20261016, run dir
   `build/runs/histmalus_l1w/build/histmalus01/sprt-w1-20261016`). Interrupted once at
   226 pairs by a GUI exe smoke test (workload lease) and resumed. History malus stays
   in SEARCH_INT_01.
   **A4 W1 PASS** (2026-10-17 17:55 local) at 215 pairs: W 189 / D 170 / L 71,
   Ptnml 1/17/87/83/27, LLR +2.94, **+97.9 ± 20.8 Elo** (SEARCH_INT_01 `5ed1fe18…eac9`
   vs production `32c32302…7e79`, same NNUE `07b9ab0f…`, 1T 10s+0.1s, persistent
   search, TB4-6 np80 + C4, 2 parallel games, H0 0 / H1 +5, seed 20261017); stderr
   empty, `sprt.json` SHA-256 `3cc8a2f0…dc48b`, run dir
   `build/runs/searchint_a4w1/build/search_int01/sprt-w1-20261017`.
   **A4 W2 PASS** (2026-10-18 01:28 local) at 229 pairs: W 201 / D 160 / L 97,
   Ptnml 2/19/111/67/30, LLR +2.95, **+80.3 ± 20.3 Elo** (SEARCH_INT_01 `5ed1fe18…eac9`
   vs production `32c32302…7e79`, same NNUE, 12T, 512 MiB, fixed 1 s, TB4-6 + C4,
   H0 0 / H1 +5, seed 20261018); `complete: true`, stderr empty, `sprt.json` SHA-256
   `7a4d26e5a0df6ca7…`, run dir `build/runs/searchint_a4w1/build/search_int01/sprt-w2-20261017`.
   Paused three times on 2026-10-17 for owner GUI/release work (68, 70, 71 pairs),
   each through the interactive-priority event, and resumed with `--resume`.
   SEARCH_INT_01 has now passed both gates and is the RC-2 search; it is not
   merged into `main` or shipped yet (RC-2 also waits for the NNUE v2 track).
   **B2 running** (started 2026-10-18 08:12 local under data contract v2). The run
   tree is `build/runs/nnue2_b2`, a `git archive` of `nnue2-stage2-data-contract`
   `96aa1fb`; its `selfplay.py` is byte-identical to `5747714`.
   - Teacher: DLL `32c32302…`, model `07b9ab0f…`, depth 10, hash power 20.
   - Load: 5 workers at Idle priority, seeds 2026200000 onward, 450,000 games.
   - Output: `build/nnue2_stage2/raw/part-1.jsonl` in that tree.
   - First rate was about 0.86M engine labels/hour, so roughly 16–17 h in total.
   - Resume after any stop: `python -B launch_b2.py` (finished seeds are skipped).
     The runner shows a pop-up when it ends.
   - B2 is not a gate. F3, C1 labels and other 12-thread work must not run beside it.
   - After it ends: run `extract_rows.py` with the 10M-train-row stop rule, then
     the coverage gates and `regen_check.py`.
   **B2 DONE 2026-10-19:** part 1 exit 0 at 00:32 (450,000 games, 16.3 h, including an
   owner GUI pause 22:30-23:38 by process suspend; labels are fixed depth 10, so no
   row changed). Part 2 exit 0 at 11:17 (350,000 games, 10.7 h). Extraction started
   11:18 in the B3 chain below.
   **B2 status 2026-10-18 11:43 local:** 104,500 / 450,000 games, about 30k games/h,
   so part 1 ends near 23:30 local.
   - **Rehearsal on real B2 output** (`build/runs/nnue2_b2_rehearsal`, read-only
     copies; findings in `benchmarks/nnue2_stage2/b2_rehearsal_20261018.json` on
     `nnue2-stage2-data-contract` `9878d37`, local). The old extractor held every
     row in memory; `9878d37` streams it (seed-ordered offsets, 128-bit key digests,
     stop rule, shard leakage re-read) and matches the old output byte for byte on
     5,000 games. Regen check 60/60.
   - **Volume:** train rows per game after dedup fall as games grow (23.7 at 1k,
     18.4 at 79,675), so 450,000 games give about 7.1M train rows, short of 10M;
     about 660,000 games are needed. The contract's stop rule fixes the volume inside
     seeds 2026200000-2026999999, so **part 2 is chained**: `b2_chain.py` (pid 11120,
     Idle, `chain.log`) starts `b2_part2_runner.py` (seeds 2026650000-2026999999,
     **350,000 games** since 2026-10-18 owner decision, `part-2.jsonl`, about 11.6 h)
     only after part 1 logs `=== exit 0`. Reason: a stop-rule count on 226,369 real
     part-1 games gave 3,738,891 train rows (slope -1.19 rows/game per doubling) and
     projected 10.22M at 700,000 games (2% margin); 800,000 give about 11.4M. Clock
     buckets at 226k games: 19,112 / 11,752 / 9,225 / 6,934 / 4,877. It stops
     with a pop-up on any other ending. It is not restarted after a reboot. Kill pid
     11120 to cancel part 2.
   - **Clock gate: data contract v3 frozen 2026-10-18 (owner chose option A).** The
     v2 gate (2% of deduplicated train rows with clock >= 30) was heading to about
     1-1.6%: 98.9% of those rows have 6 or fewer pieces, and deduplication removes
     repeats of the finite 2-piece set as games are added. v3 needs at least 5,000
     train rows in each clock bucket 30-39 .. 70-79 (rehearsal at 79,675 games: 10,650 /
     6,924 / 5,626 / 4,059 / 2,944, growing about x1.7 per doubling); nothing else
     changes, and B2 part 1 and part 2 count under v3. Local branch
     `nnue2-contract-v3-draft` `6c4ee28` (from `9878d37`): `data_contract_v3.json`, the
     options record `data_contract_v3_draft.json`, and `extract_rows.py` gating on the
     buckets while still reporting the v2 share result (17 tests pass).
   - **B3 prepared and trainer contract frozen 2026-10-18** (local `nnue2-b3-prep`
     `6d3f8a3`, which also merges contract v3, so extract, pack and train all run from
     this branch): `pack_rows.py` (uint8 features, chunked, peak 642 MB) and `train.py`
     (float NNUE with v1 parameter names, deterministic, atomic checkpoint and resume).
     Owner choices: loss from pilot arm N (`train_config.json`, declared before any
     label, arm passed +14.2 Elo): Huber 0.1, mix teacher / outcome / exact WDL
     1.0 / 0.1 / 0.5, phase weights 1.0; optimizer recovered from v1 (AdamW 1e-3, wd
     1e-4, batch 256, warm-up 2 + cosine 30, patience 5); one deterministic CPU thread.
     Two seeds, 20290001 and 20290002 (`trainer_contract_v2a_seed*.json`); the lower best
     validation loss goes on, never the sealed split. Still to adapt: quantization and
     parity for the v2 model.
   Then the C1 labels
   need gate-free gaps. The owner declined shortcuts (2026-10-16): one RC-2 with
   everything that passes.
   **Text protocol for V2 (owner, 2026-10-18: ships with Release V2):** local branch
   `text-protocol-01` `f7ade0c` from `main`. `makhos uci` now serves the GUI's release
   engine (same release selection, TB3 and NNUE checks, Threads/Hash options); refusals
   end with `bestmove (none)`; `docs/PROTOCOL.md`. Pushed to origin 2026-10-18 (owner),
   not merged into `main`. The refactored `/api/bestmove` passed an HTTP smoke on the V1
   NNUE files at 1 thread (NNUE middlegame, TB3 endgame root, forced move, validation).
   **Single default behavior (owner, 2026-10-16):** the shipped V2 engine has one
   behavior and always plays its best move, like Stockfish; no user-selectable modes
   in the GUI. Compile/runtime flags such as safety mode are default-off only for
   isolated SPRT; whatever passes its gates becomes default behavior in RC-2, and
   whatever fails is removed.
4. Not queued: STRICT_KEY_01's gates are withdrawn; TBDRAW_01 needs a
   scope-specific instruction; RFP_01 ended INCONCLUSIVE (see below).
5. **Track D backlog (owner request 2026-10-16, nothing measured yet):** Stockfish
   ideas mapped to Thai Makhos in
   [SF_IDEAS_TH.md](../../../../docs/research/SF_IDEAS_TH.md). D1 time management
   (soft/hard by best-move stability), D2 correction history, and D3 continuation
   history can be coded during gates, but screens wait for a gate-free gap. The rest
   comes after RC-2.
6. **Track E backlog (owner request 2026-10-16, nothing measured yet):** ideas from
   draughts engines (Chinook, Cake, KingsRow, Scan) in
   [DRAUGHTS_IDEAS_TH.md](../../../../docs/research/DRAUGHTS_IDEAS_TH.md). E1 forced-move
   extension (merged with S6) and E2 verified null move are default-off flags queued
   after D1-D3; null move stays (disabling it failed the screen, while the NULL_EVAL_01
   guard that uses it less often gave +55.5), so E2 adds caution, not removal. E6 ballot
   openings apply only to runs after RC-2. The rest is post-RC-2 or needs owner scope.
7. **12T root cause (owner request 2026-10-17, analysis only):**
   [SMP_ROOT_CAUSE_TH.md](../../../../docs/research/SMP_ROOT_CAUSE_TH.md). The 12T root
   split searches every root move full-window (3.4-4.3x nodes), waits for the slowest
   root move each depth (median 7 root moves), splits the TT 12 ways and pays Python
   overhead. Proposed fix: Stockfish-style Lazy SMP in C with one lockless shared TT;
   gates use 1T parity, scaling and SPRT, not >=2T determinism. M1 (hardware ceiling)
   and any prototype runs wait for a gate-free gap. **Owner decision 2026-10-17:** build
   it now as parallel Track F (branch `lazy-smp-01` from `search-int-01`), measure only
   in gate-free gaps; it joins V2 if it passes before R1, otherwise V2.1.
   **F1 done (local `lazy-smp-01` `ad5dff5`, evidence `c303258`, not pushed):**
   `MAKHOS_LOCKLESS_TT` (five relaxed-atomic words, key XOR payload) +
   `MAKHOS_NATIVE_LAZY_SMP_SKIP_DEPTH`, `makhos sprt --lazy-smp`, orchestrator
   `-LazySmp`. Candidate `21bead74…f27d` (two byte-identical builds); the default-flag
   build stays byte-identical to `5ed1fe18`. 1T parity vs `5ed1fe18`: 960/960
   middlegame_search_v5 positions at depth 13 (move, score, depth, nodes, PV); 1T
   cost about 0.5%.
   **F2 measured 2026-10-17 ~18:00 local** in the gap between A4 W1 and W2 (no GUI;
   both runs at Normal priority because of a tool bug, since fixed), files in
   `benchmarks/lazy_smp01/` on that branch. M1 ceiling: aggregate 1T NPS 4.30x at 6
   processes, 5.69x at 10, 5.62x at 12. Scaling on 24 stable v5 positions, empty TT
   per search: mean depth at 1 s 22.79 (1T), **20.62 (root split 12T), 25.17 (Lazy
   12T)**; time to depth 18 vs 1T 0.49x (root split), 1.85x / 3.00x / 3.10x (Lazy
   2T / 6T / 12T). Depth is not Elo.
   **Server limits (`7253326`, pushed to origin `lazy-smp-01` 2026-10-18):** Lazy SMP
   Threads 1..1024 and free-size Hash (4,096 to 2^36 entries; power-of-two counts keep
   the mask index, other counts use multiply-high). Candidate `b397b084…5768`; default
   flags still reproduce `5ed1fe18`; 1T parity 960/960 at depth 13 with 2^16 and 2^20
   TTs. Only `sprt --lazy-smp` selects it. README `fe0735a` (pushed 2026-10-18).
   **F3 tree frozen 2026-10-18, not started:** `build/runs/lazysmp_f3` from `7253326`
   (artifact hashes checked; Lazy 12T vs root split 12T, W2 conditions, H1 +5,
   1,000 pairs, seed 20261019). Start `launch_f3.py` there only when no gate or data
   run uses the CPU and the GUI is closed.
   **Order changed 2026-10-19 10:38 (owner: fastest path): B3 before F3.** The F3
   watcher (pid 28816) was stopped before B2 ended (noted in `f3_chain.log`).
   `build/runs/nnue2_b3/b3_chain.py` (pid 24256, Below Normal, `chain.log`, `logs/`)
   runs from a `git archive` of `nnue2-b3-prep` `6d3f8a3`. It waits for B2 part 2
   exit 0, then runs extract (contract v3), `regen_check.py` (20 per split), pack,
   and training of seeds 20290001 and 20290002 in parallel (one CPU thread each).
   After that it waits for no GUI / uci / sprt process and runs `launch_f3.py` once.
   Each finished step leaves a marker in `done/`, so a rerun resumes. Any failure
   stops the chain with a pop-up.
   **B3 DONE 2026-10-19:** extract exit 0 (697,608 games -> 10,000,000 train /
   1,685,124 validation / 1,672,029 sealed rows, coverage passed, leakage 0); regen
   20/20 per split; both v2a seeds trained (best validation loss 0.0584892 for
   20290001, 0.0586215 for 20290002). F3 started 12:48 (pid 2112).
   **v2a cannot be quantized:** its weights exceed the frozen v1 integer format
   (hidden |w| up to 5.37 against the int8 limit 0.496; feature |w| up to 4.70 against
   the int16 accumulator proof). Clipping a trained model is not allowed.
   **Owner 2026-10-19: trainer contract v2b** (`nnue2-b3-prep` `fd8a17d`, local) is
   v2a plus `weight_clamp` after every optimizer step (feature weights 0.88, feature
   bias 1.0, hidden 127/256, output 127/192). `build/runs/nnue2_v2b/v2b_chain.py`
   (pid 24804, Below Normal, `git archive` of `fd8a17d`) waits until F3's `sprt.json`
   is complete and its process has exited, then trains both seeds on the B3 packed
   rows, takes the lower validation loss, and runs `tools/nnue2/quantize.py` and
   `tools/nnue2/native_parity.py`. Pop-up on failure or at the end. Then the sealed
   report and B4.
   **F3 PASS 2026-10-19 20:38:** Lazy SMP 12T (`b397b084`) vs root split 12T
   (`5ed1fe18`), 237 pairs / 474 games, W195 D183 L96, Elo +73.6 +/- 20.0, LLR +2.96,
   pentanomial 2/26/108/73/28 (`build/runs/lazysmp_f3/build/lazy_smp_01/sprt-f3-20261019/
   sprt.json`). Lazy SMP becomes the V2 default. The v2b chain started training both
   seeds at 20:38:46.
   **History rewrite 2026-10-19 (owner approved):** every commit authored or committed as
   `pinggo@users.noreply.github.com` now reads `1112eee2`; trees, dates and messages are
   unchanged. Force-pushed main, research-archive, lazy-smp-01, text-protocol-01 and the
   `archive/*` tags; all local branches moved. Commit hashes in this file and in run trees
   (`SOURCE_COMMIT`, contracts) are the old ones: look them up in
   `docs/history_rewrite_20261019/commit-map.txt` (old new). Tags v1.0.0-v1.0.2 are
   immutable releases and still point at the old commits. Backup bundle:
   `build/backups/freed-before-rewrite-20261019.bundle`.
   **v2b DONE 2026-10-19 21:46:** both clamped seeds trained (best validation loss
   0.0584882 for 20290001, 0.0587251 for 20290002; v2a was 0.0584892 / 0.0586215), so
   the clamps cost no measurable loss. Seed 20290001 quantized with the frozen v1 format:
   PASS on 1,685,124 validation rows (MAE 0.00218, max 0.0281, sign mismatches 0.28%),
   `model.mknnue` sha256 `BC2B36CF…0D42`. Native parity PASS: 0 mismatches for scalar,
   full eval (both sides) and AVX2. Artifacts: `build/runs/nnue2_v2b/build/nnue2_stage3/
   quantized-20290001/` and `native-parity-20290001/`. Next: sealed report, then B4.
   **Sealed report DONE 2026-10-19 (owner go-ahead):** `tools/nnue2/sealed_report.py`
   (`nnue2-b3-prep` `dfb54f0`..`4b08535`, local). Commitment sha256 `622c3f4c…fbad`
   committed before opening (validation loss reproduced to 1e-8). Sealed split opened once:
   1,672,029 rows, 68,712 games. Weighted loss float 0.05840, quantized 0.05840 (parity MAE
   0.00218, max 0.0281, within limits), v1 reference 0.06993; exact-WDL MSE 0.065 vs v1
   0.183. Sealed agrees with validation (0.05849), so no sign of overfitting. It selected
   nothing. Report: `benchmarks/nnue2_stage3/sealed_report_v2b_seed20290001.json`.
   **B4 started 2026-10-19 21:58:** branch `nnue2-b4` `ca9b315` (local, from
   `lazy-smp-01`) adds `MAKHOS_NNUE_MODEL_V2B` (default 0): the search DLL pins only its
   own model. Default build reproduces `b397b084` byte for byte; `-ModelV2b` gives
   `d253f275`. `build/runs/nnue2_b4/b4_chain.py` (pid 19828): screen (1T 2s+0.02s, no TB,
   H1 +5, cap 2,000, seed 20261020), then W1 only on PASS (1T 10s+0.1s, TB4-6 + C4,
   H1 +5, cap 4,000, seed 20261021). Both sides use the RC-2 search; only the model differs.
   Screen FAIL/INCONCLUSIVE stops for DP2 (owner).
   **B4 screen PASS 2026-10-19 22:35:** 207 pairs, W234 D123 L57, +158.7 +/- 25.0 Elo,
   LLR +2.96. The first W1 start failed at once: the shared C4 endgame DLL pins v1. Fix
   `nnue2-b4` `47eb521`: `sprt --dev-native-endgame-library` (candidate gets its own C4)
   and `endgame_c4 -ModelV2b`; both C4 DLLs rebuilt from that commit (control `c642c02e`,
   candidate `287eaf77`). **W1 running since 22:39** (chain pid 35924).
   **B4 W1 PASS 2026-10-20 00:00:** v2b vs v1 on the RC-2 search, 1T 10s+0.1s, TB4-6 + C4:
   207 pairs / 414 games, W195 D159 L60, +117.6 +/- 20.6 Elo, LLR +2.96, pentanomial
   0/10/81/87/29 (`build/runs/nnue2_b4/build/nnue2_b4/sprt-w1/sprt.json`). DP2: v2b goes
   into RC-2. Next: R1 (RC-2 = SEARCH_INT_01 + Lazy SMP + NNUE v2b), then R2 G1/G2/G4/G7.
   **R1 DONE 2026-10-20:** local branch `rc-2` `e28b0cc` (from `nnue2-b4`): the GUI search
   factory uses Lazy SMP above one Thread when the DLL has it (backend `native-lazy-smp`),
   `sprt --no-early-stop` for fixed-length gates, `tools/build/build_rc2.ps1`. RC-2 = search
   `d253f275` (= the B4 candidate, byte-identical) + v2b `BC2B36CF` + C4 `da853f46` (C4 is not
   byte-reproducible). C defaults and the GUI release are unchanged until R3.
   **R2 G1 running since 2026-10-20 00:21** (`build/runs/rc2_g1/g1_chain.py`): RC-2 vs
   production (32c32302 + model_a + C4 eb8af045), 1T 10s+0.1s, TB4-6 + per-side C4, seed
   20261101, fixed 2,000 pairs, every game written for G3/G5. At 1,046 pairs (07:05):
   W1184 D686 L222, +172.7 +/- 10.9 Elo.
   **Owner decision 2026-10-20, G6:** the sealed commitment did not name MAE per piece band
   or for the king group, and the sealed split is not opened again. G6 counts as passed on
   the evidence already sealed: v2b loss below v1 in every phase band (13-16 0.0743 vs
   0.0796, 9-12 0.0501 vs 0.0576, 5-8 0.0522 vs 0.0746), overall 0.05840 vs 0.06993, and
   the v2b B4 W1 pass.
   **R2 G1 PASS 2026-10-20 13:15:** RC-2 vs production, 1T 10s+0.1s, TB4-6 + per-side C4, seed
   20261101, all 2,000 pairs / 4,000 games, no early stop: W2272 D1283 L445, **+171.4 +/- 7.8
   Elo (lower bound +163.6)**, pentanomial 3/50/578/855/514
   (`build/runs/rc2_g1/build/rc2_g1/sprt.json`; game records in `games/`). Gate +50/+35: pass.
   **G3 PASS:** RC-2 lost 445 games, production lost 2,272 (19.6%; limit 60%). **G5 PASS**
   (`tools/arena/conversion_report.py`, rc-2 `93c4d7a`; reading: own score +100..+200 at two
   consecutive own moves by ply 40): RC-2 wins 78.2% (76.1-80.1%) of 1,627 such games, production
   32.1% (29.0-35.4%). Large advantage (>= +300): RC-2 wins 93.7%, production 60.1%. Win speed:
   from a WIN bound to the end median 6 plies for both; 2 RC-2 slow kills (> 20 plies), one
   diagnosed in `build/runs/rc2_g1/slow_kill_pair964.md` (C4 downgrades a TB WIN to DRAW..WIN under
   a repetition limit; V2.1 item). **G2 started 13:16** (`g2_chain.py`, 12T 512 MiB fixed 1 s,
   Lazy SMP vs root split, seed 20261102, 1,000 pairs, ~34 h). Next: G4, G7.
   **Mined G1 games 2026-10-20** (`tools/arena/mine_games.py`, rc-2 `49d9871`; output
   `build/runs/rc2_g1/mined/`): of RC-2's 445 losses 320 (72%) are `bad_start` (its first searched
   score is already below -50: the random 6-ply opening, the partner game of a pair), 55 are sudden
   collapses (median cause ply 22, depth 22, score 0 -> -283) and 70 gradual declines. 125 entries
   form the collapse corpus for V2.1. TB-win suite: 2,636 won games reach a TB-win position, 917
   convert in > 40 plies (822 by RC-2); 500-position seeded suite for the C4 fix.
   G2 corrected ETA: ~28.5 pairs/h, about 00:15 on 2026-10-22 (no nightly pause; owner cancelled).
   **R2 G2 stopped early by owner decision 2026-10-21 11:01, at pair 624 of 1,000** (no early-stop
   flag, so the SPRT status did not end it; 1,248 game records match 624 pairs; checkpoint
   `complete: false`; the game in flight was lost). Result: 12T 512 MiB fixed 1 s, Lazy SMP RC-2 vs
   root-split production: W765 D363 L120, Ptnml 0/9/148/280/187, **+198.7 +/- 14.3 Elo (lower bound
   about +184)**, LLR +8.92. Gate +50/+20: pass by a wide margin; G2 is not a mandatory gate and
   it was not played to the planned 1,000 pairs, so report it as 624 pairs, never as complete.
   Win speed (`conversion_report.py`, 12T): WIN bound to end median 8 plies for both sides, 0 slow
   kills; one draw by `no_progress`, 362 by repetition. Report in
   `build/runs/rc2_g1/build/rc2_g2/conversion_report.json`. Next: G4, G7.
   **G7 checks done 2026-10-21 (rc-2 `49d9871`, native source unchanged since A3):** immutable
   artifacts OK against the real build tree (`verify_immutable_artifacts.py --root D:/ThaiMakhosEngine`;
   the worktree copy lacks untracked fixtures); native exe built with the RC-2 -D flags: perft 1-10
   ends at 861,842,812; `verify-native` seed 20261021 PASS (1,004 positions, 5,757 moves, 10 exact
   3-piece cases); full suite 620 passed, 67 skipped, 1 failed for a missing untracked fixture
   (`native_endgame_boundaries.exe`), that file passes with the fixture copied (11 passed). Evidence
   in `build/runs/rc2_g1/g7/`. **GUI smoke + rollback still open: do it at R3** (GUI still loads
   production until the defaults flip).
   **G4 part1 started 2026-10-21 11:18** (contract `benchmarks/rc2_g4/contract_g4.json`, rc-2
   `42a3e52`, declared before the first game; run tree `build/runs/rc2_g4/`, `g4_chain.py`): RC-2
   against itself, 1T 10s+0.1, the 613 part1 openings x 2 = 1,226 games in two halves, 4 games at
   once. Baseline part1 draws 514/1,226 = 41.9%. Pass at part1 only if the Wilson lower bound is above
   43.9%; otherwise the owner chooses whether to play part2. Owner chose part1 only (2026-10-21).
   The openings feature came from `selfplay-baseline-01` (cherry-picked `d6648e0`..`f24491c`).
   **G4 PASS at part1 (2026-10-21 13:18, 2.0 h, 1,226 games, 0 invalid):** RC-2 against itself draws
   703 = **57.3% (95% 54.6-60.1%)**; lower bound above the 43.9% gate. Baseline on the same 613
   openings: 514 = 41.9% (39.2-44.7%). Black won 300, red 223 (baseline 370/342). Termination:
   repetition 702, no legal move 523, no progress 1. Per opening: both games drawn 232 (baseline
   114), results differ 258 (349), same colour won both 123 (150). Report
   `build/runs/rc2_g4/part1_report.json`, baseline `baseline_part1_report.json`. Part1 only, never
   report it as the full part A; part2 not played. The sprt processes exit 1 (status
   INCONCLUSIVE, no pass/fail meaning in this measurement); the chain checks completeness instead.
   **Gates now: G1, G2 (624 pairs), G3, G4, G5, G6 pass; G7 open only for GUI smoke + rollback (R3).**
   rc-2 `ec100d1` adds .env/*.pem/*.key to `.gitignore` (local, not pushed).
   **Owner decision 2026-10-17:** order after A4 W2 is B2 then C1; F3 goes in a gap
   between B3 and B4 so R1 is not delayed.

## Standing scope: practical no-loss track against Invincible 2

On 2026-09-25 the user approved the
[practical no-loss track](../../../../docs/architecture/PRACTICAL_NO_LOSS_TRACK.md)
as the active strength scope. The goal is zero losses against Invincible 2 in a
large, frozen, colour-balanced match, reported with a 95% upper bound on the loss
rate and never as "proven perfect". It excludes proof/DFPN work, tablebases of 7
or more pieces, and any Lazy SMP redesign. The track is in Phase 0; no production
default, rules file, model or accepted artifact has changed under it.

**Owner 2026-10-19, second top-level goal:** beyond zero losses, Freed should **win
games that Invincible 2 can only draw** (practically stronger, not just safe).
Matches against Invincible 2 report wins, draws and losses separately, and the win
rate is a target next to zero losses. The self-play draw goal measures soundness;
it does not mean settling for draws. Ideas that trade draws for winning chances
(contempt, practical-chance tie-breaks, pressure-keeping book lines) are judged
against non-self opponents, must not raise the loss rate, and ship only if they
pass (single default behaviour).

Decisions of 2026-09-25 (still in force unless the owner changes them):

- The owner confirmed the F1 form: extract only what the track needs from PR #25
  and keep the Lazy SMP PRs open.
- A game that reaches a `project` draw that Invincible 2 does not declare is
  reported non-comparable. There is no external rules profile and `RULESET.json`
  is unchanged.
- ~~No relay or automated play against Invincible 2, and no permission request for
  now.~~ **Replaced 2026-10-19 (owner):** the owner will not relay games by hand, so
  the match is to be automated. Invincible 2's moves come from the developer's
  server, so the developer's permission comes first; a request is drafted for the
  owner to send, and the relay is built only after a yes.
  **Developer replied 2026-10-19 (owner's report):** no limit on the number of games,
  no clear restrictions. The reply text is not in the repo yet. Concurrency starts at
  2-3 games, with a stop on server errors or slowness; no training on its moves; full
  win/draw/loss results published with credit.
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

- **Branch cleanup (owner-approved, 2026-10-17).** `origin` now has only `main` and
  `research-archive`.
  - 19 branches already contained in both were deleted outright.
  - The other 24 were first tagged `archive/<branch name>` at their exact tips
    (tags verified on the remote), then deleted. Restore one with
    `git push origin archive/<name>:refs/heads/<name>`.
  - Name/SHA lists are in `D:\ThaiMakhosEngine\build\branches_A.txt` and `branches_B.txt`.
  - Deleting the head branches **auto-closed the 12 unmerged open PRs**: #18–#22,
    #24–#27, #29, #35 and #36. They are closed, not merged. Any of them can be
    reopened after restoring its branch.
  - Releases: v1.0.2 is latest (GUI only; same engine as v1.0.0). The v1.0.1
    release was deleted because it was published without files under GitHub
    immutable releases; tag `v1.0.1` remains.
  - `main` also has `docs/NNUE.md` (`62da0dc`).

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
