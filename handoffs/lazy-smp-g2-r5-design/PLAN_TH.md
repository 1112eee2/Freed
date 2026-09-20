# Proposed Lazy SMP G2 r5 acceptance design — REVIEW REQUIRED

วันที่ 2026-09-20 · ฐานวินิจฉัย PR #23 head
`f5a2f3fee1b04c0af10f74f802095ee0ce66f807` · ยังไม่ implement acceptance revision

## 1. คำตัดสิน PR #23 ที่ใช้เป็นฐาน

Local ตรวจแบบ read-only ใน detached worktree แล้ว: base `117c22a` เป็น ancestor,
r3/r4 snapshot verifiers PASS, 75 evidence entries ตรง hash, ทั้ง 12 cases เป็น
expected observations และ diff 82 paths จำกัดอยู่ใน diagnostic workflow/handoff เท่านั้น
รายละเอียด machine-readable อยู่ที่ [PR23_REVIEW.json](PR23_REVIEW.json)

รับเฉพาะข้อสรุป **CONFIRMED_HARNESS_INITIALIZATION_DEFECT**: preflight เขียน seed
`{1,2,3,4}` ภายใต้ key/epoch เดียวกับ workload แล้ว reset แค่ sequence จึงเกิด accepted
seed ที่ไม่ผ่าน workload assertions ได้โดยไม่มี thread ข้อสรุปนี้ไม่แจกแจง historical
failures ทุกครั้ง ไม่พิสูจน์ race-freedom/liveness และไม่ปิด G2

## 2. วัตถุประสงค์ r5

r5 ต้องแยกสามคำถามออกจากกัน:

1. **Initialization:** workload slot ต้อง miss ก่อน publication แรก และไม่มี stale preflight tuple
2. **Safety:** read ที่ตอบ true ต้องคืน tuple/depth ที่ writer encoding อนุญาตเสมอ
3. **Liveness/coverage:** progress ที่รับประกันใน bounded SPSC handshake แยกจาก coverage
   ที่ขึ้นกับ schedule ของ multi-writer stress

r5 เป็น acceptance harness ของ publication functions เท่านั้น ไม่ใช่ Windows worker lifecycle,
search-strength gate หรือเหตุผลย้อนกลับไป promote candidate เดิม

## 3. Source reuse และไฟล์ที่จะเพิ่มหลังอนุมัติ

ดู proposed tree/diff ที่ [PROPOSED_DIFF.md](PROPOSED_DIFF.md) ขณะนี้ **ยังไม่เพิ่มไฟล์เหล่านั้น**

- copy frozen `native/makhos_native.c`, `native/makhos_types.h` และ pthread smoke/negative
  controls จาก r4 snapshot โดยตรวจ SHA เดิม ห้ามใช้ native source จาก Local WIP
- generator ใหม่ extract `NativeCompactMove`, `SharedMoveHintEntry`,
  `shared_move_hint_write` และ `shared_move_hint_read` แบบ verbatim ด้วยกฎเดียวกับ r4
  แล้ว append `harness_body.c`; ไม่มีการแก้ atomics/memory order หรือแทรก callback ใน functions
- `verify_snapshot.py` สร้าง expected `probe.c` จาก frozen inputs + body ใหม่ทุกครั้งแล้ว
  เทียบ byte/hash ก่อนและหลัง run; r3/r4 กับผลเก่าคงเดิม byte-for-byte
- failure log ใช้ `NativeCompactMove` และ `depth` locals ที่ call เดิมคืนจริง พร้อม participant/
  iteration/writer encoding แล้ว fail ทันที ไม่อ่าน slot รอบหลังเพื่อกล่าวอ้างว่า read เดิม mixed
- ถ้าภายหลังต้องเห็น internal `seq1/seq2` ให้เสนอ diagnostic build แยก ซึ่งไม่ใช่ gate r5
  และต้องประเมินผลของ instrumentation ก่อน ห้ามแก้ gate แบบเงียบ ๆ

## 4. Initialization และ directed protocol

ใช้สาม slot แยกกันและ initialize เฉพาะก่อนสร้าง worker:

- `preflight_slot`: seed-counterexample regression ของ PR #23 และ directed rejection tests
- `workload_slot`: zero/invalid namespace (`key=0`, `epoch=0`) ขณะที่ reader ต้องการ
  `key=123`, `epoch=7`; ต้อง miss ก่อน first valid write
- `liveness_slot`: fresh invalid namespace สำหรับ SPSC handshake เท่านั้น

Preflight คง key mismatch, epoch mismatch, paused writer (odd sequence), sequence exhaustion,
valid publication และ same-entry multi-writer coverage ห้าม reset sequence/free slot ระหว่าง worker
ทำงาน Seed เดิมต้องยัง reproduce ใน `preflight_slot` เพื่อกัน regression ของความเข้าใจ แต่ห้ามใช้
slot นั้นเป็น workload

## 5. Safety workload

- 8 writers + 4 readers, start barrier, คนละ 100,000 attempts เหมือน workload เดิม
- writer encoding:
  `value=(writer_id<<32)|iteration`, move=`{value,~value,(uint32)value,~(uint32)value}`,
  key=123, epoch=7, depth=42
- freeze namespace ของ concurrent stress เป็น `writer_id` **0..7** และ `iteration`
  **1..100,000**; reader ต้อง decode high/low 32 bits แล้ว assert ว่าทั้งสองค่าอยู่ในช่วงนี้
  นอกเหนือจาก complement/meta/depth checks การ decode นอกช่วงเป็น FAIL แม้ algebraic
  complement จะยังตรง
- ทุก accepted read คง assertions ครบ: low complement, high=value low32,
  captured-high complement, depth=42 และ namespace ตรง
- counters แยก participant เป็น **thread-local non-atomic 64-bit** records:
  writer attempts/successful/skipped และ reader attempts/accepted/rejected แต่ละ worker
  เขียนเฉพาะ record ของตนเอง main อ่าน/รวมหลัง successful `pthread_join` เท่านั้น ไม่มี
  per-iteration shared counter, atomic increment หรือ counter read ข้าม worker ใน hot loop
  จึงไม่เพิ่ม synchronization ที่เปลี่ยนลักษณะ contention; start barrier ใช้ release/acquire
  เฉพาะการเริ่มงาน ส่วน failure path อาจ serialize accepted locals ไป stderr แล้ว abort ได้
- invariants หลัง join:
  - writer success + skipped = 100,000 ทุก writer
  - reader accepted + rejected = 100,000 ทุก reader
  - payload/depth mismatch หรือ TSan report = FAIL
  - writer คนใด successful=0 หรือ reader คนใด accepted=0 โดยไม่พบ defect =
    INCOMPLETE_COVERAGE ไม่ใช่ PASS
- counters ใช้ประเมิน coverage เท่านั้น ไม่อ้าง lock-freedom ของ production search

## 6. Bounded liveness แยกต่างหาก

SPSC handshake ใช้ 1 writer/1 reader จำนวน **256 distinct publications** โดย freeze
`writer_id=0`, `publication_id/iteration=1..256`:

1. reader ยืนยัน initial miss จาก `liveness_slot` แล้ว
   `atomic_store_explicit(reader_ready,true,memory_order_release)`
2. writer ห้าม publish จน
   `atomic_load_explicit(reader_ready,memory_order_acquire)` เป็น true จึงไม่มี first-write/
   initial-miss race รอบใหม่
3. writer publish tuple `n` ผ่าน production function แล้วรอ
   `atomic_load_explicit(ack,memory_order_acquire)==n`
4. reader validate/decode tuple; เฉพาะ `publication_id==next_expected` จึงนับ distinct และ
   `atomic_store_explicit(ack,n,memory_order_release)` ค่าเดิมที่อ่านซ้ำให้นับเป็น duplicate
   แต่ห้ามเพิ่ม distinct; ค่าอนาคต/ผิด writer/range/payload/depth เป็น FAIL
5. publication function และ sequence atomics คง `seq_cst` จาก frozen production verbatim;
   ready/ack ใช้ release/acquire เพื่อ ordering ของ harness เท่านั้น
6. process timeout เป็นขอบเขตภายนอก ห้าม retry process

PASS ของ stage นี้ต้องมี writer successful=256, reader distinct accepted=256,
acknowledgments=256, tuple ถูกทั้งหมดและจบในเวลา จำนวน raw successful reads อาจมากกว่า
256 เพราะ duplicate แต่ใช้แทน distinct publications ไม่ได้ เมื่อ reader-ready เกิดแล้ว
wrong tuple, จบไม่ครบ 256 distinct/acks หรือ timeout เป็น **FAIL ของ liveness test** เสมอ
ไม่ใช่ INCOMPLETE_COVERAGE ส่วน compile/launch/thread-creation หรือ prerequisite failure
ก่อน reader-ready แยกเป็น infrastructure `NOT_RUN`

## 7. Frozen run matrix

### Windows plain pre-gate

- snapshot verifier ก่อน/หลัง
- GCC C17 pthread plain build; deterministic directed cases 1 process
- protocol processes **5 fresh processes**, timeout **30 s/process** ไม่มี retry
- ตรวจ exit/status/counters, deadlock, bounded join และ binary hash
- Windows PASS เป็น readiness เท่านั้น ไม่ทดแทน Linux TSan

### Linux GitHub-hosted TSan

ต่อ compiler **Clang 18 และ GCC 13**:

1. pthread smoke 1 process, timeout 30 s — ต้อง exit 0 และไม่มี detector report
2. known-racy pthread negative control 1 process, timeout 30 s — ต้องมีข้อความ
   `ThreadSanitizer: data race`; exit codeอย่างเดียวไม่ใช่ calibration
3. r5 protocol **5 fresh processes/compiler**, timeout 120 s/process ไม่มี retry

รวม 10 sanitized protocol processes; full r5 PASS ต้อง 5/5 ทั้งสอง compiler lanes
และ snapshot verifierก่อน/หลังผ่าน งาน GitHub ใช้ time limit 30 นาทีและเก็บทุกผล

## 8. Classification และมิติผลที่แยกกัน

- **PASS:** inputs/verifiers/build/calibration ผ่าน; directed+SPSC ผ่าน; ทุก protocol process
  ไม่มี race/assertion/timeout และทุก participant ผ่าน coverage; Linux ทั้งสอง lane 5/5
- **FAIL:** correctness/liveness failure ไม่ขึ้นกับ TSan calibration: invalid accepted tuple/range,
  assertion/unexpected exit หรือ SPSC ที่เริ่มหลัง reader-ready แล้วผิด tuple จบไม่ครบ 256
  distinct publications/acks, deadlock หรือ timeout เป็น FAIL แม้เกิดใน Windows plain
  ส่วน TSan race ใน protocol เป็น FAIL ของ sanitizer lane เมื่อ lane นั้น calibrate แล้ว
  ทั้งสองกรณีเป็น failure ที่ harness สังเกตได้ ไม่ถูกเหมารวมเป็น production defect โดยอัตโนมัติ
- **INCOMPLETE_COVERAGE:** ไม่มี safety violation แต่ participant coverage ต่ำกว่าเกณฑ์ที่ freeze;
  ใช้ **เฉพาะ concurrent 8W/4R stress** เท่านั้น ไม่ใช้กับ SPSC
- **NOT_RUN:** input drift, verifier/prerequisite ขาด, compiler/TSan/runtime unavailable,
  smoke ล้มก่อนเข้า body, negative control ไม่รายงาน race จริง หรือ SPSC ไปไม่ถึง
  reader-ready เพราะ compile/launch/thread-creation infrastructure failure

Collector บันทึกอย่างน้อยสองมิติแยกกัน: `correctness_liveness_status` จาก plain/TSan
protocol observations และ `tsan_calibration_status` ต่อ compiler หาก TSan ใช้ไม่ได้ lane นั้น
เป็น NOT_RUN แต่ต้องไม่กลบ FAIL ที่ Windows/plain หรือ lane อื่นตรวจพบจริง

จำนวน process ที่ freeze คือจำนวน **slots ในผลรวม**: เมื่อ process หนึ่งเป็น
INCOMPLETE_COVERAGE หรือ FAIL ให้เก็บผลแล้วดำเนิน fresh process slots ที่เหลือตาม matrix เดิม
โดยไม่ replacement/retry/cherry-pick หากต้องยุติเพราะ inputs drift หรือ runtime/toolchain
ใช้ต่อไม่ได้ ให้สร้าง result entry ของทุก slot ที่เหลือเป็น NOT_RUN พร้อมเหตุผลเดียวกัน ห้าม
ละรายการออกจาก denominator

Aggregate precedence: correctness/liveness FAIL ที่สังเกตจริงหรือ calibrated protocol TSan
FAIL มาก่อนทั้งหมด; หากไม่มี FAIL แต่ required lane NOT_RUN ให้ overall NOT_RUN; ถ้าทุก lane
รันได้แต่ concurrent coverage ไม่ครบ ให้ INCOMPLETE_COVERAGE; จึงจะ PASS ดูรายละเอียดใน
[acceptance_matrix.json](acceptance_matrix.json)

## 9. Unknowns ที่ r5 ไม่อ้างว่าปิด

- สาเหตุ historical concurrent failure แต่ละครั้ง และ accepted==0 ทุกรอบ
- ความปลอดภัยใน interleaving ที่ TSan/จำนวน process จำกัดไม่เคยสุ่มเจอ
- Windows engine worker lifecycle, cancellation, GUI และ end-to-end search correctness
- ความคุ้มค่า/Elo ของ Lazy SMP; candidate เดิมยัง REJECT_FOR_PERFORMANCE / NOT_PROMOTED
- การเปลี่ยน harness อาจทำให้ schedule ต่างจาก r4 จึงห้ามเปรียบ accepted count ตรง ๆ

## 10. หลักฐานที่จะเก็บ

- base/head/workflow/run/job IDs และ frozen source/body/probe/generator/manifest hashes
- before/after protected inventory และ byte reconstruction verifier output
- OS/kernel/CPU/glibc/compiler/sanitizer versions, exact argv/env/timeouts
- binary hashes (ไม่ commit binaries), stdout/stderr, exit code, elapsed ของทุก process
- per-process/per-participant counters, SPSC rounds/acks และ canonical classification reason
- known-racy report text, smoke output, TSan reportเต็มถ้ามี, no-result/timeout logs
- executed workflow copy, commands.json, result.json, evidence_sha256.json และ raw logsทั้งหมด
- Windows readiness recordแยกจาก Linux TSan result; ห้ามนำอีกฝั่งมาแทนกัน

## 11. Approval boundary

เอกสารชุดนี้คือ **proposed design/diff เท่านั้น** การอนุมัติ review จึงอนุญาตเพียงเริ่ม
implement revision ใหม่ตามไฟล์/ตัวเลข/เกณฑ์นี้ การเปลี่ยน process counts, coverage,
timeouts, assertions, writer encoding หรือ compiler lanes ต้องแก้ design และ review ใหม่ก่อนรัน
ไม่มีสิทธิ์ merge/promote/open SPRT หรือแก้ production จากการอนุมัติ harness
