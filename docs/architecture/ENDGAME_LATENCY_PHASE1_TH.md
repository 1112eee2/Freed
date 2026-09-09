# Endgame latency: Phase 1A

ฐาน: main `ec26c5e`; branch สำหรับงานนี้ `codex/endgame-latency-phase1`.

สถานะ: เพิ่มการวัดเวลารายช่วงและเครื่องมือวิเคราะห์แบบ opt-in แล้ว
ยังไม่เปลี่ยน deadline, search, evaluation, TT policy หรือกฎของ tablebase.
`RULESET.json`, `makhos/core.py`, accepted DLL และ checkpoint SPRT เดิมต้องคงเดิม.

## สมมติฐานและวิธีพิสูจน์

ความหน่วงตอนเข้า endgame มีอย่างน้อยสองต้นทุนที่แยกกัน:
การสร้าง TB3 ก่อนเริ่ม search clock และงานสร้างตา/สถานะใน Python ระหว่างค้นหา.
ใช้เวลาเต็มคำขอ GUI และ CPU/IO/page faults ระดับ process ตรวจส่วนแรก;
ใช้ cProfile ที่ความลึกคงที่ตรวจส่วนหลัง โดยไม่นำเวลา profiled ไปปนกับ latency.

คำสั่งและสัญญาของข้อมูลอยู่ใน [benchmark README](../../benchmarks/README.md).
หลักฐานดิบที่บีบอัดและผลตรวจอยู่ใน `benchmarks/results/endgame_latency_phase1/`.
ไฟล์ผลบนเครื่องเก็บใน `build/endgame_latency_phase1_*` โดยแต่ละรันไม่เขียนทับกัน.

## ขอบเขต PR นี้

1. แยก validation, lock wait, engine setup, TB3 preparation, search, provenance
   และ response preparation พร้อมรักษาฟิลด์เวลาเดิม.
2. Snapshot ข้อมูล backend/resources ใน engine lock เดียวกับการค้นหา.
3. เพิ่ม profiler แบบปิดตามค่าเริ่มต้น พร้อมระบุส่วนที่วัดไม่ได้อย่างชัดเจน.
4. เพิ่ม benchmark ที่ใช้ production handler/release, แยก cold/warm/fixed-depth,
   ตรวจผลเมื่อเปิด/ปิด profiler และเก็บ provenance ของการรัน.
5. ทดสอบเวลารอคิว/โหลด TB ที่อยู่นอก search clock, exception cleanup,
   repetition/clock และเทียบ handler เดิมจาก commit ฐานด้วย fixed-depth.

ผล benchmark เป็นหลักฐานด้าน latency และการแบ่งต้นทุน ไม่ใช่ Elo หรือการ
รับรอง SMP รุ่นใหม่. ยังไม่ทำ native search modification จึงไม่มี perft gate ใหม่.

## ผลวัด 2026-09-09

ตั้งค่า 12 Threads / 512 MiB, production release `nnue-v1-20260908`.
TB3–6 ใช้ Python search ที่ความจุ 1 thread; ตำแหน่ง 7 ตัวใช้ native root split.
การมี NNUE DLL/model ใน provenance เป็นข้อมูลการตั้งค่า ไม่ได้แปลว่า Python
endgame ใช้ NNUE evaluator. ไม่มีการเปลี่ยน evaluator ในงานนี้.

| รัน | ตัวอย่าง timed | TB3 หลังคำขอแรก | P95 handler overshoot สูงสุดของกลุ่ม | P95 client wall สูงสุดของกลุ่ม |
| --- | --- | --- | --- | --- |
| 100 ms pilot, 9 ตำแหน่ง × 2 โหมด | 360 | พร้อม | 11.18 ms | ดู summary รายกลุ่ม |
| 1000 ms, TB3/repetition/native7 × 2 โหมด | 120 | พร้อม | 8.79 ms | 1027.01 ms |
| 2000 ms, repetition/native7 × 2 โหมด | 80 | ยังไม่โหลด | 9.60 ms | 2034.15 ms |

ทุกกลุ่มมี 20 timed observations. ทั้งหมดรวม 619 observations:
560 timed, 56 fixed-depth และ 3 cold-process requests.
รัน 2000 ms เริ่มจาก 4 ตัวโดยตรง จึงไม่สร้าง TB3; เป็นอีกสถานะ readiness
และห้ามนำไปอธิบายผลของ time control โดยสมมติว่าการตั้งค่า oracle เหมือนรัน 1000 ms.
OS cache ไม่ถูก flush และไม่ได้เก็บ ETW hard-fault trace.

Cold TB3 preparation ใช้ 11,920.661 ms ใน pilot และ 11,204.566 ms ในรัน 1000 ms.
pilot มี CPU delta 11,671.875 ms และ RSS เพิ่ม 679,141,376 bytes ตลอดคำขอแรก.
หลักฐานสอดคล้องกับต้นทุนสร้าง TB3 ในหน่วยความจำ ไม่ใช่สรุปจาก wall time อย่างเดียว.
Warm fixed-depth BEST profiles ของ TB3–6 ใช้ self time ประมาณ 56–63% ใน
move generation/state routines; ค่าเหล่านี้รวมงานจาก evaluation/policy ด้วย.
การแก้ probe caching เพียงอย่างเดียวจึงไม่น่าครอบคลุมต้นทุนหลักที่พบ.

การตรวจ:

- เปิด/ปิด profiler ให้ move, score, PV, depth, nodes, WDL และ TB hits ตรงกัน 28 คู่.
- เทียบ handler เดิมจาก `ec26c5e` กับ handler ใหม่ที่ depth 1/2/3 ทั้งสองโหมด
  ใน TB4–6 และ native7: ตรงกัน 48/48 กรณี.
- Full discovered suite: 434/434 PASS, 0 failures, 0 errors, 0 skips,
  97.582 seconds; source/test inventory ไม่เปลี่ยนระหว่างรัน.
- Protected-open guard พบการเปิดพื้นที่ SPRT ที่ห้ามแตะ 0 ครั้ง; SHA-256
  ของ RULESET/core/accepted DLL ตรงกับก่อนแก้.
- การรัน verification ครั้งแรกผ่าน parity แต่หยุดที่ discovery ของ namespace
  tests ใน Python 3.14; รอบสุดท้ายใช้ discovery แบบเดียวกับ unittest ปกติและผ่านครบ.

คำตัดสิน: **KEEP_DIAGNOSTICS**. ไม่ใช่การ promote การเปลี่ยน search และไม่มี SPRT ใหม่.
งานถัดไปที่มีหลักฐานรองรับมากที่สุดคือ TB3 loadable artifact/readiness เพื่อตัด
ต้นทุนสร้างฐานออกจากคำขอเดินตา ก่อนงาน shared TT/Lazy SMP.

`benchmarks/results/endgame_latency_phase1/summary.json` ผูก SHA-256 ทั้งข้อมูลดิบ
และ gzip; ตรวจว่าคลายแล้วได้ bytes เดิมทุกไฟล์. `verification_snapshot.py.gz`
เป็นสคริปต์ที่ใช้ตรวจจริง: restore ใต้ `build/` ใน checkout ที่มี artifacts พร้อม
และยังไม่มีโฟลเดอร์ผล verification ชื่อนั้นก่อนรัน. รายงานนี้เป็น implementation
verification ไม่ใช่ attestation การรับรอง NNUE release ใหม่.

## งานต่อหลัง Phase 1A

| ลำดับ | งาน | Gate ก่อนเปิดใช้ |
| --- | --- | --- |
| 1B | ทดลอง TB3 artifact ที่โหลดกลับได้ เพื่อลดการสร้างฐานในคำขอแรก; เพิ่ม readiness และ deadline ตลอดคำขอ | ตรวจรูปแบบ/กฎ/hash, cold/warm/GUI cancellation, repetition regressions, rebaseline การจัดเวลา |
| 1C | เชื่อม TB3–6 reader และ WDL-bound propagation เข้า native โดยใช้ native repetition machinery ที่มีอยู่ | reference differential รวม terminal/clock/history; เริ่ม 1T แล้ว root split |
| 2 | SMP กลไกใหม่ที่แก้ contention และการรับผล helper | atomic publication proof, 1T parity/overhead, scaling รวม 6T, paired screen และ SPRT ใหม่ |
| 3 | จัดดัชนีเครื่องมือและหลักฐานก่อนย้าย work/ | references/manifest paths ไม่ขาด; full suite และ GUI/replay smoke |
| 4 | ต่อยอด game_analysis, แก้ schema round-trip, เพิ่ม history-aware labels และ held-out suite | replay validation, source-game split และตรวจ confidence ของ labels |

ทุก phase ใช้ผลวัดกำหนด candidate ถัดไป ห้ามนำ control ที่ตัด TB WIN ผิดเดิม
มาเป็นเป้าความเร็ว และห้ามลดการตรวจ repetition เพื่อให้ผล benchmark ดีขึ้น.
