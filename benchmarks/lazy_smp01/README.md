# LAZY_SMP_01 (Track F)

All Threads search the root and share one lockless TT. The search and NNUE
are SEARCH_INT_01's; only the parallel search differs from the root split.

| | |
|---|---|
| Candidate | `build/lazy_smp_01/candidate/makhos_native_nnue_candidate_v1.dll`, SHA-256 `B397B084…5768`, source 7253326 |
| Control | SEARCH_INT_01 `build/search_int01/candidate/…`, SHA-256 `5ED1FE18…EAC9` |
| Flags | SEARCH_INT_01 plus `MAKHOS_NATIVE_LAZY_SMP`, `MAKHOS_NATIVE_LAZY_SMP_SKIP_DEPTH`, `MAKHOS_SHARED_TT`, `MAKHOS_LOCKLESS_TT` ([manifest](candidate_build_manifest.json)) |
| Status | F3 SPRT prepared, not started |

## Threads and Hash

- Threads 1..1024. Workers, jobs and thread handles are allocated per search
  handle; each worker is joined with its own wait.
- Hash is the total TT budget in MiB for all Threads, with no rounding:
  4,096 to 2^36 entries of 40 bytes. A power-of-two entry count keeps the
  private TT's mask index, so one thread replays the control exactly; any
  other count maps keys by multiply-high and uses the whole budget.
- A TT of 64 MiB or more is cleared by up to 64 threads (2 GiB: 0.48 s with
  4 Threads).

Only `makhos sprt --lazy-smp` selects it, for the candidate side.
`--threads`/`--dev-threads` then accept 1..1024; other engines stay at 1..12.
The GUI, the server and the text protocol keep the root split with 1..12
Threads and 4..1024 MB. If F3 passes, Lazy SMP becomes their default and
those limits are raised with it.

## Evidence

| File | Result |
|---|---|
| [parity_1t_d13_960_2.5mb.json](parity_1t_d13_960_2.5mb.json), [parity_1t_d13_960_40mb.json](parity_1t_d13_960_40mb.json) | b397b084 at one thread equals 5ed1fe18 (move, score, depth, nodes, PV) on all 960 middlegame_search_v5 positions at depth 13, TT 2^16 and 2^20 |
| [parity_1t_d13_960.json](parity_1t_d13_960.json) | the same check on the F1 build (ad5dff5) |
| [f2_scaling.json](f2_scaling.json) | F1 build, 24 positions, 1 s, 512 MiB: mean depth 22.8 at 1T, 25.2 at 12T; root split 12T reaches 20.6 |
| [m1_hw_ceiling.json](m1_hw_ceiling.json) | 12 independent 1T processes give about 5.6x one process: the machine's NPS ceiling, not a search result |

Reproduce the one-thread parity with
`tools/verification/lazy_smp_parity.py --hash-mb 2.5` (or 40); the Hash must
give a power-of-two TT.

## F3 SPRT

Lazy SMP 12T against root split 12T: 512 MiB, fixed 1 s per move, TB4-6 and
the C4 endgame library, H0 = 0, H1 = +5, at most 1,000 pairs, seed 20261019.

`tools/smp/prepare_f3_sprt.py --commit 7253326` froze the run tree in
`D:\ThaiMakhosEngine\build\runs\lazysmp_f3` on 2026-10-18 and checked the three
artifact hashes. Start `launch_f3.py` there only when no other gate or data
run is using the CPU and the GUI is closed.
