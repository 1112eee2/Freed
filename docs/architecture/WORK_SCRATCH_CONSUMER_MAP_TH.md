# แผนผังผู้ใช้และหลักฐานไฟล์ใน work/ และ scratch/ (Phase 1A)

เอกสารนี้จัดทำขึ้นตามข้อกำหนดของ [TECH_DEBT_ROADMAP_TH.md](TECH_DEBT_ROADMAP_TH.md) (Phase 1A)
เพื่อจำแนก caller, import, command และ manifest binding ของทุกไฟล์ที่ติดตามใน `work/` (66 ไฟล์) และ `scratch/` (47 ไฟล์)
รวมทั้งหมด 113 ไฟล์ **ก่อนเริ่มการย้ายไฟล์จริงใน Phase 1B** เพื่อป้องกันไม่ให้เกิด broken imports, missing evidence หรือ benchmark unreplayability

## 1. สรุปภาพรวมการจำแนก (Classification Summary)

| หมวดหมู่ (Category) | จำนวนไฟล์ | ความหมายและการจัดการ |
|---|---|---|
| `CRITICAL_SHARED_HARNESS` | 1 | เครื่องมือแกนกลางที่ถูก import ข้ามโฟลเดอร์หนาแน่น (`scratch/nnue_full_suite_attestation.py`) — ย้ายได้เฉพาะเมื่อมี backwards-compatible wrapper |
| `LIVE_PRODUCTION_TOOL` | 1 | เครื่องมือ smoke test ประจำ release (`work/nnue_production_smoke.py`) — ย้ายไป `tools/verification/` พร้อม wrapper |
| `MAINTAINED_TOOL` | 3 | สคริปต์ freeze/audit และ monitor terminal UI — ย้ายไป `tools/` พร้อม wrapper |
| `MAINTAINED_RUNNER` | 9 | เครื่องมือรัน SPRT arena, thread audit telemetry, endgame benchmark — ย้ายไป `tools/arena/` หรือ `benchmarks/` |
| `MAINTAINED_TEST` | 7 | ชุดทดสอบเฉพาะของ tooling (`test_*.py`, `test_*.cjs`, `test_*.ps1`) — ย้ายไป `tests/tooling/` |
| `STAGED_SNAPSHOT` | 20 | ซอร์สโค้ด C17 snapshot ของการทดลอง Ancestor Delta (`work/nnue_ancestor_delta_v1/`) — **คงที่ถาวร (KEEP_IN_PLACE)** |
| `FROZEN_EVIDENCE` | 25 | หลักฐานการวินิจฉัย/ตรวจรับที่ปิดชุดแล้ว (endgame diagnosis, gate c integrity, thread audit report, markdown logs) — **คงที่ถาวร (KEEP_IN_PLACE)** |
| `HISTORICAL_AUDIT` | 17 | สคริปต์ diagnostic audit ในอดีต (IIR, root PVS shadow, TT legality, horizon attribution) — **คงที่ใน scratch/** จนกว่าจะ archive ตามรอบ |
| `HISTORICAL_BENCHMARK` | 6 | Micro-benchmarks ในภาษา C และ Python (AVX2, scalar, incremental, cold start) — **คงที่ใน scratch/** |
| `HISTORICAL_PARITY` | 6 | สคริปต์ตรวจความถูกต้องแบบขนานระหว่าง C scalar vs AVX2 vs Python — **คงที่ใน scratch/** |
| `HISTORICAL_TRAINER` | 6 | ส่วนประกอบของ pipeline ฝึกโมเดล NNUE รุ่น Pilot (float trainer, quantized export, contract gate) — **คงที่ใน scratch/** |
| `DISPOSABLE_SCRATCH` | 2 | สคริปต์สำรวจชั่วคราวที่ไม่มี consumer — **คงที่ใน scratch/** |

**รวมทั้งสิ้น:** 113 ไฟล์

---

## 2. เจาะลึกกลุ่มความเสี่ยงสูง (High-Risk Cluster Analysis)

### 2.1 Cluster 1: `scratch/nnue_full_suite_attestation.py` (ความเสี่ยงสูงสุด)

- **หน้าที่:** จัดการ ExclusiveSuiteLease (ล็อกการทดสอบไม่ให้ชนกับงานอื่น), ProductionOpenGuard, คำนวณ SHA-256 ของ source/test inventory และรัน full suite
- **ผู้เรียก (Inbound Callers - 19 ตำแหน่ง):**
  - `benchmarks/`: `endgame_latency.py`, `endgame_transition.py`, `native_endgame_ranked.py`, `tb3_artifact.py`, `results/endgame_transition_v1/full_suite_harness.py`, `results/endgame_transition_v1/non_endgame_harness.py`
  - `tools/`: `build_tb3.py`, `verify_endgame_c1.py`
  - `tests/`: `test_nnue_full_suite_attestation.py`, `test_nnue_sealed_test_evaluate.py`, `test_nnue_trainer_contract_gate.py`
  - `work/`: `freeze_nnue_gate_c.py`, `nnue_ancestor_delta_v1/preflight.py`, `nnue_gate_c_control.py`, `nnue_gate_c_runtime_audit.py`, `nnue_production_smoke.py`, `verify_nnue_guide_implementation.py`
  - `scratch/`: `nnue_sealed_test_evaluate.py`, `nnue_trainer_contract_gate.py`
  - เอกสารข้อกำหนด: `SKILL.md`, `NNUE_ROADMAP.md`, `experiment-evidence-ledger.md`
- **ข้อกำหนดการย้าย (Phase 1B):**
  1. สร้างตัวจริงที่ `tools/verification/full_suite_attestation.py`
  2. ปรับ `scratch/nnue_full_suite_attestation.py` ให้เป็น **Thin Wrapper** ที่ re-export symbols ทุกตัว (`ExclusiveSuiteLease`, `ProductionOpenGuard`, `execute_suite`, `inventory_sha256`, `source_inventory_paths`, `test_inventory_paths`)
  3. Wrapper ต้องจัดการ `sys.modules` และ relative path resolution ไม่ให้กระทบ `__file__` ที่ใช้ค้นหา root directory
  4. **ห้ามลบ** ไฟล์ใน `scratch/` จนกว่าทุก caller จะอัปเดต import ครบถ้วน

### 2.2 Cluster 2: SPRT Arena & Runtime Control

- **ไฟล์:** `work/nnue_gate_c_control.py`, `work/source_isolated_arena.py`, `work/run_sprt_step4_1000ms.py`, `work/nnue_gate_c_status_terminal.ps1`, `work/nnue_status_terminal.ps1`
- **หน้าที่:** จัดการ life-cycle ของ process เอนจิ้น 2 ตัว, การบันทึก pair logs, การคำนวณ LLR/SPRT, และ terminal monitoring
- **จุดเชื่อมโยง:** ถูกเรียกโดย CLI หรือ PowerShell terminal และผูกกับ manifest (`build/nnue_sprt_6t_vs_12t/manifest.json`, `build/nnue_gate_c_1000ms_seed20261105.json`)
- **ข้อกำหนดการย้าย (Phase 1B):** ย้ายตัวหลักไป `tools/arena/` พร้อมสร้าง thin wrapper ใน `work/` เพื่อให้คำสั่งเดิมที่ระบุในบันทึกและ scripts ทำงานต่อได้ 100%

### 2.3 Cluster 3: Thread Scaling Telemetry Audit

- **ไฟล์:** `work/nnue_thread_audit_collect.py`, `work/nnue_thread_audit_report.py`, `work/prepare_nnue_thread_audit.py`
- **หน้าที่:** เครื่องมือเก็บและวิเคราะห์ telemetry 5,760 observations ของ Phase 4
- **ผู้เรียก:** มี unit tests รับรอง (`work/test_nnue_thread_audit_collect.py`, `work/test_nnue_thread_audit_report.py`, `work/test_prepare_nnue_thread_audit.py`)
- **ข้อกำหนดการย้าย (Phase 1B):** ย้ายไป `tools/verification/` พร้อมย้าย unit tests ไป `tests/tooling/`

---

## 3. กลุ่มหลักฐานถาวร (Frozen Evidence & Snapshots - ห้ามย้าย/ห้ามแตะ)

ไฟล์เหล่านี้ถือเป็น **Historical Evidence** ที่มี hashes หรือ relative paths ผูกอยู่ในบันทึกการทดลองและเอกสารสถาปัตยกรรม ต้องคงไว้ที่ตำแหน่งเดิม:

1. **`work/nnue_ancestor_delta_v1/` (20 ไฟล์):** C17 snapshot ของ Candidate vs Control ใช้เปรียบเทียบในอนาคต
2. **`work/endgame_diagnosis_20260908/` (15 ไฟล์):** ข้อมูลการวินิจฉัยและสคริปต์ reproduction ของกรณีศึกษา endgame TB routing
3. **`work/gate_c_evidence_integrity_20260907/` (5 ไฟล์):** บันทึกผล full-suite, preflight และ validation logs ของ Gate C
4. **`work/nnue_thread_report_evidence_v1/` (3 ไฟล์):** หลักฐานการ validate รายงาน Phase 4 Thread Audit
5. **รายงาน Markdown ใน `work/` (2 ไฟล์):** `GUI_GAME_RECORDS_IMPLEMENTATION_TH.md`, `NNUE_THREAD_AUDIT_REPORT.md`

---

## 4. ลำดับการดำเนินการ Phase 1B (Migration Sequence)

การย้ายใน Phase 1B จะแบ่งเป็น 3 PR ย่อยเพื่อความปลอดภัยสูงสุด:

1. **PR 1B-1: Cluster Attestation & Production Smoke**
   - สร้าง `tools/verification/full_suite_attestation.py` และ `tools/verification/nnue_production_smoke.py`
   - วาง backwards-compatible stubs ที่ `scratch/nnue_full_suite_attestation.py` และ `work/nnue_production_smoke.py`
   - ตรวจสอบว่า callers ทั้ง 19 ไฟล์และ tests เดิมยังผ่าน 100%

2. **PR 1B-2: Cluster SPRT Arena & Telemetry Audit**
   - สร้าง `tools/arena/` และ `tools/verification/` สำหรับ arena runners และ telemetry scripts
   - วาง stubs ใน `work/` พร้อมคง CLI interface เดิม

3. **PR 1B-3: Tooling Tests Migration**
   - ย้าย `work/test_*.py` ไปยัง `tests/tooling/`
   - อัปเดต test runner discovery ให้ครอบคลุมตำแหน่งใหม่โดยไม่สูญเสีย coverage

---

## 5. ตารางรายละเอียดไฟล์ทั้งหมด 113 รายการ (Master Inventory Table)

| Path | หมวดหมู่ | บทบาท | แผนการจัดการ | Inbound Callers |
|---|---|---|---|---|
| `scratch/adaptive_native_candidate.py` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/adaptive_native_candidate.py` | 1 |
| `scratch/adaptive_root_hash_routing_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/adaptive_root_hash_routing_audit.py` | 1 |
| `scratch/aggregate_sprt_results.py` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/aggregate_sprt_results.py` | 1 |
| `scratch/critical_target_ladder.py` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/critical_target_ladder.py` | 0 |
| `scratch/early_tt_legality_check.c` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/early_tt_legality_check.c` | 0 |
| `scratch/gui_strength_stability_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/gui_strength_stability_audit.py` | 0 |
| `scratch/hce_eval_benchmark.c` | `HISTORICAL_BENCHMARK` | Standalone C or Python benchmark harness | **KEEP_IN_PLACE** → `scratch/hce_eval_benchmark.c` | 0 |
| `scratch/hce_pairwise_fit_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/hce_pairwise_fit_audit.py` | 1 |
| `scratch/hce_tuning_readiness_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/hce_tuning_readiness_audit.py` | 1 |
| `scratch/horizon_attribution_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/horizon_attribution_audit.py` | 1 |
| `scratch/iir_census_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/iir_census_audit.py` | 1 |
| `scratch/iir_quiet_candidate_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/iir_quiet_candidate_audit.py` | 0 |
| `scratch/middlegame_v5_acquire.py` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/middlegame_v5_acquire.py` | 1 |
| `scratch/nnue_avx2_benchmark.c` | `HISTORICAL_BENCHMARK` | Standalone C or Python benchmark harness | **KEEP_IN_PLACE** → `scratch/nnue_avx2_benchmark.c` | 1 |
| `scratch/nnue_avx2_parity.py` | `HISTORICAL_PARITY` | NNUE scalar/incremental/AVX2 parity or cost verification script | **KEEP_IN_PLACE** → `scratch/nnue_avx2_parity.py` | 0 |
| `scratch/nnue_avx2_raw_cost.py` | `HISTORICAL_PARITY` | NNUE scalar/incremental/AVX2 parity or cost verification script | **KEEP_IN_PLACE** → `scratch/nnue_avx2_raw_cost.py` | 0 |
| `scratch/nnue_avx2_update_benchmark.c` | `HISTORICAL_BENCHMARK` | Standalone C or Python benchmark harness | **KEEP_IN_PLACE** → `scratch/nnue_avx2_update_benchmark.c` | 1 |
| `scratch/nnue_avx2_update_parity.py` | `HISTORICAL_PARITY` | NNUE scalar/incremental/AVX2 parity or cost verification script | **KEEP_IN_PLACE** → `scratch/nnue_avx2_update_parity.py` | 0 |
| `scratch/nnue_avx2_update_raw_cost.py` | `HISTORICAL_PARITY` | NNUE scalar/incremental/AVX2 parity or cost verification script | **KEEP_IN_PLACE** → `scratch/nnue_avx2_update_raw_cost.py` | 0 |
| `scratch/nnue_float_trainer.py` | `HISTORICAL_TRAINER` | NNUE training pipeline or quantized export helper | **KEEP_IN_PLACE** → `scratch/nnue_float_trainer.py` | 2 |
| `scratch/nnue_full_suite_attestation.py` | `CRITICAL_SHARED_HARNESS` | Exclusive suite lease, production open guard, and source/test inventory attestation harness | **RELOCATE_WITH_WRAPPER** → `tools/verification/full_suite_attestation.py` | 13 |
| `scratch/nnue_incremental_benchmark.c` | `HISTORICAL_BENCHMARK` | Standalone C or Python benchmark harness | **KEEP_IN_PLACE** → `scratch/nnue_incremental_benchmark.c` | 1 |
| `scratch/nnue_incremental_parity.py` | `HISTORICAL_PARITY` | NNUE scalar/incremental/AVX2 parity or cost verification script | **KEEP_IN_PLACE** → `scratch/nnue_incremental_parity.py` | 0 |
| `scratch/nnue_incremental_raw_cost.py` | `HISTORICAL_PARITY` | NNUE scalar/incremental/AVX2 parity or cost verification script | **KEEP_IN_PLACE** → `scratch/nnue_incremental_raw_cost.py` | 0 |
| `scratch/nnue_pilot_finalize.py` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/nnue_pilot_finalize.py` | 2 |
| `scratch/nnue_pilot_resume.py` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/nnue_pilot_resume.py` | 2 |
| `scratch/nnue_quantized_export.py` | `HISTORICAL_TRAINER` | NNUE training pipeline or quantized export helper | **KEEP_IN_PLACE** → `scratch/nnue_quantized_export.py` | 7 |
| `scratch/nnue_quiet_leaf_acquire.py` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/nnue_quiet_leaf_acquire.py` | 11 |
| `scratch/nnue_readiness_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/nnue_readiness_audit.py` | 2 |
| `scratch/nnue_scalar_benchmark.c` | `HISTORICAL_BENCHMARK` | Standalone C or Python benchmark harness | **KEEP_IN_PLACE** → `scratch/nnue_scalar_benchmark.c` | 0 |
| `scratch/nnue_scaling_capacity_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/nnue_scaling_capacity_audit.py` | 1 |
| `scratch/nnue_scaling_checkpoint_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/nnue_scaling_checkpoint_audit.py` | 2 |
| `scratch/nnue_scaling_final_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/nnue_scaling_final_audit.py` | 9 |
| `scratch/nnue_scaling_full_run.py` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/nnue_scaling_full_run.py` | 7 |
| `scratch/nnue_scaling_health_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/nnue_scaling_health_audit.py` | 7 |
| `scratch/nnue_scaling_preflight.py` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/nnue_scaling_preflight.py` | 6 |
| `scratch/nnue_sealed_test_evaluate.py` | `DISPOSABLE_SCRATCH` | Ad-hoc scratch exploration script | **KEEP_IN_PLACE** → `scratch/nnue_sealed_test_evaluate.py` | 2 |
| `scratch/nnue_search_candidate_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/nnue_search_candidate_audit.py` | 0 |
| `scratch/nnue_trainer_contract_freezer.py` | `HISTORICAL_TRAINER` | NNUE training pipeline or quantized export helper | **KEEP_IN_PLACE** → `scratch/nnue_trainer_contract_freezer.py` | 8 |
| `scratch/nnue_trainer_contract_gate.py` | `HISTORICAL_TRAINER` | NNUE training pipeline or quantized export helper | **KEEP_IN_PLACE** → `scratch/nnue_trainer_contract_gate.py` | 17 |
| `scratch/nnue_trainer_input_inventory.py` | `HISTORICAL_TRAINER` | NNUE training pipeline or quantized export helper | **KEEP_IN_PLACE** → `scratch/nnue_trainer_input_inventory.py` | 5 |
| `scratch/nnue_trainer_preflight.py` | `HISTORICAL_TRAINER` | NNUE training pipeline or quantized export helper | **KEEP_IN_PLACE** → `scratch/nnue_trainer_preflight.py` | 6 |
| `scratch/quiet_leaf_hce_gap_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/quiet_leaf_hce_gap_audit.py` | 1 |
| `scratch/repetition_census_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/repetition_census_audit.py` | 0 |
| `scratch/root_architecture_quality_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/root_architecture_quality_audit.py` | 1 |
| `scratch/root_pvs_shadow_audit.py` | `HISTORICAL_AUDIT` | Historical diagnostic audit script | **KEEP_IN_PLACE** → `scratch/root_pvs_shadow_audit.py` | 0 |
| `scratch/server_cold_start_benchmark.py` | `HISTORICAL_BENCHMARK` | Standalone C or Python benchmark harness | **KEEP_IN_PLACE** → `scratch/server_cold_start_benchmark.py` | 0 |
| `work/GUI_GAME_RECORDS_IMPLEMENTATION_TH.md` | `FROZEN_EVIDENCE` | Historical diagnostic/implementation markdown report | **KEEP_IN_PLACE** → `work/GUI_GAME_RECORDS_IMPLEMENTATION_TH.md` | 1 |
| `work/NNUE_THREAD_AUDIT_REPORT.md` | `FROZEN_EVIDENCE` | Historical diagnostic/implementation markdown report | **KEEP_IN_PLACE** → `work/NNUE_THREAD_AUDIT_REPORT.md` | 1 |
| `work/endgame_diagnosis_20260908/DIAGNOSIS_TH.md` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 0 |
| `work/endgame_diagnosis_20260908/FULL_SUITE_ATTESTATION_TH.md` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 0 |
| `work/endgame_diagnosis_20260908/IMPLEMENTATION_PLAN_TH.md` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 1 |
| `work/endgame_diagnosis_20260908/IMPLEMENTATION_RESULT_TH.md` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 0 |
| `work/endgame_diagnosis_20260908/RUNTIME_BENCHMARK_TH.md` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 1 |
| `work/endgame_diagnosis_20260908/SPRT_MANIFEST_TH.md` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 0 |
| `work/endgame_diagnosis_20260908/arena_pilot_result.json` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 2 |
| `work/endgame_diagnosis_20260908/controls.json` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 2 |
| `work/endgame_diagnosis_20260908/controls.py` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 1 |
| `work/endgame_diagnosis_20260908/fix_verification.json` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 0 |
| `work/endgame_diagnosis_20260908/identities.json` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 1 |
| `work/endgame_diagnosis_20260908/reproduce.py` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 5 |
| `work/endgame_diagnosis_20260908/reproduction.json` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 2 |
| `work/endgame_diagnosis_20260908/runtime_benchmark_data.json` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 1 |
| `work/endgame_diagnosis_20260908/sprt_manifest.json` | `FROZEN_EVIDENCE` | Historical endgame diagnosis package and reproduction logs (2026-09-08) | **KEEP_IN_PLACE** → `work/endgame_diagnosis_20260908/` | 1 |
| `work/endgame_runtime_benchmark.py` | `MAINTAINED_RUNNER` | Endgame benchmark runner and multi-threaded worker | **RELOCATE_WITH_WRAPPER** → `benchmarks/endgame_runtime_benchmark.py` | 0 |
| `work/endgame_worker.py` | `MAINTAINED_RUNNER` | Endgame benchmark runner and multi-threaded worker | **RELOCATE_WITH_WRAPPER** → `benchmarks/endgame_worker.py` | 4 |
| `work/freeze_nnue_gate_c.py` | `MAINTAINED_TOOL` | Gate C contract and result freezer / attestation validator | **RELOCATE_WITH_WRAPPER** → `tools/verification/freeze_nnue_gate_c.py` | 0 |
| `work/gate_c_evidence_integrity_20260907/fixture_tests.log` | `FROZEN_EVIDENCE` | Historical Gate C preflight integrity logs and validation (2026-09-07) | **KEEP_IN_PLACE** → `work/gate_c_evidence_integrity_20260907/` | 1 |
| `work/gate_c_evidence_integrity_20260907/full_suite.log` | `FROZEN_EVIDENCE` | Historical Gate C preflight integrity logs and validation (2026-09-07) | **KEEP_IN_PLACE** → `work/gate_c_evidence_integrity_20260907/` | 6 |
| `work/gate_c_evidence_integrity_20260907/gate_c_preflight.json` | `FROZEN_EVIDENCE` | Historical Gate C preflight integrity logs and validation (2026-09-07) | **KEEP_IN_PLACE** → `work/gate_c_evidence_integrity_20260907/` | 1 |
| `work/gate_c_evidence_integrity_20260907/lifecycle_tests.log` | `FROZEN_EVIDENCE` | Historical Gate C preflight integrity logs and validation (2026-09-07) | **KEEP_IN_PLACE** → `work/gate_c_evidence_integrity_20260907/` | 1 |
| `work/gate_c_evidence_integrity_20260907/validation.json` | `FROZEN_EVIDENCE` | Historical Gate C preflight integrity logs and validation (2026-09-07) | **KEEP_IN_PLACE** → `work/gate_c_evidence_integrity_20260907/` | 4 |
| `work/nnue_ancestor_delta_v1/README.md` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 2 |
| `work/nnue_ancestor_delta_v1/candidate/native/makhos_native.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 27 |
| `work/nnue_ancestor_delta_v1/candidate/native/makhos_native_nnue.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 6 |
| `work/nnue_ancestor_delta_v1/candidate/native/makhos_nnue_avx2.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 10 |
| `work/nnue_ancestor_delta_v1/candidate/native/makhos_nnue_avx2_update.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 11 |
| `work/nnue_ancestor_delta_v1/candidate/native/makhos_nnue_incremental.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 10 |
| `work/nnue_ancestor_delta_v1/candidate/native/makhos_nnue_scalar.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 8 |
| `work/nnue_ancestor_delta_v1/candidate/native/makhos_tb4.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 8 |
| `work/nnue_ancestor_delta_v1/candidate/native/makhos_tb5.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 6 |
| `work/nnue_ancestor_delta_v1/candidate/native/makhos_tb6.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 3 |
| `work/nnue_ancestor_delta_v1/control/native/makhos_native.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 27 |
| `work/nnue_ancestor_delta_v1/control/native/makhos_native_nnue.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 6 |
| `work/nnue_ancestor_delta_v1/control/native/makhos_nnue_avx2.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 10 |
| `work/nnue_ancestor_delta_v1/control/native/makhos_nnue_avx2_update.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 11 |
| `work/nnue_ancestor_delta_v1/control/native/makhos_nnue_incremental.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 10 |
| `work/nnue_ancestor_delta_v1/control/native/makhos_nnue_scalar.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 8 |
| `work/nnue_ancestor_delta_v1/control/native/makhos_tb4.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 8 |
| `work/nnue_ancestor_delta_v1/control/native/makhos_tb5.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 6 |
| `work/nnue_ancestor_delta_v1/control/native/makhos_tb6.c` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 3 |
| `work/nnue_ancestor_delta_v1/preflight.py` | `STAGED_SNAPSHOT` | Candidate and control C17 source snapshot for ancestor delta experiment | **KEEP_IN_PLACE** → `work/nnue_ancestor_delta_v1/` | 12 |
| `work/nnue_gate_c_control.py` | `MAINTAINED_RUNNER` | SPRT arena orchestrator and gate verification harness | **RELOCATE_WITH_WRAPPER** → `tools/arena/nnue_gate_c_control.py` | 6 |
| `work/nnue_gate_c_runtime_audit.py` | `MAINTAINED_RUNNER` | Runtime audit and guide verification harness | **RELOCATE_WITH_WRAPPER** → `tools/verification/nnue_gate_c_runtime_audit.py` | 1 |
| `work/nnue_gate_c_status_terminal.ps1` | `MAINTAINED_TOOL` | Interactive PowerShell status terminal UI for match monitoring | **RELOCATE_WITH_WRAPPER** → `tools/arena/nnue_gate_c_status_terminal.ps1` | 3 |
| `work/nnue_production_smoke.py` | `LIVE_PRODUCTION_TOOL` | GUI and HTTP engine production verification smoke test | **RELOCATE_WITH_WRAPPER** → `tools/verification/nnue_production_smoke.py` | 2 |
| `work/nnue_status_terminal.ps1` | `MAINTAINED_TOOL` | Interactive PowerShell status terminal UI for match monitoring | **RELOCATE_WITH_WRAPPER** → `tools/arena/nnue_status_terminal.ps1` | 1 |
| `work/nnue_thread_audit_collect.py` | `MAINTAINED_RUNNER` | NNUE thread scaling telemetry collector and reporting harness | **RELOCATE_WITH_WRAPPER** → `tools/verification/nnue_thread_audit_collect.py` | 3 |
| `work/nnue_thread_audit_report.py` | `MAINTAINED_RUNNER` | NNUE thread scaling telemetry collector and reporting harness | **RELOCATE_WITH_WRAPPER** → `tools/verification/nnue_thread_audit_report.py` | 6 |
| `work/nnue_thread_report_evidence_v1/focused_tests.log` | `FROZEN_EVIDENCE` | Historical Phase 4 thread audit evidence and validation logs | **KEEP_IN_PLACE** → `work/nnue_thread_report_evidence_v1/` | 2 |
| `work/nnue_thread_report_evidence_v1/synthetic_input_example.jsonl` | `FROZEN_EVIDENCE` | Historical Phase 4 thread audit evidence and validation logs | **KEEP_IN_PLACE** → `work/nnue_thread_report_evidence_v1/` | 1 |
| `work/nnue_thread_report_evidence_v1/validation.json` | `FROZEN_EVIDENCE` | Historical Phase 4 thread audit evidence and validation logs | **KEEP_IN_PLACE** → `work/nnue_thread_report_evidence_v1/` | 4 |
| `work/prepare_nnue_thread_audit.py` | `MAINTAINED_RUNNER` | NNUE thread scaling telemetry collector and reporting harness | **RELOCATE_WITH_WRAPPER** → `tools/verification/prepare_nnue_thread_audit.py` | 4 |
| `work/run_sprt_step4_1000ms.py` | `MAINTAINED_RUNNER` | SPRT arena orchestrator and gate verification harness | **RELOCATE_WITH_WRAPPER** → `tools/arena/run_sprt_step4_1000ms.py` | 0 |
| `work/source_isolated_arena.py` | `MAINTAINED_RUNNER` | SPRT arena orchestrator and gate verification harness | **RELOCATE_WITH_WRAPPER** → `tools/arena/source_isolated_arena.py` | 1 |
| `work/test_gui_game_controls.cjs` | `MAINTAINED_TEST` | Focused test suite for tooling or components | **RELOCATE_WITH_WRAPPER** → `tests/tooling/test_gui_game_controls.cjs` | 3 |
| `work/test_gui_lifecycle.cjs` | `MAINTAINED_TEST` | Focused test suite for tooling or components | **RELOCATE_WITH_WRAPPER** → `tests/tooling/test_gui_lifecycle.cjs` | 5 |
| `work/test_nnue_gate_c_control.py` | `MAINTAINED_TEST` | Focused test suite for tooling or components | **RELOCATE_WITH_WRAPPER** → `tests/tooling/test_nnue_gate_c_control.py` | 2 |
| `work/test_nnue_gate_c_status_terminal.ps1` | `MAINTAINED_TEST` | Focused test suite for tooling or components | **RELOCATE_WITH_WRAPPER** → `tests/tooling/test_nnue_gate_c_status_terminal.ps1` | 1 |
| `work/test_nnue_thread_audit_collect.py` | `MAINTAINED_TEST` | Focused test suite for tooling or components | **RELOCATE_WITH_WRAPPER** → `tests/tooling/test_nnue_thread_audit_collect.py` | 0 |
| `work/test_nnue_thread_audit_report.py` | `MAINTAINED_TEST` | Focused test suite for tooling or components | **RELOCATE_WITH_WRAPPER** → `tests/tooling/test_nnue_thread_audit_report.py` | 2 |
| `work/test_prepare_nnue_thread_audit.py` | `MAINTAINED_TEST` | Focused test suite for tooling or components | **RELOCATE_WITH_WRAPPER** → `tests/tooling/test_prepare_nnue_thread_audit.py` | 3 |
| `work/verify_nnue_guide_implementation.py` | `MAINTAINED_RUNNER` | Runtime audit and guide verification harness | **RELOCATE_WITH_WRAPPER** → `tools/verification/verify_nnue_guide_implementation.py` | 0 |
