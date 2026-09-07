# แผนพัฒนา ThaiMakhosEngine: NNUE v1 → Threads → Elo

สถานะ: คู่มือดำเนินงานที่ผู้ใช้อนุมัติเมื่อ 2026-09-07
เป้าหมาย: ความแข็งแกร่งทั่วไปสูงสุดที่มีหลักฐานรองรับ พร้อมความถูกต้อง
ความเสถียร และ rollback ไม่ใช่ชนะตำแหน่งหรือคู่แข่งรายเดียว

## 1. สถานะและแหล่งอ้างอิง

อ่านสถานะปัจจุบันเพียงจุดเดียวที่
[references/current-state.md](.agents/skills/thai-makhos-engine/references/current-state.md)
และตรวจ atomic results/process manifest ก่อนทำงานทุกครั้ง
ขณะเริ่มใช้คู่มือนี้ Gate C 1000ms ผ่านแล้ว; ขั้นดำเนินงานคือชุด 2000ms
ยังไม่มี production promotion หรือข้อพิสูจน์ว่า 12 Threads คุ้มกว่า 1 Thread

ลำดับอำนาจ: คำสั่งผู้ใช้ → current directive/invariants ใน
[SKILL.md](.agents/skills/thai-makhos-engine/SKILL.md) → คู่มือนี้ →
[NNUE_ROADMAP.md](NNUE_ROADMAP.md) สำหรับ feature/model/data contract →
historical evidence ledger → แผนที่พักไว้

แผนเดิมและประวัติ Phase 0–8 ถูกเก็บครบใน
[historical plan](.agents/skills/thai-makhos-engine/references/history/20260907-development-plan-before.md)
อ่านเมื่อจำเป็นต้องสืบ provenance เท่านั้น ไม่ resume acquisition หรือ Gate A/B
จากข้อความ “current/next” ในประวัติ

แยกความสำเร็จสามเรื่อง:
1. NNUE candidate แรงกว่า accepted HCE ภายใต้เงื่อนไขที่ล็อก
2. การใช้หลายเธรดคุ้มกว่า single-thread ของรุ่นเดียวกัน
3. accepted รุ่นใหม่มีหลักฐานดีกว่ารุ่นก่อนและคู่แข่งภายนอก

เครื่องเป้าหมาย Ryzen 5 5600H มี 6 คอร์จริง/12 logical threads
ให้แนะนำค่าที่เล่นแข็งแกร่งที่สุดจาก measurement; ไม่บังคับใช้ครบ 12
การเปลี่ยนไปใช้เธรดน้อยลงอย่างเดียวไม่ถือว่าแก้ SMP สำเร็จ

## 2. ปิด Gate C ตามสัญญาเดิม

สัญญาที่ห้ามแก้: `build/nnue_gate_c_contract_v1.json`
ใช้ DLL/model เดิมกับ accepted control, fixed 1000ms แล้ว 2000ms,
12 Threads และ Hash รวม 512 MiB ต่อเอนจิ้น, production TB3/4/5/6,
opening 8 plies, paired color swaps, persistent search, sequential games,
H0=0/H1=+2, alpha=beta=0.05, สูงสุด 10,000 คู่ต่อชุด
max_game_plies=300 ต้อง fail closed; ไม่แปลง truncation เป็น draw

- ทั้งสองชุด PASS: เข้า production review
- ชุดใด FAIL: คง HCE; วิเคราะห์เกม/runtime แล้วเปิด experiment แก้สาเหตุแยก
- ถึงเพดาน INCONCLUSIVE: ไม่ promote; ไม่เริ่ม seed ใหม่เพื่อหาผลบวก
- ขัดข้องหรือ GUI ขอทรัพยากร: ตรวจ identity/config/logs แล้ว resume คู่ที่จบครบ
- ห้ามรวมสอง time controls หรือปน smoke/diagnostic games เพื่อให้ผ่าน
- ห้ามเปลี่ยน settings/model/source ที่ถูกผูกไว้หลังคู่แรก

### การรันและหน้าสถานะ

`work/nnue_gate_c_control.py verify` ตรวจ contract/artifacts/evidence/inventories
และ recompute ผลชุดแรก; `launch` เริ่มหรือ resume เฉพาะชุด 2000ms ที่ยังไม่จบ
โดย exact argv จาก contract, hidden detached BelowNormal, เก็บ launch intent,
PID/creation ticks, logs และ run manifest ในโฟลเดอร์ใหม่
การ resume ที่มี stderr ต้องตรวจ incident ก่อน; ไม่มี blind automatic restart

`build/runtime/nnue_gate_c_active_run.json` ชี้ immutable run manifest ปัจจุบัน
`work/nnue_gate_c_status_terminal.ps1` อ่านทั้งสองชุดและแสดงจำนวนคู่/เกม,
LLR/bounds, เวลาคู่ล่าสุด, process identity และ RUNNING/PAUSED/ERROR/FINISHED
ใช้ Unix timestamp สำหรับการแสดงวันที่ไทย/อังกฤษ; ไม่ผูก PID ใน script
ระหว่างโปรเซสยังรัน ให้อ่าน append-only pair log และ recompute สถิติเท่านั้น
อ่าน canonical checkpoint หลัง writer หยุดแล้ว เพื่อไม่รบกวน atomic replace
ไม่แสดง LLR เป็นเปอร์เซ็นต์เสร็จหรือ ETA ที่รับประกันไม่ได้
ปิดจอสถานะแล้ว arena ต้องยังอยู่

ระหว่าง arena ใช้เครื่อง ทำเฉพาะ docs/read-only/fixtures/low-resource tooling
ไม่ compile native, train, profile, full-suite หรือแข่งอีกชุดทับกัน
GUI มี priority สูงสุด; เก็บคู่ที่ถูกขัดจังหวะเป็น unscored

## 3. Production promotion และนิยาม “NNUE v1 เสร็จ”

หลัง Gate C ทั้งสองชุด PASS เท่านั้น:

1. ตรวจ reproduction/provenance ของ DLL/model และครบทุก correctness gate
2. ทำ immutable release bundle ผูก DLL/model/feature ABI/rules/config/hashes
   เก็บ accepted HCE และ release manifest เดิมเป็น rollback target
3. รันทดสอบครบ suite ขณะเครื่อง idle และตรวจ source/test identity หลังรัน
4. ทดสอบ cold server → หน้าเว็บพร้อม → ตาแรก ผ่าน HTTP/GUI จริง
   แยก setup, model/TB load และเวลาคิด; เทียบ HCE ในสภาพเดียวกัน
5. ทดสอบเกมใหม่, คนกับบอท, บอทกับบอท, ทั้งสองสี, ลากเดิน,
   หมุนกระดานโดยไม่เปลี่ยนฝ่าย, เปลี่ยน Threads/Hash และยกเลิกการคิด
6. ทดสอบ forced move, terminal, repetition/no-progress, TB priority,
   timeout ที่คืน complete iteration, corrupt/missing/incompatible model
7. GUI/API แสดง requested/effective Threads, Hash จริง, backend และ model/build
   identity; ห้าม fallback เงียบแล้วอ้างว่าใช้ NNUE
8. เปลี่ยน default แบบ reversible แล้ว isolated post-promotion rebaseline
   ทดสอบ rollback กลับ HCE จริงและเก็บรายงาน; คืนค่า candidate เฉพาะเมื่อผ่าน

เพิ่ม provenance แบบ additive ไม่ทำให้ game export เดิมอ่านไม่ได้
คงค่าที่ผู้ใช้ตั้งเอง; ข้อเสนอ Threads เป็น recommendation ไม่แอบ override

NNUE v1 เสร็จเมื่อ Gates ครบ, GUI ใช้ NNUE จริง, runtime regression ที่สำคัญถูก
ปิด และ rollback ได้ ไม่ใช่เพียง training หรือ self-play ผ่าน
หาก smoke ไม่ผ่าน ให้แก้ production integration แบบแยก candidate;
ประเมิน gate ที่ต้องรันใหม่ตาม playing-path/resource/time changes จริง

## 4. การทดลองหลัง promotion: NNUE thread-scaling/profile audit

ใช้ NNUE รุ่นเดียวกันทั้ง matrix; คง features/model/search/rules/TB
วัด Threads 1/2/4/6/8/12 ที่ fixed 1 และ 2 วินาที, Hash รวม 512 MiB
รายงาน TT จริงต่อ worker/รวม; หาก allocator ทำให้ยอดจริงต่างกันให้แสดงไว้
และแยกการทดสอบ matched-allocation เพื่อวินิจฉัย ไม่แอบให้แต่ละ worker 512 MiB

### ชุดตำแหน่งและวิธีวัด

- อย่างน้อย 96 ตำแหน่งหลากหลาย: ต้นเกม/กลางเกม/ฮอส/กินต่อ/ใกล้เสมอ,
  ทั้งสองสี และหลาย reversible clocks
- แยก external เซียนเฒ่า/เกมแพ้คนเป็น diagnostic appendix;
  ไม่ใช้เป็น proven labels หรือเป็นจุดเลือก configuration เดี่ยว
- อย่างน้อย 5 repetitions, balanced/สลับลำดับรัน, fresh-state protocol เดียวกัน
- ตรึง corpus/hash/seed/schedule ก่อนวัด; รอบที่ถูกรบกวนไม่เป็น evidence
- แยก fixed-depth diagnostic กับ fixed-time playing-quality observations

วัด elapsed/deadline overshoot, complete depth, move/score/PV distribution,
nodes/qnodes, worker utilization, duplicated work, coordinator wait,
TT hit/layout, NNUE materialization/features updated/evaluation cost,
move generation/TB cost, CPU/RAM และ clock/thermal throttling เมื่ออ่านได้จริง
metric ที่ไม่มี counter ให้รายงาน unavailable; instrument ใน diagnostic build
แยกจาก timing control และวัด overhead ของ instrumentation ก่อนใช้สรุป

ผลค้นลึกเป็น observational reference ไม่ใช่ ground truth
NPS รวมและจำนวน nodes ที่เพิ่มไม่แทน Elo

### เลือกการทดลองเดียวจากผล

- duplicate-root/TT fragmentation เด่น: ออกแบบ parallel mechanism ที่แก้สาเหตุ
  และต่างจาก rejected prototypes อย่างระบุได้
- coordination overhead เด่น: ทดลองลด overhead โดยคง semantics ก่อน
- 6T ดีกว่า 12T จาก contention: คัดเป็น configuration candidate แล้วพิสูจน์แข่ง
- NNUE/eval cost เด่น: ทดสอบต้นทุนร่วมของทุก worker ก่อน architecture ใหญ่

ก่อนเขียน candidate ใด ต้องมี experiment contract ระบุสมมติฐานหนึ่งข้อ,
หลักฐาน, control, classification, expected change และ fail/stop gates
ไม่ revive private-root fail-low, root-alpha, leader-only Lazy-SMP,
fixed-window scout หรือ adaptive routing รุ่นที่แพ้ โดยไม่มี mechanism ใหม่
ที่ตอบสาเหตุเดิมใน ledger

คัด configuration ที่มีแนวโน้มดีจาก audit แล้ว paired pentanomial SPRT
เทียบ 1T ของ NNUE รุ่นเดียวกันที่ 1s/2s ใช้ openings ใหม่ที่ไม่ใช้คัดเลือก
หากเปลี่ยน backend ให้เทียบ backend เดิมที่ Threads เท่ากันด้วย
ทดสอบ candidate ทีละตัว; ผ่านเฉพาะ STC ไม่พอสำหรับค่าที่ผู้ใช้เล่นจริง
กรณีผลยังแยกไม่ได้ ให้รายงาน uncertainty ไม่อ้างว่าจำนวนเธรดเท่ากัน

เกณฑ์จบ: มี configuration แนะนำที่ผ่าน strength/runtime evidence พร้อม
คำอธิบาย 12T; ถ้ายังไม่มี multi-thread configuration ชนะ 1T อย่างมีหลักฐาน
ให้คงสถานะ SMP unresolved แม้เลือกค่าชั่วคราวที่เหมาะกว่าแล้ว

## 5. คิวเพิ่ม Elo และ NNUE รุ่นต่อไป

หลัง audit เลือก single highest-value experiment ตาม measurement ไม่ทำครบ
ทุก heuristic และไม่ stack แนวคิดที่ยังไม่ผ่าน

| ด้าน | Candidate แรกที่พิจารณา | หลักฐานที่ต้องมี |
|---|---|---|
| NNUE cost | nearest-valid-ancestor delta ที่ staged ไว้ | materialization/update เป็น hotspot |
| งานสูญเปล่า | qsearch/move-generation/data-layout/TT work ซ้ำ | profiler และ diverse corpus |
| Single-thread quality | ordering/history/horizon reduction | ค้นผิดทิศหลายตำแหน่ง ไม่ใช่ความช้าอย่างเดียว |
| เวลา | setup/stop/iteration commit overhead | requested-versus-actual budget และ fallback evidence |
| NNUE v2 | label/data quality ก่อน capacity | error strata และ learning curve |

Ancestor delta อยู่ใน `work/nnue_ancestor_delta_v1` ยังไม่ผ่าน native/performance/
strength gates ต้องผูก snapshot ใหม่กับ baseline ปัจจุบันในบันทึกใหม่
ไม่แก้หลักฐาน v21 เดิมให้ดูเหมือนใหม่ จากนั้น build control/off/on/guard แยก
และตรวจ full-refresh/accumulator bit-exact: quiet/capture/multi-capture/promotion,
clock reset/boundary/80, null move, deep/PVS/siblings, reload/corruption/overflow
วัดทั้งจำนวน materializations และจำนวน feature deltas เพราะน้อยครั้งอาจแพงขึ้น

Behavior-preserving candidate ต้องตรง move/score/nodes/PV ใน deterministic 1T
และไม่ช้าลงซ้ำได้; เมื่อ throughput เปลี่ยน depth ที่ถึงในเวลาจริง ให้ยืนยัน
paired fixed-time strength ก่อน promotion
Strength-changing candidate ต้องทดสอบ legality/bounds/stop semantics และ SPRT
ไม่บังคับ exact move parity แล้วเรียกความต่างทุกอย่างว่า correctness bug
หลายเธรดที่ scheduling ไม่ deterministic ให้วัด distribution แยกจาก oracle

Fixed 1s ต้องเคารพงบต่อตา ไม่โยกเวลาไปตาอื่นหรือ sleep เติมเวลา
forced/terminal/exact อาจตอบเร็วได้; clock-based allocation เป็นอีกโหมดหนึ่ง

### NNUE v2 และข้อมูล

- snapshot accepted teacher แต่ละรุ่น; เก็บ fresh games/independent opponents/
  controlled exploration พร้อม actual terminal outcome และ provenance
- mine disagreement/uncertainty/horizon เฉพาะ development pool
- quiet-leaf label distribution ต้องใกล้ search จริง; แยก teacher scalar,
  game outcome, exact WDL และ uncertainty ไม่ปนเป็น solved truth
- แบ่งระดับเกมก่อนเลือกตำแหน่ง/augmentation; trajectory/clock variants อยู่ split
  เดิมและ canonical dedup ข้าม split; external diagnostics ไม่เป็น tuning labels
- fresh sealed test ต่อ major generation; เปิดครั้งเดียวหลัง model freeze
- เปลี่ยน data amount, label depth, loss หรือ model size ทีละแกน
- หาก learning curve ยังดีขึ้นเมื่อเพิ่มข้อมูล ให้เพิ่มข้อมูลก่อนเพิ่ม network
- offline loss ลดไม่ใช่ Elo; model ใหม่ผ่าน export/parity/search/arena/production
  ตาม gate เดิม โดยไม่ยืมการอนุมัติหรือ sealed test ของรุ่นก่อน

## 6. ป้องกันถอยหลังและส่งมอบ

วงจร: hypothesis/contract → correctness → deterministic benchmark/profile →
paired SPRT → PROMOTE/KEEP/REJECT/INCONCLUSIVE → rollback state → next experiment

- Accepted control แยก immutable; current source ไม่ได้ accepted โดยชื่อไฟล์
- `RULESET.json` และ `makhos/core.py` คงเดิม; native move/state change ต้อง perft
  depth 10 และ randomized Python/native differential
- Full suite ต้อง discover จริงทุกครั้ง รายงาน failures/errors/skips/count/time
  ใช้ `scratch/nnue_full_suite_attestation.py` ขณะ idle ไม่รันคู่กับ arena
- เพิ่ม regression ที่จับข้อผิดพลาดได้จริง ไม่เพียงตรวจข้อความในเอกสาร
- Freeze seed/time/rules/Threads/Hash/source/model ก่อนเกม; default confirmation
  H0=0/H1=+2, alpha=beta=.05, cap 10,000 คู่ถ้าไม่ได้ประกาศอย่างอื่นก่อนเริ่ม
- ไม่ pool controls, นับคู่ซ้ำ, คิด incomplete pair หรือ truncate เป็น draw
- เก็บ compiler/model/config hashes, raw benchmark, pentanomial/LLR/Elo interval,
  actual resources, verdict และ rollback ใน historical ledger
- Current-state เปลี่ยนเฉพาะ milestone/run identity; ไม่สะสมคำสั่ง current หลายชั้น

หลังแต่ละ promotion ทดสอบกับคู่แข่งภายนอกหลายระดับอย่างเป็นธรรม สลับสี
opening ไม่เลือกจากเกมที่ชนะ กติกา/เวลาชัด พร้อม game JSON และ identity
self-play gain ไม่เท่ากับ absolute Elo หรือ world strongest
world-strength claim ต้องมี independent reproducible competitive evidence
ทั้ง short และ longer control; unavailable opponent ให้ระบุขอบเขตตามจริง

พัก DFPN, initial-position proof, tablebase >6 และ proof-guided policy/value
จนกว่าผู้ใช้สั่งเฉพาะ ไม่ทำ Goal ใหญ่ complete เพียงเพราะจบ NNUE หรือ SPRT หนึ่งชุด
