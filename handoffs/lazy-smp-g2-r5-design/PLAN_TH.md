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
- ทุก accepted read คง assertions ครบ: low complement, high=value low32,
  captured-high complement, depth=42 และ namespace ตรง
- counters แยก participant เป็น atomic 64-bit:
  writer attempts/successful/skipped และ reader attempts/accepted/rejected
- invariants หลัง join:
  - writer success + skipped = 100,000 ทุก writer
  - reader accepted + rejected = 100,000 ทุก reader
  - payload/depth mismatch หรือ TSan report = FAIL
  - writer คนใด successful=0 หรือ reader คนใด accepted=0 โดยไม่พบ defect =
    INCOMPLETE_COVERAGE ไม่ใช่ PASS
- counters ใช้ประเมิน coverage เท่านั้น ไม่อ้าง lock-freedom ของ production search

## 6. Bounded liveness แยกต่างหาก

SPSC handshake ใช้ 1 writer/1 reader จำนวน **256 publications**:

1. reader ยืนยัน initial miss
2. writer publish tuple `n` แล้วรอ atomic acknowledgment ของ `n`
3. reader อ่านจนรับ tuple `n` ถูกต้อง จากนั้น ack; writer จึงไป `n+1`
4. process timeout เป็นขอบเขตภายนอก ห้าม retry process

PASS ของ stage นี้ต้องมี writer successful=256, reader accepted=256, acknowledgments=256,
tuple ถูกทั้งหมดและจบในเวลา ไม่อนุมานว่า contention stress ต้อง accepted>0 จาก stage นี้

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

## 8. Classification

- **PASS:** inputs/verifiers/build/calibration ผ่าน; directed+SPSC ผ่าน; ทุก protocol process
  ไม่มี race/assertion/timeout และทุก participant ผ่าน coverage; Linux ทั้งสอง lane 5/5
- **FAIL:** บน runtime ที่ calibrate แล้วพบ invalid accepted tuple, TSan race ใน protocol,
  assertion/unexpected exit, deadlock/timeout หรือ source r5 compile error ที่ไม่ใช่ missing runtime
- **INCOMPLETE_COVERAGE:** ไม่มี safety violation แต่ participant coverage ต่ำกว่าเกณฑ์ที่ freeze;
  เก็บผลและหยุด ห้าม retry เพื่อหา schedule ที่ดี
- **NOT_RUN:** input drift, verifier/prerequisite ขาด, compiler/TSan/runtime unavailable,
  smoke ล้มก่อนเข้า body หรือ negative control ไม่รายงาน race จริง จึงไม่มี calibrated gate

Aggregate precedence: executed calibrated FAIL มาก่อนทั้งหมด; หากไม่มี FAIL แต่ required lane
NOT_RUN ให้ overall NOT_RUN; ถ้าทุก lane รันได้แต่ coverage ไม่ครบ ให้ INCOMPLETE_COVERAGE;
จึงจะ PASS ดูรายละเอียดใน [acceptance_matrix.json](acceptance_matrix.json)

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
