# ผลสืบสวน: Tablebase WIN เดินวนจนเสมอ

วันที่ 2026-09-08 — ตรวจบน `D:\ThaiMakhosEngine`

**ยืนยันบั๊กได้ด้วย Engine จริงและไฟล์ TB4 จริง:** Engine เลือกตาที่เปิดให้คู่แข่งเสมอซ้ำสามครั้งในตาถัดไป ทั้งที่มีทางบังคับชนะเพียง 3 พลาย ปัญหาประกอบด้วยการไม่มีระยะถึงชัยชนะสำหรับตาใน ranked tablebase และการตัดการค้นด้วยผล WDL ที่ไม่มีประวัติซ้ำ ก่อนตรวจตาตอบของคู่แข่ง

ขอบเขตงานนี้คือการวินิจฉัยตามบรีฟ ยังไม่ได้แก้หรือ promote โค้ดเล่นจริง การทดลองเปลี่ยนพฤติกรรมมีเฉพาะ subclass ในไฟล์วินิจฉัย ไม่ใช่ candidate ที่ผ่านการรับรอง

## 1. กรณีทำซ้ำและทางชนะที่ตรวจด้วยกฎจริง

เริ่มจาก `B:BK1,5,9:RK32` นาฬิกา no-progress = 0 แล้วเดินลำดับที่ถูกกติกา:

```text
9-6 32-28 6-9 28-32 9-6 32-28
```

ถึงตำแหน่ง `B:BK1,5,6:RK28` นาฬิกา = 6 ฝ่ายดำเดิน ตำแหน่งเริ่มต้นเคยเกิดแล้ว 2 ครั้ง และ TB4 ให้ผล WIN ที่นาฬิกาปัจจุบัน

| ทางเลือก | ผลที่ตรวจได้ |
|---|---|
| Engine เลือก `6-9` | คู่แข่งเดิน `28-32` กลับตำแหน่งเริ่มต้นเป็นครั้งที่ 3 และ `terminal_status` ให้ `repetition` / DRAW |
| ทางบังคับชนะ `6-24` | แดงมีตาถูกกติกาเพียง `28x19` แล้วดำมีเพียง `1x24` กินแดงหมด จบด้วยดำชนะ |

ตรวจความถูกกติกาและผลปลายทางด้วย `makhos/core.py` ที่ไม่ได้แก้ไขทุกพลาย พร้อมนับประวัติจริง ทางชนะนี้จึงไม่ได้อ้างแค่คะแนนหรือ PV ของ search

ผลซ้ำทั้ง BEST/WIN ที่ depth 1 และ 8: เลือก `6-9`, score `1000000`, bound `DRAW..WIN` ตาทั้ง 13 ตาได้คะแนนเท่ากันทั้งหมด และ DTM เป็น `None` / `exact=false`

คำสั่งตรวจบั๊ก:

```powershell
python -B work/endgame_diagnosis_20260908/reproduce.py work/endgame_diagnosis_20260908/reproduction.json
```

ผลที่รันจริง: **exit 1** พร้อมข้อความ:

```text
AssertionError: TB4 WIN: Engine chooses 6-9, allowing 28-32 to draw by repetition; 6-24 instead forces 28x19 1x24 and wins.
```

นี่คือการทดสอบที่ล้มเหลวตามคาดเพื่อจับบั๊ก ไม่ใช่การอ้างว่าแก้แล้ว ใช้เวลาประมาณหนึ่งวินาทีรวมการเริ่ม Python ไม่ต้องโหลด native search, NNUE หรือสร้าง TB3

## 2. สาเหตุในเส้นทางเลือกตา

เมื่อเปิด ranked tablebases ครบถึง 6 ตัว [search.py:450](D:/ThaiMakhosEngine/makhos/search.py:450) จะส่ง root ที่ไม่เกินขอบเขตนี้ไปเส้นทาง Python ที่รู้จัก Tablebase ส่วนตาบังคับมีทางลัดต่างหาก ดังนั้นการเลือกตาในกรณีนี้ไม่ได้มาจากการประเมิน NNUE หรือ root splitting แบบ 6T/12T

### A. Ranked TB4/TB5/TB6 ส่ง WDL แต่ไม่มี DTM

- [ranked_tablebase.py:436](D:/ThaiMakhosEngine/makhos/ranked_tablebase.py:436) อ่าน compact WDL และ threshold ของนาฬิกา no-progress
- [ranked_tablebase.py:452](D:/ThaiMakhosEngine/makhos/ranked_tablebase.py:452) คืน `NativeProbe(outcome, None)` ส่วน packed reader ที่บรรทัด 460 ก็ไม่มี distance เช่นกัน
- [search.py:783](D:/ThaiMakhosEngine/makhos/search.py:783) ให้ทุก ranked WIN เป็น `MATE_SCORE` และ LOSS เป็น `-MATE_SCORE` โดยไม่มีระยะถึงชัยชนะ

ดังนั้น WDL บอกได้ว่าตานั้นยังชนะภายใต้กฎของฐานข้อมูล แต่ไม่ได้บอกว่าจะเดินต่ออย่างไรให้ปิดเกมเร็ว ตัวอ่านตรวจนาฬิกาอยู่แล้ว ไม่ใช่ไฟล์ที่ละเลยกฎ 80 พลาย

### B. DistanceOracle มีอยู่ แต่ GUI ใช้งบขยายกราฟเป็นศูนย์

- [search.py:188](D:/ThaiMakhosEngine/makhos/search.py:188): `distance_max_nodes=0`
- [server.py:450](D:/ThaiMakhosEngine/makhos/server.py:450): สร้าง Engine โดยไม่ส่งค่านี้ จึงใช้ศูนย์
- [distance.py:91](D:/ThaiMakhosEngine/makhos/distance.py:91): `_tick()` เพิ่มจำนวนโหนดเป็น 1 แล้วเกินงบศูนย์ทันที
- [distance.py:130](D:/ThaiMakhosEngine/makhos/distance.py:130): ranked probe ไม่มี DTM จึงเข้า `_dtm()` และจบเป็น unknown เมื่อเกินงบ

งบศูนย์หมายถึง **ไม่อนุญาตให้ขยายกราฟ** ไม่ได้หมายถึงไม่จำกัด และไม่ได้ปิดระยะที่ native TB3 ส่งมาโดยตรง

เมื่อไม่มีระยะให้จัดอันดับ:

- BEST ที่ [search.py:938](D:/ThaiMakhosEngine/makhos/search.py:938) จบการตัดสินกรณีนี้ด้วยลำดับข้อความ notation จึงเลือก `6-9`
- WIN ที่ [search.py:955](D:/ThaiMakhosEngine/makhos/search.py:955) ใช้ค่ากดดันคู่แข่งหลังคะแนนเชิงนโยบายเสมอกัน ในกรณีนี้ `6-9` ได้ pressure `29.257716` แต่ `6-24` ได้ `0` เพราะทางชนะมีตาตอบบังคับเพียงตาเดียว จึงกลับเลือกตาวน

ไม่ใช่ว่าโค้ดไม่มี DTM/DTR หรือไม่เคยเรียกเลย แต่ค่าที่จำเป็นต่อ ranked endgame กลับมาเป็น unknown ในการตั้งค่าจริง

### C. Tablebase cutoff ทำให้ไม่เห็นการเสมอในตาคู่แข่ง

- [search.py:549](D:/ThaiMakhosEngine/makhos/search.py:549) เพิ่มประวัติหลังตารากอย่างถูกต้อง
- [search.py:616](D:/ThaiMakhosEngine/makhos/search.py:616) ตรวจการซ้ำและ no-progress ของตำแหน่งนั้น
- [search.py:627](D:/ThaiMakhosEngine/makhos/search.py:627) probe แล้วคืนผลทันที จึงไม่ค้นตาตอบของคู่แข่ง
- [search.py:821](D:/ThaiMakhosEngine/makhos/search.py:821) ยอมรับข้อจำกัดเรื่องประวัติ โดยลดขอบเขต WIN เป็น `DRAW..WIN` แต่คะแนนตัวเลขยังเป็นค่าชนะสูงสุด และ search ยังหยุดทันที

หลัง `6-9` ยังไม่ใช่การซ้ำครั้งที่ 3 แต่หลังคู่แข่ง `28-32` เป็นครั้งที่ 3 แล้ว การตรวจเฉพาะตำแหน่งลูกจึงไม่พอ

การ instrument ที่ depth 3 พบ `_negamax` เข้าเพียง ply 1 จำนวน 39 ครั้ง (13 ตา × 3 iterations) ไม่มีการเข้า ply 2 เลย การเพิ่ม depth จึงไม่แก้กรณีนี้

Tablebase ไม่มีประวัติซ้ำเป็นส่วนหนึ่งของ key จึงไม่สามารถใช้ WDL อย่างเดียวเป็นคำรับรองชัยชนะในเกมที่มีประวัติเดิมได้ กรณีนี้มีหลักฐานทางชนะภายใต้ประวัติจริงแยกไว้แล้ว

## 3. การตรวจแยกสาเหตุ

คำสั่ง:

```powershell
python -B work/endgame_diagnosis_20260908/controls.py
```

ผลจริง: **exit 0** ตรวจยืนยันครบทุกเงื่อนไขในไฟล์ ใช้เวลาต่ำกว่าหนึ่งวินาทีรวมการเริ่ม Python

| การเปลี่ยนเฉพาะในตัววินิจฉัย | ผล |
|---|---|
| Engine เดิม + TB4, depth 3, ประวัติครบ | `6-9`, `1000000`, `DRAW..WIN`, ค้นถึงแค่ ply 1 |
| งด `_probe_exact` cutoff โดยใช้กฎ/search เดิม | เลือก `5-32`, `999997`, `WIN..WIN`; มีการค้นถึง ply 3 และเห็นทางชนะ |
| DistanceOracle + ตัวแก้ exact สำหรับใบ 3 ตัวเหมือนกันทั้งคู่: งบ 0 เทียบงบ 1 | DTM ของ `6-24` เปลี่ยนจาก unknown เป็น exact 3; ตัวแก้ exact ใช้เพียง 2 states |
| งบ 1 เท่าเดิม แต่ไม่มี oracle สำหรับใบ 3 ตัว | DTM กลับเป็น unknown แสดงว่าขึ้นงบอย่างเดียวไม่พอ |
| เพิ่มประวัติให้ `6-9` เป็นการซ้ำครั้งที่ 3 ทันที | Engine ให้ตานั้น `0` / `DRAW..DRAW` ได้ถูกต้อง ข้อบกพร่องคือการเห็นตาคู่แข่งหลัง cutoff |

การงด cutoff เป็นการทดลองแยกสาเหตุ ไม่ใช่ข้อเสนอให้ถอด Tablebase ออกจากโปรดักชัน การแก้ทั่วไปต้องคง WDL ไว้พร้อมตรวจประวัติและความคืบหน้าในการชนะ

## 4. Server และหน้าเว็บ

- [web/app.js:538](D:/ThaiMakhosEngine/web/app.js:538) ส่ง position, clock, history, mode และ rules_profile
- [server.py:82](D:/ThaiMakhosEngine/makhos/server.py:82) แปลง history เป็น Counter และตรวจว่าจบตรงตำแหน่งปัจจุบัน
- [server.py:807](D:/ThaiMakhosEngine/makhos/server.py:807) ส่ง history ให้ `engine.search`
- [server.py:830](D:/ThaiMakhosEngine/makhos/server.py:830) ส่ง `result.move.notation` เป็น bestmove โดยตรง
- [web/app.js:575](D:/ThaiMakhosEngine/web/app.js:575) ใช้ bestmove นั้นในคำขอ apply-move

เรียก handler จริงใน process แยก โดยแทนเฉพาะ engine factory ด้วย Engine จริงที่เปิด TB4 ผลคือ HTTP-style status 200, bestmove `6-9`, score `1000000`, WDL `DRAW..WIN` ตาม Engine ทุกประการ ไม่ได้เปิด HTTP listener หรือเชื่อมต่อเกม GUI ของผู้ใช้

**การแปลงผลใน server/frontend จึงไม่ใช่สาเหตุของกรณีที่ทำซ้ำนี้** แต่ server เป็นจุดตั้งค่า distance budget ที่ต้องจัดการเมื่อแก้

อีกข้อที่เกี่ยวข้อง: [server.py:797](D:/ThaiMakhosEngine/makhos/server.py:797) เตรียม TB3 เมื่อ root เหลือไม่เกิน 3 ตัวเท่านั้น ถ้าเข้าเกมที่ root 4 ตัวใน cold session อาจยังไม่มี TB3 สำหรับใบที่ลดเป็น 3 ตัว จึงต้องมีแผนรองรับก่อนเปิดการคำนวณระยะ

## 5. แนวทางแก้ที่เสนอให้ทำต่อ

1. เพิ่มการเลือกตาปลายเกมที่ตรวจประวัติซ้ำจริง โดยใช้ WDL เป็นข้อจำกัดในการรักษาผล และค้นต่อให้เห็นตาตอบ/เส้นทางเสมอที่ทำให้ผลชนะใช้ไม่ได้ ไม่ถือ `DRAW..WIN` เป็นคะแนนชนะที่จบการค้นได้เสมอ
2. ให้ทางบังคับชนะหรือระยะความคืบหน้าที่พิสูจน์ได้มาก่อน pressure/notation เมื่อจัดอันดับตาที่รักษาผลได้ ต้องรองรับ oracle ของจำนวนหมากที่ลดลง และจำกัดทั้งเวลาและจำนวนโหนด หากข้อมูลไม่ครบยังต้องรายงาน unknown
3. อย่าแก้เพียงเพิ่ม repetition penalty หรือเปิดงบ DTM อย่างเดียว: penalty อาจไม่ถูกประเมินเลยเพราะ cutoff; DTM ใช้กฎไม่มี repetition; การเพิ่มงบอาจติดขนาดกราฟ/ใบที่ไม่มี oracle และไม่มีการรับประกันเวลาจาก max_nodes เพียงอย่างเดียว
4. ล็อก regression นี้ทั้ง BEST/WIN พร้อมกรณีซ้ำในตาตัวเอง, ซ้ำในตาคู่แข่ง, วงซ้ำที่ยาวกว่า, เปลี่ยนจำนวนหมาก 6→5→4→3, cold/warm TB3 และนาฬิกาใกล้ 80 ก่อนทดสอบผ่าน GUI

DTR ใน [distance.py:18](D:/ThaiMakhosEngine/makhos/distance.py:18) นิยามเฉพาะเส้นทางที่รักษา DRAW ไปจน capture/promotion หรือเสมอ no-progress จึงไม่ได้เป็นกลไกพา WIN ไป reset ใน implementation ปัจจุบัน หากใช้ระยะถึง reset สำหรับ WIN ต้องกำหนดความหมายและความถูกต้องเพิ่ม

## 6. หลักฐาน ข้อจำกัด และการรักษางานที่กำลังรัน

- ตรวจบน Git HEAD `d8531f6a03fbd8bb0f32a2449890212ac0770555`
- TB4 จริง ขนาด 12,419,180 bytes, SHA-256 `650B0C862343D718FD0FE438DB28E47D48618DEA69D693D65210088775DE30E9` ตรง manifest
- เก็บ SHA-256 ของ source สำคัญ, protected rules, model และ DLL ทั้งสองไว้ใน [identities.json](D:/ThaiMakhosEngine/work/endgame_diagnosis_20260908/identities.json)
- ตรวจพบ SPRT 1000ms PID 30272, creation time `2026-09-08T21:02:21.935281+07:00` ก่อนและหลังการสืบสวน ไม่หยุดหรือแก้ process นั้น ไม่อ่าน active checkpoint ไม่สร้าง native code ไม่แก้ manifest และไม่รัน arena เพิ่ม
- ชุดวินิจฉัยทำงาน BelowNormal ไม่มี native workers หรือ native TT allocation ใช้เฉพาะ TB4 แบบอ่าน ไม่แตะข้อมูลฝึกหรือ sealed partition
- focused tests เดิม 5 ข้อผ่านใน 0.006 วินาที: root no-progress terminal, root repetition terminal, bounded TB outcome, ranked-four-piece routing และ incomplete-DTM guard
- ไม่รัน full suite ขณะ SPRT ยังทำงาน ไม่มีการแก้ไฟล์ playing source/tests ที่อยู่ใน Git; มีเพียงโฟลเดอร์วินิจฉัยใหม่นี้
- ทำซ้ำ **threefold repetition** ได้แล้ว ยังไม่มีหลักฐานว่าอาการจบด้วย **80-ply no-progress** มาจากกลไกเดียวกัน และยังไม่ได้เล่นซ้ำเกมต้นฉบับของผู้ใช้
- ตรวจ TB4 ด้วยไฟล์จริง ส่วน TB5/TB6 พบว่าใช้ reader/score/distance path เดียวกันจากโค้ด ยังไม่ได้อ้างการทำซ้ำครบทุกจำนวนหมาก
- งานนี้ไม่ได้วัด Elo, NPS หรือเลือกจำนวน Threads และไม่ได้ยืนยัน runtime identity ของ GUI ในเกมเดิม

ไฟล์ส่งต่อ:

- [reproduce.py](D:/ThaiMakhosEngine/work/endgame_diagnosis_20260908/reproduce.py): regression ที่จับอาการจริงและตรวจทางชนะด้วย rules oracle
- [reproduction.json](D:/ThaiMakhosEngine/work/endgame_diagnosis_20260908/reproduction.json): ตำแหน่ง ประวัติ ตาที่เลือก และคะแนนทุก candidate
- [controls.py](D:/ThaiMakhosEngine/work/endgame_diagnosis_20260908/controls.py) และ [controls.json](D:/ThaiMakhosEngine/work/endgame_diagnosis_20260908/controls.json): หลักฐานเปลี่ยนทีละเงื่อนไข

**ข้อสรุปสถานะ: ยืนยันสาเหตุของบั๊กในกรณีที่ทำซ้ำแล้ว; ยังไม่มี production fix หรือการ promote ใด ๆ** งานถัดไปที่ตรงประเด็นที่สุดคือ candidate สำหรับการเลือกตา TB ที่ตรวจประวัติจริงและให้ลำดับความสำคัญกับการปิดเกม พร้อมรัน correctness/strength gates เมื่อทรัพยากรว่าง โดยรักษาผล SPRT ปัจจุบันแยกจาก candidate ใหม่นั้น
