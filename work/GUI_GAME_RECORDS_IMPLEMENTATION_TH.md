# GUI: บันทึกเกม ผลโดยผู้ใช้ และย้อน 1 ply

วันที่: 2026-09-09 · ฐานล่าสุด: `d0647e587686bdb26982e725c0b77a77392dc554`

เริ่มพัฒนาจาก `82299b9` แล้ว rebase บนแพตช์ rematch ของ Antigravity (`d0647e5`)
รักษา `Engine.clear()` ที่ game boundary และ `applyServerReleaseDefaults()` ไว้ครบ
ใช้ `resetEvalUI()` ตัวเดียวสำหรับ new game/undo และให้ HTML แสดงค่าเริ่มต้น 12T/512 MiB
ตรงกับ JavaScript ก่อน API identity ตอบกลับ โดยยังเคารพค่าที่ผู้ใช้บันทึกเอง

สถานะ: **IMPLEMENTED — รอตรวจหน้าจอและ full suite บน Windows Local ก่อน merge/ใช้งานจริง**

## พฤติกรรม

- ปุ่มย้อนถอยหนึ่ง completed ply เท่านั้น รวม multi-capture ทั้ง chain เป็นหนึ่งตา
  คืน board, turn, legal moves, promotion rank, last-move highlight, clock และ history
  ล้างผลจบเกม/ป้ายผลผู้ใช้ของสายเดินที่ย้อนแล้ว พักเกมจนผู้ใช้กดเล่นต่อ
- ผู้ใช้เลือกดำชนะ/แดงชนะ/เสมอได้เอง ชื่อฝั่งชัดเจนทั้งโหมดคน/บอตและหลังหมุนกระดาน
  การตัดสินหยุดการเดินเพิ่ม แต่ยังย้อนตาหรือแก้ป้ายผลได้
- กดบันทึกเมื่อจบเกมเป็น JSON ใน `saved_games/` ของเครื่อง server ใช้ชื่อใหม่ทุกครั้ง
  server เล่นทวนด้วย Python rules ก่อนเขียน ตรวจ final position, clock และประวัติทุกตำแหน่ง
  เก็บผลผู้ใช้เป็น annotation แยกจาก terminal result ตามกติกา และรักษา engine provenance รายตา
- จำกัดข้อมูล save 4 MiB / 999 plies ตามเพดาน history API 1,000 ตำแหน่ง
  client ไม่กำหนดที่อยู่ไฟล์; ไม่เขียนทับไฟล์เดิม และลบไฟล์ที่เขียนค้างเมื่อเกิด I/O error
- ใช้ generation/AbortController ป้องกันคำตอบเก่าของทั้ง human apply และ bot search/apply
  กดย้อนหรือตัดสินระหว่างรอแล้ว response เก่าจะไม่เพิ่มตา กลับ edit → human/bot เก็บ history ต่อเนื่อง
  ป้องกัน double-click ของการเดินและบันทึก รวมถึง save response เก่าที่มาหลังเริ่มเกมใหม่

## หลักฐานที่รันใน checkout นี้

```text
python -B -m unittest tests.test_game_records tests.test_web_gui tests.test_game_analysis tests.test_rules -q
37 tests: PASS, failures=0, errors=0, skips=0 (0.833s หลัง rebase)

node --test work/test_gui_lifecycle.cjs work/test_gui_game_controls.cjs
15 tests: PASS, failures=0, skips=0 (หลัง rebase)

git diff --check
PASS
```

Python ใช้ `-X pycache_prefix` ชี้โฟลเดอร์ชั่วคราวของ cloud เพื่อหลีกเลี่ยง cache ของ runtime
การทดสอบใหม่ครอบคลุม HTTP save จริง, illegal/inconsistent records, ผลผู้ใช้ทั้งสามแบบ,
ชนะจาก multi-capture, เสมอสามซ้ำ/80 plies, file collision, I/O error/retry และการยกเลิกคำตอบเก่า

รันเพิ่ม `tests.test_web_gui tests.test_game_analysis tests.test_server`: 34 tests,
31 passed, 2 failures, 1 skip. สอง failures คือ `test_handle_bestmove` และ
`test_handle_bestmove_reports_parallel_backend`: เครื่อง Linux โหลด accepted Windows DLL
ไม่ได้ (`invalid ELF header`) จึงได้ allocation 0 / backend Python แทน native
รันสองข้อนี้ซ้ำด้วย `makhos/server.py` จากฐาน `82299b9` ที่ยังไม่แก้ ได้ failures เดียวกันทั้งสองข้อ
ผลนี้ไม่ใช่ full-suite attestation หรือ native production smoke
หลัง rebase บน `d0647e5` รัน `tests.test_server` อีกครั้ง: 19 tests,
16 passed, 2 failures เดิม, 1 skip (0.738s) ไม่มี failure/error ใหม่

Browser cloud เปิด server ทดสอบ localhost ไม่ได้ (`net::ERR_BLOCKED_BY_CLIENT`)
จึงยังไม่มีหลักฐาน visual/real-browser smoke ในรอบนี้ ไม่มีการอ้างว่าตรวจหน้าจอผ่านแล้ว

## ตรวจบน Local ก่อนรวมงาน

1. แพตช์นี้รวมฐาน rematch `d0647e5` แล้ว หาก Local มีแพตช์ใหม่เพิ่มให้ตรวจ `web/app.js`
   และ route ใหม่ใน `makhos/server.py`; รันชุดทดสอบข้างบนซ้ำบน commit ที่รวมจริง
2. เมื่อ workload ว่าง รัน full discovered suite ตามกฎโครงการ พร้อมรายงาน count/failures/errors/skips จริง
3. เปิด GUI ตรวจคลิกและลากเดิน → ย้อน 1 ply → พัก → เล่นต่อ ทั้งคน/บอตและบอต/บอต
   ลองตากินหลายทอด/เข้าฮอส/จบเกม และกดย้อนขณะบอตคิด
4. ตัดสินทั้งดำชนะ แดงชนะ เสมอ แล้วบันทึก ตรวจไฟล์ `saved_games/` และข้อมูล provenance
   เปลี่ยนป้ายผลแล้วบันทึกอีกครั้งต้องไม่ทับไฟล์เดิม; เริ่มเกมใหม่แล้วย้อนต้อง disabled
5. ตรวจหน้าจอ desktop/mobile, การเลื่อน sidebar, โหลด assets รุ่น `20260909-1`
   และทดสอบ rematch เดิมซ้ำบน source commit ที่รวมแล้วพร้อม engine identity เดิม

## ขอบเขต

`RULESET.json`, `makhos/core.py`, search/native/NNUE, release pointer และ arena ไม่ถูกแก้ไข
Experiment A 27 คู่ไม่ถูก resume การแก้นี้ไม่ใช่คำรับรองว่าบั๊ก rematch ทำให้เล่นอ่อนลงถูกแก้แล้ว
AbortController ยกเลิกการรับคำตอบของ browser; ไม่ได้เพิ่มคำสั่งหยุด native search ฝั่ง server
การย้ายไฟล์ server/native หรือรวม build scripts เป็นงานแยกภายหลังตามหลักฐานของ rematch

Rollback: revert commit ของ GUI โดยเก็บโฟลเดอร์ `saved_games/` ไว้ตามเดิม
