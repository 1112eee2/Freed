# ThaiMakhosEngine: Project Status & Architecture Brief

> **Status as of: 2026-09-08**  
> Document for Lead Architect / AI Reviewer (ChatGPT / External Developers)

---

## 1. Executive Summary & Current Milestone

- **Engine Type**: High-performance Thai Makhos (Thai Checkers) engine with Bitboards, Alpha-Beta/PVS search, and NNUE evaluation.
- **Current Development Phase**: **Phase 9 — NNUE Production Promotion (Gate C)**
- **Hardware Profile**: 6 physical cores / 12 logical threads on Windows host with AVX2 support.

### Gate C Status: **BOTH TIME CONTROLS FINISHED_PASS** (Completed 2026-09-08)

The authoritative routing record is [current-state.md](.agents/skills/thai-makhos-engine/references/current-state.md). Both independent time controls have reached conclusive PASS:
- **Gate A (Contract & Parity)**: **PASS** (Bit-exact parity between Python oracle, C scalar, incremental, and AVX2 vectorization).
- **Gate B (Intrinsic Strength 1T / 256 MiB / 10s+0.1s)**: **PASS** (+94.2 +/- 13.5 Elo vs accepted HCE).
- **Gate C — 1.0s / move (12T / 512 MiB)**: **FINISHED_PASS**  
  - 546 pairs / 1,092 games | W 472 D 396 L 224 | LLR +2.946 (Threshold +/- 2.944)  
  - **Result: +80.3 +/- 13.5 Elo** vs Accepted HCE baseline.
- **Gate C — 2.0s / move (12T / 512 MiB)**: **FINISHED_PASS** (Completed at 2026-09-08 08:41 +07:00)
  - 554 pairs / 1,108 games | W 477 D 404 L 227 | LLR +2.946 (Threshold +/- 2.944)  
  - **Result: +79.8 +/- 12.9 Elo** vs Accepted HCE baseline.
  - JSON artifact: `build/nnue_gate_c_2000ms_seed20261106.json` (SHA-256: `B32B043F7144B7DC85E982FA0EF44342D22E21773FF969D2C3859D468A2AF19F`).
- **Production Promotion Attestation**: Published at `releases/nnue-v1-20260908/promotion_attestation.json` and `PROMOTION_ATTESTATION.md`, formally binding commit `2cec9f4`, Gate C evidence, HTTP smoke, and reversible HCE fallback.

---

## 2. Active Technical Architecture

1. **NNUE Architecture (`thai-makhos-shared-137-v1`)**:
   - **Inputs**: 137 sparse binary features per perspective (piece positions, king flags, clock buckets).
   - **Accumulator**: Dual 128-wide perspective accumulators.
   - **Hidden Layer**: 32 units with Clipped ReLU.
   - **Output**: 1 scalar evaluation score.
   - **Active Model**: `build/nnue_quantized_v1/model_a.mknnue` (43 KB).
   - **Inference**: Hand-optimized AVX2 SIMD in C (`native/makhos_nnue_avx2.c`, `native/makhos_nnue_avx2_update.c`).
2. **Search Engine**:
   - Bitboard move generation with Thai-specific rules in `native/makhos_native.c`.
   - Iterative deepening, Transposition Table, Quiescence search with capture chains.
3. **Endgame Tablebases**:
   - Solved and verified tablebases up to 6 pieces (`tb4`, `tb5`, `tb6_np80` ~5.4 GB total on local disk).
   - Authoritative over NNUE/HCE when probing endgame states.

---

## 3. Golden Rules & Invariants (Strict Policy)

1. **NEVER modify `RULESET.json` or `makhos/core.py`**:
   - `makhos/core.py` is the verified Python reference oracle for official Thai Makhos rules.
2. **Preserve exact Thai rules**:
   - Mandatory capture, Thai king landing (halt immediately on the square directly behind the captured piece), immediate captured-piece removal, end-of-turn promotion, threefold repetition, and 80-ply no-progress limit.
3. **Correctness Gates**:
   - Any move generation or state changes must pass Perft through depth 10 and differential verification.
4. **Local Hardware Constraints**:
   - Optimized for 6-core/12-thread host. Hash budget = 512 MiB total.

---

## 4. Current Milestone Status & Next Steps

1. **Gate C 1.0s & 2.0s SPRT Verification**: **COMPLETED (FINISHED_PASS)**
   - Both controls passed conclusively (+80 Elo vs baseline HCE).
2. **Production Smoke & Web GUI Promotion to NNUE v1**: **COMPLETED (PROMOTED)**
   - Hash-bound release manifest frozen at `releases/nnue-v1-20260908/manifest.json`.
   - Standalone promotion attestation published: `releases/nnue-v1-20260908/promotion_attestation.json`.
   - Production pointer active at `config/gui_release.json` defaulting to `nnue` profile.
   - Reversible HCE rollback preserved via `--release-profile hce`.
   - Real HTTP smoke passed; 403 Python tests + 3 Node.js tests passing 100%.
3. **Phase 4 — NNUE Thread-Scaling Audit**: **COMPLETED (5,760/5,760 observations)**
   - Measured native matrix: 1, 2, 4, 6, 8, 12 threads @ 1000ms & 2000ms, 512 MiB Hash across 96 positions (5 repetitions).
   - Full observations: `build/nnue_thread_scaling_measured_v1/observations.jsonl` (7.2 MB, SHA-256: `254FB1C685E458F7C43DCCE4C4DBB1518874FA79BC319E85BC9554689EF4384F`).
   - Authoritative report: `build/nnue_thread_scaling_measured_v1/report.json` (SHA-256: `5F19083ADE11DD9E76C9B1AC90102376328B988D1D1DF5722B20856BF477757E`).
   - Audit Limitations & Methodology Clarifications:
     - 5,760 observations is an offline diagnostic benchmark, NOT complete production profile coverage (`profile_coverage_complete=false`, `strength_evidence=false`).
     - Collector set `wall_ms=1.0` and `score=0` directly for forced moves in software logic; not a hardware timer measurement.
     - Tablebase validation in collector checked file size and manifest checksums; did not route through full Engine endgame oracle (10 playout positions have <= 6 pieces where production engine routes to tablebase).
     - Telemetry for active workers, coordination, NNUE time, CPU frequency, and temperature remained unmeasured (`null`). Branch starvation and SMT saturation are mechanistic hypotheses consistent with empirical data, not hardware-counter measurements; root barrier is architectural code logic.
     - Playout subset comprises 66 positions x 5 reps = 330 observations per configuration (30 other positions are 14 forced + 16 clock-edge). 98.5% move stability represents 65/66 positions.
     - Overshoot p95 is <= 4.4ms across most configurations, but 2T @ 2000ms playout reached p95 = 8.044ms.
4. **Phase 5 — Approved Experiment A: Direct 6T vs 12T Superiority SPRT**:
   - Question: Does 6T provide higher Elo than production 12T under fixed realistic time budgets (1000ms & 2000ms)?
   - Hypothesis: On a 6 physical core / 12 logical thread host (AMD Ryzen 5 5600H), reducing threads from 12T to 6T may increase playing strength by eliminating SMT pipeline contention and idle thread overhead, despite lower total node count.
   - Candidate: NNUE v1 6T (512 MiB Hash).
   - Control: NNUE v1 12T (512 MiB Hash).
   - Both engines use identical production DLL and `model_a.mknnue`. Two distinct file copies used to satisfy CLI validation.
   - Statistical Framework: Pentanomial SPRT, H0=0, H1=+2 Elo, alpha=beta=0.05, LLR bounds +/- 2.944438979, cap 10,000 pairs.
   - Time Controls: Fixed 1000ms (seed 20261108) and 2000ms (seed 20261109) evaluated sequentially with `parallel-games=1`.
   - Tablebases: Native 3-piece and ranked 4/5/6 pieces verified before starting.
   - Superiority testing note: A FAIL or INCONCLUSIVE result does not prove equality; it indicates lack of statistically significant superiority under the defined contract.

---

## 5. Local vs Repository Artifacts

- **On GitHub Repository**:
  - Full C & Python source code (`native/`, `makhos/`)
  - Web GUI (`web/`)
  - Unit tests suite (`tests/` - 403 tests)
  - Active NNUE model weights (`build/nnue_quantized_v1/model_a.mknnue`)
  - Accepted baseline DLL (`build/makhos_native_accepted.dll`)
  - Gate C results (`build/nnue_gate_c_1000ms_seed20261105.json`, `build/nnue_gate_c_2000ms_seed20261106.json`)
  - Contract & Verification specs (`build/nnue_gate_c_contract_v1.json`, `VERIFICATION.md`)
  - GUI Release manifest & config (`releases/nnue-v1-20260908/manifest.json`, `config/gui_release.json`)
- **Kept Local (Excluded from Git due to 7.8 GB size)**:
  - Tablebase binaries: `tb4_np80.bin`, `tb5_np80.compact.bin`, `tb6_np80.compact.bin` (5.4 GB).
  - Test run logs and 35,000 game self-play analysis JSON shards.

