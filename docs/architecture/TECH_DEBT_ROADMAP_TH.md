# แผนลด Tech Debt และควบคุม Complexity

> สถานะ 2026-09-14: Phase 0–3 เสร็จแล้วผ่าน PR #7–#16
> เนื้อหาลำดับ refactor ด้านล่างเป็นแผนฐานและเกณฑ์ประวัติศาสตร์ ไม่ใช่คำสั่งเริ่มใหม่
> งานสานต่อและผลตรวจรับปัจจุบันอยู่ที่ [current-state](../../.agents/skills/thai-makhos-engine/references/current-state.md)

ฐานที่ตรวจ: `e975d6843ee23e9fe42a3662f5d802516293796e` · 2026-09-11

เป้าหมายคือแก้ปัญหาแล้วรู้ว่าต้องแตะจุดใด มีเจ้าของ state/resource ชัดเจน และทำซ้ำ
ผลทดลองเดิมได้ การลดจำนวนไฟล์หรือ LOC อย่างเดียวไม่ถือว่าบรรลุเป้าหมาย
เอกสารนี้เสนอ refactor ตามลำดับ; ยังไม่ได้เปลี่ยน playing code หรือเริ่มทดลอง SMP/NNUE

## 1. สิ่งที่พบจาก repo จริง

[Inventory พร้อม source SHA-256](tech_debt_inventory_20260911.json) นับจาก Git commit
มี 362 tracked files; ไม่สแกน ignored artifacts หรือ checkpoint บน Local

| จุดที่ตรวจ | ขนาด/หลักฐาน | ผลต่อการวางแผน |
|---|---|---|
| `work/` / `scratch/` | 66 / 47 tracked files | มีทั้งเครื่องมือที่ถูก import จริงและหลักฐาน ห้ามจัดเป็นขยะจากชื่อโฟลเดอร์ |
| `tools/verify_endgame_c1.py`, `tools/build_tb3.py` | import helper จาก `scratch/` | ต้องจัด dependency ก่อนย้ายไฟล์ |
| `work/endgame_worker.py` | import `_create_native_search` จาก server | factory เป็น contract ข้าม frontend แล้ว ควรมี owner ที่ชัด |
| `makhos/server.py` | 1,219 บรรทัด, 18 top-level functions | ย้ายตาม lifecycle/configuration boundaries ไม่ใช่รื้อเป็น server framework ใหม่ |
| `makhos/cli.py` / `makhos/native.py` | 2,255 / 1,928 บรรทัด | CLI handlers และ ctypes contracts ต้องอยู่ใน inventory ด้วย |
| `native/makhos_native.c` / `native/makhos_tb4.c` | 6,987 / 6,663 บรรทัด | native debt ไม่ได้มีไฟล์เดียว แต่ควรทำหลัง tooling/lifecycle นิ่ง |
| Build NNUE | scalar/incremental/AVX2/update/search มีขั้นตรวจ hash/build A–B/manifest ซ้ำ | รวม orchestration ก่อนเปลี่ยน native layout |
| NNUE sources | update → AVX2 → incremental → scalar เป็น include chain | มีการใช้โค้ดร่วมอยู่แล้ว ห้ามอ้างว่าเป็นเอนจิ้นอิสระห้าชุดแล้วลบทิ้ง |
| Ancestor-delta snapshots | control/candidate native sources อยู่ใน `work/` | เป็น frozen experiment evidence ไม่ใช่สำเนา production ที่ต้องแก้พร้อมกัน |
| Evidence ledger | 4,268 บรรทัด | ใช้ index ช่วยค้น และค่อย archive ตาม phase พร้อมรักษา anchors/links |
| `SKILL.md` กับ current-state | entrypoint ยังสั่งเริ่ม A รุ่นเก่า แต่ state ระบุหยุด | แก้แหล่งคำสั่งขัดกันเป็นงานแรก |

LOC เป็นตัวช่วยกำหนดขอบเขต ไม่ใช่การวัด cyclomatic complexity หรือคะแนน maintainability
จึงยังไม่อ้างว่าคะแนน 6.5 เพิ่มเป็น 8.5 จากการย้ายไฟล์

## 2. โครงสร้างปลายทางและขอบเขต

| ตำแหน่ง | ความรับผิดชอบ | เงื่อนไขการย้าย |
|---|---|---|
| `makhos/` | rules/search/evaluation/runtime และ adapters ที่ frontend ใช้ | playing path ไม่ import เครื่องมือทดลอง |
| `native/` | C17 implementation และ ABI headers | แยก module ทีละ boundary โดยไม่เปลี่ยน ABI/flags พร้อมกัน |
| `tools/build/` | shared build orchestration และ variant configuration | คำสั่ง `.ps1` เดิมเป็น wrapper; source/output identities เดิมยังตรวจได้ |
| `tools/verification/` | reusable attestation/manifest/validation helpers | ย้าย dependency cluster ที่ระบุแล้ว; helper workload ที่ runtime ใช้อยู่คงใน `makhos` |
| `tools/arena/` | process lifecycle/checkpoint operations | ไม่ย้ายหรือแก้เครื่องมือที่ active manifest ผูกอยู่ระหว่างรัน |
| `benchmarks/` | maintained benchmark runners และ regression positions | รักษาชื่อ runner เดิมเมื่อเป็น reproduction interface |
| `benchmarks/results/<experiment>/` | frozen evidence, manifests, logs, source-bound summaries | immutable หลังปิดชุดผล; แก้ errata ด้วยบันทึกเพิ่ม ไม่เขียนทับผล |
| `tests/` | regression tests ที่ discover/run ตาม runner ที่กำหนด | คง test IDs/จำนวนและ Node entrypoints ตลอด migration |
| `docs/architecture/`, `docs/research/` | contracts/current architecture และข้อสรุปจากการทดลอง | README เป็นทางเข้า; roadmap ปัจจุบันมีจุดเดียว |
| `docs/history/` | archived narrative หรือ index ไป snapshot เดิม | relocation เฉพาะเมื่อ link/anchor consumers ได้รับการจัดการแล้ว |
| `build/`, `saved_games/` | local outputs/runtime และเกมผู้ใช้ | ไม่ sweep-delete; ห้ามนำ user games/checkpoints ไปเป็น repo-cleanup target |

ยังไม่สร้าง folder เปล่าหรือ registry ทุกชนิดล่วงหน้า และไม่ย้ายทุกไฟล์ให้ตรงตารางใน PR เดียว
`work/`/`scratch/` เดิมคงไว้เป็น compatibility/evidence locations จนพิสูจน์ว่าถอนแต่ละรายการได้

### การเก็บหลักฐาน

เก็บถาวร: raw completed game/pair results, opening/seed/TC manifests, source/test/DLL/model
hashes, build flags/toolchain identity, full-suite logs, regression fixtures และข้อยกเว้นที่ผู้ใช้อนุมัติ
รวมถึง REJECT/INCONCLUSIVE และ frozen control/candidate snapshots เพื่อไม่ทดลองผิดซ้ำ

ไฟล์ TB/model/DLL ใหญ่เก็บตาม artifact manifest และตำแหน่งที่กู้คืนได้ ไม่ใส่ Git เพิ่มเพียงเพื่อ
ทำให้ checkout ดูครบ; metadata ต้องแยก `LOCAL_ONLY` จาก `AVAILABLE` และห้ามปลอม raw result
จากรายงานสรุป กรณี PR #6 ให้ Local archive runtime/full-suite/HTTP evidence พร้อม hashes
ก่อนใช้เป็น baseline ของ refactor ถัดไป โดยรักษาไฟล์ต้นฉบับไว้

ชั่วคราวที่พิจารณาเก็บกวาดได้: cache, object files และ intermediate output ที่สร้างซ้ำได้จริง
ต้องทราบ owner, producer, consumers และไม่มี binding/live process ก่อน ลบเฉพาะรายการที่ยืนยัน
ไม่ใช้ wildcard กวาด `work/`, `build/` หรือ `saved_games/`; files ที่ยังจำแนกไม่ได้อยู่สถานะ KEEP

## 3. ลำดับงานและเกณฑ์จบ

### Phase 0 — จัดแหล่งคำสั่งและตรึงฐาน

**ทำใน planning PR นี้:** inventory ที่ผูก merge commit, แก้ `SKILL.md` ให้ current-state
เป็นผู้ระบุงานปัจจุบัน, เพิ่มหลักป้องกัน complexity และย้าย current-state เก่าเป็น snapshot
แบบ byte-for-byte โดยไม่เปลี่ยนผลทดลองเดิม อัปเดตสถานะ PR #6/ข้อยกเว้นใน ledger

**ก่อน code refactor:** Local ตรึง runtime profile, source/test inventory, DLL/model/TB identities,
full-suite/HTTP logs และ commands ของ merge baseline ให้กู้คืนได้ ระบุ feature/profile matrix
ที่ใช้งานจริง: NNUE production, HCE rollback, reference, C4 on/off, forced/endgame/non-TB,
BEST/WIN, 1T/12T และ history/clock ไม่ตีความว่าทุก Cartesian combination รองรับโดยอัตโนมัติ

จบเมื่อทีมระบุได้ตรงกันว่าควรอ่านไฟล์ไหน, baseline ไหน, next task ไหน และ stopped experiments
ไม่ถูกเปิดขึ้นจาก stale prose เอกสารอย่างเดียวใช้ link/hash/frontmatter validation; ไม่รัน arena

### Phase 1 — จัด tooling และ evidence โดยไม่หัก reproduction interfaces

**1A: ทำ consumer map ก่อนย้าย (implementation PR แรกที่แนะนำ)**

- จำแนกทุก tracked item ใน `work/` และ `scratch/`: maintained tool, test, frozen evidence,
  staged snapshot หรือ unresolved พร้อม caller/import/command/manifest binding
- เริ่มตรวจ cluster `nnue_full_suite_attestation` และผู้เรียกใน `tools/`/`work/`;
  map transitive dependencies ก่อนเลือกว่าจะย้าย helper ใด จึงไม่ย้าย trainer ทั้งชุดตามชื่อไฟล์
- ผลลัพธ์เป็นตาราง migration ในแผน/เอกสารที่มีอยู่ก่อน ไม่สร้าง framework หรือ runner ใหม่เพื่อทำ inventory
- Acceptance: ไม่มี unresolved consumer ในกลุ่มที่จะย้าย; unresolved อื่นคง KEEP;
  ไม่มี production/runtime/experiment source mutation

**1B: ย้าย reusable tooling ทีละ cluster**

ให้ implementation มีบ้านเดียว และคง import/CLI wrappers ตำแหน่งเดิมซึ่งส่งต่อ arguments,
exit codes และ exceptions โดยไม่มี policy ซ้ำ ระวัง wrapper เปลี่ยน `__file__`/repo root,
cwd resolution หรือ source-hash inventory ย้าย tests จาก `work/` เฉพาะเมื่อทดสอบผ่าน runner
เดิมและ runner ใหม่ แล้วอธิบาย test-count/ID migration อย่างครบถ้วน

**1C: จัดทางเข้า evidence/docs**

เพิ่ม index ของ phase/mechanism/verdict/source/result pointer แทนคัดลอก report ลงหลาย roadmap
ledger เดิมยังค้นได้ก่อน archive ตามช่วงเวลา/phase; ไม่ย้าย link-bound raw evidence เพื่อความสวย
README และ development plan ชี้ไป canonical documents ส่วนไฟล์เก่าเป็น stub เฉพาะเมื่อ
ไม่ใช่ immutable evidence และ consumer map ยืนยันแล้ว

จบ Phase 1 เมื่อ tool ที่ย้ายมี implementation เดียว, old commands/imports ผ่าน, ชุดที่ discover
ไม่หาย และทุกผลทดลองสำคัญย้อนถึง source/artifact identities ได้

### Phase 2 — ลด policy ซ้ำใน build และ lifecycle

**2A: รวม build orchestration ก่อน (สอง PR ย่อย)**

1. เพิ่ม shared build function และ explicit variant config จากค่าที่มีจริง: translation unit,
   flags, output filename, model/contract requirements และ manifest schema ของแต่ละ variant
2. เปลี่ยน root `.ps1` เดิมเป็น thin wrappers ทีละกลุ่ม; C1/C2/C3/C4 ตามหลังเมื่อมี coverage

คง compiler/version, `-O2`/`-O3`, `-march`, linker options, DLL exports, output paths,
refusal-to-overwrite และ error exit codes เดิม ไม่มี LTO/AVX target tuning ใน PR นี้
Build A/B reproducibility ภายใน variant ต้องผ่าน; เทียบ old-command/new-wrapper บน Windows
ด้วย input/path/compiler เดียวกัน ถ้า DLL hash ต่างให้ตรวจสาเหตุและแยกการเปลี่ยน build semantics
ออกก่อนรับ อย่าแก้ frozen expected hash เพียงให้เทสต์ผ่าน หรือ merge schema หลายรุ่นแบบทำข้อมูลหาย

**2B: แยก server ตาม owner (สองถึงสาม PR ย่อย)**

- เริ่ม extraction ของ configuration/provenance และ factory ที่ worker ใช้ โดยรักษา
  `makhos.server` import path, `run_server()` และ `_create_native_search` compatibility entrypoint
- จากนั้นให้ `makhos/engine_manager.py` เป็นเจ้าของ Engine, search lock, native sessions,
  TB handles และ clear/close lifecycle เพียงจุดเดียว `server.py` เป็น HTTP adapter/facade
- Request history/clock เป็นของ request; immutable mapped TB/model เป็นของ process/profile;
  cancellation กับ new-game generation คง contract เดิม ไม่เพิ่ม event loop/thread pool ใหม่
- Wrappers ต้อง delegate จริง ไม่คง global state ชุดเก่าและ manager state ชุดใหม่ที่ต้อง sync กัน
  ตรวจ mock/monkeypatch consumers ใน tests และ `work/endgame_worker.py` โดยเฉพาะ

Acceptance: cold/warm readiness, concurrent requests, cancellation, rematch,
config switching, forced bypass, close-on-error และ HCE rollback ผ่าน พร้อม provenance/JSON เดิม
ทดสอบสร้าง–ปิดซ้ำแล้ว handle/session counts ไม่เพิ่มค้าง; RAM วัดบนเครื่องเดิมขณะ idle
ถ้า extraction พบ bug ใหม่ ให้แยก regression + fix PR จาก pure extraction

**2C: CLI handlers หลัง factory boundary นิ่ง**

ย้าย handlers ที่มี caller map ชัดออกจาก `makhos/cli.py` ทีละกลุ่ม คง parser, help/defaults,
module entrypoint, flags, exit codes และ arena checkpoint semantics เดิม ไม่สร้าง plugin registry
สำหรับ CLI โดยไม่มีความจำเป็นจริง

### Phase 3 — Native modularization และ NNUE surface

เริ่มเมื่อ Phase 1/2 รับรองแล้ว และมี baseline native parity/performance ที่ทำซ้ำได้
เลือก leaf responsibility จาก include/call graph เช่น formatting/provenance หรือ TB reader
boundary ก่อนย้าย search/movegen ไม่กำหนดว่าจะต้องแตกเป็นจำนวนไฟล์ตายตัว

1. ทำ dependency/ABI map รวม `makhos_native.c`, `makhos_tb4.c`, C4 translation unit และ
   NNUE include chain แยก reusable implementation, differential oracle และ frozen snapshot
2. Extract ทีละ responsibility พร้อมคง linkage, struct layout, symbol visibility, compile flags,
   initialization order และ hot-path inlining ที่จำเป็น ยังไม่เปลี่ยน scheduler/TT ownership
3. จัด NNUE interface/backend/update selection จาก ABI ที่ใช้อยู่จริง ลด public combinations
   ที่ต้องดูแล แต่เก็บ scalar/full-refresh oracle อิสระไว้ตรวจ AVX2/incremental
4. ตัด legacy wrappers/variants เฉพาะเมื่อ consumer/reproduction map แสดงว่ามีทางแทนครบ
   พร้อม deprecation record; frozen experiments ไม่ถูก rewrite ให้ใช้ implementation ใหม่

ห้ามรวม SMP ใหม่, ancestor delta, pruning/history tuning, NNUE model ใหม่ หรือ LTO กับ phase นี้
หากการแยก translation units เปลี่ยน search results หรือ fixed-time depth ให้หยุดอ้าง behavior-preserving
และใช้ strength gate ใหม่ตาม skill ข้อยกเว้น PR #6 ไม่ครอบคลุมงานนี้

## 4. Verification ที่ตรงกับความเสี่ยง

| การเปลี่ยน | หลักฐานที่ต้องมี |
|---|---|
| Docs/skill/index | links, schema/frontmatter, snapshot hashes และ scope review; ไม่ใช้ full engine suite กับข้อความอย่างเดียว |
| Tool/import/CLI migration | old/new commands, outputs/errors/defaults, cwd/path/hash resolution และ full discovered suite ขณะ idle |
| Build consolidation | Windows toolchain-bound A/B builds, old/new variant identities, manifest compatibility, DLL exports และ full suite |
| Server/lifecycle extraction | full suite + Node lifecycle + source-bound HTTP smoke, concurrency/clear/close/resource checks และ deterministic search regression |
| Native boundary/move-state extraction | ABI + applicable perft ถึง depth 10 และ randomized Python/native rule differential, TB probes, NNUE goldens และ full suite |
| Search-preserving claim | fixed-depth 1T move/score/nodes/PV/bounds ตรงกับ frozen control; C4 completed-layer parity ใน config ที่สัญญา determinism |
| Scheduling/search/eval/time behavior เปลี่ยน | แยกเป็น strength candidate; paired pentanomial gate ตาม skill ก่อน promotion หรือข้อยกเว้นที่ผู้ใช้ระบุเฉพาะงาน |

Timed SMP results ไม่ควรถูกเรียกรวมว่า bit-exact โดยไม่พิสูจน์สัญญาของ config นั้น
ทุก code phase ต้องรันจำนวน tests ที่ discover ปัจจุบัน ไม่ยึด 513 เป็นเลขถาวร และไม่ปิด
failures/skips เพื่อรักษาตัวเลขสวย รัน batch/benchmark ขณะ GUI/arena ว่างเท่านั้น

## 5. วิธีระวัง Complexity หลังจากนี้

สำหรับ PR ที่เพิ่ม/แยกโครงสร้าง ให้ reviewer เห็นสั้น ๆ ว่าอะไรเพิ่มหรือลด:

| สิ่งที่เปลี่ยน | คำถามที่ต้องตอบ |
|---|---|
| Supported profiles/flags | เพิ่ม combinations ใด ใครใช้จริง และ config ที่ไม่รองรับถูกปฏิเสธที่ไหน |
| Mutable owners | ใครสร้าง/ใช้/cancel/clear/close resource มี state ซ้ำที่ต้อง sync หรือไม่ |
| Dependencies | เพิ่ม import/include edge ใด ทำให้ playing code พึ่ง experiment tooling หรือเกิด cycle หรือไม่ |
| Entry points/duplicates | implementation กลางอยู่ไหน wrapper ส่งต่อจริงหรือยังมี policy สองชุด |
| Compatibility/deprecation | ผู้ใช้หรือ manifest ใดพึ่งของเก่า เงื่อนไขถอนคืออะไร |

ไม่ตั้ง quota แบบ “ห้ามไฟล์เกิน N บรรทัด” หรือ “ต้องลดไฟล์ทุก PR” เพราะจะกระตุ้นให้แยก
ไฟล์โดยไม่ลด coupling หลีกเลี่ยง abstraction ที่ไม่มี consumer และ refactor ที่ต้องเพิ่ม fallback
หลายชั้นเพื่อพยุง API ใหม่ ถ้า scope โตเป็นหลายแนวคิด ให้แยก PR ก่อนขยายต่อ

วัดผลเป็นราย phase: policy ที่มี implementation เดียว, old-command parity, จำนวน profile
ที่มี owner/test ชัด, dependency cycles ใหม่เป็นศูนย์ และเวลาตามหาจุดแก้จากกรณีจริง
ใช้ routine review ของ PR ไม่เพิ่มอนุมัติหลายชั้นหรือสร้าง report/skill ใหม่ทุกครั้ง

## 6. สิ่งที่ทำแล้วและ handoff

PR #6 merged เป็น correctness fix ตามข้อยกเว้นจากผู้ใช้: Windows Local รายงาน 513/513,
Node 16/16, real-TB transition/HTTP smoke PASS; ไม่อ้าง paired strength/Elo PASS
แผนและ skill update นี้เป็นเอกสารเท่านั้น จึงตรวจ docs/frontmatter/hash แทนรัน engine suite ซ้ำ

งาน implementation ถัดไปที่แนะนำมีเพียง **Phase 1A: consumer/evidence map ของ work/scratch**
ก่อนเลือก helper cluster แรก ห้ามเปิด native refactor หรือ SPRT พร้อมกันเพื่อให้ทุก diff
ยังตรวจสาเหตุและ rollback ได้ ส่วน 27/539-pair checkpoints และ 12T production defaults คงเดิม
