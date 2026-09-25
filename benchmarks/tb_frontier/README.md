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

This supports one hypothesis, TBPROBE_01: exact TB4–TB6 probes inside the
main search would correct these frontier scores in 7–10 piece positions.
It does not measure the playing-strength effect. That requires the TB6
artifacts, a same-source candidate and the paired gates on the Windows host.
Labels are exact only for the 4–6 piece positions themselves. They say nothing
about how often the main search reaches such positions.
