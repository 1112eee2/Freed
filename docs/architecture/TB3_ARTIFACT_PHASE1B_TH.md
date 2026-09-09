# Phase 1B — TB3 artifact และ startup readiness

ฐานพัฒนา: `ceb25bc` · สถานะ: **KEEP candidate — รอตรวจรับ Windows Local**

สมมติฐาน: การเปลี่ยนจาก hash oracle ที่สร้างใหม่เป็นข้อมูล WDL + distance
ซึ่งคำนวณด้วย solver เดิม จะตัดเวลาสร้าง TB3 ออกจาก HTTP request โดยรักษา
ผล probe สำหรับ board/side/clock เดิม การค้น Python และ Phase 1C ไม่อยู่ในแพตช์นี้

## สิ่งที่ส่งมอบ

- `data/tb3_np80.tb3`: artifact พร้อมใช้ที่ติดตามใน Git ไม่ต้องสร้างใหม่ก่อนเปิด GUI
- `native/makhos_tb3_export.c`: โปรแกรมออฟไลน์ include solver/move generator เดิม
  จาก `makhos_native.c` โดยไม่แก้ไฟล์เดิม และไม่สร้างทับ accepted DLL
- `tools/build_tb3.py`: build ในโฟลเดอร์ใหม่ภายใต้ exclusive workload lease,
  deduplicate clock vectors, ตรวจ round-trip ทุกช่อง และบันทึก source/compiler hashes
- `makhos/compact_tb3.py`: อ่านและตรวจไฟล์ครั้งเดียว จากนั้น probe จาก immutable bytes
- `makhos/tb3_service.py`: background loader ที่ไม่ถือ engine/search lock
- Server โหลดที่ startup; readiness และ SHA ปรากฏใน API และ saved-game telemetry
- benchmark เดิมรองรับ startup policy ใหม่และเก็บ `tb3_startup` แยกจาก search

ไม่มีการแก้ `RULESET.json`, `makhos/core.py`, `native/makhos_native.c`,
`makhos/search.py`, `makhos/distance.py`, accepted DLL, NNUE model หรือ release pointer
Experiment A เดิมยังเป็นหลักฐาน 27 คู่ ไม่มีการอ่านผลเพื่อ resume หรือรันแข่งเพิ่ม

## Format v1

Little-endian header 128 bytes: `struct <8s6I32s32s32s`.

| Field | ความหมาย |
| --- | --- |
| magic / version | `MKTB3V1\0` / 1 |
| no_progress_plies | 80 สำหรับไฟล์ production |
| board_count | 651,008 slots สำหรับ 1–3 ตัว ทั้งสองฝ่ายเดิน |
| vector_count | จำนวน clock vectors ที่ไม่ซ้ำ |
| raw_size / packed_size | ขนาด payload ก่อน/หลัง zlib compression |
| rules_sha / core_sha | SHA-256 ของ source ที่ normalize CRLF เป็น LF เพื่อข้าม OS |
| payload_sha | SHA-256 ของ payload ที่คลายการบีบอัดแล้ว |

Payload เริ่มด้วย `board_count` uint32 vector IDs ตามด้วย vectors ซึ่งแต่ละอันมี
`no_progress_plies + 1` uint16 values (รวม clock 80) ตัวอ่านจำกัดขนาดก่อน
decompress ตรวจ EOF/trailing bytes, length และ checksum แล้วจึงประกาศ ready
การอ้าง vector นอกขอบเขตหรือค่าที่ไม่รองรับทำให้ probe ยก exception

Board rank เป็น colex: `sum(C(square[i], i+1))` สำหรับช่องที่เรียงจากน้อยไปมาก
type ใช้ 2 bits ต่อตัว: RM=0, BM=1, RK=2, BK=3; turn ใช้ R=0, B=1
มี offset แยกจำนวนหมาก ทำให้ไม่ต้องสร้าง Python dictionary ของทุกตำแหน่งตอนโหลด
ตำแหน่ง man บนแถวเลื่อนฮอส ซึ่ง `State` ไม่อนุญาต มี sentinel vector

ค่าภายใน vector: DRAW=0, LOSS=`0x4000 | distance`, WIN=`0x8000 | distance`,
invalid=`0xffff` ระยะชนะ/แพ้เก็บ 14 bits และ exporter ปฏิเสธ overflow
ไม่อนุมาน clock ที่เหลือจาก WDL clock 0 และไม่ทิ้ง DTM ของ TB3

ไฟล์นี้ไม่เข้ารหัส repetition history: search เดิมยังตรวจ history และ widen bounds
ตามกติกา รวมทั้งตรวจ contradiction ตามเดิม การจบเกมที่ clock 80 ยังมาก่อน blocked loss

## Readiness และ timeout

สถานะ: `unloaded`, `loading`, `ready`, `error`, `timeout`.

1. Startup เริ่ม daemon loader โดยไม่มี engine lock; decode และ checksum อยู่นอก request
2. `GET /api/readiness` อ่านสถานะได้แม้มี search ถือ engine lock
3. `ensure_native_tablebase_ready()` ทำเพียงเริ่ม background load ถ้ายังไม่เริ่ม
   และแนบ oracle ที่พร้อมแล้ว ไม่ join, ไม่อ่านไฟล์ และไม่ solve บน request thread
4. ตำแหน่งที่ใช้ Python endgame/TB3 รวม ranked TB4–TB6 ที่อาจเดินเข้า 3 ตัว
   ถ้าฐานไม่พร้อมจะคืน HTTP 503 พร้อมสถานะ โดยไม่คืนตาที่ไม่ได้ค้น
   GUI พักเกมและเปิดปุ่มเล่นต่อ ตาเดินบังคับเดียวและ terminal result ข้ามการรอนี้
5. เกิน load deadline 2 วินาที สถานะเป็น timeout; ผลจาก IO ที่จบช้าถูกปฏิเสธ
   ไม่เปิด retry loop หรือ fallback ไปสร้างฐาน ตรวจไฟล์แล้ว restart เพื่อเริ่มใหม่
   deadline นี้ควบคุมการยอมรับผล ไม่ใช่การยกเลิก OS file read ที่ติดอยู่
6. New game/Engine.clear เก็บ artifact เดิมไว้ ปิดเซิร์ฟเวอร์ยกเลิก generation
   ทำให้ loader เก่าไม่สามารถนำข้อมูลมาแนบกับ session ใหม่

`tb3.ready` หมายถึง loader พร้อม ส่วน `native_tablebase_ready` หมายถึงแนบกับ
Engine แล้ว `tb3_load_attempted` เดิมนับ attachment attempt ไม่ใช่ synchronous IO
`tb3.load_ms` เป็นระยะ startup load รวม scheduling และ `tb3.sha256` ผูกไฟล์จริง

## หลักฐาน Linux

ดูไฟล์ดิบและสรุปใน `benchmarks/results/tb3_phase1b/` และ build manifest ใน `data/`.

| การตรวจ | ผล |
| --- | --- |
| ขนาดไฟล์ | 410,452 bytes (~401 KiB) |
| ข้อมูลหลังโหลด | 2,838,446 bytes (~2.71 MiB), 1,447 vectors |
| Export round-trip | ตรงกันครบ 52,731,648 slots รวมช่องที่ไม่ใช่ State ถูกกติกา |
| Legacy oracle parity | 48,600 probes, 600 boards × clocks 0..80 |
| Fixed-depth parity | 144 comparisons: move, score, nodes, depth, bound, PV, TB hits ตรงกัน |
| Startup Linux | ดู p50/p95/max และทุก sample ใน `parity.json.gz` |
| HTTP smoke Linux | BEST/WIN ที่ 1s/2s ทั้ง 4 requests สำเร็จ; request overshoot สูงสุด 6.467 ms |
| New TB3 tests | 20 tests ผ่าน รวม corrupt file, timeout, late loader, new-game reuse, history |
| Node lifecycle | 16/16 PASS รวมพัก/เล่นต่อหลัง TB3 readiness error |

การเทียบ native ใช้ `.so` ที่ build แยกจาก C source เดิมบน Linux ไม่ใช่การอ้างว่า
Windows accepted DLL รันบน Linux ได้ ผล benchmark มี SHA/source/config ครบ
144 comparisons สลับ history count 1→2→1 บน Engine เดิม และรวม 4→3 transitions,
clock 78/79, BEST/WIN, repetition on/off โดยทั้ง control/candidate แนบ oracle ก่อนค้น

Full discovery: candidate 454 tests (434 เดิม + 20 ใหม่), baseline 434 tests
บน Linux มี fixture/Windows prerequisites ที่ใช้ไม่ได้: candidate รัน 411 tests,
8 failures, 18 errors, 64 skips; baseline รัน 391 tests และมี failures/errors/skips
ชุดเดียวกันทุกชื่อ ไม่มี failure/error ใหม่ ทั้งนี้ class setup error ทำให้จำนวนที่รัน
ไม่เท่าจำนวนที่ discovery พบ จึง **ไม่ใช่ full-suite PASS attestation**

ข้อจำกัด: OS cache ไม่ได้ควบคุม, 20 loads ยังไม่ยืนยัน tail latency ระยะยาว,
ไม่มี TB4–TB6 หรือ Windows NNUE DLL ใน runtime นี้ จึงต้องตรวจบน Local
การแนบ TB3 ตั้งแต่ต้นทำให้เส้นทาง 4→3 เข้าถึง exact oracle เร็วกว่าเดิมได้;
parity ข้างต้นไม่ใช่หลักฐาน Elo หรือการรับรอง production ทั้งระบบ

## ตรวจรับบน Windows Local

ปิด GUI/งาน batch ให้เครื่องว่าง คง Experiment A เดิมไว้ แล้ว checkout branch นี้
ใช้ artifact ที่อยู่ใน Git ได้เลย ไม่ต้องเรียก `build_native.ps1` หรือ rebuild NNUE

```powershell
python -B -m unittest discover -s tests -v
node --test work/test_gui_lifecycle.cjs work/test_gui_game_controls.cjs
python -B -m benchmarks.tb3_artifact --native-library build/makhos_native_accepted.dll --output build/tb3-phase1b-local
python -B benchmarks/endgame_latency.py --output build/phase1b-http-1000 --time-ms 1000 --repeats 20 --threads 12 --hash-mb 512
python -B benchmarks/endgame_latency.py --output build/phase1b-http-2000 --time-ms 2000 --repeats 20 --threads 12 --hash-mb 512
```

รันทีละคำสั่ง โฟลเดอร์ output ต้องใหม่ `psutil` เป็น dependency ของเครื่องมือ workload/benchmark
ตรวจ 454/454 บน host ที่มี fixtures เดิมครบ, Node 16/16, oracle parity ทุกข้อ,
startup load p95 และ max <50 ms; เปิด GUI ใหม่และลอง 4→3 รวม history/clock เดิม
ยืนยันไม่มี setup 11–12s อีก ตรวจ saved-game `engine.tb3.sha256` และ request overshoot
ใช้ comparison กับ Phase 1A ที่ผูก source/เครื่อง/time control เดิม ห้ามรวม profile timing
กับ timed samples และอย่านับ load ที่อุ่น OS cache ว่าเป็น disk-cold guarantee

ถ้าต้องสร้าง artifact ซ้ำเพื่อ audit (ออฟไลน์ ใช้ RAM ราว 1.5–2 GiB ที่ hash-power 26):

```powershell
python -B -m tools.build_tb3 --compiler "C:\Program Files\LLVM\bin\clang.exe" --output build/tb3-rebuild-a
```

ตรวจ manifest และ payload SHA กับไฟล์ที่ส่งมา ก่อนเปลี่ยนไฟล์ใน `data/`;
ความต่างของ zlib version อาจทำให้ compressed bytes ต่างกัน ให้ตรวจ decoded payload
และ oracle parity ด้วย ไม่มีคำสั่งนี้เขียนทับ accepted DLL/model/tablebase อื่น

Rollback: กลับไป source `ceb25bc` และ restart server จะคืน loader เดิมทั้งหมด
อย่าสลับ source ระหว่าง GUI/arena ที่กำลังค้น หรือ resume Experiment A ด้วย source ใหม่นี้
หลัง Windows gates ผ่านจึงพิจารณา merge/promote; Phase 1C ยังแยกเป็นงานถัดไป
