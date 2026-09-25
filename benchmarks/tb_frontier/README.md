# Tablebase frontier: how the main search scores exact endgames

Measured 2026-09-25 on Linux. This is measurement only; no engine change.

## Why it matters

The production main native search (`native/makhos_native.c`) never probes the
TB4–TB6 tablebases inside its tree. Only the separate C4 endgame search does,
and it runs only for roots with at most 6 pieces or a capture into 6 or fewer.

From an ordinary 7–10 piece root, every line that captures down to 6 or fewer
pieces is therefore scored by NNUE and search, not by the exact result. That
is the band where the practical no-loss track expects Invincible 2 to be exact.

## Result

[`draw_misjudgment.py`](draw_misjudgment.py) scores all 9,000 positions of
`corpora/exact_wdl_eval_v1.jsonl`. The corpus has exact WIN/DRAW/LOSS labels,
3,000 each, over 4, 5 and 6 pieces. The run used the Linux NNUE control
library `4178a8f7…` and NNUE v1 `07b9ab0f…`, with fresh depth-8 searches.
The full output is [`draw_misjudgment_control_depth8.json`](draw_misjudgment_control_depth8.json).

| Scorer | Exact draws scored beyond ±50 | Won or lost positions with the wrong sign |
|---|---:|---:|
| Static NNUE | 2,430 / 3,000 (81.0%) | 56 / 6,000 (0.9%) |
| Depth-8 search | 1,933 / 3,000 (64.4%) | 2 / 6,000 (0.03%) |

The search recognizes wins and losses almost perfectly, but systematically
scores exact draws as advantages or disadvantages.

A companion run on the same positions checked magnitudes.

- **Exact draws at depth 8:** the median absolute score was 69 and the 90th
  percentile 242. 38% of draws scored beyond ±100 and 15.6% beyond ±200.
- **Exact losses at depth 8:** 7.7% scored above −400.

Misjudged draws and weakly recognized losses therefore overlap between
roughly −100 and −400. That is where a defender can prefer a lost line over a
drawn one.

## Interpretation

This supports one hypothesis: exact TB4–TB6 knowledge inside the main search
would correct these frontier scores in 7–10 piece positions. It does not
measure the playing-strength effect. That requires the TB6 artifacts, a
same-source candidate and the paired gates on the Windows host. Labels are
exact only for the 4–6 piece positions themselves. They say nothing about how
often the main search reaches such positions.

## Candidate TBDRAW_01: exact draw cutoff (default-off)

Implemented behind `MAKHOS_SEARCH_TB_DRAW`, whose default build is
byte-identical to before. The rule is: at non-root main-search and
quiescence nodes, if the attached tablebase reports an exact DRAW, return 0.

This is the one rule that stays sound under project rules. A history-free
draw remains a draw under threefold repetition, which can only add draws.
WIN and LOSS are only bounds once repetition applies, so they keep the
ordinary search. The search already recognizes those almost perfectly. This
matches the C4 endgame search's own handling of exact draws.

The tablebase set and its probe come from the already loaded endgame
library. The files are not mapped a second time.

Tests (`tests/test_native_tb_draw.py`) cover:

- no hook in the default build;
- node-for-node parity while unattached;
- exact 0 on TB3 fixtures whose every reply is a draw, which NNUE scored up
  to +391 at depth 8;
- detach;
- the no-progress-horizon guard;
- persistent-search-only attach;
- probe errors failing closed;
- the root splitter.

A real-game smoke with only TB3 attached made 70K–573K probes and 2.6K–50K
draw cutoffs per game, with 0 errors.

### Windows gates for Local (the strength decision)

These are fixed before any strength run. Run them on the target host with the
GUI idle, under the workload lease at BelowNormal. If STRICT_KEY_01 is
promoted first, add `-StrictSearchKey` to **both** builds, so the only
difference remains the draw cutoff.

```powershell
.\build_nnue_search_candidate.ps1 -OutputDirectory build\tbdraw01\control
.\build_nnue_search_candidate.ps1 -OutputDirectory build\tbdraw01\candidate -TablebaseDrawCutoff
$c = 'build\tbdraw01\control\makhos_native_nnue_candidate_v1.dll'
$d = 'build\tbdraw01\candidate\makhos_native_nnue_candidate_v1.dll'
$m = 'build\nnue_quantized_v1\model_a.mknnue'
python -m unittest tests.test_native_tb_draw tests.test_sprt tests.tooling.test_build_orchestrator -v
# W1: 1T intrinsic with production TB4-6, standard strength bounds.
python -B -m makhos sprt --dev-library $d --master-library $c --dev-nnue-model $m --master-nnue-model $m --threads 1 --persistent-search --tb-draw-cutoff --time 10 --inc 0.1 --elo0 0 --elo1 2 --pairs 4000 --seed 20260928 --parallel-games 2 --output build\tbdraw01\sprt-w1-1t-10s.json --resume --games-dir build\tbdraw01\games-w1
# W2: production path, 12T and 512 MiB at a fixed 1 s per move, one game at a time.
python -B -m makhos sprt --dev-library $d --master-library $c --dev-nnue-model $m --master-nnue-model $m --threads 12 --hash-mb 512 --fixed-move-time-ms 1000 --tb-draw-cutoff --elo0 0 --elo1 2 --pairs 1000 --seed 20260929 --output build\tbdraw01\sprt-w2-12t-1s.json --resume --games-dir build\tbdraw01\games-w2
```

Decision rule:

- **PROMOTE** only if the full suite passes and W1 and W2 both PASS.
- **REJECT** on any FAIL.
- A capped run is **INCONCLUSIVE**.

The recorded games allow the losses in either run to be replayed and
classified afterwards.
