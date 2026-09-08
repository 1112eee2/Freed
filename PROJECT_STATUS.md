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
   - Production pointer active at `config/gui_release.json` defaulting to `nnue` profile.
   - Reversible HCE rollback preserved via `--release-profile hce`.
   - Web GUI race condition fixed (`AbortController` & `gameGeneration` in `web/app.js`).
   - Forced-move latency fixed from 12s down to 2.5ms (bypassing redundant TB3 init).
   - Real HTTP smoke passed; all 403 Python tests + 3 Node.js lifecycle tests passing 100%.
3. **Immediate Next Action — NNUE Thread-Scaling Audit**:
   - Run multi-thread scaling benchmark comparing 1, 2, 4, 6, 8, 12 threads at 1s and 2s fixed time controls across 96 balanced test positions (5 repetitions).
   - Generate analytical report via `work/nnue_thread_audit_report.py`.
4. **Subsequent Milestone — Evidence-Driven Elo Enhancement**:
   - Move ordering, search pruning, and ancestor delta accumulator evaluation based on the thread audit profile.

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

