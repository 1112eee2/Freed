# Invincible 2 — Practical Play Roadmap

วันที่ 2026-09-20 · แผนตามคำขอ Ethan · ยังไม่ใช่ผลทดลองหรือการอนุมัติ production

## เป้าหมายและเส้นทางหลัก

ออกเวอร์ชัน **Invincible 2** ที่เล่นจริงแข็งกว่ารุ่นใช้งานปัจจุบัน ภายใต้เวลา
และทรัพยากรเท่ากัน โดยเน้น 1s/2s ต่อตา: พลาดแท็กติกน้อยลง เปลี่ยนความได้เปรียบ
เป็นชัยชนะได้ดีขึ้น และ GUI ไม่เสียเวลา/เสียผลค้นหาเมื่อหยุดหรือเริ่มเกมใหม่
ชื่อรุ่นไม่ใช่การอ้างว่าเล่นสมบูรณ์แบบหรือไม่มีวันแพ้ และไม่กำหนดตัวเลข Elo ที่ยังไม่มีหลักฐาน

**ไม่ผูกการออกรุ่นกับ Lazy SMP หรือ NNUE รุ่นใหม่** ใช้ backend ที่ตรวจรับแล้วเป็นฐาน
และปรับทีละแนวคิด ส่วนกลไกที่ถูก reject จะไม่กลับมาทดลองแบบเดิม

## 0. หลังรับ PR จาก Astra Web: จบข้อสงสัย ไม่ขยายงานไม่รู้จบ

- ตรวจ commit/diff/source hashes, raw logs, negative control และขอบเขตคำกล่าวอ้าง
  ของ seed-state diagnostic/TSan ก่อนรับผล ไม่ auto-merge จากคำว่า PASS
- รับเฉพาะขอบเขตที่พิสูจน์: harness defect ไม่เท่ากับ production defect;
  sanitizer pass ไม่เท่ากับ strength gain หรือปิด G2–G6 ทั้งหมด
- ถ้า protocol ผ่านแต่ candidate ยังแพ้ G4 ให้คง `REJECT_FOR_PERFORMANCE / NOT_PROMOTED`
  และย้าย Lazy SMP ออกจาก critical path ของ Invincible 2
- ถ้ายังมีปัญหา ให้แยก/ปิด candidate และตรวจว่าปัญหาไม่กระทบ backend ฐาน
  งาน strength ที่ไม่ใช้ส่วนที่มีปัญหาทำต่อได้ ไม่ต้องรอให้ Lazy SMP ทุก gate ผ่าน
  แต่ถ้าข้อผิดพลาดอยู่ในฐานที่จะนำไปใช้จริง ต้องแก้และตรวจรับก่อน

**จบขั้นนี้เมื่อ:** มี verdict ที่มีขอบเขตชัดเจนและเลือกฐานปลอดภัยได้ ไม่จำเป็นต้อง promote Lazy SMP

## 1. Freeze baseline และสนามทดสอบ Practical Play

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

## 2. เลือกการเพิ่มความแข็งแกร่งรอบแรกจากหลักฐาน

### 2A — วัดต้นทุนและข้อผิดพลาดจริง

ทำ Round2 แบบ diagnostic-only ที่ 1T ก่อน: แยก elapsed/CPU และ inclusive/exclusive
ของ move generation/order, TT, NNUE incremental update/eval, qsearch และ setup/stop
วัด overhead ของ instrumentation เทียบ control และ fixed-depth move/score/nodes/PV parity
ข้อมูล qsearch 51–65% ของ nodes เดิมไม่ใช่สัดส่วน CPU และไม่พิสูจน์ว่างานสูญเปล่า
หาก profiler ทำให้ต้นทุนบิดเบือน ให้แก้การวัดก่อน ไม่ใช้ตัวเลขนั้นเลือก optimization

### 2B — ทดลองทีละหนึ่งแนวคิด ตามผล 2A

| สิ่งที่พบ | Candidate ที่ควรพิจารณา | สิ่งที่ต้องพิสูจน์ |
|---|---|---|
| ต้นทุนซ้ำใน movegen/order/NNUE update | ลด allocation/การคำนวณซ้ำ โดยไม่เปลี่ยนผล | deterministic parity + runtime gain ที่พ้น noise |
| พลาดแท็กติกแม้ไม่มี deadline | ordering/history/horizon หรือ selectivity ที่มี counterexample | regression หลายตำแหน่ง + strength gate; ไม่ปรับจากเกมเดียว |
| สูญเสียเวลาหรือผล iteration เมื่อหมดงบ | setup/stop/result retention | end-to-end latency + คำตอบที่จบสมบูรณ์ + strength gate |
| แพ้เพราะ eval มากกว่าความลึก | ข้อมูล/labels ของ NNUE ก่อนขยาย model | game-level split, fresh sealed test, inference parity และ strength gate |

ทุกการทดลองมีสมมติฐานหนึ่งข้อ, control/candidate คนละ artifact, กำหนด cap/stop rule ก่อนรัน
และจบด้วย KEEP/REJECT/INCONCLUSIVE/PROMOTE ห้ามเปลี่ยน search+model+Threads พร้อมกัน
เกิน cap แล้วยังไม่ชัดให้ INCONCLUSIVE ไม่รันซ้ำ seed ใหม่จนผ่าน

## 3. Practical conversion และเล่นกับมนุษย์ — หลังฐาน search ดีขึ้น

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

ขั้นนี้เป็น optional candidate ไม่ใช่เงื่อนไขบังคับให้เพิ่ม heuristic ในรุ่น 2

## 4. Strength acceptance และ release

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

**Definition of Done:** Invincible 2 ผ่าน correctness/runtime และหลักฐานความแข็งแกร่ง
เหนือ baseline ตาม contract ที่ประกาศไว้ทั้งช่วงสั้นและยาวที่กำหนด พร้อม reproducible report
และ rollback; หากไม่ผ่านยังคงรุ่นเดิม ไม่เปลี่ยนชื่อรุ่นแล้วเรียกว่าพัฒนาแรงขึ้น

## ขอบเขตและการแบ่งงาน

- Local: corpus/game review, profiler, same-source control/candidate, Windows/GUI และ strength runs
- Astra Web: Linux/TSan, independent source/contract review, ตรวจ PR/evidence ที่ส่งขึ้น GitHub
  ผลความเร็ว Linux runner ไม่แทนผลเครื่อง Windows เป้าหมาย และไม่เปิด arena ซ้ำกันโดยพลการ
- GitHub เป็นจุดส่งงานผ่าน branch/PR; ไม่ sync ทับ WIP, ไม่ force-push หรือ auto-merge
- คง RULESET.json, makhos/core.py, accepted DLL และ stopped checkpoints; งานหนักใช้ workload
  lease/BelowNormal และให้ GUI มี priority; ไม่เริ่ม automation จากเอกสารนี้
- ยังไม่รวม shared-score TT, SMP redesign, training ใหญ่, tablebase >6 หรือ DFPN
  จนกว่าจะมีหลักฐานและอนุมัติขอบเขตใหม่ ไม่มีข้อกำหนดให้ทำ NNUE v2 ก่อนออกรุ่น

## งานแรกเมื่อ PR จบ

**เลือกและ freeze baseline ที่ตรวจรับได้ → ทำ corpus/contract practical-play →
เก็บ Round2 timing + error classification → เลือก candidate เดียว**
นี่คือการกลับสู่ strength track ไม่ใช่การเริ่มรอบ refactor หรือเอกสารยาวอีกชุด

อ้างอิงใน repo: [project skill](../../.agents/skills/thai-makhos-engine/SKILL.md),
[development plan](../../DEVELOPMENT_PLAN_TH.md),
[coordination](../../handoffs/local-coordination-20260920/STATUS_AND_HANDOFF_TH.md).
หลักฐาน profiling/candidate verdict ใต้ build/ เป็น local evidence ไม่ได้ถูกอัปโหลดพร้อมแผนนี้
