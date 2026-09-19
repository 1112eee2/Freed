# ThaiMakhosEngine — Roadmap เทียบ Invincible 2 ของอาจารย์ทศพล ธนะทิพานนท์

วันที่ 2026-09-20 · แผนตามคำขอ Ethan · ยังไม่ใช่ผลทดลองหรือการอนุมัติ production

## เป้าหมายและเส้นทางหลัก

**แก้ความเข้าใจจากแผนฉบับแรก:** Invincible 2 เป็นคู่เทียบภายนอกของอาจารย์
ทศพล ธนะทิพานนท์ ไม่ใช่ชื่อรุ่นของ ThaiMakhosEngine เป้าหมายไม่จบเพียงชนะรุ่นเก่าของเรา
แต่ต้องไปถึงการไม่แพ้คู่เทียบนี้ แล้วเหนือกว่าใน practical play จากตำแหน่งซับซ้อน

[หน้า Invincible II ของผู้พัฒนา](https://hosbase.com/invincible2/) ระบุผู้จัดทำตรงกับเป้าหมาย
[ประวัติโดยผู้พัฒนา](https://www.aimechatron.com/future) อธิบาย Invincible 2 ว่ารักษาคุณสมบัติ
ไม่แพ้และเพิ่มการเอาชนะคู่แข่งที่พลาด ส่วน Future เป็นอีกรุ่น ห้ามนำมาแทนโดยไม่ระบุ
นี่เป็นคำอธิบายจากผู้พัฒนา ไม่ใช่การตรวจ certificate หรือกติกาของบริการนั้นโดยโครงการเราแล้ว

## เป้าหมายสาม Phase ตามคำชี้แจง Ethan

| Phase | เป้าหมาย | หลักฐานที่ต้องมี |
|---|---|---|
| **1 — ยกระดับจากจุดที่ยังแพ้ได้** | ลดการพลาดและเข้าใกล้ระดับไม่แพ้ | baseline ภายนอก, replay เกมแพ้, regression ของสาเหตุจริง และผลพัฒนาบนชุดใหม่ |
| **2 — ขั้นต่ำเสมอ Invincible 2 ได้ทุกเกม** | เป้าหมายระยะยาวคือ non-loss 100% จากตำแหน่งเริ่มต้นที่อยู่ในขอบเขต ทั้งสองสี | แยกผลทดสอบไร้พ่ายกับข้อพิสูจน์ครอบคลุมทุกทางตอบอย่างชัดเจน |
| **3 — เหนือกว่าใน practical play** | ตำแหน่งเดียวกัน เราชนะได้ในกรณีคู่เทียบทำได้แค่เสมอ หรือเรารักษาเสมอได้ในกรณีคู่เทียบแพ้ | paired comparison ทั้ง win conversion และ defensive hold, ผลซ้ำได้ และไม่แลกความปลอดภัย Phase 2 |

### Phase 2: คงเป้า 100% แต่ไม่อ้างว่าแข่งครบจำนวนหนึ่งเท่ากับพิสูจน์แล้ว

- เป้าหมายคือขั้นต่ำไม่แพ้ ไม่ได้บังคับให้ทิ้งตาชนะเพื่อจบเสมอ หากพบชัยชนะเหนือคู่เทียบ
  ให้ตรวจ version/rules/บันทึกและสาเหตุ ไม่สรุปว่าเป็นไปไม่ได้หรือถือว่าเป็นความสำเร็จทันที
- **Empirical gate:** ไม่มีแพ้ในชุดเกมที่ freeze ล่วงหน้า ครบสองสี/หลายการเปิดเกม/หลาย seed
  พร้อมจำนวน W/D/L และการกระจายรูปหมาก ต้องรายงานว่าไม่แพ้เฉพาะชุดที่ทดสอบ ไม่เรียกไร้พ่ายทุกเกม
- **Universal target:** ถ้าจะรับรอง 100% ต้องมี non-losing strategy ที่ตรวจได้ ครอบคลุมทุก legal
  reply ของคู่แข่งในขอบเขต และ implementation เลือกตาม strategy นั้นจริง ไม่ใช่แค่ NNUE score
  หรือหนังสือเปิดเกมที่ครอบคลุมเฉพาะ main line อ้างอิง [proof roadmap](../../PROOF_ROADMAP.md)
  เพื่อออกแบบเท่านั้น ตัวเลข/สถานะในเอกสารเก่าต้องตรวจใหม่ก่อนนำมาใช้
- ขอบเขตต้องรวม side-to-move, repetition history และ 80-ply clock ไม่ใช้กระดานเปล่าแทน state
  และไม่ตั้งข้อกำหนดให้รักษาเสมอจากตำแหน่งที่พิสูจน์ว่า LOSS ต่อผู้เล่นสมบูรณ์แบบ
- การรับเป้าหมายนี้ยังไม่ใช่คำสั่ง resume DFPN/checkpoints หรือสร้าง TB ใหญ่ทันที ต้องประเมิน
  ขอบเขต proof ต้นทุน และเสนอแผนแยกก่อน ไม่ลดเป้า 100% ให้เหลือเพียง win rate ที่ดูดี

### Phase 3: วัดผลเหนือกว่า ไม่ใช่หวังบังคับชนะตำแหน่งเสมอที่อีกฝ่ายเล่นสมบูรณ์แบบ

- ใช้ตำแหน่งเริ่มเดียวกัน ฝั่งเดียวกัน history/clock เดียวกัน และ defense/opponent policy
  เดียวกันที่ตอบตามสถานะจริง ไม่ replay ตายตัวที่อาจผิดกติกาหลัง engine เลือกต่างกัน
- แยก head-to-head จาก standard start ออกจาก matched task: เอ็นจิ้นทั้งสองรับบทเดียวกัน
  พบคู่ต่อสู้/defender ชุดเดียวกัน แล้วเทียบว่าใครรักษา W/D/L ได้ดีกว่า
- ตัวชี้วัดหลัก: cases ที่เรา WIN/คู่เทียบ DRAW หรือเรา DRAW/คู่เทียบ LOSS พร้อมกรณีกลับด้าน
  จำนวนทดสอบทั้งหมดและ uncertainty ไม่เลือกแสดงเฉพาะตัวอย่างชนะของเรา
- ถ้ามี independent history-aware proof/TB ให้ตรวจการรักษา WDL; ถ้ามีเพียงผลต่อคู่แข่งที่
  เล่นจริงหรือ long search ให้ระบุว่าเป็น empirical ไม่ใช่ forced win/forced draw
- การไร้พ่ายจาก standard start ไม่เท่ากับ optimal conversion ทุกตำแหน่ง arbitrary; อย่างไรก็ตาม
  หากตำแหน่งเป็น exact DRAW และอีกฝ่ายเดินถูกทุกตา เราไม่สามารถบังคับ WIN ได้

**ไม่ผูกเป้าหมายกับ Lazy SMP หรือ NNUE รุ่นใหม่** ใช้ฐานที่ตรวจรับแล้ว ปรับทีละแนวคิด
และไม่ลองกลไกที่ถูก reject ซ้ำแบบเดิม การชนะ internal baseline เป็นขั้นสนับสนุน ไม่ใช่จุดจบ

## A. หลังรับ PR จาก Astra Web: จบข้อสงสัย ไม่ขยายงานไม่รู้จบ

- ตรวจ commit/diff/source hashes, raw logs, negative control และขอบเขตคำกล่าวอ้าง
  ของ seed-state diagnostic/TSan ก่อนรับผล ไม่ auto-merge จากคำว่า PASS
- รับเฉพาะขอบเขตที่พิสูจน์: harness defect ไม่เท่ากับ production defect;
  sanitizer pass ไม่เท่ากับ strength gain หรือปิด G2–G6 ทั้งหมด
- ถ้า protocol ผ่านแต่ candidate ยังแพ้ G4 ให้คง `REJECT_FOR_PERFORMANCE / NOT_PROMOTED`
  และย้าย Lazy SMP ออกจากเส้นทางหลักของการเทียบ Invincible 2
- ถ้ายังมีปัญหา ให้แยก/ปิด candidate และตรวจว่าปัญหาไม่กระทบ backend ฐาน
  งาน strength ที่ไม่ใช้ส่วนที่มีปัญหาทำต่อได้ ไม่ต้องรอให้ Lazy SMP ทุก gate ผ่าน
  แต่ถ้าข้อผิดพลาดอยู่ในฐานที่จะนำไปใช้จริง ต้องแก้และตรวจรับก่อน

**จบขั้นนี้เมื่อ:** มี verdict ที่มีขอบเขตชัดเจนและเลือกฐานปลอดภัยได้ ไม่จำเป็นต้อง promote Lazy SMP

## B. Freeze baseline ภายในและสนามทดสอบกับคู่เทียบภายนอก

- ตรวจช่องทางใช้งาน Invincible 2 ว่าสามารถระบุสี, ตั้งตำแหน่ง, ส่ง history/clock และบันทึก
  เกมได้หรือไม่ อย่าสมมติว่ามี API หรือ position editor; ถ้าเข้าได้เฉพาะ standard start
  ให้ใช้เกม/replay ที่ทำได้จริง และรายงานข้อจำกัดของ Phase 3
- ตรวจ rules parity ก่อนจับคู่ โดยเฉพาะ repetition/no-progress/adjudication; ถ้ากติกาต่าง
  ให้รายงาน non-comparable ไม่เปลี่ยน RULESET.json/core.py เพื่อให้ผลดูตรงกัน
- freeze รุ่นคู่เทียบหรือบันทึก URL/วันเวลา/identifier ที่เข้าถึงได้ หาก backend/version/เวลา
  คำนวณ/ฮาร์ดแวร์ไม่ทราบ ให้รายงานว่าเป็น black-box service benchmark ไม่อ้าง equal-compute
  แยก think time ออกจาก network latency และไม่ตี timeout/network error เป็นผลเสมอ
- ใช้งานภายในข้อกำหนดบริการ ไม่ bulk scrape ฐานข้อมูลหรือรันโหลดหนักบนเว็บคู่เทียบ
- 1s/2s ของเราเป็น profile เริ่มต้น ไม่ใช่ข้อกำหนดว่า Invincible 2 ใช้เวลา/ทรัพยากรเท่ากัน

- ตรวจ runtime provenance ของรุ่นใช้งานจริง แล้ว freeze source/DLL/model/compiler,
  backend, mode, Threads, total Hash, เวลา, seeds และ openings ไม่อนุมานรุ่นจากชื่อไฟล์
- ใช้ production เป็น external reference/rollback; สร้าง same-source development control
  ในพื้นที่ใหม่ ห้ามถือว่า WIP ทั้งหมดเป็น production เพราะ parity เดิม 33 ตำแหน่งผ่าน
- ตรวจสถานะ strict-key TT repair แยกจาก Lazy SMP: หากยังไม่อยู่ในฐาน ให้มี regression
  และ acceptance ของการแก้ identity โดยเฉพาะ ไม่พ่วงการเปลี่ยน schedule/heuristic
- แบ่ง corpus ระดับเกม/กลุ่มตำแหน่งใกล้เคียงเป็น development กับ acceptance ที่ล็อกไว้
  ก่อน tuning; เกมที่เคยวิเคราะห์แล้วเป็น regression/development ไม่ใช่หลักฐานอิสระ
- replay `saved_games/` แบบตรวจ legality และดึง history/80-ply clock มาครบ
  แบ่งจุดอ่อน: forced capture/แท็กติก, horizon, การประเมิน, เวลา, endgame conversion,
  การป้องกันเสมอเมื่อเสียเปรียบ และสถานะเกม/TT ไม่ใช้ score จาก search เป็น solved label
- กำหนด metrics/tolerances/sample caps ล่วงหน้า: game score หลัก, tactical errors,
  proved-win preservation, latency p50/p95/p99/max, cold/warm, stop/restart และ memory

**จบขั้นนี้เมื่อ:** ทำ baseline ซ้ำได้, corpus/config มี hash, full discovered suite ผ่าน
พร้อม DLL bindings ชัดเจน ไม่มี fail/error/skip ที่ซ่อนอยู่ ไม่ใช่ยึดจำนวน 618 เป็นข้อกำหนดตายตัว

## C. งานพัฒนาใน Phase 1: เลือกการเพิ่มความแข็งแกร่งจากหลักฐาน

### C1 — วัดต้นทุนและข้อผิดพลาดจริง

ทำ Round2 แบบ diagnostic-only ที่ 1T ก่อน: แยก elapsed/CPU และ inclusive/exclusive
ของ move generation/order, TT, NNUE incremental update/eval, qsearch และ setup/stop
วัด overhead ของ instrumentation เทียบ control และ fixed-depth move/score/nodes/PV parity
ข้อมูล qsearch 51–65% ของ nodes เดิมไม่ใช่สัดส่วน CPU และไม่พิสูจน์ว่างานสูญเปล่า
หาก profiler ทำให้ต้นทุนบิดเบือน ให้แก้การวัดก่อน ไม่ใช้ตัวเลขนั้นเลือก optimization

### C2 — ทดลองทีละหนึ่งแนวคิด ตามผล C1 และเกมเทียบภายนอก

| สิ่งที่พบ | Candidate ที่ควรพิจารณา | สิ่งที่ต้องพิสูจน์ |
|---|---|---|
| ต้นทุนซ้ำใน movegen/order/NNUE update | ลด allocation/การคำนวณซ้ำ โดยไม่เปลี่ยนผล | deterministic parity + runtime gain ที่พ้น noise |
| พลาดแท็กติกแม้ไม่มี deadline | ordering/history/horizon หรือ selectivity ที่มี counterexample | regression หลายตำแหน่ง + strength gate; ไม่ปรับจากเกมเดียว |
| สูญเสียเวลาหรือผล iteration เมื่อหมดงบ | setup/stop/result retention | end-to-end latency + คำตอบที่จบสมบูรณ์ + strength gate |
| แพ้เพราะ eval มากกว่าความลึก | ข้อมูล/labels ของ NNUE ก่อนขยาย model | game-level split, fresh sealed test, inference parity และ strength gate |

ทุกการทดลองมีสมมติฐานหนึ่งข้อ, control/candidate คนละ artifact, กำหนด cap/stop rule ก่อนรัน
และจบด้วย KEEP/REJECT/INCONCLUSIVE/PROMOTE ห้ามเปลี่ยน search+model+Threads พร้อมกัน
เกิน cap แล้วยังไม่ชัดให้ INCONCLUSIVE ไม่รันซ้ำ seed ใหม่จนผ่าน

## D. นโยบาย practical conversion — รองรับ Phase 3 โดยไม่ลดความปลอดภัย

- รักษา `RootCandidate`, `_choose`, `_safety_rank` และ BEST/WIN เป็น policy จุดเดียว
  ไม่สร้าง human mode/backend อีกชุดโดยไม่จำเป็น
- Terminal/TB proof และ WDL interval สำคัญกว่าคะแนน NNUE หรือ human pressure เสมอ
  ต้องไม่สละ proved win/การรักษาเสมอที่พิสูจน์แล้วเพื่อวางกับดัก
- ถ้าจะปรับ human pressure ใช้เฉพาะการจัดอันดับภายใต้ safety bounds และ score margin
  ที่ประกาศชัด; heuristic margin ไม่ใช่คำรับรองว่าจะไม่มีทางพลาด
- BEST เป็นตัวควบคุมความแข็งแกร่งทั่วไป; WIN ทดสอบการเปลี่ยนความได้เปรียบเป็นชัยชนะ
  แยกกัน อย่าให้ผลจากคู่แข่งที่อ่อนบางรายกลบ regression กับคู่แข่งที่แข็ง
- ใช้หลาย opponents/รูปแบบความผิดพลาด, openings สลับสี และ blind positions ใหม่
  เกมมนุษย์วิเคราะห์ย้อนหลังเป็นหลักฐานประกอบ ไม่ใช้เกมเดียวประกาศ Elo

ไม่จำเป็นต้องเพิ่ม heuristic ใหม่ถ้า search/conversion ที่ดีขึ้นทำให้ชนะ matched tasks อยู่แล้ว
อย่าใช้การปรับ human pressure เพียงอย่างเดียวแทนการพิสูจน์เป้าหมาย Phase 2

## E. Internal strength acceptance และ release — ไม่ใช่ gate ทดแทน Phase 2/3

1. Correctness ปัจจุบันครบ; หากแตะ native move/state ต้อง perft ถึง depth 10 และ randomized
   differential; repetition/80-ply/TB precedence/root policy ต้องไม่ถอย
2. ทดสอบ 1T แยกจาก production multi-thread; งาน Threads ต้องรวม 1/2/4/6/8/12T
   ภายใต้ total Hash เดียวกัน ไม่เลือกรุ่นจาก NPS/depth อย่างเดียว
3. การเปลี่ยน strength ใช้ paired color-swapped pentanomial SPRT ตามกรอบโครงการ:
   intrinsic 10s+0.1s, H0=0/H1=+2 Elo, alpha=beta=0.05 และ maximum pairs ที่ freeze ก่อนเริ่ม
4. ยืนยันรุ่น release กับ baseline ที่ freeze ด้วย corpus อิสระที่ 1s และ 2s ต่อตา
   ต้องมีหลักฐานเหนือกว่า ไม่ใช่เพียง point estimate บวก; cap-INCONCLUSIVE ไม่ใช่ PASS
   สูตร non-inferiority ใด ๆ ต้องมี margin/contract แยกก่อนรัน ห้ามคิดย้อนหลัง
5. ยืนยัน candidate ที่รวมทุกส่วนอีกครั้ง เพราะผลเพิ่มแต่ละ patch ไม่รับประกันว่ารวมแล้วเพิ่ม
   ทดสอบ cold/warm GUI หลายเกม, undo/cancel/new game, endgame transition และ deadline tails
6. ประกอบ release ที่ระบุ version/hash/config พร้อม rollback ไป baseline ได้จริง
   คงค่า 12T เดิมจนมีหลักฐานเปลี่ยน; ถ้าเปลี่ยน profile ต้อง rebaseline

**Definition of Done สำหรับเป้าหมายผู้ใช้:** ThaiMakhosEngine บรรลุขอบเขต non-loss ของ
Phase 2 ด้วยหลักฐานตามระดับที่อ้าง และมี practical superiority ตาม Phase 3 ต่อ **Invincible 2**
ไม่ใช่เพียงชนะรุ่นก่อนของเรา ต้องรายงาน milestone เชิงทดลองแยกจาก universal 100% guarantee
หากยังมีเฉพาะ empirical no-loss ห้ามปิดเป้าหมายไร้พ่ายแบบพิสูจน์แล้ว ส่วนการปล่อยรุ่นย่อย
ที่ดีขึ้นระหว่าง Phase 1 ทำได้ตาม internal release gates และ rollback โดยไม่อ้างว่าเป้าหมายจบ

## ขอบเขตและการแบ่งงาน

- Local: corpus/game review, profiler, same-source control/candidate, Windows/GUI และ strength runs
- Astra Web: Linux/TSan, independent source/contract review, ตรวจ PR/evidence ที่ส่งขึ้น GitHub
  ผลความเร็ว Linux runner ไม่แทนผลเครื่อง Windows เป้าหมาย และไม่เปิด arena ซ้ำกันโดยพลการ
- GitHub เป็นจุดส่งงานผ่าน branch/PR; ไม่ sync ทับ WIP, ไม่ force-push หรือ auto-merge
- คง RULESET.json, makhos/core.py, accepted DLL และ stopped checkpoints; งานหนักใช้ workload
  lease/BelowNormal และให้ GUI มี priority; ไม่เริ่ม automation จากเอกสารนี้
- ยังไม่เริ่ม shared-score TT, SMP redesign, training ใหญ่, tablebase >6 หรือ DFPN
  จากเอกสารนี้; proof/strategy สำหรับ Phase 2 เป็น planning scope ที่ต้องประเมินเพิ่ม
  ไม่มีข้อกำหนดให้ทำ NNUE v2 ก่อนเพิ่มความแข็งแกร่ง

## งานแรกเมื่อ PR จบ

**เลือกฐานที่ตรวจรับได้ → ตรวจช่องทางและกติกา Invincible 2 → ทำ external baseline/corpus →
แยกสาเหตุแพ้และ Round2 timing → เลือก candidate เดียว**
นี่คือการกลับสู่ strength track ไม่ใช่การเริ่มรอบ refactor หรือเอกสารยาวอีกชุด

อ้างอิงใน repo: [project skill](../../.agents/skills/thai-makhos-engine/SKILL.md),
[development plan](../../DEVELOPMENT_PLAN_TH.md),
[coordination](../../handoffs/local-coordination-20260920/STATUS_AND_HANDOFF_TH.md).
หลักฐาน profiling/candidate verdict ใต้ build/ เป็น local evidence ไม่ได้ถูกอัปโหลดพร้อมแผนนี้
