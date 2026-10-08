# NULL_EVAL_01-L1W: restart after lost evidence (2026-10-08)

The first L1W attempt started on 2026-09-27 at 12:15Z from a run tree
exported into the session scratchpad under `%TEMP%`. On 2026-10-04 at 20:51
local time, Windows temp cleanup deleted every file in that tree, including
`stdout.log`, `stderr.log` and `sprt.json`. No final result was ever read.
The last observation, at 12:19Z on 2026-09-27, was pair 16: 12/13/7,
pentanomial 0/5/3/6/2, LLR +0.13, INCONCLUSIVE.

The run was restarted from pair 0 on 2026-10-08 with the contract's exact
command and seed, in the durable tree `build/runs/nullev_l1w/` (`git archive`
of `7a305fe` plus the two contract DLLs). Before launch the candidate
`e4d7b0d3…`, control `8b82fef8…`, model `07b9ab0f…`, `makhos/sprt.py`
`cf82416b…` and `sprt_handler.py` `594ac584…` were re-hashed and match the
contract. The new process (PID 14488) was created at
2026-10-08T12:07:42.59Z at BelowNormal priority.

This is a restart after evidence loss, not a reseed and not a contract change.
The lost partial tallies are not merged into the restarted run. The decision
rule in `contract_l1w.json` applies unchanged to the restarted run alone.
