# Native endgame: รองรับการกินหลายตัวข้ามขอบเขต TB6

วันที่ 2026-09-11 · ฐาน `bbdc86c0853573a66dd3da9334dd56955bc7c2b1`
Branch: `codex/endgame-transition-coverage`

สถานะล่าสุด **CORRECTNESS_MERGED_WITH_EXCEPTION** — [PR #6](https://github.com/1112eee2/ThaiMakhosEngine/pull/6)
merged ที่ `e975d6843ee23e9fe42a3662f5d802516293796e` หลังผู้ใช้อนุมัติยกเว้น paired strength
gate เฉพาะแพตช์นี้ ไม่อ้าง Elo เพิ่ม และไม่ยกเว้น gate ของงานอื่น

Windows Local รายงาน 10/10 transition tests, full suite 513/513 (177.122 s, ไม่มี
failures/errors/skips), Node 16/16, real-TB4–TB6 benchmark 48 observations และ HTTP smoke
NNUE/HCE ผ่านครบ Overshoot mean 2.12 ms/max 3.70 ms พร้อม invariant/checkpoint hashes เดิม
Raw Windows artifacts อยู่บน Local; Web ยังไม่ได้ดึงมาคำนวณ hashes อิสระ รายงาน Linux
และข้อจำกัดเดิมด้านล่างคงไว้เป็นหลักฐาน ไม่เปลี่ยนย้อนหลังให้เป็น Windows PASS

## สมมติฐานและขอบเขต

เงื่อนไขเดิมทั้ง server และ native adapter รับเฉพาะ root <=6 ตัว หรือ 7 ตัวที่กินเข้า <=6
จึงพลาดการกินหลายตัวจาก 8/9 ตัว แม้ลูกอยู่ในขอบเขต tablebase แล้ว
แก้เฉพาะ admission ให้สองจุดใช้ `makhos/endgame_routing.py` ร่วมกัน:

- Root <=6: รับตามเดิม
- Root >6: รับเมื่อ **มีตาเดินถูกกติกาอย่างน้อยหนึ่งตา** ที่ `piece_count - len(move.captures) <= 6`
- เมื่อรับแล้ว C4 ค้น **ทุกตาที่ root** รวมทางเลือกซึ่งยังอยู่นอก TB6
- การรับเข้าค้นไม่ใช่หลักฐาน WDL และไม่รับประกันว่าไฟล์ TB material นั้นพร้อม
- Quiet midgame และ capture ที่ลูกทุกตายัง >6 ใช้ route เดิม

ไม่เปลี่ยน native C, TT, NNUE, root policy, distance/pressure, BEST/WIN, forced shortcut,
repetition/80-ply หรือ default Threads/Hash เดิม ยังคง rollback ผ่าน `--no-native-endgame`
หรือ `--release-profile hce` ได้ การดัก TB ที่อยู่ลึกหลายพลายหลัง quiet root เช่นพลาย 47/49
ในเกมอ้างอิง **อยู่นอกแพตช์นี้**

## กรณีจากเกมจริง

Root ก่อนพลาย 51: `B:BM23,26:BK15:RM13,14,19,21,27`

| Root move | จำนวนตัวหลังเดิน | สิ่งที่ต้องตรวจรับ |
|---|---:|---|
| `15x24x31` | 6 | score 0 และ `[DRAW,DRAW]` จาก TB6 จริง |
| `23x16` | 7 | ต้องคงเป็น candidate และค้นแยก ห้ามเหมารวมว่า DRAW |

เพิ่ม regression 9→6: `B:BK6,13,14:RK4,16,17,18,19,21`
มี `13x22x15x24` เหลือ 6 ตัว พร้อมอีกสองทางเลือกที่เหลือ 8 ตัว
มี differential predicate กับ child material ที่สร้างด้วย rules reference 300 ตำแหน่ง
และทดสอบ 7→6 เดิม, flag-off, reference mode, forced readiness bypass,
terminal precedence, H1→H2→H1, clock 79/80, ส่ง history/rules/time ครบ และ legal fallback

`RecordingEndgame` ใน unit tests เป็น **contract double** ไม่ใช่ TB ที่แก้สำเร็จแล้ว
เทสต์ที่ยืนยัน DRAW ของเกมมนุษย์แยกไว้และต้องมีไฟล์ TB4–TB6 จริง

## หลักฐาน Linux

[สรุปและ SHA-256](../../benchmarks/results/endgame_transition_v1/summary.json)
ผูก source/test inventories, GCC, C4 isolated `.so`, model และ full logs ที่บีบอัดไว้
ไม่ได้ใช้ `.so` นี้แทน accepted Windows DLL

| Full discovery | ฐาน bbdc86c | Candidate |
|---|---:|---:|
| Discovered | 503 | 513 |
| testsRun | 460 | 470 |
| PASS จาก test log | 336 | 345 |
| Failures | 8 | 8 |
| Errors รวม setUpClass | 19 | 19 |
| Skips | 103 | 104 |
| ยังไม่ได้รันเพราะ class setup ล้มเหลว | 43 | 43 |
| เวลา | 58.73 s | 59.89 s |

Failure/error IDs ตรงกันทุกข้อ; skip ที่เพิ่มเพียงข้อเดียวคือ human-game TB6 integration
ที่ไม่มี artifact จริง ข้อผิดพลาดเดิมรวม Windows DLL ที่โหลดบน Linux ไม่ได้,
ข้อมูล/contract/dependency ที่ขาด และข้อจำกัด workload isolation ของ host นี้
**ทั้งสอง full suite เป็น NOT_PASS** ไม่มีการกรองเทสต์ออกเพื่อทำรายงาน PASS
เปิด protected data เป็นศูนย์ และ source/test/invariant hashes ไม่เปลี่ยนระหว่างรัน
ค่า PASS นับจากบรรทัด `... ok` ใน log เพราะ error ของ setUpClass ไม่อยู่ใน testsRun

เทสต์ใหม่ 10 ข้อ: **9 PASS, 1 SKIP** รวม C4 จริงที่มีเฉพาะ TB3:
1T/4T ให้ root score/bound/PV ตรงกันที่ depth 2, รักษาทุก alternative และ reuse history ได้
Native routes นอกขอบเขตแก้ไขและ flag-off ตรงกับฐานเดิม 16 กรณี
(move/score/bound/PV/depth/nodes, NNUE model/DLL เดียวกัน, hash_power=12)
Node lifecycle/game controls **16/16 PASS**

[Runtime 32 observations](../../benchmarks/results/endgame_transition_v1/linux_runtime.json):
2 ตำแหน่ง × BEST/WIN × 1T/4T × 1s/2s × 2 ซ้ำ โดย replay ประวัติเกมจริงก่อนพลาย 51

- TB3/C4 owner setup 12.49 ms; วัดแยกจาก search
- Overshoot mean 1.91 ms, p95 2.93 ms, max 3.07 ms
- RSS ที่สังเกตสูงสุด 32.93 MiB (`/proc/self/status:VmRSS`; ไม่ใช่ peak RSS หรือ RAM ของ TB6)
- Predicate ประมาณ 20–26 µs/call บน opening/quiet/non-crossing ที่วัด จึงไม่ได้อ้าง zero overhead
- สถานะ **DIAGNOSTIC_TB3_ONLY**: ไม่มีหลักฐาน raw TB6 DRAW, production HTTP timing หรือผลบน Ryzen
- Timing เป็น Engine API หลัง setup; checksum scan และ mmap preparation ไม่นับเป็น search time

ไฟล์ harness ในโฟลเดอร์ evidence เก็บคำสั่ง Linux ที่ใช้รันไว้ ไม่ต้องใช้กับ Windows
ผลนี้ยังไม่ใช่การเทียบ strength และไม่มี SPRT/arena จริงถูกเปิดขึ้น

## ตรวจรับบน Windows Local

ใช้ checkout แยกที่ branch นี้ ขณะ GUI/arena ว่าง และใช้ C4 DLL ที่ตรวจรับไว้เดิม
กับ NNUE v1/TB3–TB6 ชุดเดิม **ไม่ต้อง rebuild DLL** เพราะ native source ไม่เปลี่ยน
ตรวจ DLL/model/TB identities เทียบ manifest ที่ตรึงบน Local ก่อนรัน

```powershell
git switch codex/endgame-transition-coverage
python -B -m unittest tests.test_endgame_transition -v
python -B -m unittest discover -s tests
node --test work/test_gui_lifecycle.cjs work/test_gui_game_controls.cjs
python -B benchmarks/endgame_transition.py --threads 1 12 --time-ms 1000 2000 --repeats 3 --output build/endgame_transition_acceptance/windows-v1
Get-FileHash RULESET.json, makhos/core.py, build/makhos_native_accepted.dll -Algorithm SHA256
```

ต้องมี C4 ที่ `build/native_endgame_c4/makhos_endgame_search_nnue.dll`, model ที่
`build/nnue_quantized_v1/model_a.mknnue`, และ `build/tb{4,5,6}_np80.compact.bin`
Benchmark ปกติไม่ยอมรันหาก TB4–TB6 ไม่ครบ และสแกน SHA-256 จาก mapping ก่อนวัด search
เลือก output directory ใหม่ทุกครั้ง; ห้ามใช้ `--tb3-only` เพื่อข้าม gate บน Windows

เกณฑ์รับ:

1. เทสต์ใหม่ 10/10 ไม่มี skip; full suite รันครบจำนวนที่ discover จริง (branch นี้ 513),
   failures/errors/skips เป็นศูนย์ พร้อม source/test hashes ของ checkout ที่ใช้
2. TB6 ยืนยัน `15x24x31` เป็น score 0 / exact DRAW; มี `23x16` ใน candidates เสมอ
   และ C4 1/2/4/6/8/12T ให้ per-root results ตรงกันใน fixed-depth regression
3. Runtime ได้ `PASS_ROUTING_PROOF` พร้อมตรวจ wall/overshoot/depth/nodes/PV/RAM ที่ 1s/2s
   ค่านี้หมายถึง assertions ของ routing/proof ผ่าน **ไม่ใช่ PASS ด้าน latency หรือ Elo อัตโนมัติ**
4. HTTP smoke บน GUI NNUE profile: cold/warm โหลด replay prefix ของเกมก่อนพลาย 51,
   backend ต้องเป็น `native-endgame`, effective 12T, candidate DRAW พร้อมทุก alternative
   ทดสอบ forced move, new game, และ rollback `--no-native-endgame` โดยผูก Python source commit
   ในหลักฐานด้วย วัด startup/request แยกกัน; อย่าเอาเฉพาะ search_ms มาอ้างว่า cold HTTP ผ่าน
5. ตรวจ invariant hashes และ checkpoint identities เทียบค่าที่ตรึงเดิม โดยไม่ resume/เขียนทับ

หากเกิด bound contradiction, ตาหาย, PV ผิดกติกา, runaway timeout หรือ identity drift:
หยุดรับ candidate และเก็บ log เพื่อแก้บน branch นี้ คง production เดิมไว้

## งานต่อไป

รับรอง transition correctness/runtime บน Windows ก่อนพิจารณารวมแพตช์
หากจัดการเปลี่ยนเส้นทางนี้เป็น strength-changing ให้ตรึง source/DLL/model และออก manifest
paired gate ใหม่ตาม skill; regression หนึ่งเกมหรือ timing ไม่แทนหลักฐาน Elo
จากนั้นค่อยแยก saved-game provenance และออกแบบ SMP experiment ใหม่
ห้ามนำ Root-PVS ที่เคย REJECT กลับมารันโดยไม่มีสมมติฐานใหม่แก้สาเหตุเดิม

ตามคำสั่งผู้ใช้ Experiment A C4 1000ms หยุดที่ 539 คู่ด้วยเหตุผลจัดสรรเวลา:
สถิติยัง **INCONCLUSIVE** (LLR -0.3364), คง 12T; 2000ms ยังไม่เปิดรัน
Checkpoint 27 คู่เป็นประวัติศาสตร์คนละ source; ไม่มีการ resume ทั้งสองชุดในงานนี้
