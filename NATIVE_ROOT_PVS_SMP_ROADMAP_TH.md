# แผนร่าง Native Root-PVS/SMP สำหรับ ThaiMakhosEngine

สถานะ: **IMPLEMENTED AS DEFAULT-OFF DIAGNOSTIC; BOUND USE REJECTED WITH EVIDENCE**  
วันที่ล็อกร่าง: 2026-08-23  
วันที่ทดลอง: 2026-08-24  
เป้าหมายของ phase: เพิ่มความแข็งแกร่งของ classical/handcrafted engine ที่เวลา 1–2 วินาที โดยแก้คอขวด root search และการใช้ Threads/Hash ก่อนเริ่ม NNUE

ผลสรุป: coordinator/worker pool และ shadow telemetry ผ่าน correctness และคงไว้
หลัง compile flag ที่ default เป็น 0 แต่ทั้งการใช้ fail-low โดยตรงและ protocol
แก้ครั้งเดียวที่ปิด null-move/LMR ใน helper ยังเปลี่ยน fixed-depth result จึงไม่เชื่อม
production และไม่รัน SPRT ตาม stop condition ข้อ 18

## 1. ข้อสรุปการออกแบบ

กลไกที่จะศึกษาคือ **authoritative-main native root-PVS/SMP**:

- มี main search context เพียงตัวเดียวเป็นเจ้าของ iterative deepening, PV, score, root ordering และผลที่ส่งคืน
- main ค้นหมาก PV/root ตัวแรกก่อน เพื่อสร้าง `alpha` ที่มีคุณภาพ
- helper threads ค้นหมาก root ที่เหลือแบบ scout/null-window ภายใน native code
- helper ใช้ stack, history, killer, countermove และ TT ส่วนตัว ห้ามเขียน state ของ main
- ผล helper เป็นเพียง bound/คำแนะนำ ห้ามเลือกตาเดินสุดท้ายโดยตรง
- helper ที่ fail-high ต้องให้ main ค้นซ้ำ full-window ก่อนจึงจะเปลี่ยน best move หรือ score ได้
- depth จะถือว่า complete ต่อเมื่อ main ยืนยันผล root ที่จำเป็นครบตามกติกาของ candidate นั้น
- เมื่อหมดเวลา ให้คืนผลจาก iteration ล่าสุดที่ main ยืนยันเสร็จแล้วเท่านั้น

นี่ไม่ใช่การนำ root splitter ปัจจุบันไปเขียนใหม่เฉย ๆ และไม่ใช่ Lazy SMP แบบหลาย engine แข่งกันตอบ ผลสุดท้ายต้องมี authoritative result เดียวเสมอ

## 2. เหตุผลและหลักฐานที่ทำให้เลือกแนวทางนี้

### 2.1 ปัญหาที่วัดได้

- เกมแพ้เซียนเฒ่าล่าสุดเสียมูลค่าชัดเจนครั้งแรกที่ Black ply 21 ไม่ใช่ตั้งแต่ opening
- ตำแหน่งนั้น root splitter 12 Threads แบ่ง Hash จน worker หนึ่งได้ TT เล็ก และทำงานซ้ำหลาย root
- ordinary one-thread ที่มี TT เพียงพอเห็น `27-24` ลึกกว่าโดยใช้ node น้อยกว่า และเลือกถูกซ้ำได้
- static HCE ประเมิน `27-24` ดีกว่า `32-28` อยู่แล้ว จึงยังไม่มีหลักฐานว่าควรแก้น้ำหนัก HCE จากเกมนี้
- adaptive one-thread routing ชนะ STC แต่กลับเป็นกลางติดลบที่เวลาใกล้การใช้งานจริง จึงห้าม promote

### 2.2 สิ่งที่เคยลองแล้วและห้ามวนซ้ำโดยไม่มี mechanism ใหม่

- independent full search ต่อ root ใน Python
- global หรือ branch-count adaptive one-thread routing
- native root-SMP ที่หลาย worker ให้ผลอิสระโดยไม่มี authoritative main
- deterministic private-TT scheduler แบบเดิม
- isolated root scout ที่ helper result มี semantics ไม่ตรงกับ ordinary full search
- root-alpha/windowed path ที่ยังไม่มีหลักฐาน paired strength ครบ
- PV/root cache ที่ช่วยเพียง ordering แต่ไม่แก้งานซ้ำเชิงโครงสร้าง
- การ clear state เมื่อ fail-high โดยไม่มีหลักฐานว่ารักษาคุณภาพและคุ้มเวลา
- การปรับ HCE จากตำแหน่งหรือเกมเดียว

การทดลองใหม่จะผ่านได้ก็ต่อเมื่อพิสูจน์ว่าแตกต่างจากรายการข้างบนตรงที่ main เป็นผู้ยืนยันผล, helper ไม่ปนเปื้อน main state, coordinator อยู่ใน native code และการใช้ bound ถูกตรวจสอบอย่างเข้มงวด

## 3. ขอบเขต

อยู่ในขอบเขต:

- native root coordinator และ worker lifecycle
- root PVS/scout protocol
- private per-worker search state และ Hash budgeting
- deadline/cancellation/time management
- telemetry, correctness, deterministic benchmark และ paired SPRT
- diverse middlegame regression corpus ที่ใช้ตรวจ general strength

อยู่นอกขอบเขต:

- NNUE, policy network หรือการ train model
- DFPN และ large tablebase work
- การปรับ HCE coefficient โดยอิงเกมเซียนเฒ่าเกมเดียว
- การเปลี่ยน rules, repetition, no-progress หรือ draw adjudication
- การเปลี่ยน GUI ก่อน candidate ผ่าน production gates
- การเขียนทับ `build/makhos_native_accepted.dll`

## 4. Invariants ที่ห้ามละเมิด

1. accepted DLL เป็น immutable control ตลอดงาน
2. candidate ทุกตัวออกเป็น DLL คนละชื่อและเปิดผ่าน compile-time flag ที่ default เป็น 0
3. requested Hash เป็นเพดาน RAM ของ TT รวมทุก worker ไม่ใช่ Hash ต่อ thread
4. helper result ห้ามถูกส่งเป็น final move/score โดยไม่ผ่าน main validation
5. incomplete iteration ห้ามแทนที่ completed iteration ล่าสุด
6. Threads ต้องรายงาน requested/effective/completed ตามจริง
7. forced move เดินทันทีได้ ไม่ต้องเผาเวลาจนครบ
8. ห้าม promote จาก unit tests, benchmark ตำแหน่งเดียว หรือ SPRT time control เดียว
9. external เซียนเฒ่าใช้เป็น diagnostic/regression ไม่ใช่ sole promotion gate
10. accepted server/GUI path จะไม่เปลี่ยนจน production gate ผ่านครบ

## 5. สถาปัตยกรรมที่เสนอ

### 5.1 Authoritative main context

main context มีหน้าที่:

- ถือ root position, history, reversible clock และ repetition state
- ทำ iterative deepening ตาม depth ทีละชั้น
- รักษา previous PV, root order, aspiration state และ committed result
- ค้น PV/root ตัวแรก full-window เพื่อสร้าง alpha
- ตัดสินใจว่าผล helper ตัวใดต้อง full-window re-search
- commit best move, exact score, PV และ completed depth
- เป็นผู้ตอบกลับ ABI เพียงตัวเดียว

main TT และ heuristic state จะอยู่ข้าม iteration ภายในหนึ่ง search session เพื่อไม่ทิ้งข้อมูลที่มีประโยชน์ทุก root/depth

### 5.2 Helper contexts

helper แต่ละตัวมี:

- search stack/workspace ส่วนตัว
- history, killer และ countermove ส่วนตัว
- TT partition ส่วนตัว
- local node/depth/stop telemetry
- task queue input ที่เป็น immutable root-task snapshot

helper ไม่มีสิทธิ์:

- เขียน main TT หรือ main heuristic tables
- commit PV/best move/final score
- เปลี่ยน alpha โดยตรง
- เขียน root result หลัง generation/iteration ถูกยกเลิก

### 5.3 Root iteration protocol

ร่าง protocol ต่อหนึ่ง depth:

1. main สร้าง legal root list และเรียง previous-PV move ก่อน
2. main ค้น root ตัวแรก full-window
3. coordinator snapshot ค่า alpha, depth, deadline, generation และ root order
4. helper รับ root ที่เหลือผ่าน native task queue และค้นแบบ scout/null-window
5. main ทำงานค้น/ตรวจ root ต่อ ไม่ยืนรอเฉย ๆ
6. fail-high หรือผลที่ไม่น่าเชื่อถือถูกส่งเข้าคิว main full-window re-search
7. stale result ที่ generation ไม่ตรงถูกทิ้ง
8. main commit iteration ต่อเมื่อ validation rule ของ phase นั้นครบ
9. ถ้า deadline มาถึงก่อน ให้ cancel helper และคืน completed iteration ก่อนหน้า

ลำดับการ commit ต้อง deterministic แม้ helper finish order ต่างกัน: main พิจารณาผลตาม root order ที่ล็อกไว้ ไม่ใช่ตาม thread ที่ตอบเร็วที่สุด

### 5.4 ขอบเขตความน่าเชื่อถือของ scout bound

null-window result จาก selective alpha-beta อาจไม่ปลอดภัยพอให้ข้าม full search ทันที เพราะ LMR, null-move, TT bound และ qsearch interaction อาจทำให้ semantics ต่างจาก full search

จึงแบ่งเป็นสองระดับ:

- **Shadow mode:** helper ค้นจริงและเก็บ telemetry แต่ main ยังให้ผลเหมือน ordinary search ทุกประการ ผล helperไม่มีผลต่อ move/score
- **Bound-use mode:** ใช้ fail-low เพื่อหลีกเลี่ยงงานบางส่วนได้หลัง fixed-depth parity และ bound audit ผ่านแล้วเท่านั้น ส่วน fail-high ต้อง main full-window re-search เสมอ

ถ้าไม่สามารถพิสูจน์ bound-use parity ได้ จะหยุดที่ shadow evidence และ reject architecture แทนการผ่อน correctness gate

### 5.5 Synchronization

candidate v1 ใช้:

- fixed worker pool สร้างครั้งเดียวต่อ engine handle
- monotonic atomic generation id
- bounded task queue และ result slots ต่อ root index
- atomic stop/deadline flag
- acquire/release ordering ที่ระบุไว้ใน code comment
- barrier เฉพาะตอนจบ iteration หรือ destroy/clear ไม่ spin รอใน main loop

ห้ามใช้ shared mutable history/killers ใน v1 และห้ามใช้ lock รอบ node search hot path

## 6. Threads และ Hash design

### 6.1 Effective Threads

```text
effective_threads = min(requested_threads, 1 + helper_tasks_available, memory_safe_threads, 12)
```

- `requested_threads`: ค่า GUI/CLI 1–12
- main ใช้ 1 thread
- helper สูงสุด `effective_threads - 1`
- root ที่มี legal move เดียวใช้ main อย่างเดียวและคืนเร็ว
- ทุกผลต้องรายงาน requested/effective/completed helpers

### 6.2 Hash budget

หลักการ v1:

- main TT ได้ประมาณ 62.5% ของ requested Hash
- helper pool ได้ส่วนที่เหลือแบบเท่ากัน
- TT แต่ละส่วนปัดลงตาม allocation unit/power-of-two ที่ implementation รองรับ
- workspace, alignment และ metadata ต้องนับแยกและรายงาน
- allocated TT รวมต้องไม่เกิน requested Hash
- ถ้า Hash เล็กเกินจำนวน helper ให้ลด effective Threads แทนการสร้าง TT เล็กจนไร้ประโยชน์

ตัวอย่างเป้าหมายเบื้องต้นสำหรับ 12 Threads (ต้องคำนวณใหม่จาก `sizeof(TTEntry)` จริงตอน implement):

| Requested Hash | Main target | Helper target ต่อ 11 ตัว | TT รวมโดยประมาณ |
|---:|---:|---:|---:|
| 64 MiB | 40 MiB | 1.25 MiB | 53.75 MiB |
| 128 MiB | 80 MiB | 2.5 MiB | 107.5 MiB |
| 256 MiB | 160 MiB | 5 MiB | 215 MiB |
| 512 MiB | 320 MiB | 10 MiB | 430 MiB |

ตารางนี้เป็น policy target ไม่ใช่ค่าที่ hard-code หาก TT allocation ต้องเป็น power-of-two ให้ปัดลงและบันทึก actual bytes ทุก context

### 6.3 Hash experiments ที่ predeclare

ทดสอบ matrix:

- Threads: 1, 2, 4, 6, 8, 12
- Hash: 64, 128, 256, 512 MiB
- cold TT และ warm persistent TT
- root branching ต่ำ/กลาง/สูง

ห้ามสรุปว่า Threads มากกว่าดีกว่าจาก NPS อย่างเดียว ต้องดู completed depth, move quality, TT hit utility, re-search rate และ paired strength

## 7. Time management

### 7.1 Deadline policy

- ใช้ monotonic absolute deadline เดียวร่วมกัน
- main PV search ได้ priority สูงสุดในแต่ละ iteration
- helper task ใหม่จะไม่เริ่มเมื่อเวลาคงเหลือต่ำกว่า safety margin
- safety margin เริ่มจากค่าคงที่อนุรักษนิยม แล้วปรับจาก p90 ของ iteration growth/stop latency ที่วัดได้
- main ตรวจ stop เป็นระยะด้วย node polling interval ที่ benchmark แล้ว
- helper ที่ถูก cancel ห้าม publish stale result

### 7.2 Commit policy

- เก็บ legal depth-1 fallback ก่อนเสมอ
- commit เฉพาะ iteration ที่ validation ครบ
- ถ้า depth ปัจจุบันไม่ครบ ให้คืน previous completed result
- score/PV/depth ที่รายงานต้องมาจาก iteration เดียวกัน
- `elapsed_ms` อาจต่ำกว่า budget เมื่อ forced move, terminal, proven result หรือทุก root เสร็จก่อน

### 7.3 เป้าหมาย latency

- overshoot p99 ไม่เกิน max(10 ms, 3% ของ budget) บนเครื่องทดสอบหลัก
- ห้ามเพิ่ม startup delay ของ server; worker pool สร้างแบบ lazy ตอนต้องค้นครั้งแรกหรือ prewarm หลังหน้าเว็บพร้อม
- GUI load และ engine connection ไม่ต้องรอ allocation/clear TT ขนาดใหญ่บน UI critical path

## 8. Candidate ABI และ telemetry

candidate-only compile flag ที่เสนอ:

```text
MAKHOS_NATIVE_ROOT_PVS_SMP=0
```

API ใหม่ควรเป็น handle-based และไม่เปลี่ยน accepted ABI:

- create engine/search handle
- configure Threads/Hash
- search with deadline/history
- clear for new game
- read telemetry
- destroy handle

ขั้นต่ำที่ telemetry ต้องมี:

- backend/provenance string
- requested/effective/completed Threads
- requested/allocated main/helper Hash bytes
- completed depth และ attempted depth
- main nodes, helper nodes และ total nodes
- scout tasks started/completed/aborted/stale
- fail-low, fail-high และ main full re-search count
- per-root bound type, score, depth และ validation status
- main idle/wait time
- deadline stop latency/overshoot
- TT probe/hit/cutoff แยก main/helper
- root branching และ root order generation

หาก telemetry แยก authoritative work จาก speculative workไม่ได้ candidate ยังไม่พร้อมเข้า strength test

## 9. แผน implementation แบบเป็น phase

### Phase 0 — Freeze control และ reproducibility

งาน:

- บันทึก SHA-256 ของ accepted DLL, source, compiler และ flags
- บันทึก Python version, CPU logical cores และ test command
- ล็อก benchmark corpus/position IDs/seeds/time controls
- สร้าง candidate naming convention โดยไม่เขียนทับ control

Gate:

- accepted DLL hash ตรงก่อนและหลังทุก phase
- full test baseline ผ่าน 187/187 หรือจำนวนใหม่ที่อธิบายได้
- perft depth 10 = `861842812`

### Phase 1 — Native coordinator skeleton แบบ 1 thread

งาน:

- แยก authoritative root iteration coordinator ออกจาก ordinary search โดยยังใช้ main context เดิม
- helper count เป็น 0
- compile flag default off
- output candidate DLL แยก

Gate:

- fixed-depth move/score/PV เทียบ ordinary accepted path ต้องตรงใน corpus ที่ล็อก
- fixed-time behavior ต้องไม่แย่เกิน noise ที่ predeclare
- ไม่มี ABI/server/GUI change

เหตุผล: ถ้า coordinator ตัวเดียวเปลี่ยนผลก่อนมี parallelism แปลว่ารากฐาน semantics ไม่เท่ากัน ต้องหยุดแก้ตรงนี้ก่อน

### Phase 2 — Worker lifecycle และ memory accounting

งาน:

- สร้าง private contexts สูงสุด 11 helper
- ทำ Hash partition, allocation failure fallback, clear/destroy
- ยังไม่ส่ง task ค้นจริง

Gate:

- allocated bytes ไม่เกิน budget ทุก Threads/Hash matrix
- loop create/search/clear/destroy ไม่มี leak หรือ handle growth
- failure ที่ Hash ต่ำลด effective Threads อย่างปลอดภัย

### Phase 3 — Shadow helper scouts

นี่คือ **single highest-value first architecture experiment** หลัง skeleton ผ่าน

งาน:

- helper scout root alternatives จริงใน native task queue
- main result ยังเหมือน ordinary authoritative search และไม่ใช้ helper bound ตัดงาน
- วัด scout cost, fail-high rate, duplicate nodes, main idle time และ usable-result timing

KEEP เพื่อไป Phase 4 เมื่อ:

- deterministic/fixed-depth parity ผ่านทั้งหมด
- helper results พร้อมใช้ก่อน main ถึง root เดียวกันในสัดส่วนที่มีนัยสำคัญ
- main idle/wait time ต่ำ
- overhead ที่ Threads=1 ไม่เกิน 2%
- ที่ Threads>1 มี potential saved authoritative work ที่วัดได้ใน diverse corpus ไม่ใช่ตำแหน่งเดียว

REVERT เมื่อ:

- helper ส่วนใหญ่ตอบช้ากว่า main จนใช้ไม่ได้
- duplicate work สูงแต่ไม่มี usable bounds
- synchronization/stop overhead กินประโยชน์
- มี stale/race/illegal result แม้เพียงครั้งเดียว

### Phase 4 — Bound-use root-PVS candidate

เปลี่ยนเพียงแนวคิดเดียว: main อนุญาตให้ใช้ verified helper fail-low ตาม protocol ที่ล็อกไว้ ขณะที่ fail-high ถูก full-window re-search โดย main

งาน:

- ระบุ exact/lower/upper-bound semantics ชัดเจน
- ปิดหรือจำกัด pruning ที่ทำให้ scout bound ไม่ปลอดภัยเฉพาะจุดที่มีหลักฐาน
- deterministic root commit order
- predeclare เมื่อใดต้อง re-search แม้เป็น fail-low

Gate:

- fixed-depth parity/correctness ครบ
- ไม่มี root score/PV ที่มาจาก unvalidated helper
- common completed depth และ move quality ดีขึ้นใน timed corpus

ห้ามผสม shared TT, HCE tuning, new LMR หรือ time-manager tuning ใน candidate เดียวกัน

### Phase 5 — Time-manager integration

เริ่มหลัง search behavior ของ Phase 4 ผ่านเท่านั้น

งาน:

- deadline-aware task admission
- stop latency และ incomplete-iteration rollback
- CPU-load safety margin
- warm/cold behavior

Gate:

- legal result 100% ที่ 1/5/10/25/100/1000/2000 ms
- ไม่มี score/PV/depth mismatch
- overshoot ผ่าน p99 target
- current ply-21 regression stable ภายใต้ normal และ synthetic CPU load

### Phase 6 — Production integration

ทำได้เมื่อ correctness, deterministic benchmarks, STC และ LTC ผ่านทั้งหมดเท่านั้น

งาน:

- สลับ server backend หลัง feature flag
- ตรวจ GUI Threads 1–12 และ Hash 64–512 MiB
- prewarm แบบไม่ทำให้หน้า localhost เปิดช้า
- รักษา board flip ให้หมุนอย่างเดียว ไม่เปลี่ยนฝ่ายผู้เล่น

Gate:

- accepted control ยังเรียกกลับได้ทันที
- server smoke/end-to-end ผ่าน
- telemetry แสดง effective resources ถูกต้อง

## 10. Correctness gates

ต้องผ่านทุกข้อก่อน paired strength test:

1. full Python test suite
2. native build และ warnings ที่สำคัญเป็น error
3. perft depth 0–10 เทียบค่ามาตรฐาน โดย depth 10 = `861842812`
4. randomized native/Python legal-move differential
5. multi-jump capture, promotion during capture และ forced-capture fixtures
6. repetition/history equivalence
7. no-progress boundary 79/80 plies
8. terminal/proven WDL/tablebase authority ไม่ถูก search override
9. fixed-depth parity อย่างน้อย 96 diverse positions ที่ depth 12/15/18
10. ทำซ้ำอย่างน้อย 5 รอบที่ Threads 1/2/4/8/12 เพื่อตรวจ race/determinism
11. timeouts 1/5/10/25/100/1000/2000 ms คืน legal move และ coherent metadata
12. Hash allocation ไม่เกิน budget ที่ 64/128/256/512 MiB
13. repeated create/clear/destroy ไม่มี leak/crash/deadlock
14. accepted DLL SHA-256 ไม่เปลี่ยน

fixed-depth mismatch ไม่ถือว่าเป็น strength improvement โดยอัตโนมัติ ต้องอธิบายว่าเป็น bound semantics ที่ถูกต้องและมี oracle/ordinary full re-search ยืนยัน มิฉะนั้น reject

## 11. Deterministic benchmark plan

### 11.1 Critical regressions

- เซียนเฒ่าเกมล่าสุด Black ply 21: `B:BM14,20,22,23,27,31,32:RM2,3,5,7,11,13,15`
  - เป้าหมาย: เลือก `27-24` อย่างเสถียรที่ 2,000 ms, Threads 12, Hash 512 MiB
- ตำแหน่ง critical เดิมที่ต้อง depth 25 จึงเห็น `27-23`
  - เป้าหมาย: เห็นแผนอย่างเสถียรภายในประมาณ 1,000 ms โดยไม่ทำให้ corpus แย่ลง
- key positions จากเกมแพ้คนและเกมแพ้เซียนเฒ่าก่อนหน้า
  - ใช้เป็น regression set ไม่ใช่ tuning set

แต่ละ critical position รัน:

- 10 cold trials + 10 warm trials
- normal load + controlled background CPU load
- 1,000/1,300/2,000 ms ตามตำแหน่ง
- Threads 1/4/8/12 และ Hash 128/512 MiB

### 11.2 Diverse timed corpus

อย่างน้อย 96 positions และขยายต่อเนื่อง โดยแบ่ง:

- opening transition
- quiet middlegame
- tactical/capture-rich middlegame
- king-heavy conversion/defense
- high/medium/low branching
- ทั้ง Black/Red และ reversible clocks หลากหลาย

teacher/reference ต้องเป็น accepted persistent one-thread หรือ deeper stable reference ที่ล็อก hash/time/depth ชัดเจน ห้ามใช้ candidate สอนตัวเอง

วัด:

- stable-reference move agreement
- score loss เมื่อเลือกต่าง
- completed/attempted depth
- main/helper/total nodes และ NPS
- root best-move instability ระหว่าง iteration
- fail-high/full re-search rate
- elapsed p50/p90/p99 และ deadline overshoot
- TT hit/cutoff utility
- requested/effective Threads และ allocated Hash

### 11.3 KEEP gate ก่อน SPRT

- ไม่มี correctness failure
- diverse move agreement ไม่ต่ำกว่า control
- weighted score loss ไม่แย่ลงเกิน threshold ที่ predeclare
- critical `27-23` และ ply-21 ดีขึ้นอย่างทำซ้ำได้
- ประโยชน์ยังเห็นที่ Threads/Hash มากกว่าหนึ่งค่า
- ไม่ได้ดีเพราะใช้ RAM เกินงบหรือคิดเกินเวลา

## 12. Paired pentanomial SPRT

ทุก match ต้อง:

- candidate/control ใช้ opening เดียวกันสลับสีเป็นคู่
- ใช้ byte-identical accepted control
- one-game concurrency บนเครื่องหลัก
- production rules/tablebases เหมือนกัน
- บันทึก seed, opening plies, clocks, move cap, Threads, Hash และ DLL hashes
- H0/H1 เริ่มที่ `-10/+10 Elo`, alpha/beta 0.05 เว้นแต่ predeclare ใหม่พร้อมเหตุผล

ลำดับ gate:

### Gate A — STC screen

- อย่างน้อย 2 independent seeds
- เริ่ม 64 pairs ต่อ seed
- aggregate จน PASS/FAIL boundary หรือ sample cap ที่ predeclare
- รายงาน pentanomial `[LL, LD, DD/WL, WD, WW]`, W/D/L, LLR และ Elo CI

### Gate B — GUI-like LTC 1 วินาที

- ใช้ clock ใกล้ production เช่น `10+0.1` และ move cap 1,000 ms
- อย่างน้อย 2 independent seeds
- pilot 32 pairs ต่อ seed
- ถ้า aggregate LLR <= 0 หลัง pilot ให้ reject หรือกลับไปหากลไก ไม่กลบด้วย STC
- หาก positive ให้ขยายอย่างน้อย 128 pairs aggregate หรือจน boundary

### Gate C — 2 วินาที confirmation

- move cap 2,000 ms, Threads 12, Hash 512 MiB
- อย่างน้อย 64 pairs aggregate และสอง seeds
- point estimate ต้องไม่เป็นลบอย่างมีนัยสำคัญ และต้องไม่มี time-control reversal
- หากผลยัง inconclusive ให้คงสถานะ candidate ห้าม promote

Production promotion ต้องมี evidence สอดคล้องกันทั้ง STC และเวลาที่ผู้ใช้เล่นจริง ไม่ใช่ PASS เพียง gate เดียว

## 13. External validation

หลัง internal gates ผ่าน:

- เล่นกับเซียนเฒ่าหลาย opening และสลับฝ่าย
- บันทึก full game JSON พร้อม search provenance ทุก ply
- ตรวจว่าความเสียหายย้ายไป phase ใด ไม่ดูผลแพ้ชนะอย่างเดียว
- เปรียบเทียบ score trajectory, completed depth และ root alternatives

เกมภายนอกใช้ค้น failure mode และเติม regression corpus แต่ห้าม optimize ให้ตาหนึ่งโดยตรง

## 14. Artifact และการตั้งชื่อ

ตัวอย่าง:

```text
build/makhos_native_root_pvs_shadow_candidate.dll
build/makhos_native_root_pvs_bound_candidate.dll
build/root_pvs_shadow_audit_<date>.json
build/root_pvs_fixed_time_<seed>.json
build/root_pvs_sprt_<seed>.json
build/root_pvs_ltc_<seed>.json
```

ทุก JSON ต้องมี:

- schema/version
- source/DLL/control hashes
- command/config
- seed และ corpus hash
- start/end timestamps
- environment summary
- raw per-position/per-game rows
- aggregate statistics
- verdict `KEEP`, `REVERT`, `INCONCLUSIVE` หรือ `PROMOTE`

## 15. Revert conditions

REVERT candidate ทันทีเมื่อเกิดข้อใดข้อหนึ่ง:

- illegal move, crash, deadlock, data race หรือ stale result
- score/PV/depth metadata ไม่สอดคล้องกัน
- fixed-depth mismatch ที่ยืนยันความถูกต้องไม่ได้
- allocated Hash เกิน requested budget
- deadline overshoot เกิน gate อย่างทำซ้ำได้
- improvement จำกัดอยู่แค่ตำแหน่งเซียนเฒ่าตำแหน่งเดียว
- diverse corpus regression ที่เกิน threshold
- STC FAIL
- LTC กลับทิศเป็นลบแบบ adaptive route เดิม
- telemetry ไม่พอแยก main work กับ speculative work

หลัง revert:

- compile flag กลับ default 0
- ลบการเชื่อม production path แต่เก็บ scratch reproducer/artifacts
- รัน focused + full tests
- ยืนยัน accepted DLL hash
- บันทึก mechanism และเหตุผลที่ reject ใน `SKILL.md`

## 16. Promotion conditions

PROMOTE ได้เมื่อครบทั้งหมด:

1. correctness gates ผ่าน
2. resource/deadline gates ผ่าน
3. critical regressions ดีขึ้นซ้ำได้
4. diverse deterministic corpus ไม่ regress
5. STC ให้ positive evidence ตาม boundary
6. GUI-like 1-second LTC ไม่เกิด reversal และผ่าน gate
7. 2-second confirmation ไม่เป็นลบ
8. external games ไม่พบ correctness/systematic positional collapse ใหม่
9. server/GUI smoke ผ่านโดยหน้าเว็บไม่เปิดช้าลงอย่างมีนัยสำคัญ
10. มี rollback path กลับ accepted control ที่ทดสอบแล้ว

ก่อนครบทั้งหมดสถานะต้องเป็น candidate หรือ inconclusive เท่านั้น

## 17. ความเสี่ยงหลักและ mitigation

| ความเสี่ยง | ผลกระทบ | วิธีควบคุม |
|---|---|---|
| scout bound ไม่ sound ภายใต้ selective pruning | เลือกตาผิดแม้ดูเร็วขึ้น | shadow ก่อน, fixed-depth parity, main full re-search fail-high |
| helper ทำงานซ้ำมาก | node เพิ่มแต่ depth ไม่เพิ่ม | วัด duplicate/usable-result timing และ reject เร็ว |
| private TT เล็กเกินไป | helper quality ต่ำ | Hash-aware effective Threads และ main-heavy allocation |
| main รอ barrier | เสียเวลา deadline | main ทำ authoritative work ต่อ, bounded queue, cancelable tasks |
| finish order ทำให้ nondeterministic | benchmark/debug ยาก | generation id และ commit ตาม root order |
| oversubscription บน 12 Threads | latency แย่ภายใต้ load | matrix + loaded trials + effective thread reporting |
| startup allocation ทำให้ localhost ช้า | UX regression | lazy create/prewarm หลัง web ready |
| benchmark overfit | เล่นจริงไม่แข็งขึ้น | 96+ diverse corpus, paired seeds, STC+LTC+external validation |

## 18. Stop conditions ของ architecture นี้

หยุดและไม่ไล่ต่อเมื่อ:

- shadow audit แสดงว่า helper bound มาถึงไม่ทันหรือ potential saving ต่ำใน diverse corpus
- bound-use candidate fail correctness ซ้ำหลังแก้ protocol หนึ่งครั้ง
- candidate สองเวอร์ชันต่อเนื่องให้ STC/LTC reversal แบบเดิม
- scaling ดีเฉพาะ NPS แต่ move quality/completed depth ไม่ดีขึ้น
- RAM/time cost สูงกว่าประโยชน์ที่ 1–2 วินาที

เมื่อหยุด ให้คง classical checkpoint, สรุป evidence และประเมินใหม่ว่าจะกลับไป single-thread search/HCE/data หรือเข้าสู่ NNUE roadmap ภายใต้คำสั่งใหม่ ห้ามเริ่ม NNUE เอง

## 19. งานแรกที่ควรทำเมื่อได้รับอนุญาตให้ implement

**Experiment ID: `native_root_pvs_shadow_v1`**

เป้าหมายเดียว: พิสูจน์ว่า native authoritative coordinator + shadow helpers สามารถสร้าง helper results ที่ทันใช้และรักษาผล main เดิมได้ โดยยังไม่เปลี่ยนตาเดิน

ลำดับ:

1. freeze hashes/environment/corpus
2. ทำ Phase 1 coordinator 1-thread และผ่าน parity
3. ทำ Phase 2 private worker pool/Hash accounting
4. เปิด Phase 3 shadow scouts
5. รัน correctness
6. รัน deterministic 96-position audit + critical regressions
7. ตัดสิน `KEEP_TO_BOUND_USE` หรือ `REVERT`
8. อัปเดต `SKILL.md` ด้วย code hashes, commands, raw artifacts และ verdict

ไม่รัน SPRT ใน shadow mode เพราะ playing behavior ต้องเหมือน control; SPRT เริ่มเมื่อ Phase 4 เปลี่ยน search behavior เท่านั้น

## 20. Definition of done ของแผนนี้

แผนนี้ถือว่าจบเมื่อมีหนึ่งในสองผล:

- **PROMOTED:** native root-PVS/SMP ผ่านทุก gate และกลายเป็น production backend โดย accepted control ยัง recover ได้
- **REJECTED WITH EVIDENCE:** กลไกถูกพิสูจน์ว่าไม่คุ้ม/ไม่ปลอดภัย พร้อม artifacts ที่ทำให้ไม่ต้องทดลองซ้ำ

ทั้งสองผลต้องทำให้เราเข้าใจคอขวดมากขึ้นและรักษาเป้าหมาย general Thai Makhos strength โดยไม่ overfit เซียนเฒ่าหรือเริ่ม NNUE ก่อนคำสั่ง

## 21. Implementation record 2026-08-24

### 21.1 สิ่งที่ KEEP

`MAKHOS_NATIVE_ROOT_PVS_SMP=1` สร้าง authoritative main context หนึ่งตัว,
Win32 worker pool สูงสุด 11 helpers, private TT/history/killer/workspace, total-Hash
budget, cancellation และ telemetry โดย helper เป็น shadow เท่านั้น ผล move/score/PV/
depth/nodes ที่คืนมาจาก main เหมือน ordinary same-source search

- source: `native/makhos_native.c` SHA-256
  `EA987C0CD625E6AF2B376269474202686265F6AE35E61291DF0DA0E6B2C07E2C`
- Python bridge: `makhos/native.py` SHA-256
  `90FFF834D3F20553F6255BFA204853F71261E623A04C86E0DF003709F3C88A34`
- same-source control DLL: SHA-256
  `B66D65B8887ACFC19E833C868782B922ABCFFCFFD711954F7160CA21806127BD`
- shadow candidate DLL: SHA-256
  `00AF95C588132716E4BBB245406D98D6D2DA3AD38AE436C7DA2C9EBD889C4BDA`

Audit 96 positions, seed `20261061`, depth 12, 12 Threads, Hash 512 MiB:

- parity 96/96 และ authoritative nodes เท่ากัน 96/96
- helper nodes 2,977,805 เทียบ main 4,806,695 (`0.619512x`)
- completed 5,910/6,066 scouts (`97.4283%`)
- ready before main 4,646/5,910 (`78.6125%`)
- ready fail-high 621; ready above current alpha 265; worker failures 0
- main wait 5.56 ms (`0.3921%` ของ shadow time)
- shadow/main wall-time ratio `1.05250x`
- artifact `build/root_pvs_shadow_audit_20260824.json` SHA-256
  `732C8EBC9A35793D5C6472E54B438AADFB5D517C58831ACE8B4C6552E92BF86A`

One-thread overhead audit ใช้ 96 positions, depth 12, สาม repetitions: parity และ
nodes เท่ากัน 288/288, wall-time ratio `1.00598675x`; artifact SHA-256
`ABE914362A023D830310FF19E7B4CD2C035FC052210D8E900293F14A0DEA08B3`.

### 21.2 สิ่งที่ REJECT

การใช้ private helper fail-low เพื่อตัด main root search โดยตรงเปลี่ยนผล 4/4
ตำแหน่งใน gate แรก แม้ node ratio ลดเหลือ `0.8779x`; artifact
`build/root_pvs_bound_failure_20260824.json` SHA-256
`6FF3A2C3D9D34D509E17839BB52649A20DC66D5D55CB46FF3D34D49454EEC11F`.

protocol fix ที่อนุญาตไว้หนึ่งครั้งปิด null-move และ LMR ใน helper scout เพื่อให้
fail-low conservative ขึ้น แต่ยังเปลี่ยน move/score/PV 4/4 ตำแหน่ง ลด main nodes
เพียง `0.925450x`, ใช้ fail-low 108 ครั้ง และช้ากว่า ordinary main `1.134760x`.
สาเหตุเชิงกลไกคือการข้าม root subtree ทำให้ main ไม่ได้รับ history/killer/TT
updates; selective search ของ main ใน iteration ถัดไปจึงเปลี่ยน แม้ bound ของ
root ที่ข้ามจะ conservative. Artifact
`build/root_pvs_verified_bound_proof_20260824.json` SHA-256
`57F68FDFDDE1C8518E4EB79A500ECF46F022319B43CB8D9FCE67D02FAB61C028`;
rejected DLL SHA-256
`9C2A889FAEFFB017C5DCD7EE251BEAFB706F579F45BE68F11964CE6404F76ED7`.

จึง **ไม่รัน SPRT** เพราะ candidate ไม่ผ่าน predeclared fixed-depth gate และส่วน
bound-use ถูกถอนจาก source แล้ว เหลือเฉพาะ measurement-only shadow path ที่
default off; server/GUI/production search ไม่เปลี่ยน

### 21.3 Final correctness and isolation

- focused root-PVS tests 5/5
- full source suite 192/192 ใน 84.809 วินาที
- initial-position native perft depth 1--10 ลงท้าย `861842812`
- randomized native/Python differential: 1,004 positions, 5,402 legal moves,
  10 exact three-piece states, seed `20261061`
- requested Hash ผ่าน budget gate ที่ 1/2/4/8/12 Threads; 12T/512 MiB จัด TT
  main 320 MiB และ helper 10 MiB ต่อคน รวม 430 MiB
- accepted DLL ไม่ถูกเขียนทับและยังมี SHA-256
  `FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`

Verdict ของ architecture นี้คือ **REJECTED WITH EVIDENCE สำหรับ playing path**
และ **KEEP สำหรับ coordinator/telemetry diagnostic infrastructure**. Stop
condition ข้อ 18 ถูกกระตุ้นแล้ว: ห้ามลองผ่อน bound protocol หรือ root-skip แบบ
เดิมซ้ำโดยไม่มี mechanism ใหม่ที่รักษา main heuristic state ได้อย่างพิสูจน์ได้
