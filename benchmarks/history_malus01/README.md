# HISTORY_MALUS_01: bounded quiet history with a malus

Status 2026-10-09: **candidate, default-off, Windows screen PASS, not
promoted.** Production, the GUI release, the accepted DLL, the model and the
default build are unchanged.

`MAKHOS_HISTORY_MALUS=1` with `MAKHOS_HISTORY_GRAVITY=1` (build switch
`-HistoryMalus`) bounds quiet history to ±16384 and, after a quiet cutoff,
lowers the quiet moves searched before it by the same gravity step. See the
commit message of `65718c6` for the rationale.

## QA (2026-10-08)

- Rebuilt from `65718c6`: candidate `5d1445ac…` and strict control
  `8b82fef8…`, byte-identical to the 2026-09-27 builds.
- `tests.test_native_history_malus`: 5/5.
- Review: moves are fully ordered before the move loop, so `moves[0..index)`
  are the moves tried before the cutoff. The cutoff bonus excludes captures,
  while the malus also excludes promotions; this asymmetry is minor and was
  accepted.

## Windows screening match (HISTORY_MALUS_01-L1W)

Contract: [`contract_l1w.json`](contract_l1w.json), declared before the first
game. 1 thread, no tablebases, 2s+0.02s, seed 20261013, H0 = 0, H1 = +5,
capped at 2,000 pairs.

**PASS at pair 1,021:** 738/684/620, pentanomial 61/183/442/247/88,
LLR +2.95, **+20.1 ± 10.6 Elo**. Raw output is in
[`sprt_l1w_20261008/`](sprt_l1w_20261008/); stderr is empty.

Next: the Windows W1 (1T 10s+0.1s with TB4–6) and W2 (12T, fixed 1 s) gates,
with the owner's agreement, as for LMR_LOG_01 and NULL_EVAL_01.
