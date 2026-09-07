# รีวิวแผนเอนจิ้นหมากฮอสไทย “ไม่มีวันแพ้”

> เอกสารนี้เป็น historical proof-safety review และตัวเลข test/search บางส่วน
> เป็น snapshot เก่า ไม่ใช่แผนงานปัจจุบัน เป้าหมาย strength/NNUE และลำดับงาน
> ที่ใช้อยู่ให้ดู `DEVELOPMENT_PLAN_TH.md`; proof/DFPN จะกลับมาเป็น active scope
> เมื่อผู้ใช้สั่งหรือแผนหลักระบุใหม่เท่านั้น

## สรุปตรงไปตรงมา

แนวคิดแบ่ง Python reference → C bitboard → search → evaluation → validation นั้นดี แต่แผนเดิมยังไม่สามารถนำไปสู่คำรับประกัน “ไม่มีวันแพ้” ได้ และมีกติกาสำคัญผิดอย่างน้อยสองจุด หากสร้างตามนั้นต่อให้โปรแกรมผ่าน unit tests ของตัวเอง ก็อาจเป็นเอนจิ้นของเกมคนละกติกา

## จุดที่ต้องแก้ทันที

1. **กติกาฮอสกินผิด** — แผนเดิมให้ฮอสเลือกลงช่องว่างใดก็ได้หลังตัวที่กิน แต่กติกา Thai king-halt ที่ใช้ในโครงการนี้ต้องลงช่องแรกหลังตัวที่กินเท่านั้น
2. **เวลานำหมากที่ถูกกินออกผิด** — แผนเดิมเก็บหมากที่ถูกกินไว้จนจบ chain; reference ที่ตรวจเทียบแล้วต้องนำออกทันที การนำออกทันทีทำให้ฮอสย้อนทิศผ่านแนวที่เพิ่งเปิดได้ และเปลี่ยน legal move tree จริง
3. **ฝ่ายเริ่มไม่ควร hard-code ว่าแดงเสมอ** — แหล่ง/ระบบเรียกสีอาจต่างกัน โครงการจึงกำหนด starting player ใน `Rules` และ CLI เปลี่ยนได้ ค่าเริ่มต้นของชุดที่ตรวจคือดำ
4. **กฎเสมอยังคลุมเครือ** — คำว่า optional ใช้กับ proof ไม่ได้ ต้องระบุ repetition และ no-progress เป็นส่วนหนึ่งของ state/ruleset ให้แน่นอน โครงการใช้สามครั้งสำหรับการเล่น และ 80 reversible plies; reusable tablebase ปิด repetition และผูก no-progress ไว้ชัดเจน
5. **“20 เกมไม่แพ้” ไม่ใช่หลักฐานว่าไม่มีวันแพ้** — tournament ใช้วัดความแข็งแรงเชิงสถิติได้เท่านั้น การรับประกันต้องมี exact WDL strategy จากตำแหน่งเริ่มต้น หรือ proof certificate ที่ checker อิสระตรวจครบทุกตาตอบของคู่แข่ง
6. **NNUE ถูกวางเร็วเกินไป** — NNUE เพิ่มความแข็งแรง แต่ไม่ให้หลักประกัน และข้อมูล self-play จากเอนจิ้นที่ยังไม่ถูกตรวจอาจเรียนข้อผิดพลาดของตัวเอง ควรทำหลัง rules/perft/exact frontier/proof architecture
7. **Null Move และ LMR ใช้ใน proof search ไม่ได้** — ใช้ได้ในโหมดเล่นถ้ามีการทดสอบ แต่ proof path ต้องไม่มี forward pruning ที่อาจตัดคำตอบถูกทิ้ง
8. **Endgame tablebase ไม่ใช่ “ถ้าจำเป็น”** — เป็นแกนหลักของ weak solution จากจุดเริ่มต้น เช่นเดียวกับ proof-number/DFPN search
9. **กำหนด 5 สัปดาห์ไม่สอดคล้องกับคำว่า solved** — ระยะนั้นอาจพอสำหรับเอนจิ้นเล่นได้รุ่นแรก แต่ไม่พอสำหรับการพิสูจน์เกมเต็ม

## แผนที่ควรใช้แทน

1. ล็อก ruleset และสร้าง Python reference ที่อ่านง่าย
2. ตรวจ perft กับแหล่งอิสระและทำ randomized differential กับ C generator
3. ทำ alpha-beta สำหรับการเล่น แต่แยก WDL safety bound ออกจาก heuristic score
4. สร้าง exact tablebase จากจำนวนน้อยขึ้นไป พร้อม checksum, rank round-trip, symmetry และออราเคิลคนละ implementation
5. ใช้ AND/OR หรือ DFPN จากตำแหน่งเริ่มต้น โดยห้าม heuristic leaf และห้าม unsafe pruning
6. สร้าง proof DAG/checkpoint ที่ผูก ruleset/frontier และให้ checker แยกตรวจ legal edges ใหม่
7. หลังมี exact WDL แล้วจึงทำสองโหมด:
   - `best`: เลือกผล WDL ที่ดีที่สุดก่อน แล้วค่อยใช้ระยะ/evaluation
   - `win`: ห้ามลด WIN→DRAW หรือ DRAW→LOSS แล้วค่อยเลือกตาที่มนุษย์ตอบยาก
8. ใส่ NNUE/opening policy ภายหลังเพื่อความแข็งแรงนอก proof frontier โดยไม่มีสิทธิ์ override ผล exact

## สถานะหลักฐานปัจจุบัน

- Python/C perft ตรงถึง depth 10 และ differential move tests ผ่าน
- automated suite ปัจจุบันผ่าน 75 tests
- exact tablebase 1–6 ตัวภายใต้ no-progress 80 สร้างและเชื่อมเข้า search/proof แล้ว
- ฐาน 5 ตัวครอบคลุม 22,591,030,896 logical states ในไฟล์ประมาณ 279 MB; exhaustive rank/symmetry checks ผ่าน
- DFPN ตำแหน่งเริ่มต้น rebase เข้ากับ frontier 4/5/6 แล้วและเดินถึง 566,173,881 post-rebase expansions; checkpoint ปัจจุบันมี 672,560,946 records และรองรับ solved-only root partition แบบ checksum-validating/atomic แล้ว
- independent bitboard rules auditor ตรวจ proof edges ซ้ำได้ทั้ง JSON และ `MKSTRAT1` โดยไม่เรียก reference move generator
- **ตำแหน่งเริ่มต้นยัง UNKNOWN** (`proof/disproof = 288,000/1,032,704`) จึงยังห้ามกล่าวว่าเอนจิ้น “ไม่มีวันแพ้”

รายละเอียดตัวเลขและคำสั่งทำซ้ำอยู่ใน `VERIFICATION.md`; เส้นทาง proof ที่เหลืออยู่ใน `PROOF_ROADMAP.md`
