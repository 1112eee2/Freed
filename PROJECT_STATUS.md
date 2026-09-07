# ThaiMakhosEngine: Project Status & Architecture Brief

> **Status as of: 2026-09-07**  
> Document for Lead Architect / AI Reviewer (ChatGPT / External Developers)

---

## 1. Executive Summary & Current Milestone

- **Engine Type**: High-performance Thai Makhos (Thai Checkers) engine with Bitboards, Alpha-Beta/PVS search, and NNUE evaluation.
- **Current Development Phase**: **Phase 9 — NNUE Production Promotion (Gate C)**
- **Hardware Profile**: 6 physical cores / 12 logical threads on Windows host with AVX2 support.

### Gate C Status (Historical host snapshot; revalidate before use):

The authoritative routing record is [current-state.md](.agents/skills/thai-makhos-engine/references/current-state.md). The counters below are a historical snapshot, not a live observation from a GitHub checkout. Run `python -B work/nnue_gate_c_control.py preflight` for a read-only local prerequisite report; it does not inspect the original host or authorize a launch.
- **Gate A (Contract & Parity)**: **PASS** (Bit-exact parity between Python oracle, C scalar, incremental, and AVX2 vectorization).
- **Gate B (Intrinsic Strength 1T / 256 MiB / 10s+0.1s)**: **PASS** (+94.2 +/- 13.5 Elo vs accepted HCE).
- **Gate C — 1.0s / move (12T / 512 MiB)**: **FINISHED_PASS**  
  - 546 pairs / 1,092 games | W 472 D 396 L 224 | LLR +2.946 (Threshold +/- 2.944)  
  - **Result: +80.3 +/- 13.5 Elo** vs Accepted HCE baseline.
- **Gate C — 2.0s / move (12T / 512 MiB)**: **LAST REPORTED IN PROGRESS (282 pairs / 564 games); current state unverified here**
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

1. **Verify the existing Gate C 2.0s run on the original Windows host**:
   - Use the manifest-bound monitor and unchanged frozen contract. Never restart a completed PASS/FAIL or cap-INCONCLUSIVE checkpoint.
2. **Production smoke and reversible NNUE v1 promotion review**:
   - Both independent Gate C controls must PASS first. Verify real GUI/runtime identity and preserve accepted HCE rollback.
3. **NNUE Thread Scaling & Profile Audit**:
   - After production review, compare 1 / 2 / 4 / 6 / 8 / 12 threads at 1s and 2s, total Hash 512 MiB, at least 96 positions and five balanced repetitions.
4. **One evidence-selected Elo experiment**:
   - Select from measured bottlenecks under [DEVELOPMENT_PLAN_TH.md](DEVELOPMENT_PLAN_TH.md). Staged ancestor delta remains unproven; future model work requires a fresh development/sealed split and its own frozen contract.

---

## 5. Local vs Repository Artifacts

- **On GitHub Repository**:
  - Full C & Python source code (`native/`, `makhos/`)
  - Web GUI (`web/`)
  - Unit tests suite (`tests/` - 393 tests)
  - Active NNUE model weights (`build/nnue_quantized_v1/model_a.mknnue`)
  - Accepted baseline DLL (`build/makhos_native_accepted.dll`)
  - Contract & Verification specs (`build/nnue_gate_c_contract_v1.json`, `VERIFICATION.md`); the contract is stored as LF in Git but its frozen SHA binds Windows CRLF bytes. Preflight diagnoses this without rewriting or accepting a different identity.
- **Kept Local (Excluded from Git due to 7.8 GB size)**:
  - Tablebase binaries: `tb4_np80.bin`, `tb5_np80.compact.bin`, `tb6_np80.compact.bin` (5.4 GB).
  - Test run logs and 35,000 game self-play analysis JSON shards.

The frozen NNUE candidate DLL, Gate C results/run manifest and bound smoke/full-suite evidence are also absent from this checkout. Preserve and verify those artifacts on the original host; missing local evidence does not mean the match has not started.
