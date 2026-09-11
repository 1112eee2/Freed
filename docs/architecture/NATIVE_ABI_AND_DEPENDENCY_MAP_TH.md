# แผนผัง Dependency และ ABI ของโค้ด Native

ฐานที่ตรวจ: `5e6bd3bfe2936f5d1cc4f713dc1e2dbdad174f2d` · 2026-09-11 (หลัง Phase 2C)

เอกสารนี้ระบุความสัมพันธ์ระดับ Translation Units, Include Chains, Exported ABIs
และการจัดประเภทโค้ด C ทั้งหมดใน `native/` ตามข้อกำหนดของ Phase 3 ใน
[TECH_DEBT_ROADMAP_TH.md](TECH_DEBT_ROADMAP_TH.md)

---

## 1. การจัดประเภทโค้ด Native ทั้งหมด

| ไฟล์ | หน้าที่หลัก | ประเภท | Include Chain | Output Binary / ABI |
|---|---|---|---|---|
| `makhos_native.c` | Core rules, movegen, HCE, PVS search, TT, DLL exports | Reusable Implementation | - | `makhos_native.exe`, `makhos_native.dll` (ABI 5/6) |
| `makhos_native_nnue.c` | รวม search เข้ากับ AVX2 NNUE evaluation | Candidate Implementation | `makhos_nnue_avx2_update.c` -> `makhos_native.c` | `makhos_native_nnue_candidate_v1.dll` |
| `makhos_nnue_scalar.c` | โหลด MKNNUE1 และ evaluate ด้วย scalar C | Differential Oracle | - | `makhos_nnue_scalar_oracle_v1.dll` |
| `makhos_nnue_incremental.c` | Delta accumulator update ด้วย scalar C | Differential Oracle | `makhos_nnue_scalar.c` | `makhos_nnue_incremental_oracle_v1.dll` |
| `makhos_nnue_avx2.c` | Full accumulator evaluate ด้วย AVX2 | Differential Oracle | `makhos_nnue_incremental.c` | `makhos_nnue_avx2_oracle_v1.dll` |
| `makhos_nnue_avx2_update.c` | Delta accumulator update ด้วย AVX2 | Differential Oracle & Playing Leaf | `makhos_nnue_avx2.c` | `makhos_nnue_avx2_update_oracle_v1.dll` |
| `makhos_endgame_tb.h` / `.c` | Memory-mapped compact tablebase reader & probe | Reusable Boundary | - | Link เข้า C1..C4 endgame libraries |
| `makhos_endgame_search.h` | C2..C4 endgame session search contract | ABI Contract Header | `makhos_endgame_tb.h` | - |
| `makhos_endgame_search.c` | Endgame iterative deepening search loop | Reusable Implementation | `makhos_native.c`, `makhos_endgame_search.h` | - |
| `makhos_endgame_search_hce.c` | Translation unit ของ C1/C2 (HCE evaluator) | Candidate Implementation | `makhos_native.c`, `makhos_endgame_search.c` | `makhos_endgame_search_hce.dll` |
| `makhos_endgame_search_nnue.c` | Translation unit ของ C3/C4 (NNUE evaluator) | Candidate Implementation | `makhos_nnue_avx2_update.c`, `makhos_native.c`, `makhos_endgame_search.c` | `makhos_endgame_search_nnue.dll` |
| `makhos_tb3_export.c` | สร้าง raw TB3 image จาก exact solver | Offline Builder | `makhos_native.c` | `makhos_tb3_export.exe` |
| `makhos_tb4.c` | สร้างและตรวจสอบ compact TB4 | Offline Builder & Oracle | `makhos_native.c` | `makhos_tb4.exe` |
| `makhos_tb5.c` | สร้างและตรวจสอบ compact TB5 (OpenMP) | Offline Builder | `makhos_native.c` | `makhos_tb5.exe` |
| `makhos_tb6.c` | สร้างและตรวจสอบ compact TB6 (OpenMP) | Offline Builder | `makhos_native.c` | `makhos_tb6.exe` |

---

## 2. Include Chain และ Dependency Graph

```
[makhos_types.h] (Core Bitboards, Position, Move, MoveList)
       │
       ├─────────────────────────────────┐
       ▼                                 ▼
[makhos_format.h] (Coordinates/Notation) [makhos_endgame_tb.h]
       │                                         │
       ▼                                         ▼
[makhos_native.c] (Movegen, Rules, TT, Search)  [makhos_endgame_tb.c]
       │                                         │
       ├───────────────────┐                     │
       │                   ▼                     │
       │     [makhos_nnue_scalar.c]              │
       │                   │                     │
       │                   ▼                     │
       │     [makhos_nnue_incremental.c]         │
       │                   │                     │
       │                   ▼                     │
       │     [makhos_nnue_avx2.c]                │
       │                   │                     │
       │                   ▼                     │
       │     [makhos_nnue_avx2_update.c]         │
       │                   │                     │
       ├───────────────────┼─────────────────────┤
       │                   ▼                     ▼
       │     [makhos_native_nnue.c]  [makhos_endgame_search.c]
       │                                         │
       │                           ┌─────────────┴─────────────┐
       │                           ▼                           ▼
       │              [makhos_endgame_search_hce.c] [makhos_endgame_search_nnue.c]
       │
       ├──────────────┬──────────────┬──────────────┬──────────────┐
       ▼              ▼              ▼              ▼              ▼
[makhos_tb3_export.c] [makhos_tb4.c] [makhos_tb5.c] [makhos_tb6.c] (Offline Tools)
```

---

## 3. ขอบเขต Leaf Responsibilities ที่แยกใน Phase 3

เพื่อลดความซับซ้อนของ `makhos_native.c` (6,987 บรรทัด) โดย **ไม่เปลี่ยน ABI, ไม่เปลี่ยน codegen, และรักษา bit-exact inlining**:

1. **`native/makhos_types.h`**:
   - ชนิดข้อมูลพื้นฐาน: `Position`, `Move`, `MoveList`, `Square`, `ExactEntry`, `ExactContext`, `ExactValue`, `ExactCounts`
   - ค่าคงที่กติกา: `OUTCOME_LOSS`, `OUTCOME_DRAW`, `OUTCOME_WIN`, `MAX_MOVES`, `MAKHOS_MAX_PATH`, `BLACK`, `RED`
   - Bitboard operations: `bit_at`, `other`, `occupied`, `pieces_for`, `pop_lsb`
   - Memory layout verification ผ่าน `_Static_assert`

2. **`native/makhos_format.h`**:
   - การแปลงพิกัดกระดาน 32 ช่อง <-> (row, col) ตาราง 8x8: `index_to_coord`, `coord_to_index`
   - การตรวจสอบแถวและช่องเดิน: `is_promotion_square`, `valid_man_square`
   - การจัดรูปแบบ move notation: `print_move_notation`
   - การ parse ตำแหน่ง FEN-like notation: `parse_piece_group`, `parse_position`

3. **สัญญาความปลอดภัย (Invariants & Safety Gates)**:
   - `_Static_assert` คุ้มครอง `sizeof(Position) == 16`, `sizeof(Move) == 36`
   - ลำดับ memory layout ของ structs ทุกตัวตรงกับ ctypes wrappers ใน `makhos/native.py`
   - ทดสอบ official initial-position perft ถึง depth 10 ให้ผล bit-exact
   - รัน differential suite ระหว่าง Python `makhos/core.py` กับ Native ทั้งหมด
