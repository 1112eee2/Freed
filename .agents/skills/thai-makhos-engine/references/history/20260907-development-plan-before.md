# Historical snapshot before 2026-09-07 guide implementation

This content preserves the previous document for provenance. Relative paths
refer to its original location. Current instructions are in current-state.md,
SKILL.md and DEVELOPMENT_PLAN_TH.md; old next-action statements below are not active.

---

# แผนพัฒนา ThaiMakhosEngine สู่เอนจิ้นหมากฮอสไทยระดับโลก

สถานะเอกสาร: **แผนหลักสำหรับงานข้างหน้า**  
ทบทวนล่าสุด: 2026-09-05  
เป้าหมาย: พัฒนาเอนจิ้นให้แข็งแกร่งที่สุดเท่าที่พิสูจน์ได้ โดยไม่ยอมแลก
ความถูกต้อง ความเสถียร หรือความสามารถย้อนกลับไปยังรุ่นควบคุม

**Current phase: Gate B ผ่านแล้ว → เตรียม Gate C production confirmation.**
ผลสุดท้ายและ SHA-256 อยู่ใน Current directive ของ skill และ
`.agents/skills/thai-makhos-engine/references/current-state.md`.
ยังไม่ promote NNUE: ต้องตรวจ 1s/2s, 12 threads, Hash รวม 512 MiB ต่อเอนจิ้น
ตาม Gate C ด้านล่างก่อน ข้อความเตรียม Gate B เดิมเป็นประวัติ ไม่ใช่คำสั่งรันซ้ำ

## 1. ลำดับอำนาจของเอกสาร

เมื่อข้อความเก่าขัดกับข้อความใหม่ ให้ใช้ลำดับนี้:

1. คำสั่งล่าสุดของผู้ใช้และ goal ที่ active
2. `.agents/skills/thai-makhos-engine/SKILL.md`
3. เอกสารนี้สำหรับลำดับงานและ gate ระยะยาว
4. `NNUE_ROADMAP.md` สำหรับ feature/model/data contract ของ NNUE
5. `.agents/skills/thai-makhos-engine/references/experiment-evidence-ledger.md`
   สำหรับหลักฐานย้อนหลัง
6. `PROOF_ROADMAP.md` และ roadmap เฉพาะสถาปัตยกรรมที่ถูกพักไว้

คำว่า “next experiment” ใน historical ledger ไม่มีอำนาจสั่งงาน หากไม่ได้ถูก
ยืนยันซ้ำในหัวข้อ Current directive ของ skill หรือใน Current phase ของเอกสารนี้

## 2. นิยามความสำเร็จ

### 2.1 Correct engine

- legal move, state transition, repetition และ no-progress ตรงกับกฎโครงการ
- Python reference/native differential และ official perft ผ่าน
- proof/tablebase/terminal result มีอำนาจเหนือ heuristic หรือ NNUE เสมอ
- GUI แสดง build/settings/runtime provenance ที่ค้นจริง

### 2.2 Stronger accepted engine

- candidate ผ่าน correctness และ deterministic/fixed-time gates ที่เกี่ยวข้อง
- การเปลี่ยน search/evaluation ผ่าน paired pentanomial SPRT ตามเกณฑ์ที่ล็อกไว้
- ไม่มี regression สำคัญในเวลาที่ผู้ใช้เล่นจริง 1 และ 2 วินาที
- external regressions เป็นส่วนของชุดตรวจ แต่ไม่ใช้เป็นจุด tuning เดี่ยว
- accepted DLL รุ่นก่อนยังอยู่และ rollback ได้

### 2.3 Credibly strongest in the world

ห้ามอ้างจาก self-play หรือ SPRT กับรุ่นเก่าเพียงอย่างเดียว ต้องมี:

- ผลซ้ำได้กับ independent Thai-Makhos engines/bots ที่แข็งแกร่งที่สุดที่เข้าถึงได้
- กติกา สี เวลา opening และจำนวนเกมที่เทียบกันได้ พร้อม game records
- อย่างน้อยหนึ่ง short control ที่ใกล้การใช้งานจริงและหนึ่ง longer control
- ผลเชิงสถิติสนับสนุน ไม่ใช่เลือกเฉพาะเกมที่ชนะ
- การทดสอบกับผู้เล่นเก่งใช้เป็นหลักฐานประกอบ ไม่แทน paired engine evidence

ถ้าไม่มี opponent ที่เปิดให้ทดสอบอย่างเป็นระบบ ให้รายงานว่า “strongest internal
candidate” หรือ “strongest measured against available opponents” ห้ามขยายเป็น
world-strongest claim

## 3. ตัวตนของเอนจิ้นที่ต้องแยกจากกัน

| ตัวตน | ความหมาย | กฎ |
|---|---|---|
| Accepted control | `build/makhos_native_accepted.dll` SHA-256 `FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD` | ห้าม overwrite ระหว่าง experiment |
| Current source | โค้ดล่าสุด อาจมี source-level infrastructure/promotions | ไม่ถือว่า accepted โดยอัตโนมัติ |
| Candidate | DLL/model ชื่อแยกและ hash แยก | ทิ้งหรือ revert ได้ |
| Runtime GUI | DLL/model ที่ server โหลดจริง | ต้องเชื่อ `/api/state`/search provenance ไม่เชื่อชื่อไฟล์อย่างเดียว |

## 4. Invariants ที่ห้ามละเมิด

- ห้ามแก้ `RULESET.json` และ `makhos/core.py`
- GUI มี priority สูงสุด ห้าม acquisition/benchmark/SPRT แย่งทรัพยากร
- Hash คือ total budget และต้องวัด allocation จริงเมื่อ Threads เปลี่ยน
- sealed test ห้ามถูกอ่านเพื่อเลือก architecture, loss, scale, epoch หรือ checkpoint
- เปลี่ยนทีละแนวคิด ห้าม stack candidate ที่ยังไม่ผ่าน
- ห้ามทดลองกลไกที่ ledger ระบุ REJECTED ซ้ำ หากไม่มี mechanism/evidence ใหม่
- ห้ามเริ่ม DFPN หรือ large tablebase ใหม่โดยไม่มีคำสั่งเฉพาะ
- ห้ามเรียก outcome ของ truncated game ว่า draw
- ห้ามเรียก stable teacher move ว่า proven best move

## 5. Current phase — Phase 9 Gate B primary acceptance preflight

### สถานะที่ยืนยันแล้ว

- acquisition/final audit/inventory/full-suite/contract/preflight/authorization
  ผ่านครบ โดย final audit A/B byte-identical และ full suite v17 ผ่าน 383/383
- train 199,923 eligible rows; validation 23,550 eligible rows; sealed test เปิดแล้ว
  หนึ่งครั้งภายใต้ opening commitment ที่ห้าม model selection
- float learning curve 25k/50k/100k/all × 2 seeds เสร็จครบ 8 runs
- KEEP full-data seed `20280002` ตาม validation-loss rule ที่ freeze ไว้:
  model SHA-256 `5FD87ABD2F9CAAC81045A58AEA420445B90CAC9A70D5FFBDFC5694BA1338CA4E`
- validation teacher MAE ลดจาก accepted-HCE `0.16617580001338003` เป็น
  `0.12098223072290963`; นี่ยังไม่ใช่ Elo หรือ playing-path promotion
- quantized export A/B ผ่านและ byte-identical: binary SHA-256
  `07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C`
- validation 23,550 rows: MAE `0.00230912088115429`, RMSE
  `0.00302979286685792`, max `0.0148904375679927`, sign mismatch `0.3822%`
- overflow proof ผ่าน: int16 bound 16,935 และ int32 bound 806,516
- native scalar `MKNNUE1` loader + full refresh ผ่าน real-model parity 1,152/1,152
  และ reproducible build A/B byte-identical; full refresh ช้ากว่า accepted HCE
  111.7x--171.9x จึงเก็บเป็น correctness oracle เท่านั้น
- scalar incremental accumulator ผ่าน final-artifact parity: 640 structured,
  4 targeted, ทุก 8 clock-boundary, reset จากทั้ง 9 bucket, 300 random
  forward/undo/reapply และ deep stack โดย zero mismatch
- AVX2 dense inference ผ่าน final-artifact parity, unsupported-host fail-closed
  และเร็วกว่า scalar native 4.793x--4.993x ที่ 154--160 ns/eval
- AVX2 delta update ผ่าน exact parity และเร็วกว่า scalar 4.987x--5.926x;
  full suite v13 ผ่าน 373/373 โดย accepted DLL และ playing path ไม่เปลี่ยน
- Phase 7 candidate เสร็จและ freeze แล้ว: DLL SHA-256
  `32C323026A7F78CCD9C4013FC3067422A564EE3D0A6ADE4F1CE5C62356747E79`;
  perft/differential, recursive parity, fixed-depth/time, external diagnostics,
  Threads/Hash/time-stop/forced-move และ opt-in GUI provenance ผ่าน
- Phase 8 harness/tests ผ่าน; full suite v20 ผ่าน 386/386 ที่ SHA-256
  `DAB696B9128CB249F61E49DED85C134F2439AB21912A42AD8C16BCE80D959135`
  และ accepted DLL/production default ไม่เปลี่ยน
- opening authorization/commitment SHA-256 คือ
  `01666818F1613ABDBBB4BD452280A75F60E79F68142A88B42609F30AEA4CA23A` /
  `8F00BB6341B271D379BA48B406199B3C5AE50C75037CA2AEFB54AAE9AFEFB44E`
- Phase 8 จบครบ 6/6 shard, 1,533 เกม, 41,698 selected positions และ 23,097
  eligible positions โดย stderr/tmp เป็นศูนย์; sealed report SHA-256 คือ
  `BF5166F7BF2B5B5311C138321E5CF97AB8ECE8AC3DB3AF7E1F215A3E7AFD1077`
- sealed teacher MAE ของ quantized NNUE คือ `0.1240688054049856` เทียบ
  accepted HCE `0.16674293355207395`; นี่เป็น offline evidence ไม่ใช่ Elo
- arena ซ่อมแล้ว: `sprt_max_plies` fail closed, workload lease ตรวจ GUI ก่อน
  ทุก pair/ply, process arena เป็น BelowNormal, focused tests ผ่าน 13/13 และ
  full suite v20 ผ่าน 386/386 โดย locked acquisition source ไม่เปลี่ยน
- Gate A PASS หลัง 52 pairs / 104 games: W49 D36 L19, pentanomial
  `0/8/18/14/12`, LLR `+2.9921776889755956`, Elo
  `+103.1398415563513 +/-52.33548371749529`; result SHA-256
  `6C6C29C6D430085FF5549741485D5702FE102651B24A0C8738B8061F9AECDEDA`
- atomic per-pair checkpoint/resume ของ Gate B เสร็จแล้ว: focused tests 16/16,
  real-DLL resume smoke ผ่าน และ full suite v21 ผ่าน 389/389 ที่ SHA-256
  `9549E7A8E55A3C57713FEE92ADF32770E99574648652FCCC5E9F35A3192DA0AF`
- งานถัดไปเพียงงานเดียวคือรัน Gate B ตาม contract ที่ freeze ก่อนเกมใน
  `build/nnue_phase9_gate_b_contract.json`, SHA-256
  `DD56A5709348F6CE88B13EC14A33DFC4A8F36AE4156298962427E28D7C3A7FB8`
- ห้ามเลือก/เปลี่ยน model จากผล sealed test, ห้ามเปลี่ยน production playing path
  ห้ามสร้าง opening ครั้งที่สอง และห้าม sweep architecture/loss ใหม่

รายละเอียด acquisition ด้านล่างเป็น completed historical runbook ไม่ใช่ current
directive; ห้าม resume workers หรือสร้าง analysis เพิ่มภายใต้ manifest เดิม

### งานที่ทำระหว่าง acquisition

1. รักษา supervisor/coordinator/workers 6 ตัวตาม locked contract
2. ตรวจจำนวน analyses, per-shard tail, stderr bytes, `.tmp`, disk free และ GUI lease
   ผ่าน `scratch/nnue_scaling_health_audit.py` โดยไม่เปิด volatile status,
   analysis payload หรือ sealed-test files
3. เมื่อ GUI เปิด ให้ workers drain/yield ตาม workload lease
4. หลัง crash/reboot ให้ใช้ runbook ใน skill และ resume ผ่าน supervisor ที่ hash ตรงเท่านั้น
5. ทำได้เฉพาะ docs/read-only/focused low-resource tests ที่ไม่รบกวน workers
6. ห้ามแก้ bound acquisition scripts/manifests ระหว่าง run
7. บน Windows ต้องเปิด supervisor แบบ hidden/detached พร้อม launcher logs แยก
   ไม่ผูกอายุ process กับ terminal/task; stderr จาก external process-loss ต้อง hash,
   เก็บใน `incident_logs/` และบันทึกเหตุการณ์ ห้ามลบเพื่อทำให้ health ดูสะอาด

### NNUE v1 feature ABI tooling (prepared, non-gating)

`makhos/nnue_features.py` เป็น executable oracle ของ feature contract
`thai-makhos-shared-137-v1`: 128 piece-square inputs และ 9 reversible-clock
buckets, two-perspective canonical rotation, side-to-move/opponent ordering,
และ parent/child remove/add deltas ที่คำนวณจาก state จริง ไฟล์นี้ยังไม่ถูก
import เข้าสู่ playing path และไม่ใช่ trainer authorization

การเปลี่ยนนี้ single-sources feature payload ใน
`scratch/nnue_trainer_contract_gate.py` และมี focused tests ครอบคลุม exact
indices, symmetry, clock boundaries, quiet/capture/promotion/multi-capture และ
300 random legal transitions oracle tests ผ่าน 12/12; ก่อนเพิ่ม freezer
combined stack ผ่าน 53/53 ใน 3.984 วินาที และ freezer experiment stack ผ่าน
63/63 ใน 4.355 วินาที การผ่านนี้เป็น tooling evidence เท่านั้น ไม่มี
model/training/native inference หรือ strength promotion และไม่ต้องใช้ SPRT

### Deterministic trainer-contract freezer (prepared, non-authorizing)

เมื่อ Phase 1 exit gate ครบ ให้ใช้ `scratch/nnue_trainer_contract_freezer.py`
ประกอบ contract จาก dynamic evidence hashes, exact train/validation dataset
counts และ train-only choices ที่ระบุชัดเจนเท่านั้น ตัว freezer จะเติม feature
oracle, network shape, sealed-test policy และ authorization boundary ที่ล็อกไว้
เอง, ตรวจ key/type/leakage, deep-copy choices และเขียน canonical LF
byte-locked JSON นอก source/acquisition trees

freezer SHA-256 คือ
`B0E26673291AB92882CE48051F9C487E244E33EB64FE5A9B744A2ECEEB721273` และ
focused tests SHA-256 คือ
`3F8F0D841E19E9E4420195A243E4215B0690FD25DBC822F19FD8EAD286FDD17F`;
tests ผ่าน 10/10 และ ณ freezer checkpoint combined focused stack ผ่าน 63/63
ใน 4.139 วินาที (experiment run: 4.355 วินาที) การเปลี่ยนนี้เป็น tooling
evidence เท่านั้น ไม่สร้าง placeholder contract และไม่ authorize training

### Deterministic tiny-fixture trainer preflight (promoted tooling)

สร้าง `scratch/nnue_trainer_preflight.py` เพื่อปิดช่องว่างก่อนรัน trainer จริง
โดยใช้ fixture สังเคราะห์ขนาดเล็กเท่านั้น ไม่อ่าน production analysis, test
analysis, sealed-test manifest หรือ volatile supervisor status และทิ้ง weights
ทั้งหมดหลังจบการทดสอบ Harness นี้ตรวจ overfit, deterministic repeat,
deterministic checkpoint resume, non-tautological checkpoint checksum และ
protected-path/sealed-test guards; artifact ที่สร้างได้เป็น non-authorizing และ
ต้องอยู่นอก source/acquisition trees

preflight SHA-256 คือ
`157BF19A3E77D760F3B9B94D747F9CC314C55481A714A245ABE04A2C43019CF2` และ
focused tests SHA-256 คือ
`7432CACD5FC9C6DBE1BCB7E458DF6873CA5550C4BB990E78C9C1007AB156A411`;
focused tests ผ่าน 7/7 รวม direct-file CLI smoke และ combined low-resource NNUE
gate stack ล่าสุดผ่าน 70/70 ใน 4.766 วินาที `py_compile` ผ่านด้วย Current discovered inventories
คือ 120 source files / 44 test files โดยมี hashes
`A069013B5ABAD25F2D4935E394BE804573A3E0C24E1BB4A06C27AA54A3259B65` และ
`007A14891C6592AA0DA49F1E6BE16980248BD80E7970969738E5C6346B655437`
ตามลำดับ

นี่เป็นการ promote tooling เท่านั้น ยังไม่สร้าง real contract/preflight
artifact, ไม่อ่าน production data, ไม่ train model, ไม่เปลี่ยน playing path และ
ไม่ทำให้ training authorized Real preflight ต้องรอ acquisition ครบ, final audit
สองรอบที่ byte-identical, full-suite attestation ตอน workers idle, exact
train/validation inventories และ frozen trainer contract จริงก่อน

### Exit gate

ต้องครบทุกข้อ:

- 13,802 development analyses ตรง manifest แบบ exact set และไม่มีไฟล์เกิน
- coordinator summary verdict PASS และ gates ทุกตัว true
- source/shard/analysis inventories และ hashes ตรง
- accepted DLL/rules/Threads/Hash/persistent/clear/budget ladder ตรงทุกเกม
- recompute position, canonical id, pieces, kings, phase, turn และ legal moves จาก
  position จริง ไม่เชื่อ self-reported metadata อย่างเดียว
- zero duplicate development positions
- zero truncated-game outcome labels
- stderr และ temporary artifacts เป็นศูนย์
- test analysis reads และ sealed-test-manifest reads เป็นศูนย์
- coverage ผ่าน train total/king/ทุก phase/ทั้งสอง turn และ validation minimum
- final audit ทำซ้ำแล้ว byte-identical
- full discovered test suite ผ่านหลัง workers idle

ตัว verifier ที่เตรียมไว้คือ `scratch/nnue_scaling_final_audit.py`; artifact ของมัน
ต้องระบุ `trainer_authorized_by_this_artifact=false` จนกว่า trainer contract ใน
Phase 2 จะถูก freeze แยกต่างหาก

### Failure policy

- ไฟล์ analysis เสีย/ผิด binding: quarantine เฉพาะไฟล์นั้นและ rerun เกมนั้นผ่าน
  locked worker; ห้ามแก้ JSON ด้วยมือ
- manifest/source hash เปลี่ยน: fail closed และ audit ก่อน resume
- coverage ไม่ผ่าน: เพิ่ม fresh train/validation source games ภายใต้ manifest ใหม่
  ห้ามลด gate หรือดึง sealed test มาชดเชย
- reboot: artifacts ที่ atomic ยังใช้ได้ แต่ process watcher ไม่รอด reboot

## 6. Phase 1 — Finalize และ seal development data

### งาน

1. ปล่อย coordinator ปิด run และสร้าง final summary
2. รัน focused final-audit tests
3. รัน final audit ครั้งที่หนึ่ง
4. รันซ้ำใน completed state และตรวจ byte-identical output hash
5. เมื่อไม่มี teacher worker แล้ว รัน full discovered suite
6. บันทึก Python/compiler/OS, script hashes, manifests, corpus counts และ disk usage
7. ทำสำเนา immutable ของ manifest/audit/summary ก่อนเริ่ม trainer

### Full-suite tooling ที่เตรียมแล้ว

ใช้ `scratch/nnue_full_suite_attestation.py` เท่านั้นเพื่อสร้างหลักฐาน full suite
หลัง acquisition ครบ เครื่องมือนี้บังคับ health เป็น
`COMPLETE_PENDING_FINAL_GATES`, ไม่มี pipeline process/GUI, ยึด workload lock ครบ
32 slots, ตรวจ GUI ก่อน/หลังทุก test, guard ไม่ให้เปิด production analyses,
sealed manifest หรือ volatile status, ตรวจว่ารันครบทุก discovered test และ bind
accepted DLL, final audit, runner/result output และ exact source/test inventories
ทั้งก่อนและหลัง จากนั้นจึงเขียน v2 attestation นอก acquisition/source/test trees

source/test SHA-256 ของ runner คือ
`4109D973F7200A3EC61ABC262F93CC3820D1B3F59B1EA2F34F8CDE21690AADB9` และ
`B1C255946AE68822BDE10ECCF5F7C1782C478435A996884F42CCE0E9033DC653`;
focused tests ผ่าน 11/11 ขณะนี้ยังไม่รัน full suite จริงเพราะ workers ยัง active

### Inventory tooling ที่เตรียมแล้ว

หลัง final audit สองรอบ byte-identical ให้ใช้เฉพาะ
`scratch/nnue_trainer_input_inventory.py` สร้าง train/validation inventories
ตัว builder จะจับคู่ development game ทุกเกมกับ analysis SHA-256 จาก coordinator
PASS, ประกอบกลับเป็น analysis-set SHA-256 จาก final audit, บังคับ exact/disjoint
split, เรียง game id แบบ deterministic และไม่ยอมเขียน output ภายใน acquisition
directory มันไม่อ่าน analysis payload หรือ sealed-test file และ artifact ที่ได้
ยังไม่อนุญาต training

focused tests ผ่าน 9/9 และ ณ preflight-freezer checkpoint focused gate stack
ผ่าน 63/63 ใน 4.355 วินาที (latest stack รวม preflight ผ่าน 70/70 ใน 4.766
วินาที)
source/test SHA-256 คือ
`B33B7ACACB0F5C0F5374B27D7289A6061CF40C77F969F93552CB34E0B8330C5E` และ
`1932F769B6AB7406E2E7CFA5E97FECA296424305F60072A06FBC51C673AFF211`
ตามลำดับ ขณะนี้ยังไม่มี real inventory เพราะ acquisition ยังไม่ครบ

### Gate ผ่าน

- Exit gate จาก Phase 0 ผ่านทั้งหมด
- accepted DLL hash ไม่เปลี่ยน
- sealed test ยังไม่มี label file ถูกเปิดหรือสร้าง
- trainer input inventory ระบุเฉพาะ train/validation source games

หากไม่ผ่าน ให้ซ่อม data pipeline เท่านั้น ห้ามข้ามไป training

## 7. Phase 2 — Freeze first trainer experiment

ก่อนรัน training ต้องสร้าง machine-readable trainer manifest ที่ล็อก:

- feature spec v1: shared 137 inputs, two 128 accumulators, hidden 32, scalar output
- canonical rotation, perspective order และ 9 clock buckets
- exact train/validation game IDs และ dataset hashes
- target normalization/clipping และ centipawn conversion
- loss formula และสัดส่วน teacher score / game outcome / exact WDL
- weighting ต่อ source game, position, phase และ exact-WDL stratum
- optimizer, learning rate schedule, batch size, max epochs
- random seeds, deterministic flags, dependency versions และ target CPU
- learning-curve sizes เช่น 25k/50k/100k/all โดยใช้ split เดิม
- checkpoint/early-stop rule ที่เลือกจาก validation เท่านั้น
- architecture count = 1 สำหรับ v1; ห้าม post-hoc network sweep
- test-opening authority และเงื่อนไข “เปิดครั้งเดียวหลัง model/export freeze”

### Authorization tooling ที่เตรียมแล้ว (ยังไม่อนุญาต training)

`scratch/nnue_trainer_contract_gate.py` เป็นตัวตรวจแบบ fail-closed สำหรับ gate
นี้ โดยไม่อ่าน analysis payload หรือ sealed-test file มันจะออก authorization ได้
ต่อเมื่อมีหลักฐานจริงครบดังนี้:

ให้สร้าง frozen contract ด้วย `scratch/nnue_trainer_contract_freezer.py` ก่อน
แล้วจึงทำสำเนา byte-identical สองไฟล์ส่งเข้า gate; freezer เองไม่ใช่
authorization และห้ามถูกใช้กับ partial acquisition

- final-data audit สองไฟล์ที่สร้างซ้ำแล้ว byte-identical
- frozen trainer contract สองไฟล์ที่สร้างซ้ำแล้ว byte-identical
- development manifest ตัวจริงและ train/validation inventories ที่ exact,
  disjoint และประกอบกลับเป็น analysis-set SHA-256 จาก final audit ได้
- full discovered suite PASS หลัง acquisition workers หยุดแล้ว
- v2 full-suite attestation bind current source/test inventories, runner hash,
  final audit และ accepted DLL โดย trainer gate recompute inventories ซ้ำ
- tiny-fixture trainer preflight PASS: overfit, deterministic repeat,
  deterministic resume, checkpoint checksum และ sealed-test guard

focused tests ของ gate ผ่าน 10/10; ณ freezer checkpoint focused gate stack ผ่าน
63/63 ใน 4.355 วินาที (latest stack รวม preflight ผ่าน 70/70 ใน 4.766 วินาที)
source/test SHA-256 ณ freezer checkpoint คือ
`FB99AE3DC546D4B3FC1B4E1CFDD6025439FA4C2A72787E43460FD968D4FBBA31` และ
`B3B4977926F7CC8B2E6B5E66182179646E474033D47DC08F960C057E611F386D`
ตามลำดับ ขณะ acquisition ยังไม่ครบ ห้ามสร้าง placeholder attestation หรือ
contract เพื่อบังคับให้ gate ผ่าน และยังไม่มี model training ใดเกิดขึ้น

### Measurement ก่อน freeze

- ใช้ train games เท่านั้นสำหรับ calibration/CV ของ target scale และ loss mix
- ตรวจ outcome/exact-WDL availability และ phase/king/clock support
- validation ใช้ประเมิน trainer/checkpoint ตาม rule ที่ freeze แล้ว
- external regressions ใช้รายงาน ไม่ใช้เลือก hyperparameter

### Gate ผ่าน

- trainer manifest ทำซ้ำ byte-identical
- unit tests ป้องกันการเปิด test path
- tiny-fixture overfit, deterministic resume และ checkpoint checksum ผ่าน
- ไม่มี choice ใดอาศัย sealed test

## 8. Phase 3 — Float NNUE learning curve

### งาน

1. train architecture เดียวตาม manifest หลาย data sizes ที่ predeclare
2. ทำอย่างน้อยสอง deterministic seeds; seed เพิ่มได้เมื่อ variance gate ระบุไว้ก่อน
3. บันทึก train/validation loss และ calibration ทุก epoch
4. แยกรายงานตาม phase, king/no-king, turn, clock bucket, exact-WDL และ source game
5. เทียบ HCE baseline บน rows เดียวกัน
6. ตรวจ external-regression margins แบบ read-only

### Keep gate

- validation improvement เกิดทั้ง aggregate และ strata สำคัญ ไม่ใช่เฉพาะ opening
- ไม่มี material/sign/pathology หรือ saturation ที่อธิบายไม่ได้
- seeds ให้ทิศทางสอดคล้องกัน
- learning curve บอกได้ว่าจำกัดด้วย data หรือ model capacity
- checkpoint ถูกเลือกตาม rule เดิมเท่านั้น

ถ้า 100k→all ยังดีขึ้นชัด ให้เพิ่ม fresh development data ก่อนเพิ่ม network size
ถ้า plateau พร้อม underfit สม่ำเสมอ จึงออกแบบ size experiment รุ่นถัดไปเป็นแนวคิดเดียว

## 9. Phase 4 — Quantized export และ model identity

- export header `MKNNUE1` ผูก dimensions, feature spec, scales, ruleset hash,
  payload length/checksum และ model SHA-256
- int16 feature accumulators, int8 dense weights/activations, int32 sums/biases
- prove accumulator/dense overflow bounds จาก exported weights และ legal max occupancy
- corrupt/truncated/incompatible model ต้อง fail closed ไป classical fallback ที่ระบุชัด
- Python float-vs-quantized error distribution ต้องผ่าน limits ที่ freeze ก่อน export
- quantized export ของ checkpoint เดิมต้อง byte-identical เมื่อ rerun

ยังไม่แตะ production search ใน phase นี้

## 10. Phase 5 — Native scalar oracle

- implement model loader และ scalar C inference แบบ default-off
- randomized Python-quantized/scalar-C equality บนทุก phase/turn/clock bucket
- test terminal/tablebase/proof precedence และ corrupt-model rejection
- perft/move generation ต้องไม่เปลี่ยน
- benchmark raw eval latency, cache footprint และ evals/s บน Ryzen 5 5600H

ถ้า scalar cost สูงจน search NPS ลดจนไม่น่าชดเชย ให้หยุด optimize inference ก่อน integration

สถานะ 2026-08-31: **KEEP เป็น measurement-only correctness oracle**

- reproducible `/Brepro` DLL A/B SHA-256
  `2D071F91EC9551FD82EB8793F4E651BD1FA87A9B14C1EA3A6A4B3588B248634C`
- real-model bit-exact 1,152/1,152; corrupt/incompatible/unsafe inputs fail closed
- model allocation 43,684 bytes; full-refresh scalar 1,431--2,356 ns/eval
- accepted HCE 8.329--21.088 ns/eval; scalar ช้ากว่า 111.7x--171.9x
- full suite v9 ผ่าน 351/351; accepted DLL และ playing path ไม่เปลี่ยน

ดังนั้นห้าม integrate oracle เข้า search; AVX2 dense ผ่านแล้วแต่ scalar delta
update 438--638 ns/ตากลายเป็นคอขวดหลัก จึงเดินต่อด้วย AVX2 delta arithmetic
เป็นแนวคิดเดียว

## 11. Phase 6 — Incremental accumulator + AVX2

### Phase 6A scalar incremental — complete KEEP measurement only

- reproducible DLL SHA-256
  `E455B708423F4B8B8B126263DB7A5F7BD5E7645DDF300114DC07EAB8B01C0CE7`
- full refresh = parent/child/undo incremental แบบ bit-exact ครบ targeted,
  random, deep stack, multi-capture, promotion, ทุก clock boundary/reset,
  model reload และ invalidation
- accumulator 584 bytes; dense scalar eval 761--789 ns ในช่วง 6--16 หมาก
  และ 781 ns ที่ 2 หมาก; update สอง perspective 438--638 ns/ตา
- full suite v11 ผ่าน 356/356; accepted DLL และ playing path ไม่เปลี่ยน

### Phase 6B AVX2 dense evaluation — complete KEEP measurement only

- reproducible baseline-x86-64/AVX2-target DLL SHA-256
  `EA6B6A1C47671CC1050E9FC861D3BF403E2AD6FCB6D07A7B24BE62E41B8C250A`
- complete scalar/AVX2 parity ผ่าน; target capability PASS และ forced-off fail closed
- AVX2 dense 154.062--159.664 ns/eval เร็วกว่า native scalar 4.793x--4.993x
- full suite v12 ผ่าน 363/363; accepted DLL และ playing path ไม่เปลี่ยน

### Phase 6C complete — AVX2 accumulator delta arithmetic

#### Correctness

- source SHA-256
  `6A236861A185D6C6DAD8DA785F10C92D680D26823C4A534F5733E56651FD182C`
  และ reproducible DLL SHA-256
  `64C862F3FC2AB99ACFE2AEE04966401E05B48849FF61EAE14A5F5208C5873095`
- scalar/AVX2 parity ผ่าน quiet 1/1, clock-boundary 2/2, capture 3/2,
  multi-capture 4/2, promotion 2/2, ทุก clock transition/reset, random/deep,
  invalid delta, reload และ forced-unsupported fail closed; focused 10/10
- full suite v13 ผ่าน 373/373; attestation SHA-256
  `7E7F1BBB1D1AB73BC76B0C02C8228C4C6540322766BD659E28D540D5549F2964`

#### Performance

- AVX2 update median 87.427--138.179 ns ตาม delta shape เร็วกว่า scalar
  4.987x--5.926x บน Ryzen 5 5600H
- เมื่อนำไปรวมกับ Phase 6B dense reference คาด 245.542--296.294 ns ต่อ
  update+eval; นี่เป็น estimate ไม่ใช่ measured search NPS
- verdict: KEEP measurement only; ไม่มี SPRT เพราะ playing path ไม่เปลี่ยน

## 12. Phase 7 — Opt-in NNUE search candidate

**Current.** เปลี่ยนทีละแนวคิดเฉพาะการต่อ KEEP NNUE เข้า native search
ผ่าน per-ply accumulator stack; ห้าม stack search heuristic ใหม่ใน candidate นี้

- DLL/model แยกจาก accepted และ development slot
- NNUE แทนเฉพาะ non-terminal static evaluation ณ quiet leaves/normal nodes ตาม contract
- proof/tablebase/terminal/mate/repetition/no-progress ยังคง authoritative
- native loader/model SHA/feature ABI แสดงใน CLI, server และ game provenance
- classical fallback ต้อง explicit ไม่ silent

### Gate ก่อนเกม

- current full suite, perft depth 10 และ randomized differential ผ่าน
- legal/time-stop/forced-move/Hash/Threads/GUI startup tests ผ่าน
- diverse fixed-depth/fixed-time corpus รายงาน move/score/depth/nodes/PV/NPS
- raw evaluator และ qsearch eval-call cost อยู่ใน budget
- external regressions ทั้งหมดถูกรายงาน แต่ไม่มีตาใดเป็น hard-coded gate เดี่ยว

## 13. Phase 8 — Sealed test เปิดครั้งเดียว

**Complete.** Six shards passed 1,533/1,533 games and the one-time report is
`build/nnue_sealed_test_v1/sealed_test_report.json`, SHA-256
`BF5166F7BF2B5B5311C138321E5CF97AB8ECE8AC3DB3AF7E1F215A3E7AFD1077`.
It covers 41,698 selected / 23,097 eligible positions and remains forbidden for
model selection.

เปิด test labels ได้เมื่อ architecture, trainer loss, checkpoint, feature spec,
quantization และ model binary ถูก freeze แล้วเท่านั้น

- ใช้ accepted teacher contract เดิมในการ label sealed test
- test job ต้องอยู่ใน manifest ใหม่ที่ประกาศว่า model selection forbidden
- รายงาน test calibration/loss/strata/exact-WDL เพียงครั้งเดียว
- ห้ามเปลี่ยน model จากผล test แล้วเรียก test เดิมว่า unseen อีก
- หาก model ถูก reject และต้องออกแบบรุ่นใหม่ ให้สร้าง fresh sealed test split ใหม่

ผ่าน offline test ไม่เท่ากับ strength promotion; เป็นเพียง gate ก่อน arena

## 14. Phase 9 — Playing-strength gates

### Gate A: intrinsic evaluator screen

- Threads=1 เพื่อตัด known Python root-split confound
- paired color-swapped openings, persistent search, production tablebases
- arena ต้อง fail closed เมื่อเกมใดชน `max_game_plies`; ห้ามนับ truncation เป็น draw
- workload lease ต้องตรวจ GUI priority ก่อนทุก pair และ ply; คู่ที่กำลังเล่น
  ห้ามถูกนับถ้า GUI ขอทรัพยากร
- contract ที่ freeze แล้ว: seed `20261101`, `0.2s+0.01s`, H0/H1
  `-10/+10`, max 256 pairs, Threads=1, Hash=256 MiB, persistent search,
  opening 8 plies, sequential games, production tablebases, max 300 plies
- PASS เท่านั้นจึงไป Gate B; FAIL หรือ INCONCLUSIVE ที่ cap ห้าม advance

### Gate B: primary acceptance SPRT

- `10s + 0.1s`, H0=0 Elo, H1=+2 Elo
- independent seed/opening set, pentanomial exact LLR
- ต้อง checkpoint แบบ atomic หลังทุกคู่; resume ต้องตรวจ config/hash และ replay
  RNG opening stream เดิม ห้ามนับคู่ที่ GUI ขัดจังหวะ
- predeclare max pairs; ค่าเริ่มต้น 10,000 pairs หากทรัพยากรอนุญาต
- PASS เท่านั้นจึงไป promotion; positive estimate ที่ CI คร่อมศูนย์คือ INCONCLUSIVE

### Gate C: production confirmation

- 1 วินาทีและ 2 วินาทีต่อ move ที่ Threads=12 / Hash=512 MiB
- rebaseline accepted และ candidate ภายใต้ workload isolation
- รายงาน allocation, depth, nodes, timeout overshoot และ backend จริง
- known root-split weakness ต้องถูกแยกจาก NNUE gain ไม่ตีความรวมแบบคลุมเครือ

ต้องไม่มี material external regression ที่ทำซ้ำได้ หาก gate ต่าง time control กลับทิศ
ให้คง candidate/inconclusive และวิเคราะห์ก่อน promote

## 15. Phase 10 — Production promotion และ rollback

1. reproduce candidate DLL/model จาก source/trainer manifests
2. backup accepted DLL/model พร้อม hashes
3. smoke CLI/server/GUI, first-request latency, forced move และ <=3-piece TB load
4. ทำเกมใหม่และยืนยัน provenance แสดง hashes/settings จริง
5. เปลี่ยน default แบบ reversible
6. รัน post-promotion isolated rebaseline
7. เก็บ previous accepted เป็น rollback target จนกว่ารุ่นถัดไปผ่าน

Promotion report ต้องมี tests, benchmarks, SPRT pentanomial/LLR/Elo CI,
external evidence, RAM/Threads/Hash และ rollback procedure

## 16. Phase 11 — Data/strength flywheel หลัง NNUE v1

- รักษา snapshots ของทุก accepted teacher
- เพิ่ม fresh games จาก promoted engine, independent opponents และ controlled exploration
- mine disagreement/uncertainty/horizon positions เฉพาะ train pool
- exact WDL ใช้คุม endgame calibration โดยไม่ให้ balanced artificial set ครอบงำ opening
- สร้าง fresh sealed test ต่อ major model generation
- เทียบ model size, data size, label depth หรือ loss ทีละแกน
- ทุก playing candidate กลับเข้ากระบวนการ correctness→benchmark→SPRT เดิม

## 17. Phase 12 — Search architecture หลัง NNUE

ทำเมื่อ profiling หลัง NNUE ชี้ว่า search ไม่ใช่ evaluator/data เป็นคอขวดหลัก

งาน credible ถัดไปต้องเป็น architecture ใหม่ ไม่ใช่ revive root scout ที่ reject:

- native one-thread path ต้อง exact-parity กับ authoritative search ก่อน
- shared structures ใช้ strict keys/bounds/mate-score conversion
- helper histories/stacks เป็น private และ main เป็นเจ้าของผลสุดท้าย
- helper influence ผ่านกลไกที่พิสูจน์ safety หรือถูกจัดเป็น strength-changing candidate
- timeout commits เฉพาะ complete main iteration
- วัด 1/2/4/8/12-thread scaling, total Hash, RAM, determinism distribution และ Elo

ห้ามนำ rejected private-root fail-low, root-alpha, leader-only Lazy-SMP,
fixed-window scout หรือ adaptive routing เดิมกลับมาโดยไม่มี mechanism ใหม่ที่แก้สาเหตุแพ้ gate

## 18. Phase 13 — External championship evidence

- สร้าง opening suite ที่ไม่เลือกจากเกมซึ่ง candidate ชนะ
- สลับสีและใช้กติกา/เวลาเดียวกัน
- เก็บ game JSON พร้อม engine/opponent identity และทุก search provenance ที่หาได้
- ทดสอบคู่แข่งอิสระหลายระดับ รวม เซียนเฒ่า เมื่อทำได้อย่างถูกเงื่อนไขของบริการ
- รายงาน W/D/L, paired result เมื่อจับคู่ได้, confidence interval และ adjudication
- ทำซ้ำหลัง production promotion บนเครื่องสะอาด

คำว่า world strongest ใช้ได้เมื่อ external evidence สนับสนุนอย่างเป็นธรรมเท่านั้น

## 19. งานที่พักไว้

- large DFPN / initial-position weak solution
- tablebase ใหญ่กว่า 6 ตัว
- proof-guided policy/value รุ่นใหม่

งานเหล่านี้มีคุณค่าเชิงความถูกต้อง/รับประกันไม่แพ้ แต่ไม่ใช่ current critical path
และใช้ RAM/disk สูง เริ่มใหม่ได้เมื่อผู้ใช้สั่งหรือหลักฐานหลัง NNUE ชี้ว่าคุ้มที่สุด

## 20. Definition of done ของแต่ละ experiment

ทุก experiment ต้องจบด้วย:

- hypothesis และ bottleneck evidence
- files/source/model/config hashes
- correctness gates และผลจริง
- deterministic fixed-depth/fixed-time deltas
- memory/Threads/Hash เมื่อเกี่ยวข้อง
- SPRT settings, pentanomial, LLR, Elo CI เมื่อ behavior เปลี่ยน
- verdict `PROMOTE`, `KEEP`, `REJECT`, หรือ `INCONCLUSIVE`
- revert/rollback state
- single highest-value next experiment

Goal ใหญ่ยังไม่ complete จนกว่าจะผ่านนิยาม world-strength ในข้อ 2.3; การจบ phase
หรือมี NNUE ที่เล่นได้เป็นเพียง milestone
