# Practical no-loss track against Invincible 2

Status 2026-09-25: the user approved this as the active strength scope, and
confirmed the changes in section 8. The track is in Phase 0. No production
default, rules file, model or accepted artifact has changed under it; the
default-off candidates are listed in current-state.
[current-state](../../.agents/skills/thai-makhos-engine/references/current-state.md)
owns the single next action, and results go to the
[evidence ledger](../../.agents/skills/thai-makhos-engine/references/experiment-evidence-ledger.md).
This document is the plan. It does not authorize launching any run.

## 1. Goal and honest framing

The goal is an engine that does not lose in practice. Only a proof can
guarantee perfect play, and proof work is excluded here. The DFPN root was still
`UNKNOWN` after 566,173,881 expansions ([proof roadmap](../../PROOF_ROADMAP.md)).
Exact 7-piece and 8-piece tablebases would cover 68.5 and 806 billion
positions, about 68 GB and 806 GB at TB6's rate of roughly one byte per
position.

The target is therefore empirical: zero losses against Invincible 2 (the
external engine by อ.ทศพล ธนะทิพานนท์) in a large, frozen, colour-balanced
match. Report it as "0 losses in N distinct games (95% upper bound on the loss
rate = 3/N)", never as "proven perfect". This covers Phase 1 and the empirical
half of Phase 2 in the Invincible 2 roadmap. That roadmap, `INVINCIBLE_2_ROADMAP_TH.md`,
exists only on the PR #25 branch for now (see F1).

## 2. Definition of done

| Gate | Requirement | Runs on |
|---|---|---|
| Final | Frozen match against Invincible 2: at least 300 games (150 per colour) from frozen opening positions at a fixed time control, with 0 losses. That bounds the loss rate at about 1%. Stretch goal: 1,000 games, about 0.3%. | Local |
| Consistency | 2,000-game self-play gauntlet against the accepted control, with 0 candidate losses. | Local |
| Regression | Never-lose suite: every historical loss position is held at the production time control. | Local |
| Correctness | The full suite passes. Native move/state changes also need perft through depth 10 and the Python/native differential. | Local and Web |

Counting rules, fixed before any run:

- Count distinct games only. Deduplicate by move-sequence hash, because a
  repeated trajectory is not new evidence. Report `N_distinct` and
  `3/N_distinct`, per colour and per opening. A zero-loss result across `k`
  openings bounds the share of losing openings at `3/k`.
- A game counts only after `makhos.game_analysis.replay_game()` validates it.
  Record aborted, timed-out or network-failed games, but never score them as
  draws.
- If the rules differ, report the results as non-comparable. Never edit the
  rules to make a match fit.
- A result applies only to the frozen opponent version, settings and opening
  set.

## 3. Verified facts and corrections

This is a Web review of `main` at `a0f7964` on 2026-09-25, plus open PR state.

### 3.1 The root safety policy does not reach production middlegame play

| Position class (production NNUE profile) | Backend | Root choice |
|---|---|---|
| At most 6 pieces, or any legal capture that lands at 6 or fewer (`makhos/endgame_routing.py:10`); checked first | `native-endgame` (C4) | `search.py:_choose` with WDL bounds from tablebase probes, exact at 6 or fewer pieces (`search.py:679`) |
| More than 6 pieces and no capture into 6 or fewer, Threads > 1 | `native-root-split` | `ParallelNativeSearch._choose` (`parallel_native.py:492`): highest score wins, and ties go to the first legal move. It has no WDL bound and no BEST/WIN mode. |
| The same, Threads = 1 | `native-single` | the C search's own root choice |
| One legal move | `forced` | none |
| Native endgame disabled at 6 or fewer, native unavailable, or reference search | Python | `search.py:_choose` |

On the native path, `search.py:_native_result` wraps the native pick as a
single candidate with `UNKNOWN_WDL` and never calls `_choose`
(`search.py:565-581`). A safety mode added only to `_choose`/`_safety_rank`
would therefore change only positions at or next to the tablebase frontier,
where probes already bound the result. It would not touch the quiet
middlegame with more than 6 pieces, which is where losses start. Phase 2
needs one root policy that every backend calls (F2).

### 3.2 Plan dependencies that exist only on unmerged branches

[PR #25](https://github.com/1112eee2/ThaiMakhosEngine/pull/25) holds several
things this track needs:

- `analyze-game --nnue-model`. The version on `main` lacks the flag. The
  [PR #27](https://github.com/1112eee2/ThaiMakhosEngine/pull/27) handoff runs
  analysis from a separate tooling checkout at `7cca706`.
- `docs/architecture/INVINCIBLE_2_ROADMAP_TH.md`.
- The game-review evidence: `benchmarks/game_reviews/saved_games_corpus_audit_20260923/`
  (the staged `6ef62f9998d12db4` review), `2139e329d3c5def3/` and
  `e26872d254ea0041/`.

That PR's Lazy SMP candidate is `REJECT_FOR_PERFORMANCE / NOT_PROMOTED`
([PR #26](https://github.com/1112eee2/ThaiMakhosEngine/pull/26)). The raw
`saved_games/` files are gitignored and exist only on the Local machine.

F1 status: PR #28 extracts `analyze-game --nnue-model` and the
`2139e329d3c5def3/` evidence from PR #25 head `7cca706`. The other two
evidence directories and the roadmap are still only on PR #25. The roadmap
links a handoff file that is not on `main`, so it cannot be copied byte for
byte without a broken link.

### 3.3 The game-record schema has drifted

The GUI writes `result`, `rules_result` and the per-move backend
`native-endgame` (`web/app.js:956`). The schema
`schemas/thai-makhos-game-v1.schema.json` forbids extra top-level keys and
lacks that backend, so current records fail it. No code or test validates
against the schema, although `references/positional-diagnosis.md` names it
as the record schema. The working validator is `load_game_record()` plus
`replay_game()`.

### 3.4 An external rules profile already exists

`project` follows [RULESET.json](../../RULESET.json): threefold repetition and
80 reversible plies. A second profile, `external-no-repetition`, drops the
repetition limit and keeps the 80-ply limit (`engine_manager.py:48`,
`game_analysis.py:53`). The ledger describes it as a way to reproduce
external sites that play past threefold, not as a claim about any site's draw
counter.

### 3.5 What is known about Invincible 2

#### Access

Early on 2026-09-25 this container's egress proxy denied `hosbase.com`,
`www.aimechatron.com`, `www.blognone.com`, `pantip.com` and
`www.deepai21.com`. Later that day the PR #28 review loaded the live page in a
separate cloud browser, and this container could then fetch it too. Network
settings can change, so re-check access before relying on it. Access does not
imply permission to automate play (section 7).

#### Primary page (observed 2026-09-25)

This container fetched the page and its three scripts once each: five
requests, no WebSocket connection, no game started. Nothing from the site is
stored in this repository. The observation is identified by hashes, not by a
product version:

| Item | Identity |
|---|---|
| `https://hosbase.com/invincible2/` | SHA-256 `3f84c59d8642db6714f10bf136f227ce8814471c38c997f96c02993301079bb4`, `Last-Modified: 2026-09-02` |
| `js/control_250618.js` (game logic) | SHA-256 `ef7296c7cfe6bcf2dc7a2b1407cefa2e4eb952a7dbf3200cfa8e78d52f0b4a50` |
| `js/class.js`, `js/utility.js` (helpers) | `b04c12d6…`, `a4596842…` |

The script filename is not treated as a version. No first-party version
string is visible.

- The page has three controls: new game as Black, new game as White, and
  About. About names ทศพล ธนะทิพานนท์, links AIMechatron and shows
  "© พ.ศ. 2563–2568". The page shows no version, rules text, terms, game
  export, position setup, or time or level setting.
- The page script validates the human's moves and draws the board. The
  engine's moves come from a remote WebSocket server named in the script.
  Automated play would therefore load the developer's server, and needs the
  developer's permission first (section 7).
- Rules as implemented by the page script, compared with `project`
  ([RULESET.json](../../RULESET.json)):

  | Rule | Page script | `project` |
  |---|---|---|
  | Start | 8 men each on the two back rows; Black moves first | same |
  | Men | one square diagonally forward; capture forward only, landing immediately beyond | same |
  | Kings | any distance on a clear diagonal; capture the first piece on a ray if it is an opponent's, landing immediately beyond; continue in any direction | same |
  | Captures | mandatory; no majority rule; the capturing piece must continue; each captured piece is removed at once | same |
  | Promotion | on landing, and it ends the move | same |
  | No legal move | loss | same |
  | Threefold repetition | draw, but declared only when 10 or fewer pieces remain | draw at any piece count |
  | No-progress limit | none | 80 reversible plies |
  | One king each | draw once two consecutive positions have one king each and no capture is available | no special rule |

- The page numbers the squares 0–31 row by row, starting from the row where
  Black promotes. Its dark squares are the left-right mirror of ours, so page
  index `i` is our square `4·⌊i/4⌋ + 4 − (i mod 4)`. This is derived from the
  script only, so check it against a real game before any relay uses it.

What this means for the track:

1. Moves and captures match. Draw adjudication does not, and neither
   `project` nor `external-no-repetition` reproduces it. Under section 2, a
   service result is non-comparable once the game reaches a `project` draw
   (80 reversible plies, or threefold repetition with more than 10 pieces)
   that the service does not declare.
2. Our TB4–TB6 values assume the 80-ply limit. Without that limit, a
   tablebase WIN or LOSS keeps its value, but a DRAW may become a WIN or a
   LOSS. A draw the engine counts on is therefore not guaranteed against the
   service.
3. The server's own behaviour is unknown: for example, how it chooses a move
   in a drawn position, or whether it is deterministic.

The Phase 0 verdict stays INCONCLUSIVE. The user has to decide how to treat
the draw-rule difference, and permission for automated play is unknown.

#### Secondary sources (unverified)

The following comes from search-result summaries
([HosBase page](https://hosbase.com/invincible2/),
[Blognone article](https://www.blognone.com/node/112944),
[Pantip thread](https://pantip.com/topic/39356507)). None of it is confirmed
by the page itself.

- It is a free web application at `hosbase.com/invincible2/`, launched on
  2019-10-26. The site root presents a different engine called "Future",
  which must not be substituted for Invincible 2.
- Claims:
  - an endgame database covering 10 or fewer pieces, with 38,522,321,533,439
    positions;
  - an opening book of more than 300 million positions, built from about
    three weeks of self-play and linked to that database;
  - that it has "solved" Thai Makhos and never loses.
- HosBase also has an "End Game" page (`hosbase.com/endgame/`). Its purpose is
  not verified.
- Still unknown: the server's own rules and determinism, terms of use, and
  whether automated play is allowed.

If those claims hold:

1. With 10 or fewer pieces the opponent is close to an oracle, while our exact
   coverage stops at 6. It will certainly punish a theoretical error in the
   7–10 piece band or a late-middlegame error that leads into it.
2. Each loss is a high-value counterexample. The position before our losing
   move goes into the never-lose suite first.
3. A deterministic service may repeat games from the same opening, which is
   why only distinct games count (section 2).
4. Relaying 300 games by hand could take tens of operator hours. Phase 0 must
   settle feasibility and the terms of use before any harness is built.

### 3.6 Phase 0 access checklist

Items marked done were answered from the page and its script on 2026-09-25
(section 3.5). The open items need the developer or a Local session.

- [x] Access modes: a web page only. Moves come from a remote server, and
      there is no download or documented API.
- [x] Colour choice: the player picks Black or White. Black moves first.
- [x] Position setup: none. Games start from the initial position only.
- [x] Game export: none. The square mapping to our 1–32 numbering is derived
      but not yet checked on a real game.
- [ ] Time or level settings: none on the page. Whether the server plays
      deterministically from one position is unknown.
- [ ] Rules parity with [RULESET.json](../../RULESET.json): moves, captures,
      promotion and the loss rule match. Repetition, the no-progress limit and
      the bare-king rule differ in the page script. Server-side adjudication,
      resignation and timeouts are unknown.
- [ ] Terms of use, whether automated play is permitted, and a contact for
      permission. The page shows none, and About links the developer's
      Facebook page and AIMechatron.
- [x] Identity to freeze: URL, observation date and the page and script
      SHA-256 values. No version string is visible.

## 4. Designing for future development

These rules let later work reuse this track's outputs: NNUE v2, search patches,
other opponents. They add no frameworks, and each one answers a need found in
section 3.

- **F1: build on `main`.** Pull what this track needs out of PR #25 into small
  PRs:
  - `analyze-game --nnue-model` with its tests;
  - the three game-review evidence directories;
  - the Invincible 2 roadmap.

  After that, archive or close the Lazy SMP stack (#18–#26) as evidence. The
  user confirmed this on 2026-09-25 in this form: extract only what the track
  needs, and keep the Lazy SMP PRs open until the extracted pieces are on
  `main`.
- **F2: one root policy.** Before any safety change, extract a single
  root-choice function. The Python search, the native endgame adapter and the
  native root split all call it, and it keeps each path's current tie-break
  exactly. Ship it as a behavior-preserving refactor: move, score and PV must
  be identical on the deterministic suite at fixed depth, 1T and 12T. The
  Phase 2 safety mode then becomes one default-off branch inside it. Any
  deliberate tie-break change is a separate strength candidate.
- **F3: one game-record format.** GUI games, gauntlet games and Invincible 2
  games all use `thai-makhos-game-v1`, validated by `load_game_record()` and
  `replay_game()`.
  - First bring the schema in line with what the GUI writes (section 3.3).
    Then test it against a GUI-built record and a recorder-built record.
  - Add only the provenance fields a match needs: opponent identity and
    version, opening id, time control and result source.
  - Additive optional fields keep v1. A breaking change needs v2 and a
    converter.
- **F4: the never-lose suite is data plus one command.** Each entry stores:
  - the full state: board, side to move, repetition history and reversible
    clock;
  - the source game's SHA-256 and ply;
  - the holding moves and the refuted move;
  - a classification: horizon, evaluation, time, root policy or environment;
  - the identity it was found with.

  Split entries by source game into development and acceptance sets, and tune
  only on development. The suite runs as one subcommand of the existing CLI
  router for any candidate and writes a JSON verdict.
- **F5: gate verdicts are data.** Each gate writes a JSON report bound to the
  source commit, the DLL, model and book SHA-256s, and the settings, in the
  style of the existing SPRT checkpoints and audit manifests. Promotion reads
  those reports, not prose.
- **F6: reuse the match tooling.** The gauntlet and SPRT runs extend
  `tools/arena/source_isolated_arena.py` and the pentanomial `makhos/sprt.py`,
  adding game dumps in the F3 format. The Invincible 2 recorder is the only new
  match tool. It is a thin relay: our engine plays through the existing engine
  manager, the opponent's moves are entered or relayed, and every game is
  written as an F3 record.
- **F7: the book is rebuildable and tied to an engine identity.** Each entry
  records the engine identity, depth, time and stability that produced it.
  After an engine change, entries are re-verified before use. One builder
  command runs resumably at safe boundaries, at BelowNormal priority, and
  yields to the GUI. Runtime lookup sits behind one default-off flag in
  `engine_manager.py`.
- **F8: every step is tagged Web or Local.**
  - Web (cloud) does documentation, source changes, Linux tests, reviews, and
    fixed-depth screens that need no Windows artifact.
  - Local (Windows) does DLL builds, GUI work, matches, gauntlets, SPRT, and
    anything that uses `saved_games/` or tablebase files.
  - Whether a cloud session can reach HosBase depends on its network
    settings. Reaching it never implies permission to automate play.
- **F9: one plan, one next action.** This document is the plan and
  current-state holds the next action. A Local/Web handoff is a PR that
  updates current-state and attaches evidence; it does not restate the plan.

## 5. Phases

### Phase 0: baseline and match harness (first)

0.1. [Web + Local] Check access, rules and terms of use against section 3.6,
     and report before building anything. The exit verdict states whether the
     match can be automated, run by hand, or not run at all. It also states
     the rules finding: comparable under `project`, comparable under
     `external-no-repetition`, or non-comparable.

0.2. [Web] The F1 extraction, confirmed and partly done in PR #28, and the F3
     schema fix.

0.3. [Local] Freeze the production identity: DLL and model SHA-256 taken from
     runtime provenance, 12T with 512 MiB, and the time control. Also freeze an
     opening set that covers both colours and varied first 2–4 plies, with a
     game-level development/acceptance split and a hashed manifest.

0.4. [Web, then Local] Build the match recorder (F3, F6), but only after 0.1
     settles how moves can be exchanged.

0.5. [Local] Play a baseline match of about 40 games to measure today's loss
     rate and collect losses. Forty loss-free games bound the loss rate only
     at 7.5%, so this is a baseline, not a gate.

### Phase 1: loss-finding loop

For every loss, or every game whose evaluation fell sharply:

1. Replay it with `analyze-game --nnue-model`. Find the earliest reproducible
   loss of value with fresh-state ladders.
2. Classify the cause: search horizon, evaluation, time management, root
   policy, or environment.
3. Add the position, with its history and clock, to
   `benchmarks/never_lose_suite/` and record the move that holds (F4).
4. Choose one fix candidate.

The first case is the staged `6ef62f9998d12db4` review: `BASELINE_HORIZON_01`
in PR #27, covering plies 8, 10 and 12 at 5 s and 10 s, 1T and 12T, with
depth-capped controls. It runs on Local only. It needs the game's DLL
`32c32302…`, model `07b9ab0f…`, and the gitignored saved game.

### Phase 2: safety-first move choice

- Prerequisite: the single root policy from F2, with parity proven.
- Then add one default-off safety mode to that policy:
  - among candidates within a margin declared in advance, prefer the best
    worst case found by a deeper verification search;
  - avoid moves whose score falls at higher depth;
  - tablebase and terminal proofs still override everything, and a proved win
    is never given up.
- Gate: no regression on the never-lose suite, fewer gauntlet losses, and a
  non-inferiority SPRT whose margin and contract are declared before the run.

### Phase 3: a small verified opening book (MBs, not GBs)

- Take the positions our engine reaches in the first 12–16 plies of the
  development corpus and of Invincible 2 games. Analyse each for about 60 s at
  12T, in idle time only, at BelowNormal priority.
- Store move, score, depth, a stability flag and the producing identity in one
  hashed file (F7). Unstable lines get deeper analysis or are avoided.
- Label entries "deep-search verified", never "solved". The book stays
  default-off until an SPRT passes and it beats the no-book loss rate.

### Phase 4: middlegame and 7–10 piece strength without new tablebases

- Run the Round-2 diagnostic profile of qsearch and move generation. Then test
  one search candidate at a time, each justified by Phase 1 counterexamples
  and each with its own SPRT.
- NNUE v2 data:
  - Phase 1 loss positions and Invincible 2 games;
  - positions just above the 6-piece frontier, labelled by searching down into
    TB6 for exact leaves;
  - a fresh game-level sealed split, following the
    [NNUE roadmap](../../NNUE_ROADMAP.md);
  - the v1 architecture, unless the data justifies a change.
- The risk band is 7–10 pieces because of the opponent's claimed 10-piece
  database (section 3.5). A label far above the TB6 frontier is still a search
  observation, not an exact result.

### Phase 5: time and robustness

- The engine must never lose on time. Check deadline tails, cold and warm
  starts, undo and new game, and transitions into TB6.
- Keep the 12T default unless a 1/2/4/6/8/12-thread comparison proves
  otherwise.

### Phase 6: final acceptance and release

Build one integrated candidate, rerun all four gates, tag the release with its
manifest, and keep rollback to the accepted control.

## 6. Rules for every step

These come from the [project skill](../../.agents/skills/thai-makhos-engine/SKILL.md):

- Never modify `RULESET.json`, `makhos/core.py` or the accepted DLL.
- Change one concept at a time, and keep it default-off.
- Every strength change needs a paired pentanomial SPRT at 10s+0.1s with
  H0=0 and H1=+2.
- The GUI has priority, and batch work runs at BelowNormal.

## 7. Out of scope

The following are out of scope:

- resuming DFPN or proof work;
- 7-piece or larger tablebases;
- a shared-score TT;
- a Lazy SMP redesign;
- any claim of "proven" or "guaranteed" perfect play;
- bulk scraping of HosBase, or any load on it;
- using Invincible 2 or the HosBase End Game page as a bulk labelling oracle
  without the developer's permission.

## 8. Changes from the approved plan (2026-09-25 review)

The user confirmed these changes on 2026-09-25.

1. Phase 2 now has a prerequisite: the single root policy (F2). The
   `_choose`/`_safety_rank` path the plan named does not run for positions
   with more than 6 pieces (section 3.1).
2. Phase 4 widens the risk band from 7–8 to 7–10 pieces, if the opponent's
   10-piece claim holds (section 3.5).
3. Phase 0 now includes a feasibility and terms-of-use verdict, and the
   counting rule is distinct games only.
4. The planned addendum lives in this document on `main`, because
   `INVINCIBLE_2_ROADMAP_TH.md` exists only on the PR #25 branch. Link to it
   from there once F1 lands, rather than duplicating it.
5. Future-development rules F1–F9 and the Web/Local tags were added. The F3
   schema fix now comes before the recorder.
