# Positional Loss Diagnosis

Use this workflow when an independent opponent wins by space, restriction,
locking, promotion pressure, or another long-term plan rather than an obvious
tactical blunder.

## Preserve trustworthy evidence

1. Export `thai-makhos-game-v1` JSON from the GUI.
2. Preserve games from both colours and record equal clocks where possible.
3. Prefer new records containing `actor` and the exact engine settings on every
   engine-controlled ply. A side selector changed during a game makes final
   settings insufficient evidence.
4. Reject illegal moves, wrong side-to-move labels, final-position mismatch,
   or a reconstructed no-progress clock mismatch. Never repair such records by
   guessing.

The parser in `makhos/game_analysis.py` replays every edge with the verified
Python rules and assigns a stable content-derived game ID. The schema is
`schemas/thai-makhos-game-v1.schema.json`.

## Compare search budgets

Start with one non-forced engine ply so a long run cannot accidentally consume
many minutes:

```powershell
python -B -m makhos analyze-game `
  --game path\to\game.json `
  --side engine `
  --budget-ms 2000 `
  --budget-ms 5000 `
  --budget-ms 20000 `
  --threads 1 `
  --hash-mb 64 `
  --max-positions 1 `
  --output build\analysis.json
```

Use `--ply N` to reproduce a reported divergence and `--max-positions` only
after estimating total runtime. Clear the persistent TT between budgets so the
longer observation does not inherit work from the shorter one. Record the DLL
path and SHA-256 in every report.

Interpret classifications as follows:

- `stable`: all tested budgets chose the same move. If the plan is bad, suspect
  evaluation or a horizon beyond the longest tested budget.
- `short-search-divergence`: the shortest budget differs while the two longer
  budgets agree. Prioritize search efficiency or time management.
- `long-horizon-divergence`: the longest budget still changes the move. Extend
  analysis before assigning blame to evaluation.
- `settings-or-version-mismatch`: the replayed move differs from the shortest
  reproduction. Match the recorded per-ply DLL/settings before drawing a
  strength conclusion.

## Read the evaluation trace

`trace_evaluation` decomposes the exact current handcrafted score into material,
man/king PST, support, back rank, passed men, simplification, king edge, and king
mobility. Randomized parity tests guard it against the allocation-free playing
evaluator and native evaluator.

The trace exposes what the current evaluator values; it does not prove that a
missing term should receive a particular weight. Add positions immediately
before the first strategic divergence to a versioned corpus, label them with
independent games, exact tablebases, long search, or expert judgement, and keep
held-out positions before tuning. Promote any playing-strength change only
through the normal paired pentanomial SPRT gate.
