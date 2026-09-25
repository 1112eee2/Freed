# เกมแพ้เซียนเฒ่า 2139e329d3c5def3: TT identity และ search horizon

วันที่ 2026-09-12 · ฐาน source `e41a2469f2e5cdeb9158a36d0a511f392bac293e`

**Verdict: INCONCLUSIVE สำหรับ strength / KEEP production เดิม**
พบ deterministic TT alias ที่เกิดจริงในการค้นตำแหน่งจากเกม และเปิดทาง build
candidate ที่ใช้ strict key เดิมของโครงการเพื่อแก้บั๊กนี้โดยเฉพาะ ยังไม่ได้พิสูจน์ว่า
candidate ช่วยไม่ให้แพ้เกมนี้ หรือเหนือกว่า production ในการแข่งขัน

## ตัวตนและการตรวจเกม

[game.json](game.json) คือ attachment เดิมทุก byte SHA-256
`5afd9031f611a6842872330dc47af10e4984cb0e111d51fced24c84829d54d9f`.
เล่นถูกกติกาครบ 63 plies, position history 64 รายการตรง replay,
PV ที่บันทึกของ engine 31 รายการถูกกติกา จบ Black ชนะเพราะ Red ไม่มีตาเดิน
ไม่ใช่ผลแพ้ที่เกิดจาก importer หรือเกมที่ถูกตัดจบ

Engine เล่น Red: NNUE v1, 12T, 1,000 ms, Hash ขอ 512 MiB/จัดสรร 480 MiB.
DLL ตาม metadata: `build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll`
SHA `32c323026a7f78ccd9c4013fc3067422a564ee3d0a6ade4f1ce5c62356747e79`.
Model SHA `07b9ab0f83e253cb74b2acd2bd5291f5f91eb086e042790f33ea0a8c0914164c`.
Metadata ไม่มี source revision ของเกม, SHA endgame DLL ที่ใช้จริง,
effective threads และ WDL lower/upper แบบตัวเลขครบทุกตา จึงยังผูกผลเกมกับ
source refactor ล่าสุดหรือจำลอง Windows แบบ exact ไม่ได้

## จุดเสียเปรียบที่ควรตรวจต่อ

| Ply ของ Red | ตาที่เล่น | คะแนนในเกม | สิ่งที่พบ |
|---|---|---:|---|
| 22 | 15-19 | +69 | คะแนนขึ้นอยู่กับ horizon; fresh strict 5s ยังเลือกตานี้ |
| 24 | 9-13 | +5 | fresh 1T 5s ทั้ง control/strict เลือก 8-11 |
| 28 | 8-12 | +35 | fresh 1T 5s มองเสียเปรียบมากกว่าเดิม |
| 30 | 12-16 | -183 | เริ่มรายงานเสียเปรียบชัดหลังดำแทรกเข้ามา |
| 42 | 24-28 | -410 | เสียเปรียบมากก่อนเข้าเส้นทาง native endgame |
| 52 | 20-24 | -999988 | native endgame รายงาน LOSS |

ตำแหน่งก่อน ply 24 (clock 9):

```text
R:BM17,18,22,26,27,31:RM1,2,8,9,10,19
```

การค้นลูกแต่ละทางด้วย strict 1T, TT 320 MiB, context ใหม่และ history ครบ:

| ทางเลือก | 5s คะแนนฝ่าย Red / depth ลูก | 20s คะแนนฝ่าย Red / depth ลูก |
|---|---:|---:|
| 8-11 | -61 / 32 | -73 / 33 |
| 9-13 (เล่นจริง) | -168 / 28 | -236 / 29 |

นี่เป็นหลักฐานเชิงสังเกตว่า 8-11 ต้านทานได้ดีกว่าใน search ชุดนี้ ไม่ใช่ proof ว่า
8-11 เสมอ หรือว่า ply 24 เป็นตาแรกที่เปลี่ยนผลตาม minimax อย่างแน่นอน
PVs แสดงการแทรกของเบี้ยดำและการขึ้นฮอส ซึ่ง search งบสั้นประเมินช้า
คะแนนบวกของตาบังคับบางตาเป็น static/forced result ไม่ได้แปลว่าฐานะกลับมาดี
ดู [raw child searches](ply24_alternatives.json), [control ladder](pilot.json),
[earlier plies](earlier.json), [strict ladder](strict_pilot.json).

## บั๊กที่พิสูจน์ได้และขอบเขตของแพตช์

`search_position_state_input()` ใน `native/makhos_native.c` ใช้
`state | 0x9e3779b97f4a7c15` เมื่อ strict flag ปิด ทำให้ king/clock bits
ที่ตรงกับบิต 1 ของ salt หายไป สถานะที่ต่างกันจึงมี TT key เดียวกันแบบ
กำหนดตายตัว ไม่ใช่การชนของ hash แบบสุ่มที่โอกาสต่ำ
TT ใช้ key ตัดสินตัวตน จึงนำ bound ของอีกสถานะมาตัดกิ่งได้

มี repair อยู่แล้วภายใต้ `MAKHOS_STRICT_SEARCH_POSITION_KEY=1`:
เปลี่ยนการผสม salt เป็น XOR ซึ่งไม่ลบข้อมูลของ packed state
แพตช์นี้เปิด switch `-StrictSearchKey` ใน build orchestrator เดียวและ wrapper เดิม
พร้อมบังคับ directory candidate แยกจาก production และบันทึก flag/source hashes.
ไม่เปลี่ยนค่า default, C ABI, NNUE model, endgame backend หรือ search heuristics.

ไม่ใช่การเสนอ strict key ครั้งแรก: ledger เดิมบันทึก compat/legacy-index/PGO
บนเกม HCE ก่อนหน้า ซึ่งไม่แก้ fixture ply 21 ตามเกณฑ์เวลาจึงไม่รับเข้า production.
หลักฐานใหม่ครั้งนี้คือ full-position trace บน **เกม NNUE ปัจจุบัน** ที่ยืนยัน
ว่ามี false cutoffs จริง ไม่ได้อ้างว่า retry เดิมผ่าน strength gate แล้ว

Instrumentation เก็บ full Position ข้าง TT entry ใน context 1T เท่านั้น
ที่ depth 20, hash power 20 (40 MiB), model เดียวกัน, context ใหม่:

| Ply | Legacy false cutoffs | ในนั้น king mask ต่างกัน | Strict false cutoffs |
|---|---:|---:|---:|
| 22 | 2,643 | 149 | 0 |
| 24 | 2,886 | 227 | 0 |
| 28 | 2,885 | 217 | 0 |
| รวม | **8,414** | **593** | **0** |

Instrumented/uninstrumented ของ encoding เดียวกันตรงกันทั้ง move, score,
nodes และ PV ทั้ง 6 comparisons. Raw arrays ใน [legacy audit](alias_audit.json)
และ [strict audit](alias_audit_strict.json): `counts` เรียง hits, false hits,
king false hits, cutoffs, false cutoffs, king false cutoffs.
`sample` เรียง key, old red/black/kings/turn/clock, current fields ชุดเดียวกัน,
requested depth, stored depth, bound flag.

**ข้อจำกัดสำคัญ:** strict และ legacy ยังเลือกตาเหมือนกันทั้ง 3 roots ที่ depth 20
ดังนั้น trace พิสูจน์บั๊ก TT แต่ไม่ได้พิสูจน์ว่าเป็นสาเหตุเดียวของการแพ้
XOR แก้ deterministic encoding alias นี้ ไม่ได้พิสูจน์ TT ปลอดภัยต่อทุก
history context หรือทำให้ 64-bit hash ไม่มีโอกาสชนกันเลย
ห้ามนำ shared-TT SMP มาใช้ก่อนแยกตรวจเรื่อง history และ atomic publication

## การตรวจที่ทำได้ใน Linux

ดู [verification.json](verification.json) สำหรับ counts, SHA และผลเทียบฐานจริง.
ผล full discovery ล่าสุด: candidate พบ 544 tests, รัน 501,
สำเร็จ 364 test methods / skip 107 / failure 6 / error events 30 (141.268 s).
ฐานพบ 542, รัน 499, สำเร็จ 361 / skip 105 / failure 6 / error events 42
(138.225 s). Error events รวม class setup/subtests จึงห้ามนำไปลบ testsRun
เพื่อคำนวณจำนวน PASS. ไม่มี failure/error ID ใหม่; PowerShell errors เดิม
ถูกจัดเป็น skip เพราะไม่มี Windows PowerShell. Invariants/source inventories
คงเดิมและ protected-data open attempts เป็น 0 ทั้งสองชุด

Regression ของ key สร้าง HCE control/strict จาก source ปัจจุบันอัตโนมัติ
แทนการ skip เมื่อไม่มี DLL ทดลองเก่า: ทดสอบ clock ครบ 256 ค่า, king bits ครบ 32,
และ contamination จาก TT ที่ warm ด้วย king/clock อีกสถานะใกล้ clock 80.
Perft strict depth 1–10 ตรง reference; depth 10 = 861,842,812.
Python/native differential PASS 204 positions / 1,149 moves (ไม่ได้รัน exact 3-piece solver);
Node GUI lifecycle/game controls 16/16 PASS.

Full suite บน Linux ยัง **NOT_PASS**; ขาด DLL Windows, ข้อมูลและ dependency
บางส่วน ไม่ใช้ Linux result เป็น attestation ของ Windows หรือเป็น strength gate.
ไฟล์ `full_suite_linux.py` เป็น snapshot ของ diagnostic runner ใช้ guard/lease/
runner definitions จาก maintained attestation โดยไม่ import pipeline dependencies
ที่ไม่มีในเครื่อง ไม่ใช้สร้างหรือยกเว้น trainer authorization. ทำซ้ำด้วย
`python benchmarks/game_reviews/2139e329d3c5def3/full_suite_linux.py <checkout-root> <new-output-dir>`.
ผลก่อนหน้าใน `build/loss_review_full` ไม่ใช้รับรองเพราะ guard ผูก directory เก่าผิด;
ชุดที่แนบนี้รันใหม่โดย guard ผูก `build/nnue_scaling_full_v1` ตาม canonical constant.

เวลาจาก Linux container เป็น diagnostic เท่านั้น โดยเฉพาะ 12T เคยมี overshoot
122 ms ในหนึ่ง observation จึงไม่อ้าง performance PASS หรือ depth superiority.
Instrumentation มี sidecar 16 bytes ต่อ entry ห้ามใช้ binary นี้วัดเวลา/เล่นจริง.

## ทำซ้ำและตรวจรับ Windows Local

ทำใน checkout ของ PR โดยบันทึก commit จริงก่อนรัน, ไม่มี GUI/งาน batch อื่น,
ใช้ BelowNormal และ workload lease. คำสั่งต่อไปนี้ไม่เปลี่ยน GUI release pointer:

```powershell
$review = 'benchmarks/game_reviews/2139e329d3c5def3/review.py'
python $review --output build/game2139-windows/replay.json
.\build_nnue_search_candidate.ps1 -OutputDirectory build\game2139-control
.\build_nnue_search_candidate.ps1 -OutputDirectory build\game2139-strict -StrictSearchKey
python -m unittest tests.test_native_search.NativeSearchPositionKeyCandidateTests tests.tooling.test_build_orchestrator -v
$control = 'build/game2139-control/makhos_native_nnue_candidate_v1.dll'
$candidate = 'build/game2139-strict/makhos_native_nnue_candidate_v1.dll'
python $review --library $control --ply 22 --ply 24 --ply 28 --threads 1 --hash-power 20 --depth 20 --budget-ms 0 --output build/game2139-windows/control-depth20.json
python $review --library $candidate --ply 22 --ply 24 --ply 28 --threads 1 --hash-power 20 --depth 20 --budget-ms 0 --output build/game2139-windows/strict-depth20.json
python $review --library $control --ply 24 --ply 28 --threads 12 --budget-ms 1000 --budget-ms 2000 --output build/game2139-windows/control-12t.json
python $review --library $candidate --ply 24 --ply 28 --threads 12 --budget-ms 1000 --budget-ms 2000 --output build/game2139-windows/strict-12t.json
python $review --library $candidate --ply 24 --root-move 8-11 --root-move 9-13 --budget-ms 5000 --budget-ms 20000 --output build/game2139-windows/alternatives.json
```

`review.py` ใช้ full game history, context ใหม่ทุก observation, ตรวจ legal move/PV,
ผูก DLL/model SHA, บันทึก actual TT allocation และไม่เขียนทับ output เดิม
การเทียบกับ DLL ที่เกมโหลดจริงต้องใช้ SHA จาก metadata ข้างบน ไม่ถือว่า
fresh same-source control เท่ากับ binary Windows ตัวเก่าโดยอัตโนมัติ

ตรวจ instrumentation ด้วย compiler เดียวกับ control/strict:

```powershell
python benchmarks/game_reviews/2139e329d3c5def3/instrument_tt.py --output build/game2139-windows/audit.c
$cc = 'C:\Program Files\LLVM\bin\clang.exe'
& $cc -O3 -march=x86-64 -std=c17 -shared -I native build/game2139-windows/audit.c -o build/game2139-windows/audit.dll
& $cc -O3 -march=x86-64 -std=c17 -shared -I native -DMAKHOS_STRICT_SEARCH_POSITION_KEY=1 build/game2139-windows/audit.c -o build/game2139-windows/audit-strict.dll
python $review --library build/game2139-windows/audit.dll --tt-audit --ply 22 --ply 24 --ply 28 --hash-power 20 --depth 20 --budget-ms 0 --output build/game2139-windows/audit.json
python $review --library build/game2139-windows/audit-strict.dll --tt-audit --ply 22 --ply 24 --ply 28 --hash-power 20 --depth 20 --budget-ms 0 --output build/game2139-windows/audit-strict.json
```

รับ correctness เมื่อ audit/non-audit ของแต่ละ encoding ตรงทั้ง move/score/nodes/PV,
strict false hits/cutoffs เป็น 0, regression ผ่าน, invariants ตรงเดิม และ
full currently discovered suite ผ่านด้วย maintained full-suite attestation
(`scratch/nnue_full_suite_attestation.py --help` สำหรับ bound audit prerequisites).
ต้องตรวจ NNUE parity, TB4–TB6, GUI lifecycle และ HTTP smoke NNUE/HCE บน Windows ด้วย
แพตช์ไม่ตั้ง hard-coded expected move เพื่อบังคับให้ผ่านเกมเดียว

จากนั้นใช้ paired pentanomial SPRT เดิมของโครงการใน **output/manifest ใหม่**
เทียบ same-source control กับ strict (1T intrinsic 10s+0.1s, แล้ว production
12T fixed 1s/2s แยก seed/results), ตรึง SHA/compiler/model/hash/time controls,
H0/H1 และเพดานก่อน launch. ต้องวัดเวลา/หน่วยความจำบนชุด held-out รวม 6T
ก่อนตั้งค่าใช้งาน ไม่มีการ resume Experiment A หรือ checkpoint 27 คู่
ห้าม promote จากเกมนี้, tactical fixture หรือ NPS เพียงอย่างเดียว

**งานถัดไปหนึ่งเรื่อง:** ตรวจ strict-key candidate บน Windows พร้อม paired strength
บน baseline ที่ยืนยัน TT identity แล้ว หาก search horizon ยังด้อยจึงทำ profile/design
SMP แยกงาน ไม่เพิ่ม heuristic หรือปรับ NNUE จากเกมเดียวใน PR นี้
