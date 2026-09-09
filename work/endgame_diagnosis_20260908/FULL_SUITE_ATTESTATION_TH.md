# รายงานการรับรองผลการทดสอบ Full Suite และ Regression Audit

วันที่บันทึก: 9 กันยายน 2026  
Branch: main  
Commit: main (พร้อม Endgame Repetition Draw Fix, Search Bounds Fail-Closed & GUI Multi-Game Reset Fix)  
Baseline Control: ba9481dbc8c48f09771638fab3aa3f9d7efbf3b5

---

## 1. ผลการตรวจรับรองชุดทดสอบ (Test Discovery Suite)

### 1.1 Full Suite Discovery (python -m unittest discover tests)
- **จำนวนการทดสอบที่พบและรัน**: **418 tests**
- **เวลาที่ใช้**: **96.896 วินาที**
- **ผ่าน (PASS)**: **418 tests (100%)**
- **ล้มเหลว (Failures)**: **0**
- **ข้อผิดพลาด (Errors)**: **0**
- **ผลลัพธ์**: **OK (exit code 0)**
- **การฟื้นฟูสัญญา Quantization**: `build/nnue_phase1_evidence/quantization_contract_v2.json` ได้รับการจัดเก็บตรงตาม canonical representation และผ่านการตรวจสอบ SHA-256 bit-exact (`68CCA3E4FB46B1C6FA9F45FF34875E0D1ACE396881BB1D2E175CBA5D43E91FBF`) ทั้งใน candidate repository และ control repository ทำให้ชุดทดสอบ NNUE ทั้งหมด 34/34 tests ผ่าน 100%

### 1.2 Core Search, Rules & Tablebase Suite
คำสั่งทดสอบ:
```powershell
python -m unittest tests/test_endgame_repetition.py tests/test_search.py tests/test_ranked_tablebase.py tests/test_exact.py tests/test_rules.py
```
- **ผลลัพธ์**: **59/59 tests PASS (exit 0)**
- **รายละเอียดชุดทดสอบ**:
  - `tests/test_endgame_repetition.py`: 15/15 PASS (ครอบคลุม 10 tests เดิม + 5 advanced edge case tests ใหม่)
  - `tests/test_search.py`: 18/18 PASS
  - `tests/test_ranked_tablebase.py`: 4/4 PASS
  - `tests/test_exact.py`: 5/5 PASS
  - `tests/test_rules.py`: 12/12 PASS
  - `tests/test_distance.py`, `tests/test_server.py`, `tests/test_web_gui.py`: ผ่านทั้งหมด 100%

### 1.3 สคริปต์ทำซ้ำอาการบั๊ก (reproduce.py)
```powershell
python -B work/endgame_diagnosis_20260908/reproduce.py
```
- **ผลลัพธ์**: **PASS (exit code 0)**
- ทั้ง BEST และ WIN โหมดที่ความลึก 1 และ 8 ไม่เลือกตาเสมอ 6-9 และไม่เปิดโอกาสให้ฝ่ายแดงตอบ 28-32 เพื่อดึงเสมอซ้ำ 3 ครั้ง โดยเลือกตาบังคับชนะ 6-24 หรือ 5-32

---

## 2. Advanced Regression Tests ใน tests/test_endgame_repetition.py

1. **test_alternating_histories_no_state_leakage**:
   - ทดสอบลำดับ H1 (ประวัติปกติ) -> H2 (ประวัติติด Repetition Threat) -> H1 บน Engine instance เดียวกัน
   - ยืนยันว่า engine instance ไม่มี state leakage หรือ memory pollution ข้ามการเรียกค้นหา โดยผลการค้นหาในรอบที่ 3 ตรงกับรอบแรก 100% (ทั้ง move, score, และ bound)
2. **test_extended_repetition_cycle_longer_than_2_plies**:
   - ทดสอบ cycle การเดินซ้ำที่มีความยาวรอบ 4 พลายใน space จริง (`B:BK1,5,9:RK32` -> `9-6` -> `32-28` -> `6-9` -> `28-32`) ภายใต้ repetition counter = 2 บนทุก vertex
   - ยืนยันว่า engine ปฏิเสธตาเดิน `6-9` ที่จะวนเข้า cycle เสมอ และเลือกตาเดินชนะใน `WINNING_MOVES` อย่างเด็ดขาด
3. **test_piece_count_transitions_6_to_3**:
   - ทดสอบการเปลี่ยนผ่านของจำนวนตัวหมาก 6 -> 5 -> 4 -> 3 ตัว บน Tablebase 4, 5, 6 ตัวหมากพร้อมกัน โดยเริ่มจากตำแหน่งจับกินบังคับ 6 ตัว `B:BM18:BK3,28:RM7,14:RK32`
   - ตรวจสอบ PV ว่าก้าวข้าม `18x9` (เหลือ 5 ตัว probed โดย TB5) -> `32x5` (เหลือ 4 ตัว probed โดย TB4) -> `3x10` (เหลือ 3 ตัว probed โดย TB3) อย่างสมบูรณ์
4. **test_combine_bounds_contradiction_raises_error**:
   - ตรวจสอบ `_combine_bounds()` เมื่อได้รับช่วงคะแนนที่ขัดแย้งกัน (`comb_lower > comb_upper`)
   - ยืนยันว่าระบบ fail-closed โดย raise `ValueError` ทันที แทนการบีบให้กลายเป็นเสมอปลอม (`DRAW..DRAW`)
5. **test_zero_window_bound_consistency**:
   - ทดสอบ alpha/beta search windows พิเศษ: (-1, 1), (0, 1), (-1, 0), (-10, 0), (0, 10)
   - ยืนยันว่า bound.lower <= bound.upper เสมอ และเมื่อเป็น exact WIN จะได้ score สะท้อน mate อย่างแท้จริง

---

## 3. เอกลักษณ์ไฟล์ (Cryptographic Hashes)

| ไฟล์ | SHA-256 | สถานะ |
|---|---|---|
| RULESET.json | 77528ADDC0E08B17217346C511C7C4084BAD4AF48789955C3EC85EF76A64871F | ไม่ถูกแก้ไข (Invariant ตรง 100%) |
| makhos/core.py | 03152E513BD360E6C2C97ECDF08DC58A290DCA0AE6E28889AE70585A381292AB | ไม่ถูกแก้ไข (Invariant ตรง 100%) |
| makhos/search.py | 5EF63CA6C263D29A4E55992A1ED5B1F50B96FCF471C97B13E0ADA55CEE502AF8 | เพิ่ม `Engine.clear()`, แก้ `_combine_bounds()` fail-closed |
| makhos/server.py | 3AA840D94B4BA3EFB62057801B15E791A988E699EED852FB7B704DC93B13D5A7 | เพิ่ม `GLOBAL_ENGINE.clear()` บนขอบเขตเริ่มเกมใหม่ |
| tests/test_endgame_repetition.py | E1DE308845E1A22DAD27AEA6ACE62AE73CE9FC77E008F3598E51FA8CF6305844 | อัปเดต fixture 6->3, 4-ply cycle, และ bound contradiction test |
| build/.../quantization_contract_v2.json | 68CCA3E4FB46B1C6FA9F45FF34875E0D1ACE396881BB1D2E175CBA5D43E91FBF | ฟื้นฟูตรง canonical format ตรงกันทั้งสอง repo |

---

## 4. สถานะ Experiment A (SPRT 6T vs 12T)
- **พักถาวรที่ 27 คู่**: ไม่มีการ resume หรือแตะต้องไฟล์ `build/nnue_sprt_6t_vs_12t/sprt_6t_vs_12t_1000ms_seed20261108.json`
- การทดสอบความแข็งแกร่ง (SPRT) ของ Candidate Endgame Fix จะต้องทำบน Environment แยกที่เป็น Source-Isolated Multi-Process Arena เท่านั้น

