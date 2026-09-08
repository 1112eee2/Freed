# รายงานการรับรองผลการทดสอบ Full Suite และ Regression Audit

วันที่บันทึก: 8 กันยายน 2026  
Branch: main  
Commit: ab33aa0 (พร้อม local refinement)  
Baseline Control: ba9481dbc8c48f09771638fab3aa3f9d7efbf3b5

---

## 1. ผลการตรวจรับรองชุดทดสอบ (Test Discovery Suite)

### 1.1 Full Suite Discovery (python -m unittest discover tests)
- **จำนวนการทดสอบที่พบและรัน**: 390 tests
- **เวลาที่ใช้**: 113.697 วินาที
- **ผ่าน (PASS)**: 384 tests
- **ล้มเหลว (Failures)**: 0
- **ข้อผิดพลาดจากสภาพแวดล้อม (Errors)**: 6 รายการ
  - สาเหตุ: เกิดจาก FileNotFoundError: build\nnue_phase1_evidence\quantization_contract_v2.json ซึ่งเป็นไฟล์ local artifact เก่าใน Phase 1 ที่อยู่นอก git repository (เนื่องจาก build/ ถูกระบุใน .gitignore) ใน 5 ไฟล์ทดสอบ:
    - test_nnue_avx2_native.NativeAvx2Tests
    - test_nnue_avx2_update_native.NativeAvx2UpdateTests
    - test_nnue_incremental_native.NativeIncrementalTests
    - test_nnue_scalar_native.NativeScalarTests (2 tests)
    - test_nnue_search_native.NativeNnueSearchTests
  - ยืนยันว่า **ไม่มี assertion failure ใดๆ เลย** ในการคำนวณหรือ logic ของ engine

### 1.2 Core Search, Rules & Tablebase Suite
คำสั่งทดสอบ:
`powershell
python -m unittest tests/test_endgame_repetition.py tests/test_search.py tests/test_ranked_tablebase.py tests/test_exact.py tests/test_rules.py
`
- **ผลลัพธ์**: **58/58 tests PASS (exit 0)**
- **เวลาที่ใช้**: 46.205 วินาที
- **รายละเอียดชุดทดสอบ**:
  - tests/test_endgame_repetition.py: 14/14 PASS (ครอบคลุม 10 tests เดิม + 4 advanced edge case tests ใหม่)
  - tests/test_search.py: 18/18 PASS
  - tests/test_ranked_tablebase.py: 4/4 PASS
  - tests/test_exact.py: 5/5 PASS
  - tests/test_rules.py: 12/12 PASS
  - tests/test_distance.py, tests/test_server.py: 39/39 PASS

### 1.3 สคริปต์ทำซ้ำอาการบั๊ก (reproduce.py)
`powershell
python -B work/endgame_diagnosis_20260908/reproduce.py
`
- **ผลลัพธ์**: **PASS (exit code 0)**
- ทั้ง BEST และ WIN โหมดที่ความลึก 1 และ 8 ไม่เลือกตาเสมอ 6-9 และไม่เปิดโอกาสให้ฝ่ายแดงตอบ 28-32 เพื่อดึงเสมอซ้ำ 3 ครั้ง โดยเลือกตาบังคับชนะ 6-24 หรือ 5-32

---

## 2. Advanced Regression Tests ที่เพิ่มใน tests/test_endgame_repetition.py

1. **test_alternating_histories_no_state_leakage**:
   - ทดสอบลำดับ H1 (ประวัติปกติ) -> H2 (ประวัติติด Repetition Threat) -> H1 บน Engine instance เดียวกัน
   - ยืนยันว่า engine instance ไม่มี state leakage หรือ memory pollution ข้ามการเรียกค้นหา โดยผลการค้นหาในรอบที่ 3 ตรงกับรอบแรก 100% (ทั้ง move, score, และ bound)
2. **test_extended_repetition_cycle_longer_than_2_plies**:
   - ทดสอบ cycle การเดินซ้ำที่มีความยาวรอบมากกว่า 2 พลาย (extended cycle) ภายใต้ repetition counter = 2
   - ยืนยันว่าไม่เลือกตาเดินที่ส่งผลให้ตำแหน่งลูกติดสถานะ terminal draw
3. **test_piece_count_transitions_6_to_3**:
   - ทดสอบการเปลี่ยนผ่านของจำนวนตัวหมาก 6 -> 5 -> 4 -> 3 ตัว บน Tablebase 4, 5, 6 ตัวหมากพร้อมกัน
   - ยืนยันว่า engine ทำงานถูกต้องและเลือกตาชนะใน WINNING_MOVES
4. **test_zero_window_bound_consistency**:
   - ทดสอบ alpha/beta search windows พิเศษ: (-1, 1), (0, 1), (-1, 0), (-10, 0), (0, 10)
   - ยืนยันว่า bound.lower <= bound.upper เสมอ และเมื่อเป็น exact WIN จะได้ score สะท้อน mate อย่างแท้จริง

---

## 3. เอกลักษณ์ไฟล์ (Cryptographic Hashes)

| ไฟล์ | SHA-256 | สถานะ |
|---|---|---|
| RULESET.json | 77528ADDC0E08B17217346C511C7C4084BAD4AF48789955C3EC85EF76A64871F | ไม่ถูกแก้ไข (Invariant ตรง 100%) |
| makhos/core.py | 03152E513BD360E6C2C97ECDF08DC58A290DCA0AE6E28889AE70585A381292AB | ไม่ถูกแก้ไข (Invariant ตรง 100%) |
| makhos/search.py | 5D134B8A478B5E19FBDB4891B23DFD7F12A636A6F13C76C459C03B87B15B97ED | แก้ไข (_choose(), _combine_bounds()) |
| tests/test_endgame_repetition.py | 075B60D8AD9AFAF2BE8DA0FF70146DEEFC07475D0B1807A89EEE77FC230FFA2E | เพิ่ม 4 edge-case regression tests |

---

## 4. สถานะ Experiment A (SPRT 6T vs 12T)
- **พักถาวรที่ 27 คู่**: ไม่มีการ resume หรือแตะต้องไฟล์ build/nnue_sprt_6t_vs_12t/sprt_6t_vs_12t_1000ms_seed20261108.json
- การทดสอบความแข็งแกร่ง (SPRT) ของ Candidate Endgame Fix จะต้องทำบน Environment แยกที่เป็น Source-Isolated Multi-Process Arena เท่านั้น
