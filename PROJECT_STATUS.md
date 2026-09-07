# ThaiMakhosEngine: Project Status & Architecture Brief

> **Status as of: 2026-09-07**  
> Document for Lead Architect / AI Reviewer (ChatGPT / External Developers)

---

## 1. Executive Summary & Current Milestone

- **Engine Type**: High-performance Thai Makhos (Thai Checkers) engine with Bitboards, Alpha-Beta/PVS search, and NNUE evaluation.
- **Current Development Phase**: **Phase 9 — NNUE Production Promotion (Gate C)**
- **Hardware Profile**: 6 physical cores / 12 logical threads on Windows host with AVX2 support.

### Gate C Status (Live from Test Arena):
- **Gate A (Contract & Parity)**: **PASS** (Bit-exact parity between Python oracle, C scalar, incremental, and AVX2 vectorization).
- **Gate B (Intrinsic Strength 1T / 256 MiB / 10s+0.1s)**: **PASS** (+94.2 +/- 13.5 Elo vs accepted HCE).
- **Gate C — 1.0s / move (12T / 512 MiB)**: **FINISHED_PASS**  
  - 546 pairs / 1,092 games | W 472 D 396 L 224 | LLR +2.946 (Threshold +/- 2.944)  
  - **Result: +80.3 +/- 13.5 Elo** vs Accepted HCE baseline.
- **Gate C — 2.0s / move (12T / 512 MiB)**: **IN PROGRESS (282 pairs / 564 games)**  
  - W 235 D 214 L 115 | LLR +1.461 | **Result so far: +75.1 +/- 17.7 Elo** vs Accepted HCE.
  - Target: Reach LLR >= +2.944 to confirm PASS.

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

## 4. Immediate Next Milestones (Where Help is Needed)

1. **Complete Gate C 2.0s verification**:
   - Verify final convergence to LLR +2.944.
2. **NNUE Thread Scaling & Profile Audit**:
   - Audit scaling across 1 / 2 / 4 / 6 / 8 / 12 threads at 1s and 2s fixed time controls.
   - Optimize root search and SMP synchronization (mitigate Python root-splitter overhead).
3. **Search & Pruning Enhancements**:
   - Late Move Reductions (LMR) tuning.
   - Null Move Pruning / Reverse Futility Pruning for Thai Makhos dynamics.
   - History heuristics & killer move ordering tailored to high-branching capture chains.
4. **NNUE v2 Pipeline Preparation**:
   - Feature engineering improvements beyond 137 features (e.g. piece interaction / square relations).
   - Training dataset expansion and loss weighting.

---

## 5. Local vs Repository Artifacts

- **On GitHub Repository**:
  - Full C & Python source code (`native/`, `makhos/`)
  - Web GUI (`web/`)
  - Unit tests suite (`tests/` - 393 tests)
  - Active NNUE model weights (`build/nnue_quantized_v1/model_a.mknnue`)
  - Accepted baseline DLL (`build/makhos_native_accepted.dll`)
  - Contract & Verification specs (`build/nnue_gate_c_contract_v1.json`, `VERIFICATION.md`)
- **Kept Local (Excluded from Git due to 7.8 GB size)**:
  - Tablebase binaries: `tb4_np80.bin`, `tb5_np80.compact.bin`, `tb6_np80.compact.bin` (5.4 GB).
  - Test run logs and 35,000 game self-play analysis JSON shards.
