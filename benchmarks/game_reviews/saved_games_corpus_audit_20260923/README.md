# Saved-game replay audit — 2026-09-23

## Result

All three saved GUI games replay legally through the verified rules reference.
The replayed move sequence, every stored `position_history` entry, final
position, and reversible-ply clock agree with the records: **197 plies checked,
0 mismatches**. This makes the records usable as development/triage inputs; it
does **not** make user adjudications ground truth or establish engine strength.

| Game | Plies | Engine side | Result label | Rules result | Triage |
|---|---:|---|---|---|---|
| `e26872d254ea0041` | 81 | Black | Rules: Black win | Terminal: Black wins by `no_legal_move` | Completed engine win; already has a separate detailed review. |
| `6ef62f9998d12db4` | 62 | Red | User adjudicated Black win | Ongoing, not terminal | Highest-priority review: engine was adjudicated lost, but the saved game is not a rules loss. The last recorded engine decision is ply 62, `23-5`, score `-271`, WDL `LOSS..DRAW`, depth 9. This is metadata for the pre-move root, not proof of the final position's outcome. |
| `f65be3eb5558f9af` | 54 | Red | User adjudicated draw | Ongoing, not terminal | Useful hold/control case, not a rules draw. The last recorded engine decision is ply 54, `9-5`, score `0`, WDL `DRAW`, depth 9; this describes that search root, not an adjudicated proof for the final position. |

The two adjudicated games are especially useful because their full move history
and clock can be replayed, but their labels must remain separate from natural
terminal outcomes. No retrospective score is promoted to solved truth.

## Screening anchors for the engine-adjudicated game

Recorded move metadata gives a narrow first review window, not a blunder verdict:

- At engine ply 8, Red played `7-10` (score `-42`); its PV expected Black `18-14`,
  but the human played `27-23`. The next recorded Red root at ply 10 scored `-55`.
- At engine ply 10, Red played `3-7` (score `-55`); its PV expected `23-19`, but
  Black played `28-24`. The next recorded Red root at ply 12 scored `-140` and
  selected `5-9`.

Those cross-position score changes are only triage signals. The root state,
history, clock, elapsed-time search and alternatives must be freshly reproduced
before attributing any loss of value to one move.

## Reproducibility and identities

`manifest.json` binds each raw game file by SHA-256, the replay counts, rules
result, and recorded engine provenance. The records all name the same native
candidate SHA-256
`32c323026a7f78ccd9c4013fc3067422a564ee3d0a6ade4f1ce5c62356747e79` and NNUE
model SHA-256 `07b9ab0f83e253cb74b2acd2bd5291f5f91eb086e042790f33ea0a8c0914164c`.
The native candidate and model files were re-hashed locally and matched those
recorded identities. The accepted DLL remains a different artifact and was not
changed.

The audit used `makhos.game_analysis.load_game_record()` and
`replay_game()` with project rules, then compared the reconstructed sequence
against each JSON `position_history`, `final_position`, and `reversible_plies`.
No engine search was run. Arena was open during this turn, so GUI/resource
priority was preserved.

## Next strength-work action

When the GUI workload is idle, review `6ef62f9998d12db4` first using its exact
history and clock. Bind any fresh search to the recorded DLL/model hashes, keep
1T diagnostic runs separate from production 12T, and inspect the earliest
reproducible loss of value before calling anything a blunder. Use the draw case
as a separate hold/control review. Neither record is an acceptance set or
independent SPRT evidence; keep both in development/regression only.

The first profile-matched 12T diagnostic is staged for plies 8, 10, and 12 at
the recorded 5 s budget plus a 10 s horizon check. It is intentionally not
launched while Arena is open:

```powershell
python -B -m makhos analyze-game `
  --game saved_games/game_20260912T171858412589Z_b1154bad339246e7b40645405267ce23.json `
  --library build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll `
  --nnue-model build/nnue_quantized_v1/model_a.mknnue `
  --side engine --rules-profile project `
  --ply 8 --ply 10 --ply 12 `
  --budget-ms 5000 --budget-ms 10000 `
  --threads 12 --hash-mb 512 --max-positions 3 `
  --output benchmarks/game_reviews/saved_games_corpus_audit_20260923/analysis_6ef_ply8_10_12_12t.json
```

No engine, rules, model, accepted artifact, checkpoint, or experiment state was
changed by this audit.
