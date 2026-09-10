# Milestone C3: Native Endgame Routing และ NNUE Candidate

เอกสารนี้บันทึก seam ที่เพิ่มบน branch `codex/endgame-latency-phase1c` โดยไม่
เปลี่ยนกติกา, reference core, accepted DLL หรือ checkpoint ของ Experiment A

## Routing

`Engine` รับ `native_endgame_search` และ `native_endgame_enabled` ซึ่งปิดเป็น
ค่าเริ่มต้น `False` การเปิดใช้งานจะตรวจตำแหน่งไม่เกิน 6 ตัว หรือราก 7 ตัวที่มี
ตาถูกกฎหมายซึ่ง capture ลงสู่ขอบเขต 6 ตัว จากนั้น native result จะถูกแปลงเป็น
`RootCandidate` เดิม แล้วใช้ `_attach_distances`, `_safety_rank` และ `_choose`
ชุดเดิมต่อไป ไม่มี root policy ชุดที่สอง

ถ้า candidate DLL, TB3 หรือผลลัพธ์ native ใช้งานไม่ได้ Engine จะเก็บข้อความ
ผิดพลาดไว้ใน provenance และกลับไปค้น Python ตามเส้นทางเดิม ค่า default-off ทำให้
midgame/opening ไม่ต้องตรวจ capability หรือ map artifact เพิ่ม

## Proof precedence

Kernel C2/C3 ใช้ลำดับ `terminal (repetition/no-progress/no-move) -> TB WDL
interval -> NNUE/HCE evaluation` ทุก node การคืนผลจาก TB แบบ interval จึงไม่ถูก
ตีความเป็น mate scalar และผล NNUE ไม่มีสิทธิ์ทับ terminal หรือ TB proof

## Candidate NNUE

`native/makhos_endgame_search_nnue.c` เป็น translation unit แยกที่รวม runtime
NNUE v1 และ kernel endgame เดิม สร้างด้วย `tools/build_endgame_c3.ps1` ไปยัง
`build/native_endgame_c3/makhos_endgame_search_nnue.dll` เท่านั้น การโหลด model
ใช้ ABI/provenance เดียวกับ production NNUE และ fail-closed หาก DLL หรือ model ไม่
ตรงกัน ไม่แตะ `build/nnue_search_v1_r5/` หรือ pointer release

## GUI configuration

ใช้ `configure_gui_native_search(..., native_endgame=True,
native_endgame_library=...)` หรือ CLI `--native-endgame` และ
`--native-endgame-library` เพื่อ opt-in เฉพาะ session ค่า response เพิ่ม
`native_endgame_enabled`, `native_endgame_ready`, `native_endgame_evaluator` และ
`native_endgame_proof_precedence` เพื่อให้ GUI แสดง backend จริง

## Verification

- `tests/test_endgame_c3.py` ครอบคลุม default-off, opt-in, terminal precedence,
  clear, server response และ NNUE candidate
- `benchmarks/endgame_c3_latency.py` วัด cold/warm setup/search ภายใต้ 2,000/1,000
  ms โดยแยก artifact C3 จาก production
