# Proof roadmap: จาก 3-piece tablebase ไปสู่ “ไม่แพ้จากตำแหน่งเริ่มต้น”

## หลักฐานที่มีแล้ว

- Python reference และ C bitboard generator ให้ legal moves ตรงกัน โดย official child-state differential ล่าสุดผ่าน 1,004 ตำแหน่ง/5,720 ตา และ exact WDL/distance comparisons 5 รายการ
- official hardened native rebuild/smoke ผ่าน, automated suite ปัจจุบันผ่าน 75 tests ใน 40.335 วินาที และ C perft ตรงชุดอิสระถึง depth 10
- Exact W/D/L แบบ exhaustive สำเร็จครบทุกตำแหน่ง 1–3 ตัวภายใต้ no-progress 80 plies
- 3-piece tablebase เชื่อมเข้ากับ alpha-beta search แล้ว
- 4-piece WDL tablebase แบบ combinatorial rank สร้างครบ 1,005,909,192 clock-indexed states ที่ no-progress 80 เก็บ 2 bits/state และเชื่อมเข้า search ผ่าน memory mapping แล้ว
- ตรวจครบทุก clock แล้วว่า WDL ของแต่ละตำแหน่ง 4 ตัวเปลี่ยนจาก WIN/LOSS เป็น DRAW ได้ไม่เกินครั้งเดียว จึงบีบอัดเหลือหนึ่ง threshold byte ต่อตำแหน่ง และเทียบค่าครบทั้ง 1,005,909,192 states ตรงกับไฟล์เดิม
- สร้าง 5-piece tablebase ครบทั้งระดับทดสอบ no-progress 1/4 และกฎเต็ม 80 plies แล้ว ฐานเต็มครอบคลุม 22,591,030,896 logical states ใน payload ประมาณ 279 MB พร้อม exhaustive rank/symmetry verification, Python differential, checkpoint/resume และตัวสร้างขนาน 12 เธรดที่ให้ไฟล์ตรงกับ baseline ทุกไบต์
- checkpoint ตำแหน่งเริ่มต้นรุ่น five-frontier เชื่อมฐาน 5 ตัวและผูก checksum ฐาน 4/5 แล้ว frontier ที่ยังไม่ถูกเลือกไม่จองช่องในไฟล์หรือ RAM การแปลงแรกตัด frontier ทิ้งได้ 97,436,643 รายการ จากนั้น compact exact key รุ่นใหม่ลด live/solved entries เหลือ 13/10 ไบต์ โดยฝังสถานะ unexpanded ใน proof-code marker ที่ encoder ปกติไม่สร้างและใช้ block-float counters ที่รักษา zero/infinity exact ทำให้ live power 29 / solved 27 มี 536,870,912 live slots ในตารางรวม 8.32 GB พร้อม BMI2 acceleration; ชุด live power 29 / solved 28 ใช้ 9.66 GB ส่วน workflow ปัจจุบันบน D ใช้ explicit live 671,088,640 / solved 160,000,000 slots รวม 10.32 GB เพื่อลด RAM thrash และใช้ disk-backed mapping แทน pagefile พร้อม automated cleanup verifier Checkpoint v2 ยังคงใช้ record 16 ไบต์และผ่าน v1 migration, v2 byte-identical round-trip, unexpanded omission และ real load/search/write ก่อน rebase checkpoint นี้มี 552,998,405 persistent records (resolved 106,387,064), ไฟล์ 8,847,974,546 ไบต์, ลึกสุด 50 plies และ root ยัง UNKNOWN ที่ proof/disproof 232,704/801,280 ไฟล์ต้นฉบับ SHA-256 `AEB1B991A39769317A7604EF3B672C4EFA1FA6C5D95E22BDC278542E1D34503D` ถูก archive แบบ lossless เป็น `build/dfpn5_initial_seeded.tt.tar.zst` ที่มี SHA-256 `B3ED45CE7366F9FF2782490AADAFCD4B2194092E9B52262AEB328A53DAD8C0F1`; ทดสอบแตก archive แล้วได้ SHA ต้นฉบับตรงกันก่อนลบไฟล์ raw เดิม
- สำรวจ reply ทั้ง 7 หลัง `28-24` แล้วทุกกิ่งยัง UNKNOWN; กิ่ง `6-10` ถูกขยายต่อจนมี 125,999,383 records (resolved 16,190,646) และยัง UNKNOWN ที่ 36,793/147,861 ส่วนกิ่ง `8-12` รุ่นฐาน 5 ตัวใหม่ import exact seed 13,999,312 states แล้วขยาย DFPN 100 ล้านครั้ง มี 113,999,312 records (resolved 16,536,095) และยัง UNKNOWN ที่ 42,438/127,516 สำหรับอีกห้ากิ่ง การสำรวจเท่ากัน 5 ล้านครั้งได้ `5-9` 5,087/20,150, `6-9` 4,837/19,946, `7-10` 4,797/17,598, `7-11` 5,683/15,208 และ `8-11` 5,233/17,000; จากนั้นขยาย `7-10` เพิ่ม 50 ล้านจนมี 68,999,130 records (resolved 14,954,939) และยัง UNKNOWN ที่ 21,152/89,275 โดยพบฐาน 5 ตัวเพียง 67,871 ครั้งในก้อน 50 ล้าน จึงชี้ว่าชั้น 6 ตัวคือคอขวดถัดไป
- ขยาย compact tablebase metadata/reader รองรับ 6 ตัวและ 70 signatures แล้ว ตัวสร้าง transitions/layers แบบ disk-backed เคยสร้างฐาน no-progress 1 ครบ 4,852,171,352 roots และผ่าน Bellman verification ทุก root โดย error 0; ไฟล์นั้นถูกลบภายหลังเพื่อคืนพื้นที่ แต่ผล audit และ hashes ยังบันทึกอยู่ ฐานกฎจริง 80 plies สร้างครบทั้ง 70 signatures เป็น final `build/tb6_np80.compact.bin` ขนาด 4,852,172,800 ไบต์ ครอบคลุม 4,852,171,352 roots และ 393,025,879,512 logical states มี internal FNV `7102f5514870a253`, SHA-256 `17A0196F3AFEEFD9D57FB00B641045B0EF790B38A64DA73E19DA3F3369D04A4F` และผ่าน Python checksum read หลัง sampled threshold/symmetry checks ผ่านแล้ว exhaustive stride-1 `verify-thresholds` ตรวจครบทั้ง 4,852,171,352 roots โดย Bellman error/rank error เป็นศูนย์ และ full `verify-prefix` ที่ clock 0/79 ตรวจ clock ละ 4,852,171,352 roots โดย error เป็นศูนย์; W/D/L ที่ clock 79 เท่ากับ 1,872,419,814 / 2,183,229,668 / 796,521,870 ฐานจึงผ่าน acceptance ชุดปัจจุบันแล้ว หลังจากนั้นลบ intermediate `.sixpart` 70 ไฟล์รวม 4,852,175,272 ไบต์ ซึ่งสร้างใหม่ได้ โดยเก็บ compact final ไว้
- การ rebase จริงอ่าน 552,998,405 records จาก checkpoint five-frontier เก็บ 106,387,064 resolved records และตัด 446,611,341 unresolved records binding เปลี่ยนจาก `5e34484249e74be4` เป็น `72dfbbf22d77e430`; checkpoint หลัง rebase ก่อนค้นหามี internal checksum `09d9fbea4a0e3fda` และ SHA-256 `C903FD65CFF68570B4652E00A13FFF73C541ACF18C26313BF999BEB93E50811D` ที่ 230 ล้าน post-rebase expansions เคยมี 336,387,065 entries (resolved 111,081,043), internal checksum `c9626eea0165a62a` และ root `UNKNOWN` ที่ 140,032/489,216 ที่ 280 ล้าน expansions มี 386,387,065 entries และ root `UNKNOWN` ที่ 162,304/571,392 จากนั้นอีก 100 ล้าน expansions ทำให้ checkpoint มี 486,387,065 entries (resolved 116,220,672), internal checksum `b86c5b06585790d4` รอบถัดไปเดินได้ 86,173,881 expansions ก่อน live hash ถึงขีด 85% และได้ 572,560,946 records checksum `26d5b4b9eaa7bd75` หลังลด live entry เป็น 13 ไบต์ รอบ 11 สิงหาคม 2026 เพิ่มครบอีก 100 ล้านใน 1,432.540 วินาที รวมเป็น 566,173,881 post-rebase expansions checkpoint ปัจจุบันมี 672,560,946 records (resolved 124,750,486; unresolved live 547,810,460), internal checksum `8f55a028def49d6d`, SHA-256 `EDCD4E17B7FD1434937C36D3BC5E13BB44ACBC09D2E87EE59D8F18EDE8F7E999` และ root ยัง `UNKNOWN` ที่ 288,000/1,032,704 การเขียน checkpoint แบบ atomic สำเร็จทุกครั้งที่รายงานนี้อ้างถึง และตัวเลขทั้งหมดเป็นเพียงความคืบหน้าการค้นหา ไม่ใช่ผลพิสูจน์
- workflow รุ่นถัดไปรายงาน checkpoint load ทุก 25 ล้าน records, search ทุก 10 ล้าน expansions และ checkpoint write ทุก 50 ล้าน hash slots ตัวเขียนใหม่สตรีม temp + patch header + atomic replace ด้วยการกวาด hash รอบเดียวแทนสองรอบ โดย checkpoint fixture จาก writer ก่อน/หลัง optimization ตรงกัน byte-for-byte
- ตัวสร้าง proof DAG แบบ AND/OR และ checker แยกโมดูลใช้งานได้แล้ว โดย checker สร้าง legal edges ซ้ำจาก Python reference ตรวจ no-progress horizon และผูก ranked tablebase leaves กับชุด checksum ที่ระบุไว้ Native 1–3 ตัวถูก re-probe ภายใต้ horizon/config ที่ตรงกัน แต่ binary ไม่ได้ถูก checksum-bind ใน certificate การตรวจ closure หยุดที่ exact tablebase leaf และ runtime จะ derive continuation บนตาฝ่ายเอนจิ้นภายหลังเฉพาะเมื่อ dependencies ที่จำเป็น probe ได้ครบ
- มี independent bitboard rules auditor แยกชุดใน `makhos/audit_rules.py` ซึ่งไม่เรียก Python reference move generator/apply/coordinate helpers และ `check-proof --independent-rules-audit` ใช้มันเทียบ notation กับ child state ของทุก proof edge ทั้ง JSON/MKSTRAT1 ชุด differential ผ่าน 500 ตำแหน่งสุ่มมากกว่า 1,000 ตาและ closure fixtures แล้ว งานที่เหลือคือใช้กับ strategy ตำแหน่งเริ่มต้นจริงหลัง root ปิด
- DFPN ที่ปิด root ได้สามารถส่งออก proof DAG v2 โดยตรง ตัว back-end แต่ละรุ่นผูก checksum ของ ranked frontiers ที่ใช้จริง: TB4 ผูก `{4}`, TB5 ผูก `{4,5}` และ TB6 ผูก `{4,5,6}` ตัว checker ตรวจโครงสร้างซ้ำ และ runtime จำกัดการเดินไว้ในชุดตาปลอดภัยจาก DAG ได้จริง
- legacy native DFS/AND-OR back-end มี checksummed checkpoint/resume, ขยาย hash table ข้ามรอบได้ และรับ preferred principal variation เพื่อ seed การค้นหา; การทดลองจากจุดเริ่มสะสม 95,998,404 completed subpositions แล้วแต่ root moves ทั้ง 7 ยังเป็น unknown ตัวเลขนี้เป็นคนละ checkpoint กับ DFPN 552,998,405 records ข้างต้น

## เหตุผลที่ 4 ตัวต้องเปลี่ยนโครงสร้าง (ทำสำเร็จแล้ว)

จำนวนตำแหน่งรากที่ถูกกติกาโดยประมาณเมื่อรวมชนิดเบี้ย/ฮอส สี และฝ่ายเดิน แต่ยังไม่รวม no-progress clock:

| จำนวนหมาก | ตำแหน่งราก |
|---:|---:|
| 2 | 6,976 |
| 3 | 392,064 |
| 4 | 12,418,632 |
| 5 | 278,901,616 |
| 6 | 4,852,171,352 |
| 7 | 68,486,227,248 |
| 8 | 806,380,501,122 |

เมื่อรวม no-progress clock 0–80 ฐาน 5 ตัวมี 22,591,030,896 logical states แต่ผล exhaustive ของฐาน 4 ตัวพิสูจน์สมบัติ threshold monotonic สำหรับ WDL ภายใต้กฎ no-progress ชุดนี้แล้ว รูปแบบใหม่จึงเก็บหนึ่ง byte ต่อ board/turn root: ฐาน 5 ตัวใช้ payload ประมาณ 279 MB แทน 5.26 GiB พร้อมคำนวณทีละ clock layer และ checkpoint ราย signature

exact hash solver รุ่นเดิมใช้ประมาณ 20 bytes ต่อสถานะ และฐาน 3 ตัวสร้าง 14,714,444 สถานะภายใน การขยายตรง ๆ เป็น 4 ตัวจึงมีแนวโน้มใช้ RAM หลาย GB ถึงหลักสิบ GB และไม่เหมาะเป็นฐานสำหรับจำนวนหมากที่สูงกว่า ตัวเลขนี้ไม่ใช่ขนาด entry ของ DFPN รุ่นปัจจุบัน ซึ่งแยก live/solved เป็น 13/10 ไบต์

## โครงสร้าง 4–6 piece tablebase

1. แบ่ง tablebase ตาม material signature `(red men, red kings, black men, black kings)`
2. ใช้ combinatorial ranking แทน hash key เพื่อให้ทุกตำแหน่งมี index แน่นอนโดยไม่เก็บ bitboards ซ้ำ
3. ใช้ W/D/L layers ระหว่างสร้าง แล้วเขียน compact threshold หนึ่ง byte ต่อ board/turn root สำหรับฐาน 4–6 ตัว ไฟล์ ranked ปัจจุบันเก็บ WDL เท่านั้นและยังไม่มี distance sidecar; decisive DTM มาจาก native/Python exact oracle ส่วน ranked DTM/DTR derive แบบ on-demand และคืนค่าเฉพาะเมื่อ traversal ที่จำเป็นเสร็จภายในงบ
4. คำนวณ dependency ตามลำดับ:
   - จำนวนหมากน้อยไปมาก เพราะการกินชี้ไปยัง tablebase ที่เล็กกว่า
   - จำนวนเบี้ยน้อยไปมาก เพราะการเข้าฮอสชี้ไปยัง signature ที่มีเบี้ยน้อยลง
   - no-progress clock จาก 80 ลงมาหา 0 เพราะ quiet move ชี้ไปยัง clock ที่มากขึ้น
5. header v1 ผูก format version, piece/signature dimensions, no-progress horizon, state counts และ payload checksum แต่ไม่มีพื้นที่ reserved สำหรับ hash เพิ่ม โครงการจึงเพิ่ม committed `TABLEBASE_PROVENANCE.json` โดยไม่เลื่อน payload: manifest ผูก canonical `RULESET.json` SHA-256, audited generator-source bundle SHA-256, metadata/FNV และ complete-file SHA-256 ของฐาน 4/5/6 ตัว คำสั่ง `verify-tablebase-provenance` ตรวจไฟล์จริงครบแล้ว และ final proof checker บังคับชั้นนี้ได้ด้วย `--verify-tablebase-provenance`
6. มี differential/Bellman/symmetry checks และ independent bitboard rules auditor แล้ว ตัว auditor ตรวจทุก edge ซ้ำแบบ opt-in ด้วย `--independent-rules-audit`; final audit ของ strategy ตำแหน่งเริ่มต้นยังทำไม่ได้จนกว่า DFPN จะปิด root และส่งออก strategy สำเร็จ

โครงสร้างนี้ตัดวงจรได้โดยไม่ใช้ heuristic: capture ลดจำนวนหมาก, promotion ลดจำนวนเบี้ย และ quiet move เพิ่ม clock จนเป็น draw

## Weak solution จากตำแหน่งเริ่มต้น

การสร้าง strong tablebase ครบ 8 ตัวหรือ 16 ตัวไม่ใช่เส้นทางที่คุ้มที่สุด เป้าหมาย “เอนจิ้นไม่แพ้จากจุดเริ่ม” ต้องการ weak solution เท่านั้น:

สถาปัตยกรรมนี้สอดคล้องกับงาน [Checkers Is Solved](https://www.cefns.nau.edu/~edo/Classes/CS470-570_WWW/Readings/Schaeffer2007.pdf) ซึ่งแยก endgame database, proof-tree manager และ back-end proof solvers ออกจากกัน งานนั้นใช้ฐานท้ายเกมไม่เกิน 10 ตัวร่วมกับ forward proof แทนการสร้าง strong tablebase ครบทั้งเกม ตัวเลขดังกล่าวเป็นเพียงแบบอย่างจาก American checkers ไม่ใช่หลักฐานว่าหมากฮอสไทยต้องใช้ frontier เท่ากัน

1. ไฟล์ rank-partitioned 6-piece frontier กฎ 80 plies สร้างครบและผ่าน exhaustive threshold/prefix acceptance แล้ว; intermediate `.sixpart` ถูกลบหลัง acceptance แต่สร้างใหม่ได้ และ compact final ยังอยู่
2. rebase solved seed เข้ากับ frontier 4/5/6 สำเร็จและเดิน global DFPN ถึง 566,173,881 post-rebase expansions แล้ว แต่ root ยัง `UNKNOWN`; checkpoint เหลือ global live headroom เพียงราว 22.61 ล้าน จึงเพิ่ม `retarget-dfpn-solved` ที่ตรวจ checksum/binding, เก็บเฉพาะ exact resolved records และเปลี่ยน root header แบบ atomic เพื่อเดิน proof-table partition ทีละ root move โดยเริ่มกิ่ง `26-22`
3. ปิด Null Move, LMR และ forward pruning ทุกชนิดใน proof search
4. ส่งออก solved DFPN เป็น proof/strategy DAG ที่ประกอบด้วย move, child hashes และค่าที่พิสูจน์แล้ว พร้อมตัว probe ที่เอนจิ้นใช้เลือกเฉพาะตาใน DAG ระหว่างเกม; การปิดค่า root โดยไม่มี strategy ใช้งานจริงยังไม่นับว่าเป้าหมายสำเร็จ
5. ใช้ checker อ่าน proof DAG และเปิด independent bitboard audit เพื่อสร้าง legal edges/child states ซ้ำจาก implementation คนละชุด แล้วตรวจว่า:
   - ที่โหนดฝ่ายเอนจิ้นมีอย่างน้อยหนึ่ง child ที่รักษาผล non-loss
   - ที่โหนดฝ่ายตรงข้าม legal children ทุกตัวรักษาข้อพิสูจน์
   - leaf ทุกตัวเป็น terminal หรือ exact tablebase entry; ranked 4–6 ต้องตรงกับ checksum set ใน certificate ส่วน native 1–3 ต้องตรง horizon/config แต่ binary ยังไม่ถูก checksum-bind
6. ถ้าค่าตำแหน่งเริ่มต้นเป็น LOSS สำหรับฝ่ายที่เลือก จะรายงานว่าเป้าหมาย “ไม่แพ้” เป็นไปไม่ได้สำหรับฝ่ายนั้น แทนการซ่อนด้วย evaluation

## นโยบายสองโหมดเมื่อมี WDL exact

- `best`: เรียงแบบ lexicographic ด้วย exact WDL ก่อน แล้วจึงใช้ระยะ exact-on-success และ evaluation; ถ้า traversal ระยะไม่ครบต้องคงเป็น `unknown`
- `win`: ห้ามลด WDL จาก WIN เป็น DRAW หรือจาก DRAW เป็น LOSS จากนั้นเลือกตาที่เพิ่มโอกาสพลาดของ bounded/human opponent
- ตำแหน่งนอก proof frontier ใช้ alpha-beta score เป็นค่าชั่วคราวและต้องแสดงว่าเป็น `unknown` ไม่ใช่ exact DRAW
