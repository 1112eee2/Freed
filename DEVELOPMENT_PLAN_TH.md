# คู่มือพัฒนา: จบ NNUE v1 → แก้ความคุ้มค่าของ Threads → เพิ่ม Elo ต่อเนื่อง

## งานปัจจุบัน 2026-09-14: ปิด Readiness P0 ก่อนพิสูจน์ Lazy SMP

สถานะและ next action มีจุดเดียวที่
[current-state.md](.agents/skills/thai-makhos-engine/references/current-state.md)
โครงสร้าง Tech-Debt Phase 0–3 เสร็จแล้ว ไม่เริ่ม refactor ชุดเดิมซ้ำ

1. **P0 — หลักฐานและทางเข้าพัฒนา:** แยก tooling/docs จาก native/SMP WIP,
   ครอบคลุม source inventory ของเครื่องมือที่ย้ายแล้ว, CI, Node tests และ runtime
   entrypoints; ผ่าน focused/reference/full checks โดยรักษา workload lease
2. **G0–G3 — ฐานและความถูกต้อง:** ตรึง control/candidate จากซอร์สเดียวกันและ DLL/model
   hashes, ทดสอบ 1T parity, publication/history isolation และ lifecycle
3. **G4 — ความคุ้มค่า:** held-out positions, 1/2/4/6/8/12T, 1s/2s, cold/warm,
   repeats, hints ON/OFF ที่งบหน่วยความจำเท่ากัน และเทียบ root-split control
4. **G5–G6 — ความแข็งแกร่งและ production:** paired SPRT ชุดใหม่ตามเกณฑ์ที่ตรึงล่วงหน้า
   แล้วจึง full suite, GUI NNUE/HCE/TB smoke และ rollback; INCONCLUSIVE ไม่ promote

ใช้ [Lazy SMP ฉบับหลัก](docs/architecture/NATIVE_SHARED_TT_LAZY_SMP_DESIGN_TH.md)
สำหรับรายละเอียด gates: แชร์เฉพาะ move hints, ไม่แชร์ score cutoff, thread หลัก
เป็นผู้ตัดสิน คง C4 endgame/root policy และ production เดิมจนผ่านเกณฑ์
ไม่ resume Experiment A ที่หยุดไว้ และไม่เปลี่ยน NNUE model พร้อมกับ SMP

หลังปิดการทดลองนี้ ใช้เกมจากมนุษย์สร้าง benchmark ที่เก็บ full history/clock
แยกชุดวิเคราะห์ออกจากชุดตรวจรับ แล้วใช้ผล error analysis เลือกงาน search/data ถัดไป

## Gate matrix Native Lazy SMP (ตรวจสด 2026-09-16)

ข้อกำหนด gate ฉบับเต็มอยู่ที่
[NATIVE_SHARED_TT_LAZY_SMP_DESIGN_TH.md §7](docs/architecture/NATIVE_SHARED_TT_LAZY_SMP_DESIGN_TH.md)
ตารางนี้ระบุว่ามีหลักฐานอะไรแล้ว ช่องว่างจริงคืออะไร และเงื่อนไขผ่านคืออะไร
ตัวเลข/identity ทั้งหมดวัดสดในรอบนี้ ไม่ได้คัดลอกจากข้อความเก่า

**ฐานที่ตรึงไว้ (r3-terminal-root):**
candidate `0BFA505D67B52CE899F01639ED57E9A651D19E6FD85CB54CE3C2B67057B05E6B`
control `8BAF2F31E4C0311030568014DE9F8F0FFA84C475C73D0A3C8D259A41D5706BED`
compiler clang 22.1.6 `F168B58C…C07239A` · model `07B9AB0F…C0914164C`
invariants `77528add…` / `03152e51…` / `FEEDD39C…` (ตรวจตรงทั้งสาม)
production NNUE profile `build/nnue_search_v1_r5/…` `32c32302…` **ไม่ถูกแทนที่**

| Gate | เงื่อนไขผ่าน | หลักฐานที่มี (path + identity) | Verdict | ช่องว่าง / งานที่เหลือ |
|---|---|---|---|---|
| **G0 Freeze** | profile ต้นฉบับ + ตรึง strict-key control, compiler/model/config/corpus SHA, protocol, tolerance ก่อนเปิด candidate | `r3/contract.json` (19 source SHA + invariants + NOT_PROMOTED); `r3/{candidate,control}/build_manifest.json` (verdict PASS, reproducible ×2, byte_identical); model + quantization contract SHA; `config/gui_release.json` → `releases/nnue-v1-20260908/manifest.json` `8A8F15B0…` | **PARTIAL** | ตรวจสด: **18/18 engine source ตรง worktree เป๊ะ**; ต่างเฉพาะ `tests/test_native_lazy_smp.py` (`55db36f6`→`874e6fae`) และเป็นการ**เพิ่มเทสเท่านั้น** ไม่มี engine change → r3 DLL ยังเป็น same-source build ที่ใช้ได้ **corpus SHA + คำประกาศ tolerance ไม่มีในบันทึก G0** โดย `contract.json` เองระบุ `later_gates` ให้ไปตรึงตอน workload freeze (G4/G5) — ไม่ต้อง freeze ใหม่ที่ G0 |
| **G1 1T parity** | ไม่ปลุก helpers; move/score/PV/nodes/depth ตรง same-source strict 1T ที่ fixed depth + history/TT เดียวกัน | `tests/test_native_lazy_smp.py::test_gate_g1_comprehensive_parity_against_strict_control_binary` — threads=1, depth=6, hash_power 23 ทั้งสองฝั่ง, 7 เคส (initial/tactical/middlegame/multi_capture/promotion/clock_79/repetition_history) assert move+score+nodes+pv+depth ตรง, warm-TT parity, clock-80 terminal rejection parity | **CLOSED (parity)** | เงื่อนไข "วัด overhead แยก" ยังไม่มีตัวเลข → ยกไปวัดรวมใน G4 ไม่ต้องสร้าง gate ใหม่ |
| **G2 TT correctness** | key aliases, forced multi-writer interleavings, partial publication, writer paused, ABA/generation, clear/resize; race detector + Windows target tests; ปิด score-admissibility P0 | `build/lazy_smp_acceptance_20260915_g2/protocol_result.json` (normal+ASan PASS, `race_detector: NOT_RUN`); `build/lazy_smp_race_portable_20260916/` probe `67f8b7cf…`, zip `5b090c64…`, `windows_smoke.json` 1,200,000 ops PASS | **PARTIAL** | **ASan ไม่ใช่ race detector** TSan ยัง NOT_RUN — bundle ส่ง Astra Web แล้วและ**ตรวจสดว่ายัง byte-current** กับ worktree+r3 (source 3 ไฟล์ตรงเป๊ะ) รอผล Linux: negative control + sanitized probe 5 runs + logs/exit codes, ไม่มี suppressions ปิดได้เฉพาะ publication race-detector scope |
| **G3 Search/lifecycle** | legal moves/PV, independent low-depth oracle, history H1→H2→H1/long cycles, clock 79/80, multi-capture/promotion, terminal/proof precedence, timeout/cancel/restart, **repeated games**, allocation failure, **leaked handles/memory** | 22 เทสใน `tests/test_native_lazy_smp.py` + 2 เทส wiring · full suite `build/deepseek_handoff_full_003/result.json` **618/618 Python + 16/16 Node PASS** · **และ behavioural audit `build/lazy_smp_r4_integration_audit_20260916/audit.json` (A1–A6)** | **CLOSED (native) + integration ยืนยันด้วยพฤติกรรม** | ยืนยันด้วยการรันจริง ไม่ใช่จำนวนเทส: **default-off** คืน production backend เดิม · **C4 admission** exact endgame ไป `python`/tablebase path ไม่ใช้ lazy · **terminal precedence** ถูกปฏิเสธก่อนถึง backend (`ValueError: cannot search a terminal position`) · **cancellation** engine ใช้ `clear()` ไม่เคยเรียก `stop()` (grep ยืนยัน) · **fallback** DLL ที่ไม่มี Lazy SMP → degrade อย่างปลอดภัยพร้อม `last_native_error` ⚠️ **ช่องว่างที่ยังไม่ครอบ:** C4 exact-outcome agreement ใต้ lazy backend (TB3 ไม่พร้อมใน process ทดสอบ) และ GUI HTTP smoke/perft อยู่ใน G6 |
| **G4 Runtime/scaling** | held-out diverse suite 1/2/4/**6**/8/12T, 1s/2s, repeats, cold/warm, BelowNormal/isolation; main depth, nodes, CPU, TT contribution, memory, deadline/stop latency | `build/lazy_smp_scaling_20260916_g4_003/result.json` (798 cells) · `..._g4_007_interleaved/` (12T 5 repeats) · `..._g4_008_hints_control/` (**freeze.json + result.json, 352 cells, 0 errors** — negative control) · `..._g4_002_hash{512,256}/` · `..._g4_004_f8/`, `..._g4_006_worker0/` · **corrections: `build/lazy_smp_g4_corrections_20260916/corrections.json` (C1–C8)** | **MEASURED (ผลลบ แต่แคบกว่าที่เคยรายงาน)** | ✅ **ทนต่อ noise:** stop latency 0.176–0.270 ms · overshoot median 0.5–0.8 ms · pv_legal 792/792 · ทั้งสอง backend อยู่ในงบ Hash · aggregate scaling **5.96x vs root-split 1.35x** · worker 0 nodes ลดตาม ~1/T (1T 2,894,848 → 12T 1,067,286 เกิน noise ±14% มาก) · **paired 12T vs root-split: median −1 ply, ตื้นกว่า 37/55 คู่, เท่า 11, ลึกกว่า 7** และ **calibrated แล้ว** เทียบกับ noise floor ที่วัดจริง (`..._g4_010_depth_noise_control/` — ใช้ DLL เดียวกันทั้งสอง role, 110 cells: noise median 0.00, range [−1,+1], เท่า 47/55) ขณะที่ real มีเท่าแค่ 11/55 และหางลบถึง −4 ply · worker-0 node diff **ลบทั้ง 55/55 คู่** (median −2.9M เทียบ noise ที่ ±ล้าน) → **ส่วนต่างนี้อยู่เหนือ noise floor จริง** · **ไม่มี thread count ใดที่ candidate ชนะ root-split** ❌ **ถอนแล้ว (C1):** "hints เป็นลบทุก thread count" — **negative control ที่ 1T พิสูจน์ว่า hints ON/OFF เหมือนกันทุกไบต์** (1T bypass: `shared_hint_table=NULL`, env var ไม่อ่าน) และที่ 12T fixed depth **score/PV เหมือนกัน 12/12 โดย hints ใช้ nodes เท่าหรือน้อยกว่า** → hints ช่วย ordering ไม่ทำลายผลลัพธ์ ⚠️ **แคบลง (C2):** "พิสูจน์ว่าเพิ่ม depth ไม่ได้" ใช้ได้เฉพาะ candidate/config/corpus/runtime ชุดนี้ ไม่ใช่ข้อสรุปสากล ⚠️ **สถานะจริง (C5/C6):** overshoot 328.92 ms และ "worker-0 collapse" = **NOT REPRODUCED / CAUSE UNKNOWN** ไม่ใช่ "พิสูจน์ว่า environmental" และไม่ใช่ defect ⚠️ ข้อจำกัด: node share ≠ CPU share · correlation ≠ causation · 11 positions เครื่องเดียว |
| **G5 Strength** | fresh paired color-swapped pentanomial; intrinsic 1T ตามโครงการ แล้ว 12T production 1s/2s แยก seed/output; ตรึง H0/H1/alpha/beta/cap ก่อน launch | ยังไม่มี (ไม่ resume Experiment A) | **NOT_RUN** | **ยังไม่ launch และไม่ใช่ "พิธีการ"** — G4 ให้ข้อสังเกตด้านประสิทธิภาพ (node/depth) ซึ่ง**ไม่ใช่ strength** จึงยังไม่มีข้อสรุป Elo ใด ๆ การจะเดินหน้า G5 ต้องผ่าน prerequisite ที่เกี่ยวข้องก่อน (รวม race-detector gate) และต้อง freeze protocol/seeds/H0/H1/alpha/beta/cap ล่วงหน้า · ถ้าผู้ใช้อนุมัติให้ยุติ candidate รุ่นนี้ด้วยหลักฐาน G4 ต้องบันทึก G5/G6 เป็น NOT_RUN พร้อมเหตุผล ไม่ใช่เปลี่ยนเป็น PASS |
| **G6 Production** | full current suite, perft/differential เมื่อ native state เปลี่ยน, NNUE parity, TB4–6, NNUE/HCE GUI smoke/rollback | ยังไม่มี | **NOT_STARTED** | ต้องรอ G5; ยังไม่มีการแทนที่ production DLL/profile ใด ๆ |

**สถานะรวม: NOT_PROMOTED** — G3 ปิด (native) + integration ยืนยันด้วยพฤติกรรม, G4 วัดครบด้วยผลลบที่แคบกว่าที่เคยรายงาน, G0/G1/G2 ยัง PARTIAL
ผล 618/618 เป็น**ผลทดสอบ ไม่ใช่ promotion attestation และไม่ใช่ผล SPRT**
**ยังไม่มี gate ใดที่ให้สิทธิ์ promote** และ**ยังไม่มีข้อสรุป Elo ใด ๆ**
ข้อสรุป G4 ใช้ได้เฉพาะ candidate/config/corpus/runtime ชุดนี้ · **ห้ามใช้ผลลบนี้เป็นเหตุเปิด shared-score cutoff หรือ redesign กลไกเอง**

## รอบ 1 (2026-09-16): Diagnostic — วัดว่า production ใช้แรงตรงไหน แล้วจัดลำดับ avenue

**ขอบเขตที่ประกาศก่อนรัน:** profile production เท่านั้น ไม่มี candidate ไม่เปลี่ยนพฤติกรรม ไม่ promote
**เกณฑ์ตัดสิน:** avenue จะ "มี headroom" ต่อเมื่อ **precondition ที่แผน §4 ระบุไว้ ถูกวัดและผ่าน** · avenue ที่วัดไม่ได้ให้บันทึกเป็น BLOCKED ON INSTRUMENTATION ห้ามเดา · **node count ไม่ใช่เวลา**

**สิ่งที่ต้องยืนยันก่อน (ทำแล้ว):** ไม่มี process งานหนักค้าง · GUI ไม่ได้ assert priority · **toolchain deterministic** (build ที่ชื่อ output เดิมซ้ำ → byte-identical)

**ข้อค้นพบด้านสถานะ (สำคัญ):** worktree native source **ไม่ใช่** source ที่ build production (`.text` 155648 vs 158720, `.pdata/.rdata/.reloc` ต่างกัน) **แต่ให้พฤติกรรมเหมือนกันเป๊ะ** บน default path — 1T fixed-depth parity 33/33 (11 ตำแหน่ง × depth 6/8/10) move/score/nodes/depth/PV ตรงทั้งหมด → โค้ดที่เกินมาเป็น inert จนกว่าจะเปิด opt-in · worktree ยังมี native delta ที่ยังไม่ commit (539+/163−) ซึ่ง**ไม่ revert ในรอบนี้** และการมี **baseline ที่นิยามชัด** เป็น prerequisite ของงาน candidate

**Instrumentation:** `makhos_search_nnue_telemetry` ใช้ได้ทุก DLL · **`makhos_search_telemetry` ถูก compile ออกทุก DLL** → รอบนี้สร้าง **diagnostic build** `-DMAKHOS_SEARCH_TELEMETRY=1` (`build/round1_profile_20260916/telemetry/`, sha `56753BFD…`) และ **พิสูจน์ว่าไม่รบกวนพฤติกรรม** (parity 33/33 กับ production) → ใช้ profile พฤติกรรม production ได้ · มี **ablation defines** ครบ (`MAKHOS_NULL_MOVE`, `MAKHOS_LMR_SECOND_REDUCTION`, `MAKHOS_EARLY_TT_CUTOFF`, `MAKHOS_PRECOMPUTED_ORDERING`) → วัด time attribution ได้โดยไม่แก้ source

**ผลวัด (1T, production behavior):**

| metric | depth 10 | 1000 ms |
|---|---|---|
| qsearch share ของ nodes | **64.7%** | **51.4%** |
| ordering efficiency (cutoff ตั้งแต่ตาแรก) | 86.9% | **89.1%** |
| avg cutoff index | 0.27 | 0.24 |
| TT hit rate | 48.4% | 66.5% |
| null cutoff rate | 44.8% | 61.1% |
| LMR / PVS researches ต่อ node | 0.0025 / 0.031 | 0.0031 / 0.023 |
| **refreshes ต่อ evaluation (NNUE)** | **0.022%** | **0.0002%** |
| overshoot | — | 0.049% (1T) / 0.151% (12T) |
| NPS | 1.26M | 1.53M (12T: 2.40M = **1.57x**) |

**จัดลำดับ avenue (ใช้เกณฑ์ที่ประกาศไว้):**

| ลำดับ | avenue | precondition | ผล | สรุป |
|---|---|---|---|---|
| **1** | งานค้นหาสิ้นเปลือง (movegen/qsearch ซ้ำ) | มี hotspot | qsearch 51–65% ของ nodes, q_beta_cutoffs เพียง 18–20% ของ qnodes | **CANDIDATE — บล็อกใหญ่สุดที่วัดได้ (แต่ยังไม่ใช่เวลาจนกว่าจะทำ ablation)** |
| 2 | NNUE cost (`ancestor delta`) | profile ยืนยันว่าต้นทุนสำคัญ | refresh 0.0002–0.022% ของ evaluation | **ไม่ผ่าน precondition → ตัดออกจากคิว** |
| 3 | single-thread search quality (move ordering) | ตำแหน่งหลากหลายชี้ว่าค้นผิดทิศ | ordering efficiency 86.9–89.1% | **ไม่ผ่าน precondition (ordering อิ่มตัวแล้ว)** · history/horizon ยังไม่ได้วัด |
| 4 | time management | มีเวลาสูญเปล่า/ถอยเมื่อ deadline | overshoot 0.049–0.151% ของงบ | **ไม่ผ่าน precondition → ลดความสำคัญ** |
| 5 | NNUE รุ่นถัดไป | error analysis + learning curve | ยังไม่ทำ | **workstream แยก** ต้องมี data + sealed split |

**แก้ข้อผิดพลาดการวัดของตัวเอง 2 จุด (บันทึกใน `round1.json`):** (R1-C1) ตัวเลข NNUE ที่ 12T **ถอน** — counter reset ต่อ search call และ root-split เรียก search ต่อ root move → อ่านได้แค่ subtree สุดท้าย · (R1-C2) qsearch share เดิม 34–39% **แก้เป็น 51–64.7%** เพราะ `qnodes` ถูกนับที่เดียวกับ `nodes` (บรรทัด 3962-3963)

**รอบ 2 ที่เสนอ:** ablation-based time attribution สำหรับบล็อก qsearch/movegen (ใช้ define ล้วน ไม่แก้ source) พร้อมเกณฑ์ที่ประกาศล่วงหน้า: feature ใดที่ถอดออกแล้ว NPS เพิ่มเกิน noise floor = บล็อกต้นทุนจริงที่ควรปรับ · feature ใดที่ถอดออกแล้ว nodes เพิ่มมากกว่า NPS = เป็นบวกสุทธิ ต้องเก็บไว้ · **ผล ablation ทุกรายการเป็น diagnostic ห้ามอ้างเป็น strength และห้าม promote**

**สถานะรอบนี้: NOT_PROMOTED · ไม่มี strength claim ใด ๆ · ไม่มีการเปลี่ยน production** · หลักฐาน: `build/round1_profile_20260916/round1.json`

## ประวัติ 2026-09-11: ลด Tech Debt ก่อนเพิ่ม Complexity

PR #6 merged เป็น `e975d68` หลังผู้ใช้อนุมัติ correctness-only exception เฉพาะงานนี้
Windows Local รายงาน full suite 513/513, Node 16/16, real-TB4–TB6 transition และ
NNUE/HCE HTTP smoke PASS ไม่อ้างว่า Elo เพิ่ม และไม่ใช้ข้อยกเว้นนี้กับงานอื่น

ใช้ [Tech-debt roadmap](docs/architecture/TECH_DEBT_ROADMAP_TH.md) เป็นแผนรายละเอียดจุดเดียว:

1. Phase 0: inventory/แหล่งคำสั่ง/skill complexity guard — เสร็จสมบูรณ์ (PR #7)
2. Phase 1: consumer/evidence map, ย้าย tooling และจัดทำสารบัญหลัก — เสร็จสมบูรณ์ (PR #8-#12)
   - สารบัญประวัติและหลักฐานการทดลอง: [ดัชนีหลักฐานการทดลอง](docs/architecture/EXPERIMENT_EVIDENCE_INDEX_TH.md)
3. Phase 2: shared build orchestration → server lifecycle owner → CLI handler boundaries — เสร็จสมบูรณ์ (PR #13–#15)
4. Phase 3: native/NNUE leaf modularization — เสร็จสมบูรณ์ (PR #16)

รายงานสถานะปัจจุบันอยู่ที่ [.agents/skills/.../references/current-state.md](.agents/skills/thai-makhos-engine/references/current-state.md); เนื้อหาด้านล่างเป็นประวัติการพัฒนา

## ประวัติ 2026-09-11: ปิดรอยต่อ multi-capture เข้า TB6 ก่อน SMP

ผู้ใช้ยุติ Experiment A C4 1000ms ที่ 539 คู่: **INCONCLUSIVE**, คง 12T;
2000ms deferred และ 27 คู่เดิมเก็บเป็นประวัติศาสตร์ ห้ามใช้ข้อความ launch ด้านล่าง
หรือในเอกสารรุ่นเก่าเป็นคำสั่ง resume

Candidate `codex/endgame-transition-coverage` ขยาย admission จาก 7→6 เป็นทุก legal
multi-capture เข้า <=6 และใช้ predicate ร่วมกันใน server/native adapter
ยังค้นทุก root alternative และใช้ WDL/root policy เดิม Native/rules/model ไม่เปลี่ยน
Linux: เทสต์ใหม่ 9 PASS/1 SKIP (ไม่มี TB4–6 จริง), Node 16/16; full discovery
513 พบ/470 run, 8 failures/19 errors/104 skips เทียบฐาน 503 พบ/460 run,
failure/error IDs เดียวกัน ไม่มี regression ID ใหม่ แต่ **ไม่ใช่ full-suite PASS**
Runtime TB3-only 32 observations: overshoot p95 2.93 ms/max 3.07 ms; ไม่มี Elo claim
ขั้นถัดไป: Windows full-suite + real TB6/HTTP smoke ก่อน merge/promote
รายละเอียด: [Transition acceptance](docs/architecture/ENDGAME_TRANSITION_COVERAGE_TH.md)

ข้อความสถานะก่อนหน้านี้ด้านล่างเป็นหลักฐานประวัติศาสตร์

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


## 2026-09-09/10 — Phase 1C C1 Part 2: compact native TB4–TB6 reader

KEEP experimental/default-off; implementation ready for Windows acceptance,
not C2/search integration or production promotion. Base `135aafb`. Added
read-only Windows/POSIX mappings, exact typed completion ranking, canonical
25/44/70-signature metadata checks, threshold WDL decoding, immutable worker
references and a unified TB3–6 ctypes interface. No allocation/decompression
per probe. Optional checksum/SHA/provenance checks use the actual mapping.

Linux C1 regression: 20/20 tests pass in full discovery; 48,600 TB3 probes and
360,288 TB4–6 probes match Python (139 signatures, both turns, all 81 clocks).
Ranked fixtures are sparse synthetic layouts, not solved TB evidence. ASan/UBSan
passes 100,000 probes, zero probe allocations, balanced allocation/free counts;
LeakSanitizer is unavailable in this container. Full discovery: 474 found, 431
run, 8 failures, 18 errors, 64 skips. Unchanged `135aafb`: 461 found, 418 run,
same failure/error IDs and skip reasons. This is NOT a Windows full-suite PASS.
Source/test inventories unchanged and protected-data opens zero in both runs.

Existing provenance manifest has a historical generator-source mismatch and
lacks compact TB4 binding; strict verification remains fail-closed. Local must
resolve the original provenance chain, never rewrite hashes merely to pass.
Rules/core, production DLL/model/pointer and paused 27-pair experiment preserved.
Evidence: `benchmarks/results/endgame_c1_ranked/summary.json`. Windows commands
and architecture: `docs/architecture/ENDGAME_NATIVE_C1_TB456_TH.md`. Next: isolated
Windows build, complete suite and real TB4–6 parity/provenance before C2.


## 2026-09-10 — Phase 1C C2: native 1T reference search

KEEP experimental/default-off. Added a WDL-carrying native Negamax/PVS and
quiescence session reusing unchanged native moves/HCE/repetition machinery.
No scalar TT read/write, selective pruning, NNUE or GUI routing changes.
Reference configuration matches Engine.search per-root score/WDL/PV and
BEST/WIN choice at depth 1/2/4/6; repetition fixture at 1/2/3/8; all 139 ranked
signatures covered at clock 79/depth 2 with both turns and repetition None/3.
Cancellation publishes only complete layers; error and max-ply boundary gates
pass. Windows full suite 485/485 PASS, zero skips/failures/errors, 163.304 s;
source/test inventories unchanged, protected opens zero, invariant hashes intact.
Evidence: `benchmarks/results/endgame_c2/summary.json` and
`docs/architecture/ENDGAME_NATIVE_C2_TH.md`. No latency/Elo promotion claim.
Next: C2 review and fixed-depth/fixed-time cost measurements before C3
routing; production NNUE and root split require separate gates.
