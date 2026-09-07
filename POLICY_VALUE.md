# Proof-guided policy–value และระยะเอนเกม

โมดูลนี้แยก “สิ่งที่พิสูจน์ได้” ออกจาก “สิ่งที่เรียนรู้จากสถิติ” อย่างเคร่งครัด เพื่อไม่ให้โมเดลที่มั่นใจผิดทำลายผล non-loss

## ลำดับการเลือกตา

1. จัดชั้นด้วย **WDL lower bound** ก่อนเสมอ: `WIN` > `DRAW` > `LOSS` ตาที่มีหลักประกันต่ำกว่าจะถูกตัดออก แม้โมเดลให้โอกาสชนะสูงเพียงใด
2. ถ้ามี proof strategy ที่ตรวจแล้ว โหมด `win` พิจารณาตาปลอดภัยทุกตาในชั้น WDL สูงสุดโดยไม่ให้คะแนน heuristic ตัดตาทิ้ง; หากไม่มี proof จึงใช้ `--win-margin` เป็น score envelope ตามปกติ
3. ถ้ามี exact WIN/LOSS พร้อม decisive DTM ที่คำนวณสำเร็จ โหมด `win` จะปิดชัยชนะให้สั้นที่สุดหรือยืดการต้านทานให้นานที่สุดก่อนใช้สถิติ เพราะระยะนี้เป็นหลักฐานที่แข็งกว่าโมเดล
4. นอกกรณี DTM ตัดสิน โหมด `win` เลือกโอกาสชนะจาก self-play สูงสุด แล้วใช้ expected score, DTR, human pressure และคะแนนค้นหาเป็นตัวตัดสินลำดับถัดไป
5. โหมด `best` ยังคงใช้คะแนน minimax เป็นหลัก แล้วใช้ DTM/DTR และ policy–value เฉพาะตอนคะแนนเท่ากัน

ดังนั้น self-play เป็นเพียงตัวเลือกใน safety envelope ไม่ใช่หลักฐาน WDL

หากระบุ `--proof-strategy` certificate จะถูกตรวจด้วย `CertificateChecker` ก่อนใช้งาน ที่โหนดฝ่ายเอนจิ้น ทั้งสองโหมดและ self-play exploration ถูกจำกัดให้อยู่ในชุดตาที่มีหลักฐาน non-loss โดยตรง หากสร้างด้วย `--all-safe-choices` จะเก็บตาปลอดภัยทุกตาเพื่อให้ policy–value และ DTM/DTR เลือกตาที่น่าชนะที่สุดภายในหลักประกัน การตรวจ closure หยุดที่ exact tablebase leaf ที่ยืนยันผลแล้ว ไม่ได้ขยายฐานทั้งหมดล่วงหน้า เมื่อถึงตาฝ่ายเอนจิ้นภายใน exact frontier runtime จึง derive ตาปลอดภัยต่อแบบไดนามิกได้เฉพาะเมื่อสถานะและลูกทุกตาที่จำเป็น probe ได้; หาก dependency ไม่ครบจะ fail closed ตาคู่แข่งยังเลือกได้จาก legal replies ทุกตาที่ proof ครอบคลุม และระบบปฏิเสธตำแหน่งฝ่ายเอนจิ้นที่ไม่อยู่ใน DAG หรือ exact frontier แทนการ fallback ไป heuristic แบบเงียบ ๆ

proof ขนาดใหญ่ใช้ไฟล์ `MKSTRAT1` แบบ memory-mapped ได้ พฤติกรรมการเลือกตาเหมือน JSON DAG แต่ไม่โหลดโหนดทั้งหมดเป็น Python objects JSON certificate ตรวจ no-progress horizon และชุด checksum ของ ranked frontiers ที่ระบุไว้ ส่วน `MKSTRAT1` ตรวจ payload checksum และ combined DFPN binding เพิ่มด้วย Ranked 4–6 ตัวจึงถูกผูกกับ certificate/strategy โดยตรง ขณะที่ native 1–3 ตัวตรวจเพียง horizon/config และ binary ไม่ได้ถูก checksum-bind ใน certificate ตัวโหลดตรวจ AND/OR closure ถึง terminal/tablebase leaves แล้วเก็บเฉพาะ bitset ของโหนดที่ผ่านการตรวจไว้บังคับ runtime ผู้เรียกต้องเปิด native/ranked tablebase handles ไว้ตลอดอายุของ engine/strategy

## โมเดล policy–value รุ่นแรก

`EmpiricalPolicyValueModel` เป็นโมเดล Bayesian ที่อ่านตรวจสอบได้และไม่มี dependency ภายนอก เก็บสถิติ W/D/L จากมุมของฝ่ายที่เดิน โดยรวม feature แบบ side-relative เช่นจำนวนเบี้ย/ฮอส, clock, mobility, การบังคับกิน, ชนิดตัวเดิน, จำนวนที่กิน, การเข้าฮอส, การรุก และโซนปลายทาง

โมเดลคืนค่า:

- `win/draw/loss`: posterior probability ของผลเกมหลังเลือกตานั้น
- `policy`: prior จากความถี่ที่ action bucket ถูกเลือกในบริบทคล้ายกัน
- `samples`: effective evidence หลังรวม context กับ back-off bucket

ไฟล์ JSON มี `format` และ `version` ชัดเจน โหลดไฟล์คนละชนิดหรือคนละรุ่นไม่ได้ สัญญา `predict/update/save/load` ถูกแยกจาก search เพื่อให้เปลี่ยนเป็น neural policy–value ภายหลังได้โดยไม่แตะ invariant ของ proof layer

## DTM และ DTR

- **DTM**: ถ้าผลเป็น WIN เลือกระยะบังคับชนะสั้นที่สุด; ถ้าเป็น LOSS เลือกระยะต้านทานยาวที่สุด
- **DTR**: สำหรับ exact DRAW วัดระยะ minimax ถึง capture/promotion ที่ reset no-progress clock หรือถึง terminal จากกฎ no-progress โดยฝ่ายเอนจิ้นพยายามให้สั้นและคู่ต่อสู้พยายามให้ยาว

ฐาน native 1–3 ตัวและ Python exact solver ให้ decisive DTM โดยตรง ส่วนฐาน ranked 4–6 ตัวเก็บ WDL เท่านั้น จึงไล่เฉพาะ edge ที่รักษา WDL แบบ on-demand ภายใต้งบ `--distance-nodes` ค่าระยะจะถูกแสดงว่า `exact` เฉพาะเมื่อไล่ subgraph ที่จำเป็นครบ ถ้างบหมดจะแสดง `unknown` และไม่สร้างค่าประมาณปลอมขึ้นมา ค่าเริ่มต้นเป็น `0` จึงไม่ไล่ระยะแบบ recursive จากฐาน ranked แต่ยังใช้ DTM ที่ oracle ให้โดยตรงและ DTR หนึ่ง ply ที่จบด้วย capture/promotion ได้; เปิดเช่น `--distance-nodes 50000` เมื่อต้องการลอง derive ระยะจากฐาน WDL-only

เมื่อกฎเล่นจริงเปิด threefold repetition แต่ tablebase ใช้ no-progress อย่างเดียว ค่า WDL ยังถูกลดเป็นช่วง `DRAW..WIN`/`LOSS..DRAW` ตามเดิม ระยะที่ได้จึงเป็นระยะภายใต้ฐาน no-progress ไม่ใช่คำรับรองว่าจะหลบ repetition ได้ทุกประวัติ

DTR เป็นระยะ minimax เฉพาะถึง reset หรือ no-progress terminal ถัดไป ไม่ใช่ระยะถึงจบเกมหรือ mate และไม่ใช่หลักฐานว่าเกมจะปิดเป็นชัยชนะในที่สุด

## ฝึกและใช้งาน

เริ่มโมเดลใหม่:

```powershell
python -B -m makhos train-selfplay --games 100 --depth 4 --output-model build/policy-value.json
```

ฝึกต่อจากไฟล์เดิม:

```powershell
python -B -m makhos train-selfplay --games 100 --depth 4 --policy-model build/policy-value.json --output-model build/policy-value.json
```

ใช้เลือกตา:

```powershell
python -B -m makhos bestmove --mode win --depth 7 --policy-model build/policy-value.json
```

ระหว่าง exploration ตัวฝึกจะสุ่มเฉพาะตาใน WDL lower-bound ชั้นสูงสุด และจำกัดด้วย `--exploration-score-margin`; การเล่นจริงไม่สุ่ม

หากไม่ส่ง `--proof-strategy` การฝึกเป็นเพียง WDL-guided self-play จาก search bounds; เมื่อส่ง strategy ที่ตรวจแล้วจึงเป็น proof-guided self-play และฝ่ายเอนจิ้นจะสำรวจเฉพาะตาที่ใบรับรองอนุญาต ทั้งตัวฝึกและเอนจิ้นต้องใช้กติกาชุดเดียวกันทุกฟิลด์

เกมที่ชน `--max-game-plies` จะถูกนับเป็น `truncated` และ **ไม่** ถูกติดป้ายว่าเสมอ เพื่อไม่ป้อน label เท็จให้ value model; เสมอจะถูกใช้ฝึกต่อเมื่อกฎ repetition/no-progress ตัดสินเกมจริงเท่านั้น

## ขอบเขตหลักฐาน

โมดูลนี้เพิ่มคุณภาพการเลือกตาภายในผลที่ปลอดภัย แต่ **ยังไม่พิสูจน์ตำแหน่งเริ่มต้น** ตำแหน่งเริ่มต้นทั้งเจ็ดตายังเป็น `UNKNOWN` ใน DFPN การกล่าวว่าเอนจิ้น “ไม่มีวันแพ้” จะทำได้ต่อเมื่อ root ได้รับการพิสูจน์เป็น WIN/DRAW และทุกตาที่เล่นเชื่อมต่อกับ proof/tablebase ที่ตรวจซ้ำได้
