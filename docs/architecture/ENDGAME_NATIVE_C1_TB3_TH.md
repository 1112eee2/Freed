# Phase 1C / C1: Native TB3 reader milestone

สถานะ: experimental / default-off. นี่เป็นส่วน TB3 ของ C1 เท่านั้น;
TB4–6 reader และ C2–C4 ยังไม่เสร็จ ไม่ใช่การ promote search หรือหลักฐาน Elo.

## สิ่งที่ลงมือทำ

- `native/makhos_endgame_tb.c/.h`: additive C17 API version 1,
  immutable owned image, atomic retain/release, native colex ranking และ
  WDL/distance decoding. ไม่มี Python callback, allocation หรือ I/O ใน probe.
- `CompactTablebase.export_native_image()`: ส่ง snapshot bytes ที่ผ่านการ
 ตรวจ checksum/rules/core ของ Phase 1B แล้ว พร้อม clock/vector metadata.
  Native copy ครั้งเดียวและตรวจ layout/vector references ก่อนรับ ownership.
- `makhos/native_endgame.py`: opt-in ctypes bridge; lock ป้องกัน close แข่ง
  กับ probe ของ Python owner. Native worker ต้องถือ reference ของตัวเอง;
  ห้าม retain/probe แข่งกับการปล่อย reference สุดท้าย.
- Error/MISS แยกจาก DRAW; result ใช้ได้เฉพาะ status OK. Raw TB WDL
  ยังไม่ใช่ผลพิสูจน์ภายใต้ repetition และยังไม่เชื่อมเข้ากับ search.

## Build และตรวจซ้ำ

```powershell
./tools/build_endgame_c1.ps1
python -B -m unittest tests.test_native_endgame_tb tests.test_compact_tb3
```

Build ใช้ clang 22.1.6, C17, O2, warnings-as-errors ที่ path แยก
`build/native_endgame_c1/makhos_endgame_tb.dll`. ไม่เขียนทับ production DLL.
หากไม่ build candidate ชุด native regression จะ skip อย่างชัดเจน;
การตรวจรับ C1 ต้อง build และได้ zero skips ของชุดนี้.

Regression ใช้ seed 20260909: 300 boards, material 1/2/3, ทั้งสองสีเดิน,
ทุก clock 0–80 รวม 48,600 probes เทียบ Python ทั้ง outcome/distance.
มี input/ABI/overflow/corrupt reference/value, MISS, close และ concurrent
native readers โดยยังไม่ใช้ search threads. ผล full suite และ hashes อยู่ใน
`benchmarks/results/endgame_c1_tb3/`.

## งานถัดไปและเกณฑ์ที่ยังค้าง

1. TB4–6 native read-only mapping, ranking, file-handle provenance และ
   differential ครบ 139 signatures ตามแผน C1; ห้ามถือว่า TB3 PASS แทน gate นี้.
2. เมื่อ C1 ครบ จึงทำ C2: terminal ก่อน TB/TT, WDL intervals แยก scalar,
   history-safe TT isolation และ reference differential ที่ 1T.
3. C3 routing/GUI latency และ fixed-time evidence; C4 root split ตามลำดับ.

ยังไม่มี end-to-end latency benchmark ของ native search, ไม่มี SPRT ใหม่,
ไม่มีการเปลี่ยน GUI backend, release pointer หรือ frozen SPRT checkpoint.
