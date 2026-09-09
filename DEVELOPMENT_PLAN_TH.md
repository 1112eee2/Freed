# คู่มือพัฒนา: จบ NNUE v1 → แก้ความคุ้มค่าของ Threads → เพิ่ม Elo ต่อเนื่อง

งาน GUI ตามคำขอผู้ใช้ 2026-09-09: เพิ่ม save เกม, ผลตัดสินโดยผู้ใช้ และ undo 1 ply
อยู่ใน branch แยก รอ Local smoke/full-suite และประสานแพตช์ rematch ก่อนรวมเข้าระบบ
รายละเอียดและหลักฐาน: [GUI implementation](work/GUI_GAME_RECORDS_IMPLEMENTATION_TH.md)
งานนี้ไม่สั่ง resume Experiment A ที่พักไว้ 27 คู่ และไม่แก้ search/native/release pointer

## 1. จุดเริ่มต้นและเป้าหมายที่ใช้ตัดสิน

สถานะอ้างอิงจาก [บันทึกปัจจุบัน](.agents/skills/thai-makhos-engine/references/current-state.md) วันที่ 8 กันยายน:

- NNUE ฝึกและผ่านการตรวจข้อมูล/การคำนวณแล้ว; Gate A และ Gate B **PASS**
- Gate C: **FINISHED_PASS ทั้ง 2 ระดับเวลา**
  - 1.0 วินาที: 546 คู่ / 1,092 เกม, LLR +2.946, Elo vs HCE +80.3 +/- 13.5
  - 2.0 วินาที: 554 คู่ / 1,108 เกม, LLR +2.946, Elo vs HCE +79.8 +/- 12.9
- Production Promotion: **เสร็จสมบูรณ์ — GUI ใช้ NNUE v1 เป็นค่าเริ่มต้นแล้ว**
  - ตรึง release manifest ที่ `releases/nnue-v1-20260908/manifest.json`
  - สลับ pointer `config/gui_release.json` เป็น `nnue`
  - ผ่านการตรวจ Full suite (403/403 tests), Node lifecycle (3/3 tests), และ HTTP production smoke
  - คงความสามารถ rollback กลับไปใช้ baseline HCE ได้ผ่าน `--release-profile hce`
- เครื่องมี **6 คอร์จริง/12 เธรด** ตามที่คุณเลือก เป้าหมายคือความแข็งแกร่งสูงสุดบนเครื่อง ไม่บังคับใช้ 12 เธรดหากจำนวนอื่นมีหลักฐานว่าดีกว่า

แยกความสำเร็จเป็นสามเรื่อง: NNUE แข็งแกร่งกว่า HCE, การใช้หลายเธรดคุ้มค่า และรุ่นใหม่แข็งแกร่งกว่ารุ่นก่อน อย่าใช้ผลทดสอบเรื่องหนึ่งแทนอีกเรื่องหนึ่ง

## 2. ผลการนำ NNUE v1 ขึ้นใช้งานจริง (เสร็จสมบูรณ์)

- ผ่าน Gate C ทั้ง 1s และ 2s (+80 Elo) ชนะเอนจิ้นเดิมเด็ดขาด
- Web GUI (`python server.py`) เปิดใช้งานด้วย NNUE v1 เป็นค่าเริ่มต้น (12T, 512 MiB TT)
- แก้ไขปัญหา race condition บนหน้าเว็บด้วย `AbortController` และแก้ความเร็ว forced move (2.5ms)
- ตรึงบันทึกรับรองการขึ้นระบบไว้ที่ `releases/nnue-v1-20260908/promotion_attestation.json` และ `PROMOTION_ATTESTATION.md`
- สถานะ: **PROMOTED AS PRODUCTION DEFAULT**

## 3. แก้ปัญหา 12 Threads ไม่คุ้มโดยแยกสาเหตุให้ได้ก่อน (เสร็จสิ้น Phase 4: Thread Audit)

### ผลการตรวจวัด NNUE thread-scaling audit (5,760 observations ครบถ้วน)

รันด้วยตัวเก็บผล native (`work/nnue_thread_audit_collect.py`) และสรุปผลด้วย `work/nnue_thread_audit_report.py`
บันทึกไว้ที่ `build/nnue_thread_scaling_measured_v1/report.json` (สถานะ `COMPLETE_DIAGNOSTIC`):

เปรียบเทียบ **1 / 2 / 4 / 6 / 8 / 12 เธรด** ที่ 1 และ 2 วินาที Hash รวม 512 MiB บน 96 ตำแหน่ง (5 repetitions):

1. **การสเกลของโหนด (Playout positions ที่ 2 วินาที)**:
   - 1T: 3.94M nodes (1.00x)
   - 2T: 5.77M nodes (1.46x)
   - 4T: 8.41M nodes (2.13x)
   - 6T: 9.67M nodes (2.45x)
   - 8T: 11.01M nodes (2.79x)
   - 12T: 11.73M nodes (2.97x)
2. **สาเหตุคอขวดที่ค้นพบจากข้อมูลจริง**:
   - **Root-Split Branch Starvation**: จำนวนตาเดินเฉลี่ยของตำแหน่งทดสอบคือ 6.82 ตา และมีถึง 31/96 ตำแหน่งที่มีตาเดิน <= 6 ตา ส่งผลให้เมื่อตั้ง 12 เธรด เธรดส่วนเกินจะว่างงาน (idle) ทำให้ CPU utilization ที่ 12T ได้เพียง ~3.9x
   - **SMT Saturation บน 6 Physical Cores**: การขยับจาก 6T เป็น 12T ได้โหนดเพิ่มเพียง +21.3% เพราะต้องแย่ง execution resources ในแต่ละ core
   - **Synchronization Barrier**: Root-splitting ต้องรอให้ทุกตาเดินที่ root จบความลึก D-1 ก่อน ความลึก D จึงจะได้รับการยอมรับ ทำให้ความลึกที่จบเฉลี่ยอยู่ที่ 18-20 (เทียบกับ 1T ที่ตัดกิ่งได้เร็วจนได้ความลึก 22-23) แม้ 12T จะประเมินโหนดมากกว่าถึง 3 เท่า
3. **ความเสถียรและการบริหารเวลา พร้อมข้อจำกัดของชุดข้อมูล**:
   - Playout subset คือ 66 ตำแหน่ง × 5 ซ้ำ = 330 observations ต่อ configuration (อีก 30 ตำแหน่งเป็น forced 14 และ clock-edge 16) โดย stability 98.5% ของ 1T คือ 65 จาก 66 ตำแหน่ง
   - Overshoot p95 อยู่ในช่วง <= 4.4ms ในเกือบทุกขนาดเธรด ยกเว้น 2T ที่ 2s กลุ่ม playout มี p95 = 8.044ms
   - ตัวเลข forced latency 1.0ms และ score 0 ถูกกำหนดไว้ในโค้ดตัวเก็บผล ไม่ใช่ผลจับเวลาฮาร์ดแวร์จริง
   - การตรวจ tablebase ในตัวเก็บผลตรวจเฉพาะขนาดและ checksum ไม่ได้วิ่งผ่าน Engine endgame oracle ในการเดินหมากจริง (ซึ่งในชุด playout มี 10 ตำแหน่งที่มีตัวหมาก <= 6 ตัวที่ใน production จะวิ่งเข้า tablebase)
   - Telemetry ที่ไม่ได้วัด (active workers, coordination, NNUE time, ความถี่ CPU, อุณหภูมิ) มีค่าเป็น null ตามจริง; ข้อสรุปเรื่อง branch starvation และ SMT saturation เป็นสมมติฐานเชิงกลไกที่สอดคล้องกับข้อมูล ไม่ใช่ตัวเลขจาก hardware counter โดยตรง
   - ข้อมูล observations 5,760 รายการเป็น offline diagnostic matrix ไม่ใช่การตรวจ profile/production ครบ (`profile_coverage_complete=false`, `strength_evidence=false`)

ผลค้นลึกใช้เป็นข้อมูลวินิจฉัย ไม่ถือเป็นคำตอบถูกแน่นอน และไม่ใช้ NPS รวมแทนความแข็งแกร่ง

### การทดลองที่อนุมัติสำหรับ Phase 5: การแข่งขัน A (6T vs 12T Superiority SPRT)

- **คำถามวิจัย**: “6T ให้ Elo สูงกว่า 12T ที่เวลาใช้งานจริงหรือไม่?” บนเครื่อง 6 physical cores / 12 threads นี้
- **Candidate / Control**: NNUE v1 6T / NNUE v1 12T (ใช้ DLL และ `model_a.mknnue` ชุดเดียวกัน โดยทำสำเนา DLL เป็นสองไฟล์เพื่อผ่านเงื่อนไข CLI)
- **Hash**: 512 MiB ต่อเอนจิ้น
- **เวลา**: Fixed 1,000ms (seed 20261108) และ 2,000ms (seed 20261109) รันสองชุดอิสระ
- **SPRT Framework**: Pentanomial SPRT, H0=0, H1=+2 Elo, α=β=0.05, ขอบเขต LLR ±2.944438979, เพดาน 10,000 คู่ต่อชุด
- **การรัน**: `parallel-games=1` (รันทีละคู่เพื่อไม่ให้เอนจิ้นแย่งทรัพยากรกันเอง)
- **เงื่อนไข**: นี่คือ Superiority test หากผลเป็น FAIL หรือ INCONCLUSIVE ไม่ได้พิสูจน์ว่าแรงเท่ากัน แต่หมายถึงไม่มีหลักฐานความเหนือกว่าอย่างมีนัยสำคัญ และจะคงค่าเริ่มต้น 12T ไว้ตามเดิม

**เกณฑ์จบ:** มี configuration แนะนำที่ผ่านหลักฐานความแข็งแกร่งและ runtime พร้อมคำอธิบายว่า 12 เธรดเสียตรงไหน หากยังไม่พบ multi-thread configuration ที่เหนือกว่า 1 เธรด ให้รายงานว่า SMP ยังไม่สำเร็จ แม้จะตั้งค่าที่ปลอดภัยกว่าให้ใช้ชั่วคราวแล้วก็ตาม

## 4. เพิ่ม Elo จากด้านอื่น โดยเลือกทีละการทดลอง

ลำดับนี้เป็นคิวตามชนิดของหลักฐาน ไม่ใช่คำสั่งให้เพิ่ม heuristic ทุกตัว

| ด้าน | งานที่ควรทดลอง | เงื่อนไขเลือก |
|---|---|---|
| ต้นทุน NNUE | `ancestor delta` ที่เตรียมไว้: ลดการสร้าง accumulator ระหว่างทาง | profile ยืนยันว่าต้นทุนส่วนนี้สำคัญ |
| งานค้นหาสิ้นเปลือง | ลดการสร้างตาซ้ำ งาน qsearch ที่ซ้ำ และต้นทุนข้อมูล/หน่วยความจำ | มี hotspot และยังรักษาความหมายเดิมได้ |
| คุณภาพ single-thread search | move ordering, history และการลดปัญหา horizon | ตำแหน่งหลากหลายแสดงว่าค้นผิดทิศ ไม่ใช่แค่ช้า |
| การบริหารเวลา | ลด setup/stop overhead และรักษาผล iteration ที่จบ | มีเวลาสูญเปล่าหรือผลถอยเมื่อ deadline |
| NNUE รุ่นถัดไป | เพิ่มคุณภาพข้อมูล/teacher ก่อนขยายโมเดล | error analysis และ learning curve สนับสนุน |

สำหรับ `ancestor delta` ต้องเริ่มจากตรวจ snapshot และอัปเดตการผูกกับ baseline ปัจจุบันในบันทึกใหม่ เพราะ preflight เดิมยังอ้างรุ่นเก่า จากนั้นตรวจ native accumulator เทียบ full refresh ให้ตรงทุกค่า รวมกินหลายต่อ เลื่อนเป็นฮอส เปลี่ยน clock, null move, sibling และ PVS retry ก่อนวัดความเร็ว

การแก้ประสิทธิภาพที่อ้างว่าไม่เปลี่ยนพฤติกรรม ต้องคง move/score/nodes/PV ใน deterministic single-thread benchmark ส่วนการเปลี่ยน search quality ให้ประกาศว่าเป็น **strength-changing candidate** และตรวจความถูกต้องของกติกา/ขอบเขตคะแนนควบคู่กับการแข่งขัน ไม่อ้างว่าเป็น refactor ที่เหมือนเดิม

การบริหารเวลาต้องเคารพโหมดผู้ใช้: ตั้ง 1 วินาทีต่อตาไม่ควรแอบย้ายงบข้ามตา และไม่เพิ่มการรอเฉย ๆ ให้ดูเหมือนใช้เวลาครบ ส่วนตาบังคับหรือคำตอบ exact อาจคืนผลเร็วได้

สำหรับ NNUE รุ่นถัดไป:

- เก็บเกมใหม่จากรุ่นที่ผ่านแล้ว คู่แข่งอิสระ และการสำรวจตาที่หลากหลาย
- ใช้ตำแหน่งไม่แน่ใจ/เสียเปรียบเพื่อหาข้อมูลเพิ่ม ไม่ตีตราตาจากเกมเดียวว่าเป็นคำตอบจริง
- แยกข้อมูลระดับเกม ป้องกันตำแหน่งซ้ำข้ามชุด และสร้าง sealed test ใหม่สำหรับรุ่นใหญ่
- เปลี่ยนทีละแกน: ข้อมูล, คุณภาพ label, loss หรือขนาดโมเดล
- ไม่เปิดชุดทดสอบที่เคยใช้แล้วซ้ำเพื่อเลือกโมเดล และไม่ถือว่า offline loss ลดลงแปลว่า Elo เพิ่ม

## 5. ระบบป้องกันถอยหลังและเกณฑ์ส่งมอบ

ทุกการทดลองใช้วงจรเดียวกัน:

**ล็อกสมมติฐาน/เกณฑ์ → correctness → benchmark/profile → paired SPRT → PROMOTE / REJECT / INCONCLUSIVE**

- เก็บ accepted เป็น control เสมอ แยก candidate และข้อมูลผลทดสอบ ไม่ overwrite ของที่กำลังใช้งาน
- เมื่อ workers ว่าง ให้รันชุดทดสอบที่ค้นพบทั้งหมด พร้อม regression ของสิ่งที่แก้; 393/393 เป็นหลักฐานเดิมบน Windows ไม่ใช่ผลของ checkout ใหม่ ต้องรายงาน failures/errors/skips ตามจริง การผ่าน tests อย่างเดียวไม่ใช่หลักฐานเพิ่ม Elo
- ล็อก seed, กติกา, เวลา, Hash, Threads, hashes และเกณฑ์หยุดก่อนแข่ง สำหรับการยืนยัน strength ใช้กรอบ H0=0/H1=+2, α=β=0.05 และเพดานที่ประกาศล่วงหน้า; ไม่เปลี่ยนกลางทาง
- ทดสอบทั้งการกลับมาทำงานหลังหยุด การไม่เพิ่มผลคู่ซ้ำ การให้ GUI ใช้ทรัพยากรก่อน และการไม่แปลงเกมที่ถูกตัดเป็นเสมอ
- บันทึกผลแต่ละครั้งใน ledger; ให้ `SKILL.md` ชี้เพียงงานถัดไปที่ยังใช้จริง พร้อมเหตุผลเลือกและเงื่อนไขหยุด

Status terminal ต้องแสดงขั้นปัจจุบัน จำนวนคู่/เกม LLR เทียบขอบเขต เวลาที่ผลขยับล่าสุด และสถานะรัน/พัก/ผิดพลาด อ่านตัวตนโปรเซสจากข้อมูลการรันแทน PID ที่ฝังไว้ และไม่แปลง LLR เป็น “เปอร์เซ็นต์ใกล้เสร็จ”

หลังแต่ละ promotion จึงแข่งกับคู่แข่งภายนอกหลายระดับด้วย openings และสีที่สมดุล เก็บเกมพร้อม provenance เพื่อแยกความก้าวหน้าใน self-play ออกจากความสามารถจริงกับคู่แข่ง

**ลำดับหลัก:** จบ Gate C → ขึ้น NNUE v1 อย่างปลอดภัย → วัด thread scaling/profile → แก้คอขวดที่คุ้มที่สุดทีละตัว → ยืนยัน Elo → พัฒนาข้อมูล/NNUE รุ่นถัดไป

ไม่รวมการกลับไปทำ DFPN หรือ tablebase ใหญ่กว่า 6 ตัวในรอบนี้ และไม่รับประกันว่า 12 เธรดต้องเร็วหรือแรงกว่าเสมอ เป้าหมายคือรุ่นที่เล่นแข็งแกร่งขึ้นจริงโดยมีหลักฐานและย้อนกลับได้


## 2026-09-09 — Phase 1C: native TB3 implementation milestone

KEEP experimental/default-off; C1 remains incomplete pending TB4–6.
Added native owned TB3 image, C17 versioned probe API and ctypes bridge.
48,600 raw Python/native probes match (seed 20260909); full Windows suite
461/461 PASS, zero skips/failures/errors in 150.154 s. Inventories unchanged;
protected production opens zero; rules/core/accepted DLL hashes unchanged.
Evidence: `benchmarks/results/endgame_c1_tb3/summary.json`; implementation
notes: `docs/architecture/ENDGAME_NATIVE_C1_TB3_TH.md`. No GUI routing change
or search performance/Elo claim. Next gate: native TB4–6 mapped readers with
139-signature differential and opened-file provenance before C2 integration.
