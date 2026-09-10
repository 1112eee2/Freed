# Phase 1C / C2 — Native reference search, 1T

ฐาน C1: `9ea5547`; candidate default-off บน `codex/endgame-latency-phase1c`.
อ้างอิงแผน `ENDGAME_NATIVE_PHASE1C_TH.md` (ชื่อจริงไม่มี NATIVE ซ้ำ).
สถานะการทดลอง: KEEP สำหรับ correctness integration; ยังไม่ promote เล่นจริง.

## Implementation

- `native/makhos_endgame_search.c/.h`: C17 search session กับ additive ABI v1.
  Negamax/PVS และ mandatory-capture quiescence ส่ง scalar และ WDL interval
  แยกกัน ไม่มีการอนุมาน proof จากคะแนนใกล้ MATE.
- ใช้ translation unit ทดลอง include `makhos_native.c` เพื่อ reuse move
  generator, HCE และ `search_repetition_count` เดิมโดยไม่แก้ implementation
  เหล่านั้น. Loop ใหม่แยกจาก legacy scalar-only loop เพราะต้องส่ง WDL/PV
  ทุก root และรักษา common completed depth. ยังไม่แทน legacy playing path.
- ลำดับทุก node: repetition -> clock -> no legal moves -> safety ply limit ->
  TB -> expansion/eval. เมื่อ repetition เปิด raw WIN/LOSS ถูกลดเป็น
  DRAW..WIN / LOSS..DRAW; exact DRAW คืนทันที. บีบ window ที่ 0 และ quiet
  eval ตาม bound; รวม child intervals แบบ conservative แล้ว intersect กับ TB.
- No TT score allocation/read/write ทั้ง request รวม ancestors >6; ไม่มี
  null move, LMR, futility. ใช้ PVS ที่ full depth และ re-search ตาม window.
  Reference ordering เรียง move notation; ไม่มี killer/history hints.
- Session retain immutable C1 TB set, history copy/private line และ heap
  workspace. การกลับ recursion จำกัดการนับ line ด้วย ply ปัจจุบัน จึงไม่ต้อง
  decrement global Counter; หลังจบ/cancel/error ล้าง line และคืน history copy.
- Cancel และ deadline ตรวจทุก node. Publish เฉพาะ iteration ที่ครบทุก root;
  cancel ก่อน depth 1 คืน empty snapshot และ CANCELLED ไม่มี fabricated proof.
  Corrupt/invalid/ply-limit เป็น error และ invalidate snapshot. Safety cap
  95 plies ต้องตรวจ terminal ก่อน ไม่ใช้ heuristic สร้าง proof ที่ขอบนี้.
- `makhos/native_endgame_search.py`: opt-in bridge, session lifetime lock,
  completed roots และ gate adapter ใช้ root policy ของ Python. ไม่เรียก Python
  ระหว่าง native tree search. Preparation/allocation อยู่นอก search deadline.
- `Engine(reference_search=True)` ใช้ Python reference เดิม โดยปิด selective
  pruning, TT score reuse/write, forced-root shortcut และ native dispatch;
  canonical ordering เดียวกับ C. ค่า default False คง playing behavior เดิม.

## Build / ตรวจซ้ำ

```powershell
./tools/build_endgame_c2.ps1
python -B -m unittest tests.test_native_endgame_search
```

Build ด้วย clang, `-O2 -std=c17 -Wall -Wextra -Werror -Wno-unused-function`.
Candidate path `build/native_endgame_c2/makhos_endgame_search.dll` แยก production.
Boundary harness เป็น executable ทดลองแยก ไม่เพิ่ม diagnostic entry point
ลง production ABI. ใช้ source/test inventories + DLL hash ในผลตรวจรับ.

ชุดทดสอบต้องมี C2 DLL และไฟล์จริง TB4–TB6; หากไม่มีจะ skip อย่างชัดเจน
และไม่ถือเป็น acceptance. ไม่มีการ build tablebase หรือ hash 4.85 GB ทุก search.

## Gate coverage

- Native vs `Engine.search()` ที่ depth 1/2/4/6 ใน 7 ตำแหน่ง TB3–TB6,
  repetition None/3; เปรียบเทียบทุก root score/bound/PV และ selected move
  ทั้ง BEST/WIN พร้อม replay ตรวจ legal PV.
- Repetition fixture เดิมและ defender draw ที่ depth 1/2/3/8 ทั้งสองโหมด.
- clock 0/1/77/78/79/80, current repetition count 1/2/3 และ root terminal
  precedence (ไม่มี TB probe ก่อนคืน terminal).
- ทุก 139 material signatures: deterministic seed 20260910, ทั้งสองสีเดิน,
  repetition None/3 ที่ clock 79/depth 2. นี่เป็น coverage แบบ bounded ใกล้
  clock ไม่ใช่ exhaustive search ทุกกระดาน/clock. Raw decoder exhaustive
  sampling เป็นหลักฐาน C1 แยกต่างหาก.
- 7->6 และ 4->3 capture transitions, TT poisoning/history reuse,
  completed-layer cancellation/node limit, real deadline/external cancel,
  closed TB lifetime, invalid inputs/ABI และ corrupt data fail-closed.
- C harness ตรวจ negamax/quiescence window, exact WDL เมื่อ repetition ปิด,
  terminal/max-ply precedence และ explicit resource-limit error.

ผลรวมและ log ของ full discovered suite อยู่ที่
`benchmarks/results/endgame_c2/summary.json` และ `full_suite.log.gz`.

## ข้อจำกัดและขั้นถัดไป

- HCE/1T เท่านั้น; ยังไม่เปิด native endgame ใน GUI, ไม่เชื่อม NNUE หรือ
  Root Split. ไม่มีการอ้าง latency improvement หรือ Elo จาก correctness tests.
- ไม่แก้ RULESET.json, core.py, native move/state reference หรือ production DLL.
  ไม่มีการเปิด/resume frozen SPRT checkpoint.
- Session เตรียมพื้นที่สูงสุด 4096 roots สอง buffers และ 96 move workspaces
  (~48 MiB ของโครงสร้างหลัก, ไม่รวม TB maps). ยังไม่ optimize allocation/Hash;
  ต้องวัดก่อนเพิ่ม workers. TT budget เป็นศูนย์ใน C2 configuration.
- ขั้นถัดไป: review C2 และวัด fixed-depth/fixed-time ค่าใช้จ่ายของ bridge/root
  policy กับ Python ก่อน C3 routing. NNUE เป็น evaluator ต่างจาก HCE จึงต้อง
  มี gate ของตัวเอง; multi-thread/TT optimization ต้องแยก change และหลักฐาน.
