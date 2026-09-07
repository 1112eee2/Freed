# Thai Makhos Engine

> Current forward development is governed by `DEVELOPMENT_PLAN_TH.md` and
> `.agents/skills/thai-makhos-engine/SKILL.md`. The proof/tablebase counts below
> are historical evidence snapshots; current work is the locked NNUE
> development-label acquisition, with no model training or sealed-test opening
> yet.

เอนจิ้นอ้างอิงหมากฮอสไทยที่เน้นความถูกต้องก่อนความเร็ว พร้อมนโยบายเลือกตา 2 แบบบน search core เดียวกัน

ผลที่พิสูจน์แล้วและข้อจำกัดปัจจุบันบันทึกไว้ใน [VERIFICATION.md](VERIFICATION.md) เพื่อไม่ให้ผลทดลองถูกตีความเป็นคำรับประกัน

ข้อวิจารณ์แผนต้นฉบับและลำดับงานที่แก้แล้วอยู่ใน [PLAN_REVIEW_TH.md](PLAN_REVIEW_TH.md)

สถาปัตยกรรม proof-guided policy–value, การฝึก self-play และนิยาม DTM/DTR อยู่ใน [POLICY_VALUE.md](POLICY_VALUE.md)

- `best`: เลือกตาที่ได้คะแนน minimax สูงสุด แล้วใช้ระยะ exact และ policy–value ตัดสินเมื่อคะแนนเท่ากัน
- `win`: ไม่ลดระดับ WDL; เมื่อมี proof จะพิจารณาตาปลอดภัยทั้งหมดในชั้น WDL lower-bound ที่สูงที่สุด หากมี exact decisive DTM ที่คำนวณสำเร็จจะใช้ปิดผลชนะ/ยืดการต้านทานก่อน แล้วจึงเลือกโอกาสชนะจาก self-play โดยใช้ DTR ที่พิสูจน์ระยะสำเร็จและความยากในการตอบเป็นตัวตัดสินถัดไป หากไม่มี proof จึงรักษา score envelope จาก search ตาม `--win-margin`

ทั้งสองโหมดจัดลำดับด้วย WDL interval ก่อนคะแนน heuristic เช่น ตาที่มีช่วง `DRAW..WIN` จะอยู่เหนือตา `UNKNOWN (LOSS..WIN)` เสมอ ส่วน tablebase ที่ไม่รวมกฎ repetition จะไม่ถูกแสดงเป็น exact WIN/LOSS เกินหลักฐานจริง: เมื่อเปิด repetition ผลอาจแสดงเป็น `DRAW..WIN` หรือ `LOSS..DRAW`

คำว่า “ไม่ลด” ในรุ่นนี้หมายถึงผลการค้นหาที่ความลึกปัจจุบัน ยังไม่ใช่บทพิสูจน์ว่าเกมหมากฮอสไทยไม่มีทางแพ้ การรับประกันจริงต้องอาศัย exact solver/tablebase และต้องทราบก่อนว่าตำแหน่งเริ่มต้นมีค่าเป็นชนะหรือเสมอสำหรับฝ่ายที่เอนจิ้นเล่น

## กติกาที่ใช้

- กระดาน 8×8 ใช้ 32 ช่อง แต่ละฝ่ายมี 8 ตัว
- เบี้ยเดินและกินไปข้างหน้าเท่านั้น
- บังคับกินและต้องกินต่อด้วยตัวเดิมจนกินต่อไม่ได้
- เลือก capture chain ใดก็ได้ ไม่บังคับกินจำนวนมากที่สุด
- ฮอสเดินไกลตามแนวทแยง แต่เมื่อกินต้องลงช่องแรกหลังตัวที่กิน
- นำหมากที่ถูกกินออกทันที ฮอสจึงสามารถย้อนทิศผ่านแนวที่เปิดใหม่ได้
- เบี้ยที่กินถึงแถวสุดท้ายเข้าฮอสและจบตาทันที
- ค่าเริ่มต้นให้ดำเดินก่อน แต่ CLI เปลี่ยนฝ่ายเริ่มได้
- สำหรับเกมคอมพิวเตอร์ กำหนดเสมอเมื่อเกิดตำแหน่งเดิมครั้งที่ 3 หรือไม่มีการกิน/เข้าฮอสครบ 80 plies; ค่านี้แยกอยู่ใน `Rules`

## ใช้งาน

ต้องมี Python 3.11 ขึ้นไป และไม่ต้องติดตั้งแพ็กเกจเสริม

```powershell
python -m unittest discover -s tests -v
python -m makhos perft --depth 5
python -m makhos bestmove --depth 7 --mode best
python -m makhos play --human red --mode win --depth 7
python -m makhos play --human red --mode win --depth 7 --native-tablebase
python -m makhos bestmove --position "B:BK1,5:RK2,6" --mode win --native-tablebase --ranked-tablebase build/tb4_np80.bin
python -m makhos solve --position "B:BK1:RK2" --no-progress 8
python -m makhos arena --pairs 2 --mode-a win --mode-b best --depth 4
python -m makhos train-selfplay --games 100 --depth 4 --output-model build/policy-value.json
python -m makhos bestmove --mode win --depth 7 --policy-model build/policy-value.json
python -m makhos verify-endgames --no-progress 80
python -m makhos gauntlet --pairs 4 --depth 4 --opponent-depth 2 --opponent-error-rate 0.15
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_native.ps1
./build/makhos_native.exe perft 10
python -B -m makhos verify-native --samples 500 --exact-samples 10
./build/makhos_native.exe verify-1v1 80 20
./build/makhos_native.exe verify-3piece 8 24
./build/makhos_native.exe solve "B:BK1:RK2" 80 20
./build/makhos_tb4.exe build 4 24 build/tb4_np4.bin
./build/makhos_tb4.exe build 80 25 build/tb4_np80.bin
./build/makhos_tb4.exe verify-monotonic build/tb4_np80.bin
./build/makhos_tb4.exe compress build/tb4_np80.bin build/tb4_np80.compact.bin
./build/makhos_tb4.exe compare-compact build/tb4_np80.bin build/tb4_np80.compact.bin
./build/makhos_tb5.exe compact-dfpn build/dfpn-old.tt build/dfpn-expanded-only.tt
./build/makhos_tb5.exe verify-dfpn-codec
./build/makhos_tb6.exe verify-dfpn-disk-backing build/dfpn-disk-verify
./build/makhos_tb5.exe plan-six 8000000
./build/makhos_tb5.exe dfpn-hashes build/tb4_np80.bin build/tb5_np80.compact.bin "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8" black 20000000 29 27 25 build/dfpn5_reproduction.tt
./build/makhos_tb5.exe build 1 build/tb4_np1.compact.bin 22 build/tb5_np1.compact.bin
./build/makhos_tb5.exe build 80 build/tb4_np80.compact.bin 25 build/tb5_np80.compact.bin
./build/makhos_tb5.exe verify build/tb5_np80.compact.bin 0
# Historical no-progress-1 TB6 reproduction only (about 4.85 GB); run only when enough additional disk space is available.
./build/makhos_tb6.exe build 1 build/tb4_np1.compact.bin build/tb5_np1.compact.bin 25 8000000 70 build/tb6_np1.compact.bin 8
# The final full-rule file exists and passed the acceptance commands below; rerun this command only to rebuild/resume it.
./build/makhos_tb6.exe build 80 build/tb4_np80.compact.bin build/tb5_np80.compact.bin 25 8000000 70 build/tb6_np80.compact.bin 8
./build/makhos_tb6.exe verify-prefix 80 build/tb4_np80.compact.bin build/tb5_np80.compact.bin 25 70 0 build/tb6_np80.compact.bin
./build/makhos_tb6.exe verify-prefix 80 build/tb4_np80.compact.bin build/tb5_np80.compact.bin 25 70 79 build/tb6_np80.compact.bin
./build/makhos_tb6.exe verify-threshold-logic
./build/makhos_tb6.exe verify-thresholds build/tb4_np80.compact.bin build/tb5_np80.compact.bin build/tb6_np80.compact.bin 25
./build/makhos_tb6.exe verify-symmetry build/tb6_np80.compact.bin 0 997
./build/makhos_tb6.exe verify-symmetry build/tb6_np80.compact.bin 79 997
./build/makhos_tb6.exe verify-symmetry build/tb6_np80.compact.bin 80 997
# Reproduction only: extract the archived DFPN5 source to RECOVERED_DFPN5_CHECKPOINT, verify its original SHA-256, and use fresh output paths. Do not overwrite the current canonical checkpoint.
./build/makhos_tb6.exe rebase-dfpn build/tb4_np80.bin build/tb5_np80.compact.bin build/tb6_np80.compact.bin RECOVERED_DFPN5_CHECKPOINT build/dfpn6_rebased_copy.tt
# The D workflow defaults to 671,088,640 live / 160,000,000 solved slots; keep enough disk space for the mapped hashes and atomic temporary checkpoint.
./build/makhos_tb6.exe dfpn-slots build/tb4_np80.bin build/tb5_np80.compact.bin build/tb6_np80.compact.bin "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8" black 100000000 671088640 160000000 25 build/dfpn6_rebased_copy.tt
# ชุดทำงานบนไดรฟ์ D: ตรวจพื้นที่/ไฟล์ก่อน แล้วจึงเดิน DFPN ต่อโดยใช้ disk-backed hash และ checkpoint บน D อัตโนมัติ
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_dfpn_on_d.ps1 -ValidateOnly
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_dfpn_on_d.ps1 -ExpansionBudget 100000000
# When the global hash approaches RAM limits, retain only exact solved records and retarget one root branch.
.\build\makhos_tb6.exe retarget-dfpn-solved build\tb4_np80.bin build\tb5_np80.compact.bin build\tb6_np80.compact.bin build\dfpn6_initial_seeded.tt build\dfpn6_branch_26-22.tt "R:BM22,25,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8" 1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_dfpn_on_d.ps1 -CheckpointPath build\dfpn6_branch_26-22.tt -Position "R:BM22,25,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8" -Clock 1 -RunName dfpn6-26-22 -LiveSlots 130000000 -SolvedSlots 150000000 -ExpansionBudget 100000000
./build/makhos_tb4.exe verify build/tb4_np80.bin 0
./build/makhos_tb4.exe prove build/tb4_np80.bin "B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8" black 10000000 27 25 build/proof_initial.tt "28-24,8-12,27-23,7-11,26-22,6-9,25-21,9-14,24-20"
python -B -m makhos verify-tablebase --tablebase build/tb4_np4.bin --no-progress 4 --samples 50
python -B -m makhos verify-tablebase --tablebase build/tb4_np80.bin --no-progress 80 --samples 0 --tactical
python -B -m makhos verify-tablebase --tablebase build/tb5_np1.compact.bin --no-progress 1 --samples 2000
python -B -m makhos verify-tablebase --tablebase build/tb5_np80.compact.bin --no-progress 80 --samples 100 --min-captures 3
python -B -m makhos verify-tablebase-provenance --tablebase build/tb4_np80.bin --tablebase build/tb5_np80.compact.bin --tablebase build/tb6_np80.compact.bin
python -B -m makhos bestmove --position "B:BM5:BK25,26:RM3,4" --no-progress 1 --depth 1 --ranked-tablebase build/tb4_np1.compact.bin --ranked-tablebase build/tb5_np1.compact.bin
python -B -m makhos prove-nonloss --position "B:BM29,30:BK18:RM11,22" --root-player black --all-safe-choices --certificate build/proof_tactical.json
python -B -m makhos check-proof --certificate build/proof_tactical.json --independent-rules-audit
python -B -m makhos bestmove --position "B:BM29,30:BK18:RM11,22" --mode win --proof-strategy build/proof_tactical.json
```

เมื่อ DFPN พิสูจน์ root สำเร็จ คำสั่งตระกูล `dfpn*` รับอาร์กิวเมนต์ต่อท้ายหลัง checkpoint และ seed เป็น `[CERTIFICATE|-] [ALL_CHOICES_0_OR_1]` เพื่อส่งออก proof DAG v2 ที่ checker และเอนจิ้นใช้ได้โดยตรง ตัวอย่างเช่นเติม `build/proof_initial.json 1` เพื่อเก็บทุก child ที่ DFPN พิสูจน์ non-loss แล้ว หรือใช้ `0` เพื่อเก็บตาปลอดภัยแรกและลดขนาด DAG ไฟล์จะผูกกับ checksum ของ ranked frontiers ที่ back-end นั้นใช้จริง: `makhos_tb4` ผูกฐาน 4 ตัว, `makhos_tb5` ผูกฐาน 4/5 ตัว และ `makhos_tb6` ผูกฐาน 4/5/6 ตัว โดยจะเขียน certificate เฉพาะเมื่อ root เป็น `PROVEN NON-LOSS`

สำหรับ proof ใหญ่ที่ JSON ใช้ RAM มาก ให้แปลง solved checkpoint เป็นกลยุทธ์แบบ memory-mapped แล้วใช้กับ `check-proof`/`--proof-strategy` ได้โดยตรง:

```powershell
./build/makhos_tb6.exe export-strategy build/tb4_np80.bin build/tb5_np80.compact.bin build/tb6_np80.compact.bin build/dfpn6_initial_seeded.tt build/strategy_initial.bin 27 1
python -B -m makhos check-proof --certificate build/strategy_initial.bin --ranked-tablebase build/tb4_np80.bin --ranked-tablebase build/tb5_np80.compact.bin --ranked-tablebase build/tb6_np80.compact.bin --verify-tablebase-provenance --independent-rules-audit
python -B -m makhos bestmove --mode win --proof-strategy build/strategy_initial.bin --ranked-tablebase build/tb4_np80.bin --ranked-tablebase build/tb5_np80.compact.bin --ranked-tablebase build/tb6_np80.compact.bin
```

อาร์กิวเมนต์สุดท้าย `1` ให้ checker/runtime ใช้ทุก child ที่ checkpoint พิสูจน์ non-loss แล้ว ส่วน `0` เลือกตาแรกเพื่อลด closure ให้เล็กที่สุด ไฟล์เก็บเฉพาะ exact position keys ที่พิสูจน์แล้วใน hash ขนาดคงที่; checker ยังคงสร้าง legal moves ซ้ำ ตรวจทุก reply ของคู่แข่ง ตรวจ terminal/tablebase leaf และเก็บ bitset ของโหนดที่ตรวจผ่านเพื่อปฏิเสธตำแหน่งนอกกลยุทธ์ ค่า `HASH_POWER` ต้องทำให้จำนวน entry ไม่เกิน 85% ของ capacity: power 27 รับได้สูงสุด 114,085,068 entries; หากมากกว่านี้ต้องใช้ power 28 หรือสูงกว่า

เลขตาเดินใช้ช่อง 1–32 เช่น `25-21` และการกินต่อเนื่องใช้ `x` เช่น `25x18x11`

ตำแหน่งกำหนดได้ด้วยข้อความรูปแบบ `B:BM25,26:BK29:RM5,6:RK1` ตัวแรกคือฝ่ายเดิน และกลุ่มหมากคือ `BM`/`BK`/`RM`/`RK` ตามด้วยเลขช่อง 1–32 คำสั่ง `bestmove`, `play` และ `perft` รับ `--position` ได้เช่นกัน

เมื่อไม่มี proof strategy ค่าเริ่มต้น `--win-margin 0` ทำให้โหมด `win` เลือกเฉพาะตาที่ search ให้คะแนนเท่าตาที่ดีที่สุด และค่าที่มากขึ้นยอมเปิด score envelope เล็กน้อย เมื่อมี proof strategy ที่ตรวจแล้ว WDL/ชุดตาปลอดภัยคือ safety envelope ที่แท้จริง: `win` จะพิจารณาตาปลอดภัยทุกตาในชั้น WDL lower-bound สูงสุด ใช้ exact decisive DTM ก่อนเมื่อคำนวณสำเร็จ แล้วเลือก posterior P(win) จาก self-play สูงสุด; `--win-margin` จึงไม่ใช้ในกรณีนี้ ส่วนโหมด `best` ยังคงเลือกคะแนน minimax เป็นหลัก

เมื่อมี proof certificate ที่ผ่านการตรวจแล้ว ใช้ `--proof-strategy FILE` กับ `bestmove`, `play` หรือ `train-selfplay` ได้ ตัว checker จะสร้าง legal edges ซ้ำ ตรวจ no-progress horizon และตรวจ checksum ของ ranked frontiers ชุดเดียวกับ certificate; สำหรับ `MKSTRAT1` จะตรวจ payload checksum กับ combined DFPN binding เพิ่มด้วย ส่วน native 1–3 ตัวตรวจความเข้ากันได้ของ horizon/config แต่ binary ไม่ได้ถูกผูกด้วย checksum ใน certificate การตรวจ closure จะหยุดที่ exact tablebase leaf ที่ยืนยันผลแล้ว ไม่ได้ขยายลูกหลานในฐานทั้งหมดล่วงหน้า จากนั้นที่โหนดฝ่ายเอนจิ้น ระบบจะเลือกได้เฉพาะตาปลอดภัยใน proof DAG และยกระดับ WDL lower bound เป็นอย่างน้อย DRAW หากสร้าง certificate ด้วย `--all-safe-choices` ระบบจะเก็บตาที่พิสูจน์ว่าไม่แพ้ทุกตาไว้ให้ `best`/`win`, policy–value และ DTM/DTR เลือกภายในชุดนั้น ขณะที่ตาคู่แข่งยังครอบคลุม legal replies ทุกตา หลังเข้าสู่ exact tablebase frontier ระบบจะ derive continuation ที่ไม่แพ้ต่อแบบไดนามิกเฉพาะบนตาฝ่ายเอนจิ้นและเฉพาะเมื่อสถานะกับลูกทุกตาที่จำเป็น probe ได้; ถ้าไม่ครบจะ fail closed เช่นเดียวกับตำแหน่งอื่นนอก DAG ผู้เรียกต้องเปิด native/ranked tablebase handles ไว้ตลอดอายุของ engine/strategy ที่ใช้งาน

สำหรับ final audit ให้เพิ่ม `--independent-rules-audit` กับ `check-proof` ตัวตรวจจะสร้าง legal move และ child state ทุก edge ซ้ำด้วย bitboard implementation แยกใน `makhos/audit_rules.py` ซึ่งไม่เรียก move generator, move application หรือ coordinate helpers ของ Python reference แล้วปฏิเสธ certificate ทันทีหากสอง implementation ต่างกัน รองรับทั้ง JSON DAG และ `MKSTRAT1`; ชุดทดสอบปัจจุบันเทียบสุ่ม 500 ตำแหน่งมากกว่า 1,000 ตา พร้อม targeted capture/promotion/terminal และ closure fixtures แล้ว แต่ยังต้องรันกับ strategy จากตำแหน่งเริ่มต้นจริงหลัง DFPN ปิด root

ไฟล์ header รุ่นแรกไม่มีพื้นที่ reserved สำหรับ cryptographic provenance จึงใช้ `RULESET.json` และ committed `TABLEBASE_PROVENANCE.json` ผูก canonical ruleset SHA-256, audited generator-source bundle SHA-256, metadata/FNV เดิม และ complete-file SHA-256 ของฐาน 4/5/6 ตัวโดยไม่เลื่อน payload หลาย GB คำสั่ง `verify-tablebase-provenance` ตรวจครบทั้งสามชั้น และ `--verify-tablebase-provenance` บังคับตรวจชุดเดียวกันก่อน prover/checker/search เปิดใช้ frontier สำหรับ final audit

ค่า perft เริ่มต้นของ native C core ถูกตรวจเทียบกับชุดอิสระของ World Draughts Forum ถึง depth 10: `7, 49, 392, 3136, 26592, 218695, 1820189, 14533014, 114530830, 861842812` ส่วน Python reference ตรวจถึง depth 7 ชุดทดสอบปกติตรึง depth 1–5 เพื่อให้รันเร็ว และ depth ที่สูงกว่านั้นใช้เป็น extended verification

โฟลเดอร์ `native/` มี C17 bitboard move generator แยกจาก Python reference และ `build_native.ps1` จะค้นหา MinGW GCC หรือ LLVM Clang ในตำแหน่งมาตรฐานบน Windows จากนั้นสร้าง `build/makhos_native.exe` การยอมรับ native core ต้องผ่าน perft ชุดเดียวกับ reference ก่อนเสมอ

เมื่อเปิด `--native-tablebase` เอนจิ้นจะสร้าง exact tablebase 3 ตัวในหน่วยความจำหนึ่งครั้ง แล้ว probe ทุกตำแหน่งที่เหลือไม่เกิน 3 ตัวโดยไม่ใช้ heuristic หลาย instance ที่ใช้ DLL/horizon/hash config เดียวกันแชร์ฐานด้วย registry และ refcount; config ที่ขัดกันถูกปฏิเสธ และ native global จะ shutdown เมื่อ instance สุดท้ายปิด การเริ่มครั้งแรกใช้เวลาประมาณสิบกว่าวินาทีและใช้หน่วยความจำหลายร้อย MB บนเครื่องทดสอบ

ไฟล์ `build/tb4_np80.bin` เป็น WDL tablebase 4 ตัวแบบ rank-indexed ที่สร้างครบ 1,005,909,192 สถานะตาม clock กฎ 80 plies ขนาดไฟล์ประมาณ 252 MB ใช้ `--ranked-tablebase build/tb4_np80.bin` เพื่อเปิดผ่าน memory mapping; CLI จะเปิด native 3-piece dependency ให้อัตโนมัติ ตำแหน่งที่พิสูจน์ WIN/LOSS โดย tablebase ซึ่งไม่รวมประวัติ repetition จะแสดงเป็นช่วง `DRAW..WIN`/`LOSS..DRAW` เมื่อใช้กฎเล่นจริงที่มี repetition

ผล WDL ของฐาน 4 ตัวผ่านการตรวจครบทุกตำแหน่งและทุก clock ว่าเข้ารหัสเป็น threshold ได้ จึงมีไฟล์ compact ขนาดประมาณ 12.4 MB ที่ให้ค่าตรงกับไฟล์เดิมครบ 1,005,909,192 states ตัวอ่านแบบ memory-mapped รองรับฐาน compact 4, 5 และ 6 ตัว และ option `--ranked-tablebase` ระบุซ้ำได้เพื่อให้เอนจิ้นเลือกไฟล์ตามจำนวนหมากอัตโนมัติ ตัวสร้าง 5 ตัวบันทึก checkpoint แยกตาม material signature; หากหยุดกลางทาง ให้รันคำสั่งเดิมอีกครั้งเพื่อทำต่อ

ไฟล์ `build/tb5_np80.compact.bin` เป็นฐาน 5 ตัวกฎเต็ม 80 plies ครบ 22,591,030,896 logical states ในไฟล์ประมาณ 279 MB (SHA-256 `718763FB0F7E026E2FBFE09C066B5B40C480D37DF9586F1BE84CBE604466F4CC`) ผ่าน exhaustive rank round-trip/สมมาตรสีที่ clock 0, 79 และ 80 และผ่าน Python differential แบบบังคับหลายกิน 100 ตำแหน่ง ใช้คู่กับฐาน 4 ตัวโดยระบุ `--ranked-tablebase` สองครั้ง

คำสั่ง native `makhos_tb4 prove` เป็น exact AND/OR back-end สำหรับพิสูจน์ non-loss โดยรับ node budget, ขนาด proof hash, ขนาด 3-piece hash, checkpoint และ preferred line ตามลำดับ Checkpoint เขียนแบบแทนที่อย่างปลอดภัยพร้อม checksum และใช้ต่อกับ hash table ที่ใหญ่ขึ้นได้ ผล `UNKNOWN` หมายถึงงบหมดเท่านั้น ไม่ใช่ผลเสมอ

DFPN checkpoint รุ่นปัจจุบันบันทึกเฉพาะโหนดที่ขยายแล้ว โหนดชายขอบที่ยังเป็นค่าเริ่มต้น `pn=1,dn=1` จะถูกสร้างกลับจาก legal moves ของ parent ได้ตรงเดิม ทั้งในไฟล์และระหว่างค้นหาใน RAM จึงยังไม่จอง live hash slot จนกว่าจะถูกเลือกมาขยายจริง Checkpoint v2 เก็บ compact key และ proof codes โดยตรง 16 ไบต์ต่อ record แทน 24 ไบต์ ใช้ `makhos_tb5 compact-dfpn INPUT OUTPUT` (หรือคำสั่งเดียวกันใน `makhos_tb4`) เพื่อแปลง v1/v2 แบบ streaming พร้อมตรวจ checksum; ระบุ INPUT กับ OUTPUT เป็นไฟล์เดียวกันได้เพราะคำสั่งเขียนผ่านไฟล์ชั่วคราวก่อนแทนที่

ตัวโหลด checkpoint รายงานและ flush ความคืบหน้าทุก 25 ล้าน records ส่วน search รายงานทุก 10 ล้าน expansions ตัวเขียน checkpoint กวาด live/solved hash เพียงรอบเดียวโดยสตรีม records ลงไฟล์ชั่วคราว แล้ว seek กลับไปเติม count/checksum ก่อน atomic replace พร้อมรายงานทุก 50 ล้าน slots fixture จาก writer รุ่นก่อนและรุ่นใหม่ตรงกันทั้ง 82 ไบต์และ SHA-256 `9B3EB743EFEC42EFA1510425F2FA430CBE3E1C84940C7C847A9663E357CE0343`

ในหน่วยความจำ DFPN แยก live กับ solved hash ออกจากกัน live entry ขนาด 13 ไบต์เก็บ occupied bitboard และบีบทั้งสีดำกับ king flags ตามลำดับ occupied squares แบบ bijection; solved entry ขนาด 10 ไบต์ใช้คีย์ exact แบบเดียวกัน ไบต์ `expanded` เดิมถูกแทนด้วย marker ใน proof code ที่ encoder ปกติไม่เคยสร้าง ทำให้ยังแยก frontier `(pn=1,dn=1)` ออกจาก expanded node ค่าเดียวกันได้ exact โดย checkpoint 16 ไบต์ไม่เปลี่ยน Proof/disproof ใช้ integer block-float 16 บิตซึ่งมีผลเฉพาะลำดับค้นหา โดยสงวน `0` และ infinity แบบ exact จึงไม่สามารถสร้างผลพิสูจน์ปลอม คำสั่ง `verify-dfpn-codec` ตรวจ colour/king flags ครบอย่างละ 65,536 แบบที่ 16 ตัว, finite counters มากกว่าหนึ่งล้านค่า และ marker transition เครื่องที่มี BMI2 ใช้ PEXT/PDEP อัตโนมัติและมี portable fallback หากตั้ง `MAKHOS_DFPN_HASH_BACKING` live/solved hash จะใช้ไฟล์ memory-mapped บนดิสก์ที่กำหนดแทน pagefile และลบอัตโนมัติเมื่อ process ปิดตามปกติ คำสั่ง `verify-dfpn-disk-backing` ตรวจ zero initialization, boundary writes, normal cleanup และ partial-initialization cleanup โดยอัตโนมัติ

เมื่อต้องการ live capacity มากขึ้นโดยไม่เพิ่ม solved table เกินจำเป็น ใช้ `dfpn-hashes ... LIVE_HASH_POWER SOLVED_HASH_POWER ...` หรือ `dfpn-clock-hashes` และใช้ `dfpn-slots` เมื่อต้องการ capacity ที่ไม่จำเป็นต้องเป็นเลขยกกำลังสอง คำสั่งเดิม `dfpn`/`dfpn-clock` ยังคงแบ่ง slot เท่ากันเพื่อเข้ากันได้กับสคริปต์เดิม หลังลด live entry เป็น 13 ไบต์ โหมดเดิม hash power 28 ใช้สองตารางขนาด 2^27 รวม 3.09 GB, live 28 / solved 27 ใช้ 4.83 GB, live 29 / solved 27 ใช้ 8.32 GB, live 29 / solved 28 ใช้ 9.66 GB และ global workflow ใช้ live 671,088,640 / solved 160,000,000 slots รวม 10.32 GB รองรับ checkpoint 672 ล้าน records โดยใช้ disk-backed mapping เพื่อลด pagefile commit บนเครื่อง RAM 16 GB หลัง reload checkpoint ปัจจุบันจะมี resolved 124,750,486 และ unresolved live 547,810,460 records เหลือ global live headroom เพียงราว 22.61 ล้านก่อนขีด 85% จึงต้องเปลี่ยนเป็น branch partition แทนการขยาย global hash ต่อ

คำสั่ง `plan-six PARTITION_STATES` ใช้ ranker เดียวกับ tablebase เพื่อวางแผนฐาน 6 ตัวโดยไม่จัดสรร payload เต็ม ผลที่พาร์ทิชันละ 8,000,000 states คือ 70 material signatures, 4,852,171,352 placement/turn roots, 393,025,879,512 logical states เมื่อรวม clock 0–80, threshold payload 4,852,171,352 ไบต์ และ 633 rank partitions ตัวสร้าง `makhos_tb6` คำนวณ transition partitions บนดิสก์, ประมวลผล clock layers แบบขนาน, บันทึก checksum checkpoint ทั้ง threshold และ layer เพื่อหยุด–ต่อภายใน signature และประกอบไฟล์ compact เมื่อครบ 70 signatures ฐานทดสอบ no-progress 1 สร้างครบและผ่าน Bellman verification ทุก 4,852,171,352 roots แล้ว แต่ไฟล์ local ถูกลบเพื่อคืนพื้นที่ให้ฐานกฎจริงและสร้างใหม่ได้ด้วยคำสั่ง `build 1` ด้านบน

ฐานกฎจริง 80 plies สร้างครบทั้ง 70 signatures เป็นไฟล์ final `build/tb6_np80.compact.bin` ขนาด 4,852,172,800 ไบต์ ครอบคลุม 4,852,171,352 placement/turn roots และ 393,025,879,512 logical states มี internal FNV `7102f5514870a253` และ SHA-256 `17A0196F3AFEEFD9D57FB00B641045B0EF790B38A64DA73E19DA3F3369D04A4F`; Python อ่านไฟล์และตรวจ checksum ผ่าน ชุด hardened rebuild/smoke ผ่าน, automated suite ปัจจุบันผ่าน 75 tests ใน 40.335 วินาที, official perft ผ่านถึง depth 10 และ child-state differential ผ่าน 1,004 ตำแหน่ง/5,720 ตา พร้อม exact comparisons 5 รายการ หลัง sampled checks ผ่านแล้ว exhaustive `verify-thresholds` แบบ stride 1 ตรวจครบ 4,852,171,352 roots โดย Bellman error และ rank error เป็นศูนย์ ส่วน full `verify-prefix` ที่ clock 0 และ 79 ตรวจครบ clock ละ 4,852,171,352 roots โดย error เป็นศูนย์; ที่ clock 79 มี W/D/L เท่ากับ 1,872,419,814 / 2,183,229,668 / 796,521,870 จึงถือว่าฐานผ่าน acceptance ชุดปัจจุบันแล้ว หลัง acceptance ไฟล์กลาง `.sixpart` 70 ไฟล์ รวม 4,852,175,272 ไบต์ถูกลบเพื่อคืนพื้นที่ โดยสร้างใหม่ได้จาก builder; ไฟล์ compact final ยังคงอยู่

การ rebase checkpoint เดิม 552,998,405 records เข้ากับ frontier 4/5/6 เก็บ exact resolved records ไว้ 106,387,064 และตัด 446,611,341 records ที่ไม่ใช่ solved seed ออก binding เปลี่ยนจาก `5e34484249e74be4` เป็น `72dfbbf22d77e430`; checkpoint หลัง rebase ก่อนค้นหามี internal checksum `09d9fbea4a0e3fda` และ SHA-256 `C903FD65CFF68570B4652E00A13FFF73C541ACF18C26313BF999BEB93E50811D` ต้นฉบับ DFPN5 ถูกเก็บแบบ lossless เป็น `build/dfpn5_initial_seeded.tt.tar.zst` ซึ่งมี SHA-256 `B3ED45CE7366F9FF2782490AADAFCD4B2194092E9B52262AEB328A53DAD8C0F1`; การแตกไฟล์ทดสอบให้ SHA-256 ของต้นฉบับตรงกับ `AEB1B991A39769317A7604EF3B672C4EFA1FA6C5D95E22BDC278542E1D34503D` แล้วจึงลบไฟล์ต้นฉบับที่ไม่บีบอัด

ณ 11 สิงหาคม 2026 ยอดหลัง rebase รวมเป็น 566,173,881 DFPN expansions รอบล่าสุดเพิ่มครบ 100 ล้านด้วย live entry 13 ไบต์ใน 1,432.540 วินาที checkpoint ปัจจุบันมี 672,560,946 records (resolved 124,750,486; unresolved live 547,810,460), internal checksum `8f55a028def49d6d`, SHA-256 `EDCD4E17B7FD1434937C36D3BC5E13BB44ACBC09D2E87EE59D8F18EDE8F7E999` และเขียนแบบ atomic สำเร็จ ตำแหน่งเริ่มต้นยังเป็น `UNKNOWN` ที่ proof/disproof 288,000/1,032,704 ตัวเลขนี้เป็นเพียงความคืบหน้าการค้นหา ไม่ใช่ผลพิสูจน์ว่าเอนจิ้นไม่มีวันแพ้

แผนขยายจาก 3 ตัวไปสู่ proof solver เต็มอยู่ใน [PROOF_ROADMAP.md](PROOF_ROADMAP.md)

## สถานะโครงการ

เสร็จแล้ว:

- reference move generator พร้อม capture chains แบบ atomic
- draw state, promotion และ terminal rules
- correctness-first iterative-deepening alpha-beta พร้อม capture quiescence
- โหมด `best` และ `win`
- ชุดทดสอบกฎสำคัญ
- property tests แบบสุ่มที่ตรวจการกลับสีกระดานและจำนวนหมากหลังเดิน
- exact WDL solver สำหรับตำแหน่งหมากน้อยภายใต้กฎ no-progress ที่กำหนดชัดเจน
- independent bitboard rules auditor สำหรับตรวจทุก proof edge ซ้ำโดยไม่ใช้ reference move generator
- cryptographic tablebase provenance manifest ที่ผูก ruleset, audited generator source และ complete-file SHA-256 ของฐาน 4/5/6 ตัว

### Exact solver

`ExactSolver` ไม่ใช้ heuristic และคืน `WIN`, `DRAW` หรือ `LOSS` พร้อมระยะบังคับชนะ/แพ้ แต่ตั้งใจให้ใช้กับตำแหน่งหมากน้อยก่อน เพราะจำนวนสถานะโตเร็ว ตัว solver กำหนดให้ปิดกฎ repetition และใช้ no-progress counter เป็นตัวทำให้กราฟเกมมีขอบเขต เนื่องจาก repetition แบบสามครั้งต้องเก็บประวัติทั้งเกมและไม่สามารถแทนด้วย board key เพียงตัวเดียวได้ Search ใช้ผล exact อัตโนมัติเมื่อเหลือไม่เกิน 2 ตัว (`--exact-pieces` ปรับได้) ถ้าเปิดกฎเสมอสามครั้ง ผล WIN จาก tablebase อาจลดเป็น DRAW เร็วขึ้น แต่ไม่เปลี่ยนเป็น LOSS

คำสั่ง `verify-endgames` ไล่ครบทุกการวางหมากที่ถูกกติกาสำหรับ 1 ตัวต่อ 1 ตัว ทั้งเบี้ย/ฮอส ทั้งสองฝ่ายเดิน โดยใช้ exact solver เดียวกันจัดประเภท W/D/L ทุกตำแหน่งที่ no-progress clock เท่ากับศูนย์

`gauntlet` เปรียบเทียบ `win` กับ `best` โดยให้ทั้งสองโหมดพบ opening และคู่ต่อสู้ตื้นกว่าแบบเดียวกัน คู่ต่อสู้มี bounded-error model ที่กำหนด seed, อัตราพลาด และ temperature ได้ นี่เป็นเครื่องมือวัดสมมติฐานเรื่อง “เล่นกับคน” ไม่ใช่ตัวแทนข้อมูลมนุษย์จริง

ขั้นต่อไปสำหรับเป้าหมาย “ไม่มีวันแพ้”:

1. ใช้ `retarget-dfpn-solved` สร้าง branch checkpoint จาก exact resolved seed ของ global checkpoint โดยไม่แก้ไฟล์ canonical แล้วเดินกิ่ง `26-22` ด้วย live 130,000,000 / solved 150,000,000 slots ก่อน
2. เดิน branch DFPN จนกิ่งใดกิ่งหนึ่งพิสูจน์ non-loss แล้วนำ solved child กลับมาปิด root/สร้าง certificate; หลัง 566,173,881 global post-rebase expansions สถานะยังเป็น `UNKNOWN`
3. ส่งออก strategy/proof DAG และตรวจ closure ด้วย `check-proof --independent-rules-audit` กับไฟล์จากตำแหน่งเริ่มต้นจริง
4. ใช้ exact/tablebase labels และ self-play ที่ตรวจสอบแล้วพัฒนา policy–value/NNUE โดยไม่ลดชั้น WDL ที่พิสูจน์ได้
