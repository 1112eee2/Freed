# แผนงานและข้อกำหนดการทดสอบความแข็งแกร่ง (SPRT Testing Manifest)
## สำหรับ Endgame Tablebase Repetition Draw Candidate vs Control Baseline

วันที่บันทึก: 8 กันยายน 2026  
Control Baseline: `ba9481dbc8c48f09771638fab3aa3f9d7efbf3b5` (worktree: `D:\ThaiMakhosEngine_control`)  
Candidate Fix: `main` (commit `885753c`, repo: `D:\ThaiMakhosEngine`)  
Arena Engine: `work/source_isolated_arena.py`

---

## 1. สถานะและการแยกขาดจาก Experiment A (Isolation Invariant)

- **Experiment A (SPRT 6T vs 12T)**:
  - พักอย่างปลอดภัยไว้ที่ 27 คู่เกม (checkpoint: `build/nnue_sprt_6t_vs_12t/sprt_6t_vs_12t_1000ms_seed20261108.json`)
  - **ข้อกำหนดเด็ดขาด**: ห้าม resume, แก้ไข, หรือรันต่อด้วย main codebase ที่มีแพตช์ endgame fix นี้ เพื่อป้องกันไม่ให้ข้อมูลสถิติของ Experiment A เสียหายจากการปนเปื้อนของโค้ดค้นหาคนละเวอร์ชัน
- **Repository Invariants**:
  - `RULESET.json`: ห้ามแก้ไข (SHA-256: `77528ADDC0E08B17217346C511C7C4084BAD4AF48789955C3EC85EF76A64871F`)
  - `makhos/core.py`: ห้ามแก้ไข (SHA-256: `03152E513BD360E6C2C97ECDF08DC58A290DCA0AE6E28889AE70585A381292AB`)

---

## 2. สถาปัตยกรรม Source-Isolated Multi-Process Arena

การทดสอบความแข็งแกร่งระหว่าง Control (`ba9481d`) และ Candidate (`main`) ไม่สามารถรันผ่าน standard in-process CLI loop ได้ เนื่องจากทั้งสองเวอร์ชันมีความแตกต่างใน Python module `makhos/search.py`

Arena ใช้สถาปัตยกรรมแบบแยกโปรเซสสมบูรณ์ (`work/source_isolated_arena.py` + `work/endgame_worker.py`):
1. **Control Worker Process**: รันด้วย `PYTHONPATH=D:\ThaiMakhosEngine_control` ควบคุมเอนจินรุ่นเดิม
2. **Candidate Worker Process**: รันด้วย `PYTHONPATH=D:\ThaiMakhosEngine` ควบคุมเอนจินรุ่นแก้บั๊ก
3. **Arena Coordinator**: ควบคุมกฎกติกาการแข่งขัน การสลับหมากดำ/แดง การตรวจจับการเดินซ้ำ 3 ครั้ง (3-fold repetition) และการนับ 80 พลายอย่างเป็นกลาง

---

## 3. ผลการทดสอบนำร่อง (Pilot Verification Result)

ไฟล์หลักฐาน: `work/endgame_diagnosis_20260908/arena_pilot_result.json`

| เกม | หมากดำ (เดินก่อน) | หมากแดง | ตาแรกของหมากดำ | ผลการแข่งขัน | สาเหตุที่จบเกม | จำนวนพลาย |
|---|---|---|---|---|---|---|
| เกม 1 | **Candidate** | Control | `5-32` | **Candidate ชนะ** | no_legal_move (แดงหมดตาเดิน) | 3 พลาย |
| เกม 2 | Control | **Candidate** | `6-9` (บั๊กเดิม) | **เสมอ (DRAW)** | repetition (ซ้ำ 3 ครั้ง) | 2 พลาย |

**สรุปผลนำร่อง**:
- ในเกม 1: Candidate ไม่หลงเลือกตาเสมอ `6-9` แต่เลือก `5-32` (หรือ `6-24`) ซึ่งเป็นตาชนะ บังคับให้ Control แพ้ใน 3 พลาย
- ในเกม 2: Control เดินตาติดบั๊ก `6-9` ทำให้ Candidate (แดง) ตอบ `28-32` ส่งผลให้ตำแหน่งเกิดการซ้ำ 3 ครั้ง (threefold repetition) จบเสมอทันทีใน 2 พลาย
- สกอร์รวมของคู่เกมนี้: Candidate ชนะ 1.5 - 0.5 (+1 พอยต์ใน Pentanomial WD class)

---

## 4. โครงสร้างการทดสอบแบบคู่เกม (Paired-SPRT Manifest)

ไฟล์ Machine-readable Manifest: `work/endgame_diagnosis_20260908/sprt_manifest.json`

### 4.1 Tier 1: Intrinsic Single-Thread (1T) Correctness & Deep Search
- **วัตถุประสงค์**: ตรวจสอบความถูกต้องของการค้นหาลึกและยืนยันว่าไม่มี regression ในการประเมิน endgame
- **Hardware/Threads**: 1 Thread (1T)
- **Time Control**: 10s + 0.1s increment ต่อตา
- **Opening Suite**: Endgame & late middlegame position suite (ครอบคลุมทั้ง 4-piece, 5-piece, และ 6-piece transitions)
- **Mode**: BEST & WIN
- **SPRT Parameters**:
  - Elo0: 0.0
  - Elo1: +2.0
  - Alpha (Type I error): 0.05
  - Beta (Type II error): 0.05
  - Max Pairs: 10,000
  - Pentanomial model: WW (+2), WD (+1), DD (0), LD (-1), LL (-2)
  - Stopping boundaries: LLR <= -2.944 (FAIL) หรือ LLR >= +2.944 (PASS)

### 4.2 Tier 2: Production Multi-Thread (12T) Standard Speed
- **วัตถุประสงค์**: ทดสอบความเสถียรในสภาพแวดล้อมเสมือน GUI / Tournament จริง
- **Hardware/Threads**: 12 Threads (12T)
- **Time Control**: 1000ms และ 2000ms fixed time
- **Tablebase**: Native TB3 + Ranked TB4, TB5, TB6
- **Stop Conditions**:
  - LLR >= +2.944 (Accept H1: Candidate แข็งแกร่งกว่าอย่างมีนัยสำคัญทางสถิติ)
  - LLR <= -2.944 (Reject H1: ไม่ผ่านเกณฑ์)

---

## 5. คำสั่งสำหรับการรันคู่เกมใน Arena

```powershell
# รัน Pilot ตรวจสอบตำแหน่งบั๊กซ้ำ
python work/source_isolated_arena.py --pilot

# รันแมตช์ทดสอบแบบคู่เกม (เช่น 10 คู่เกมที่ 1000ms)
python work/source_isolated_arena.py --pairs 10 --time-ms 1000 --mode BEST
```
