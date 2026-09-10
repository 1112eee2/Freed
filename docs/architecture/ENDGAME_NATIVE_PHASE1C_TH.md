# Phase 1C — Native Endgame Search Integration

สถานะ: DESIGN READY; ยังไม่เปลี่ยน playing path หรือรับรอง candidate.
ฐาน source ที่ตรวจ: `1e121d8` บน main; branch `codex/endgame-latency-phase1c`.
ใช้กติกาและลำดับ authority ของ root AGENTS.md/engine skill โดยคำขอ Phase 1C
ล่าสุดเป็นขอบเขตงาน ไม่ใช่คำสั่งเริ่ม SPRT เก่าใน current-state.md.

ผู้ใช้รายงาน Windows acceptance Phase 1B: load 15.02 ms, parity 48,600 probes,
454/454 tests PASS. รอบนี้ตรวจ source/branch และออกแบบ ไม่ได้รัน acceptance ซ้ำ.
`benchmarks/results/tb3_phase1b/summary.json` เป็นหลักฐานเก่าที่ระบุ Windows
pending จึงคงไว้ตามเดิม ไม่เขียนสถานะย้อนหลังทับหลักฐานนั้น.

## 1. จุดเชื่อมที่ตรวจจาก source

| จุดปัจจุบัน | งาน Phase 1C |
| --- | --- |
| `makhos/search.py: Engine._can_use_native_search` กัน root <= exact limit ออก | เพิ่ม capability/config gate สำหรับ native TB search; legacy DLL ใช้ Python ตามเดิม |
| `makhos/compact_tb3.py: CompactTablebase` | ใช้ decoder/checksum ของ Phase 1B แล้วส่ง immutable decoded image เข้า native ครั้งเดียว |
| `makhos/tb3_service.py: TB3Service` | รักษา readiness/generation; native handle มี lifetime ของตัวเองหลัง attach |
| `makhos/ranked_tablebase.py` | ย้าย ranking/threshold decoding เข้า C; map TB4–6 แบบ read-only |
| `native/makhos_native.c: native_negamax/native_quiescence` | terminal -> TB bounds -> TT/expansion; ส่งต่อ bounds แยกจาก scalar |
| `makhos/native.py: NativeSearchResult/NativeRootMoveResult` | เพิ่มข้อมูล bounds/completeness ผ่าน additive extension; ไม่ขยาย legacy C struct เดิม |
| `makhos/parallel_native.py` | หลัง 1T ผ่าน ให้ worker ใช้ immutable TB set ร่วมกัน แต่ history/TT/workspace แยก |
| `Engine._native_result/_choose` | แปลง root results กลับ RootCandidate; ใช้ BEST/WIN policy เดิม |

ฝั่ง native เป็น **C17** ไม่จำเป็นต้องเปลี่ยนเป็น C++ เพื่อทำงานนี้.
ไม่แก้ `RULESET.json`, `makhos/core.py`, accepted DLL, artifact เดิม หรือ
`build/nnue_sprt_6t_vs_12t/`; ไม่เริ่ม builder/arena ที่ไม่ได้อยู่ใน gate นี้.

## 2. Module และ ownership

**NativeTablebaseSet** มี interface prepare/retain/release/probe.
Implementation แบ่ง TB3 vector decoder กับ TB4–6 ranked decoder ภายใน module.
ไม่มี Python callback, decompression, malloc หรือ file open ต่อ node ใน production.

- TB3: เพิ่ม public `export_native_image()` แทนให้ bridge อ่าน `_data` โดยตรง.
  คืน immutable bytes พร้อม clock, board/vector counts, payload/artifact identity.
  C ตรวจขนาด/overflow/layout และ copy payload ~2.8 MB ครั้งเดียว; ไม่เพิ่ม zlib
  dependency ใน search DLL และไม่เปลี่ยน artifact format ของ Phase 1B.
- TB3 indexing ต้องตรง colex + piece-code + turn encoding ของ board_index().
  vector reference/value tag ผิดต้องคืน ERROR; distance เป็น no-repetition DTM
  ไม่ใช่หลักฐาน conversion ภายใต้ repetition.
- TB4–6: native เป็นเจ้าของ mapping/file handles. Windows ใช้ read-only file
  mapping; portable implementation ใช้ mmap. ใช้ uint64_t สำหรับ rank/offset
  และตรวจ multiplication/addition overflow, signature order, length และ clock.
- การรับรองไฟล์ทำครั้งเดียวใน prepare โดยผูก identity กับ handle ของไฟล์ที่ map
  จริง ไม่ใช่ตรวจชื่อไฟล์ก่อนแล้วเปิดไฟล์อื่นภายหลัง. ใช้ manifest/provenance
  validation เดิม; ไม่ hash TB6 ทั้งไฟล์ทุกครั้งที่เปลี่ยน Threads หรือเริ่มเกม.
- root/search session retain TB set; release หลัง workers หยุดครบเท่านั้น.
  Engine.clear() ล้าง TT/history แต่ไม่ถอด immutable TB set. Reconfigure/close
  ต้องหยุด session ก่อนเปลี่ยน handle; TB3Service.close() ทำให้ C memory dangling ไม่ได้.
- status แยก HIT, MISS (ไม่มี material coverage), INVALID/CORRUPT และ CANCELLED.
  ERROR ไม่ใช่ DRAW หรือ MISS. Strict GUI candidate ต้องมี TB3–6 พร้อมก่อน dispatch;
  เมื่อไม่พร้อม ใช้ Python path ที่มี verified oracle เดิม หรือแจ้ง unavailable ตาม
  readiness contract. ห้ามคืนผล native ที่ล้มเหลวเป็นผลปกติ.

## 3. ข้อตกลงคะแนนและ WDL

ทุก node มี scalar score, WDL interval [lower, upper], search status และ flags
แยกกัน. ค่า LOSS=-1, DRAW=0, WIN=1; UNKNOWN=[-1,+1]. TT alpha-beta flag ไม่ใช่
WDL flag และค่า score ใกล้ MATE ไม่สามารถสร้าง WDL proof ได้เอง.

ลำดับที่ negamax และ quiescence ต้องใช้:

1. ตรวจ repetition -> no-progress -> no legal move ตาม terminal_status() ทุกจุด
   รวม depth=0 และ max-ply boundary; terminal ต้องมาก่อน TB/TT/static evaluation.
   เสมอคืน 0/exact DRAW; ไม่มีตาเดินคืน -MATE_SCORE+root-relative-ply/exact LOSS.
2. Probe raw TB. repetition disabled คืน exact outcome/score ตามเดิม.
   repetition enabled: WIN -> [DRAW,WIN], LOSS -> [LOSS,DRAW], DRAW -> exact DRAW.
   แม้ current repetition count เท่ากับ 1 ก็ยังต้องใช้ช่วง เพราะอาจวนในอนาคต.
3. exact outcome คืนทันที. ช่วงที่ lower=DRAW บีบ alpha=max(alpha,0);
   upper=DRAW บีบ beta=min(beta,0). ถ้า window ปิด คืน alpha สำหรับ lower DRAW
   มิฉะนั้น beta พร้อม known bound; ถ้ายังเปิดให้ค้นต่อ.
4. quiet q-leaf ใช้ evaluator แล้ว clamp ตาม known bound. Capture q-node ค้น
   mandatory capture ต่อ; ไม่ใช้ stand pat ตัด mandatory capture.
5. child bound กลับมุมมองเป็น [-child.upper,-child.lower]. Parent รวม lower
   ด้วย max; รวม upper ด้วย max เฉพาะเมื่อครอบคลุม legal moves ทั้งหมด มิฉะนั้น
   upper=WIN. Intersect กับ known TB bound และ clamp score ตามช่วงที่ยืนยัน.
   Conflicting interval เป็น diagnostic error ไม่ใช่บังคับให้เสมอ.
6. timeout/cancel/error unwind path/history ทุกทาง; ไม่ publish iteration ที่ค้าง
   หรือ upper proof จาก root candidates ที่ยังค้นไม่ครบ. Root result มี status
   completed/fallback แยกชัดเจน; ห้ามอ้าง fallback ว่าได้ผลที่พิสูจน์แล้ว.

ใช้ native search_repetition_count()/initial history machinery เดิม แต่ตรวจว่า
root count ถูกใส่ครั้งเดียว, child นับเพิ่มครั้งเดียว, และ ply offset เมื่อ root
split เริ่มจาก child ตรงกับ Python. ไม่เปลี่ยน repetition identity ให้รวม clock.

**TT isolation รุ่นพิสูจน์แรก:** เมื่อเปิด TB integration และ repetition ให้
ปิด TT score read/write ทั้งคำขอ รวม ancestors >6 ตัว; ยังใช้ legal move hints ได้.
นี่เป็นจุดเริ่มที่ conservative เพื่อกัน TT จากกระดานเดียวแต่คนละ history รวม
ปัญหา 7->6 transition. แค่ตรวจ current repetition_count หรือ propagate flag หลัง
พบ draw ไม่พอรับรองการอ่าน TT ก่อนค้น subtree. ต้นทุน guard นี้ต้องวัดทั้งกลางเกม
และท้ายเกม; การเปิด score reuse ต้องเป็น change แยกที่มี exact history-context
validation/differential gate. ถ้ากลางเกมถดถอย ยังไม่เปิด candidate ทั้งระบบ.

**Pruning:** reference mode ปิด null move, LMR, futility และ heuristic score TT
cutoffs. ใน production TB subtree ใช้ full-depth legal search ก่อน; synthetic
null move และ reduced/unsearched branches ห้ามสร้าง exact WDL. การเปิด pruning
ทีละอย่างภายหลังต้องรักษา sound interval และผ่าน differential ใหม่.

## 4. ABI และ root policy

ดู [interface sketch](phase1c_native_api.h) ซึ่งเป็นเอกสาร ไม่ได้ include ใน build.
ใช้ extension version/capability ใหม่ แยกจาก legacy search ABI 2..6; struct เก่า
และ entry points เก่าคงขนาดเดิม. Bridge negotiate ก่อนใช้ extension; DLL เก่าไม่
ถูกเรียกด้วย layout ใหม่. New result buffers มี struct_size/version/capacity.

Native ส่งผล **ทุก root candidate ของ common completed depth** พร้อม score,
bound, PV และ root-relative ply. Adapter ใน Python สร้าง RootCandidate และใช้
_choose/_safety_rank เดิมทั้ง BEST/WIN. Pressure/policy/distance ทำเฉพาะระดับ root
ตาม contract เดิม; ยังไม่ย้ายส่วนนี้ใน PR แรก. วัดเวลาส่วนนี้แยกหลัง offload tree.

Gate routing ต้องครอบคลุม root <=6 และ root >6 ที่จับกินจนเข้า TB ระหว่างค้น.
Candidate ใช้ feature flag default-off และ capability endgame-v1; ไม่มี native
MISS/error ที่ถูกซ่อนเป็น proof. Diagnostics ระบุ TB hits แยก 3/4/5/6, raw exact
cutoff/bound-only hits, repetition draws, TT score bypass และ oracle identities.

## 5. Reference differential ที่คำว่า “ตรงกัน” ตรวจได้จริง

ไม่เทียบ native NNUE กับ Python HCE แล้วบังคับให้ heuristic score ตรงกัน.
เริ่มจาก **reference configuration เดียวกัน**: HCE ทั้งคู่ (ต่อยอด existing
test_native_evaluation_matches_python_reference), rules/history/clock/artifacts
เดียวกัน, fixed depth ไม่มี time cutoff, legal-move ordering/tie-break เดียวกัน,
ปิด selective pruning และ score TT ทั้งคู่. Test-only adapter จัด canonical
move order และปิด killer/history ordering; ไม่แก้ core.py หรือ production policy.

- Gate A: raw probe outcome/distance/status ต้องตรง Python decoder ทุกตัวอย่าง.
- Gate B: ตรวจ terminal reason, scalar score, WDL interval, legal PV และคำตอบที่
 เลือกตรงกันใน reference configuration. บันทึก per-root scores/bounds เพื่อระบุ
  mismatch แรก; เมื่อใช้ canonical tie-break แล้วไม่ละเว้น mismatch ด้วยข้ออ้าง
  ว่าหลายตาดีเท่ากัน. Node/probe counts มีนิยามแยกเพราะการนับ q-entry อาจต่างกัน.
- Gate C: production evaluator/pruning configuration เป็นอีก experiment; exact
  WDL/terminal/repetition ต้องผ่านเหมือนเดิม แต่ heuristic equality ไม่ใช่สิ่งที่
  454 tests เดิมรับรองให้โดยอัตโนมัติ. Native NNUE endgame ต่างจาก Python HCE
  และต้องมี fixed-time/paired evidence ก่อน promotion.

ชุดตรวจต้องมี: 1..6 pieces ทุก material signature ที่รองรับ, clock 0/1/77/78/79/80,
repetition None/3, count 1/2/3, board เดียว history ต่าง, forced capture/promotion,
ไม่มี legal move, 7->6/4->3 transitions, qsearch, max-ply, alpha-beta window ปิด
และเปิด, TT poison, repeated calls/clear/reconfigure, invalid/corrupt/closed artifact,
timeout ก่อนจบรอบแรกและระหว่าง worker search. ข้อมูลสุ่มต้องผ่าน legal validation;
unsupported board ต้องเทียบสถานะ error ไม่ติดป้าย DRAW.

ใช้ fixture ชนะเดิมที่ depth 1/2/3/8 ทั้ง BEST/WIN: acceptable set
{5-32,6-10,6-15,6-19,6-24}, ตรวจคู่แข่งไม่มี immediate repetition draw;
รวมฝ่ายเสียเปรียบที่ควรเลือก 28-32 ดึงเสมอ และ clock 78/79 regressions.
Cases ต้องผูก seed, histories, source/DLL/model/TB hashes และเก็บ failure fixture.

## 6. ลำดับ PR และเงื่อนไขหยุด

| PR | ผลส่งมอบ | Gate |
| --- | --- | --- |
| C1 | NativeTablebaseSet, TB3 image transfer, TB4–6 ranking/decode และ bridge probe | raw differential ขั้นต่ำ 48,600 TB3 probes; ครอบคลุม 139 TB4–6 signatures/clock edges, corruption/lifetime/overflow tests |
| C2 | 1T bounds propagation, additive result ABI, reference harness; default-off | strict Gate B, depth 1/2/3/8 ทั้งโหมด, all invariants, full discovered suite; perft10/native move-state differential ถ้าแก้ move/state machinery |
| C3 | เชื่อม Engine routing/root policy และ production NNUE candidate | GUI cold/warm 1s/2s; non-TB regression/latency; scalar/proof provenance ถูกต้อง; source-isolated paired gate ก่อน promote |
| C4 | เชื่อม existing root split/session ABI; ไม่เปลี่ยนเป็น Lazy SMP | private histories, shared immutable TB handles, all-root completion/cancel/clear; differential 1T ก่อน แล้ว 2/4/6/8/12T และ matched Hash |

เริ่มทำ C1 โดยยังไม่เปิด native endgame ใน GUI. Any raw/terminal/bound mismatch
หยุด candidate ทันที เก็บ reproduction และแก้ก่อน benchmark ต่อ. การผ่าน 1T
ไม่อนุมัติ Root Split อัตโนมัติ; การผ่าน tests/NPS ไม่ใช่ Elo promotion.
งานหลาย thread และ TT optimization ใช้คนละ commit/manifest เพื่อระบุสาเหตุได้.

## 7. Invariant snapshot ก่อนงาน

- RULESET.json SHA-256: 77528ADDC0E08B17217346C511C7C4084BAD4AF48789955C3EC85EF76A64871F
- makhos/core.py SHA-256: 03152E513BD360E6C2C97ECDF08DC58A290DCA0AE6E28889AE70585A381292AB

บันทึกนี้เป็นแผนและ ABI sketch เท่านั้น ไม่มี native implementation/build,
ไม่มีการรัน full suite/benchmark/SPRT และไม่มีการเปลี่ยน production pointer.
