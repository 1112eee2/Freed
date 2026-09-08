# ผลการแก้ Endgame Tablebase Repetition Draw

Worktree: `D:\ThaiMakhosEngine_tb_fix`  
Branch: `fix/tb-repetition-v1`  
ฐานก่อนแก้: `ba9481dbc8c48f09771638fab3aa3f9d7efbf3b5`

## พฤติกรรมที่แก้

ในตำแหน่ง `B:BK1,5,6:RK28` พร้อมประวัติจากกรณีวินิจฉัย Engine เดิมเลือก `6-9` และเปิดให้ `28-32` เสมอซ้ำสามครั้ง ทั้งที่มีทางบังคับชนะภายใน 3 พลาย หลังแก้เลือก `6-24` หรือ `5-32` ตาม mode/depth และไม่เปิดตาเสมอทันที

ดำเนินการตาม [แผนปฏิบัติการ](IMPLEMENTATION_PLAN_TH.md):

- `_negamax()` และ `_quiescence()` ใช้ `terminal_status` ก่อนพิจารณา Tablebase เพื่อให้กฎซ้ำและนับ 80 พลายมีลำดับถูกต้อง
- ผล Tablebase ที่เป็น exact ยังคืนทันทีตามเดิม ส่วน `DRAW..WIN` / `LOSS..DRAW` ใช้บีบ alpha/beta และค้นต่อด้วยประวัติเกมจริง ใบเงียบจำกัดคะแนนประเมินตาม WDL
- ข้าม TT score cutoff ใน endgame ภายใต้กฎ repetition ตามขอบเขตในแผน โดยยังใช้ best move ช่วยเรียงตาได้
- คืน counter ของตำแหน่งลูกผ่าน `try/finally` ทุกเส้นทาง recursive ทั้ง root, negamax และ quiescence เมื่อ timeout หรือ exception
- จัดอันดับขอบเขต WDL ด้วย `(lower, upper)` และให้ตาชนะที่พิสูจน์แล้ว/คะแนน mate มาก่อน heuristic pressure ใน Mode.WIN

มีการเติมรายละเอียดเพื่อรักษาความถูกต้องของแผนอีกหนึ่งจุด: เมื่อรวมผลหลังการตัดกิ่ง ต้องนำขอบเขตจาก Tablebase มาจำกัดผลรวมและคะแนนด้วย มิฉะนั้นตำแหน่ง TB LOSS ที่พบตาเสมออาจถูกรายงานเป็น `DRAW..WIN` แทน `DRAW..DRAW` มี regression แยกยืนยันข้อผิดพลาดนี้ก่อนแก้

## ผลตรวจ

คำสั่งที่ผู้ใช้กำหนด:

```powershell
python -B work/endgame_diagnosis_20260908/reproduce.py
python -m unittest tests/test_search.py tests/test_endgame_repetition.py
```

- สคริปต์ทำซ้ำ: **exit 0** ตรวจทั้ง BEST/WIN ที่ depth 1 และ 8 ทุกตาอยู่ใน `{5-32, 6-10, 6-15, 6-19, 6-24}` และไม่มีตาตอบที่จบเสมอทันที
- ชุดทดสอบเฉพาะ: **27 tests ผ่านทั้งหมด ไม่มี skip**, 26.231 วินาที
- Regression ใหม่ 10 tests ครอบคลุม BEST/WIN × depth 1/2/3/8, clock 78/79, ฝ่ายเสียเปรียบเลือกตาดึงเสมอ, exact TB cutoff, quiet score bounds, TT isolation, terminal draw, timeout cleanup และการจัดอันดับตาชนะ
- ชุดทดสอบรวมรอบสุดท้าย: อยู่ระหว่างตรวจ รายละเอียดจะบันทึกหลัง process จบ

ผลสคริปต์ทำซ้ำ:

| Mode | Depth | ตาที่เลือก | Score | ตาตอบที่เสมอทันที |
|---|---:|---|---:|---|
| BEST | 1 | `6-24` | 999997 | ไม่มี |
| BEST | 8 | `6-24` | 999997 | ไม่มี |
| WIN | 1 | `6-24` | 999997 | ไม่มี |
| WIN | 8 | `5-32` | 999997 | ไม่มี |

การตรวจชุดรวมใช้ตัวควบคุม workload และตัวป้องกันการอ่านข้อมูลจาก `scratch/nnue_full_suite_attestation.py` พร้อมเพิ่มการห้ามเปิดโฟลเดอร์ SPRT 6T vs 12T ทั้งสอง worktree เป็นการตรวจ unit suite ของ branch นี้ ไม่ใช่ attestation อนุมัติ trainer หรือ production promotion

รอบตรวจรวมครั้งแรกพบ DLL รุ่นเก่าที่เป็น fixture ของ `NativeHashSizingTests` ขาดจาก worktree (0 assertion failures, 1 environment error) จึงคัดลอก `build/makhos_native.dll` จากโฟลเดอร์หลักโดยไม่แก้ต้นฉบับ และยืนยันว่ารายการนั้นผ่านแล้ว SHA-256 ของต้นฉบับและสำเนาตรงกัน: `404D18C8FDAEEEFC746CE62F31FA2A327A5197D83B08A136E16774B9FD6E6A08`

## ขอบเขตและเอกลักษณ์ไฟล์

ไม่ได้แก้ `RULESET.json`, `makhos/core.py`, native source, โมเดล, release pointer หรือข้อมูล Tablebase และไม่ได้เปิด/แก้/สั่งรัน checkpoint SPRT 6T vs 12T

SHA-256 ที่ตรวจ:

| ไฟล์ | SHA-256 |
|---|---|
| `RULESET.json` ก่อน/หลัง | `77528ADDC0E08B17217346C511C7C4084BAD4AF48789955C3EC85EF76A64871F` |
| `makhos/core.py` ก่อน/หลัง | `03152E513BD360E6C2C97ECDF08DC58A290DCA0AE6E28889AE70585A381292AB` |
| `makhos/search.py` ก่อน | `4125360FF236A17D0BDEE21486A7593483DF6EEAE96DF93DBD040A4831E1A253` |
| `makhos/search.py` หลัง | `430E7E871F03F84D941AC291E478F4364BD08999623B56CF7165D189B02A9CA4` |
| accepted control DLL หลังตรวจ | `FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD` |

สถานะ: **KEEP บน branch สำหรับแก้บั๊ก** ยืนยันความถูกต้องของกรณี regression แล้ว แต่ยังไม่ได้วัด Elo หรือทำ paired SPRT เปรียบเทียบ candidate นี้ ไม่ได้ merge main หรือเปลี่ยน production profile

ขั้นถัดไปสำหรับการรับขึ้น production คือทดสอบ candidate กับ control ที่ตรึงเอกลักษณ์แยกกัน ตรวจเวลาใน endgame/GUI และผ่านเกณฑ์ paired strength ที่เกี่ยวข้อง โดยเก็บผลและ checkpoint SPRT 6T vs 12T เดิมแยกไว้ครบถ้วน
