# Phase 1C / C1 Part 2: Native compact TB4–TB6

สถานะ: **KEEP — experimental / default-off, รอตรวจรับ Windows และ artifact จริง**.
ต่อจาก `135aafbf478b3bda4bc317803f2ca403d36e8090`; ไม่ใช่ C2 search integration
หรือ production promotion. หลักฐาน C1 TB3 เดิมยังอยู่ที่ `endgame_c1_tb3/`.

## ขอบเขตและสมมติฐาน

สมมติฐาน: C สามารถ probe compact WDL แบบเดียวกับ Python `RankedTablebase`
ครบ 25/44/70 material signatures โดยเตรียม metadata/ranking ครั้งเดียว และไม่มี
heap allocation, Python callback หรือ dynamic decompression ในแต่ละ probe.

- `native/makhos_endgame_tb.c/.h`: เพิ่ม factory `makhos_tb_set_create` แบบ
  atomic preparation: TB3 optional + compact TB4/5/6 อย่างละไม่เกินหนึ่งไฟล์.
  ถ้าขั้นใดล้มเหลว ปล่อย resource ทั้งหมดและคืน output handle เป็น NULL.
- Windows ใช้ UTF-8 → UTF-16, `CreateFileW` / `CreateFileMappingW` /
  `MapViewOfFile`, read-only และ share read เท่านั้น. POSIX ใช้ `open` /
  `fstat` / `mmap(PROT_READ, MAP_PRIVATE)`. รองรับ offset 64-bit;
  TB6 fixture มีขนาด logical 4,852,172,800 bytes.
- Ranking ของ TB4–6 **ไม่ใช่ colex ของ TB3**: ใช้ completion-count DP ที่มี
  empty-square/type ordering และข้อจำกัดแถวเข้าฮอสตรงกับ `_rank_board`.
  ตาราง DP 33 × 7^4 × 8 = 633,864 bytes เตรียมครั้งเดียวต่อ set, immutable.
  Probe ใช้ stack และอ่าน mapping เท่านั้น; page fault จาก OS ยังเกิดได้.
- ตรวจ magic/version/horizon, canonical signature order, จำนวน boards,
  byte counts, offsets, total positions/states และความยาวไฟล์ทั้งหมดก่อนพร้อม.
  ถอดค่า threshold ตาม clock ใน C; ค่า `0x80` หรือ threshold > horizon เป็น
  CORRUPT แม้ clock ถึง 80 แล้ว. WDL ไม่มี DTM จึงคืน `distance=-1` / `None`.
- status MISS/INVALID/CORRUPT/IO แยกจาก DRAW; ผล probe ใช้ได้เฉพาะ OK.
  ผลลัพธ์ไม่ถูกเขียนทับเมื่อไม่ใช่ OK. ABI v1 เดิมและ TB3 entry point ยังอยู่.

## Ownership และ provenance

Set ไม่เปลี่ยนหลัง create. Python owner ใช้ lock ป้องกัน close แข่งกับ probe;
C worker ถือ retained reference ของตนเองและ probe โดยไม่ผ่าน Python lock.
ห้าม retain จาก pointer ที่ไม่มีเจ้าของ หรือ probe หลังปล่อย reference สุดท้าย.

`ranked_info()` คืน file identity จาก handle ที่เปิดจริง. `mapped_sha256()` hash
bytes ของ mapping ขณะที่ owner ยังถืออยู่ ไม่ reopen pathname ที่อาจชี้ไปอีกไฟล์.
`verify_provenance()` ใช้ contract เดิมของ `makhos.provenance` ตรวจ rules,
generator, file size, header checksum และ SHA-256 ของ mapping ที่ใช้งานจริง.

การตรวจ metadata ไม่ได้แปลว่าผ่าน cryptographic provenance. FNV scan เปิดด้วย
`verify_checksum=True`; SHA/provenance เป็นการตรวจเต็มไฟล์ที่เรียกอย่างชัดเจน
ตอน acceptance/warm-up เท่านั้น ไม่ทำทุก probe, worker หรือ request.
POSIX mapping ไม่ป้องกัน process อื่นแก้/truncate inode เดิม: artifact ต้อง immutable
ตลอดอายุ mapping. Windows ไม่อนุญาตเปิด writer ขณะถือ handle นี้.

**ข้อค้นพบจาก baseline:** `TABLEBASE_PROVENANCE.json` ผูก hash ของ generator
รุ่นเก่า ซึ่งไม่ตรงกับ source bundle ใน `135aafb` และไม่มี compact TB4 binding.
คำสั่ง strict provenance จึงอาจปฏิเสธอย่างถูกต้อง. ไม่แก้ manifest ให้เข้ากับ
candidate เพื่อให้ผ่าน: Local ต้องตรวจ chain ของ generator/artifact เดิมก่อน
ทำ manifest รุ่นใหม่ที่มีหลักฐานรองรับ. Parity report ที่ hash ไฟล์ได้ ไม่ถือว่า
ผ่าน provenance gate โดยอัตโนมัติ.

## Python interface

```python
from makhos.compact_tb3 import CompactTablebase
from makhos.native_endgame import NativeEndgameTablebase

with CompactTablebase() as tb3:
    with NativeEndgameTablebase(tb3, ranked_paths=[
        "build/tb4_np80.compact.bin",
        "build/tb5_np80.compact.bin",
        "build/tb6_np80.compact.bin",
    ]) as tables:
        result = tables.probe(state)
```

`source` เป็น optional สำหรับ ranked-only set; ลำดับไฟล์ไม่จำกัด และ horizon
ทุกไฟล์ต้องตรงกัน. DLL เก่าที่ยังมีเพียง TB3 ใช้ constructor เดิมได้;
หากขอ ranked API ต้อง rebuild isolated C1 library ก่อน.

## ตรวจรับ Windows Local

รันขณะ GUI / arena ว่าง โดยคง Experiment A ที่ 27 คู่เดิมไว้:

```powershell
./tools/build_endgame_c1.ps1
python -B -m unittest tests.test_native_endgame_tb tests.test_native_endgame_ranked -v
python -B tools/verify_endgame_c1.py --output build/native_endgame_c1/windows-suite-part2
python -B -m benchmarks.native_endgame_ranked --tablebase build/tb4_np80.compact.bin build/tb5_np80.compact.bin build/tb6_np80.compact.bin --verify-checksum --output build/native_endgame_c1/windows-real-parity-part2
```

ปรับเฉพาะ path ให้ตรง artifact ที่ Local มี. Output directory ต้องยังไม่มี
เพื่อรักษาผลเดิม. ต้องใช้ Python/OS 64-bit และ temp volume ที่รองรับ sparse files
(NTFS บน Windows); fixture จะขอ `FSCTL_SET_SPARSE` และ fail ชัดเจนหากทำไม่ได้.
ไม่ build/solve TB4–6 จริงใน unit tests.

เกณฑ์ส่งกลับ:

1. Focused 20 tests, zero failures/errors/skips; TB3 48,600 + ranked 360,288
   comparisons แบบกำหนด seed และทุก clock 0–80 ต้องตรงกัน.
2. Full discovery ทุกข้อ; `verify_endgame_c1.py` บันทึก log, จำนวนจริง,
   failures/errors/skips, source/test/library SHA-256, inventory unchanged และ
   protected-data opens. Missing dependencies หรือ skips ไม่ได้ PASS.
3. Parity บนไฟล์จริงต้องเป็น `PARITY_PASS`, `complete_139_signatures=true`;
   ค่า default สุ่มได้สูงสุด 64 ranks/signature พร้อม boundary ranks, ทั้งสองสี
   ทุก clock. Report เก็บ SHA-256 ของ mapping, signature coverage และ W/D/L counts.
   นี่เป็น sampled differential ไม่ใช่ exhaustive proof ของทุกตำแหน่ง.
4. ปิด provenance mismatch ที่อธิบายด้านบนด้วยหลักฐานเดิมก่อนนำ reader ไปใช้
   production; เมื่อตรวจ manifest ได้แล้วรันเพิ่ม `--verify-provenance --manifest ...`.

Build เขียนเฉพาะ `build/native_endgame_c1/makhos_endgame_tb.dll`.
Linux ใช้ `.so` ใน directory เดียวกัน; ไม่ทับ accepted/production DLL หรือ model.
ไม่มีการแก้ `RULESET.json`, `makhos/core.py`, search/history/bounds, GUI routing,
release pointer หรือ checkpoint การทดลอง.

## Linux developer verification

```sh
mkdir -p build/native_endgame_c1
gcc -O2 -std=c17 -Wall -Wextra -Werror -shared -fPIC native/makhos_endgame_tb.c -o build/native_endgame_c1/makhos_endgame_tb.so
python -B -m unittest tests.test_native_endgame_tb tests.test_native_endgame_ranked -v
```

Harness ตรวจ allocation และ memory safety (ใช้ไฟล์ sparse จาก
`tests.test_native_endgame_ranked.write_fixture`, ไม่ใช่ solved tables):

```sh
python -B -c 'from pathlib import Path; from tests.test_native_endgame_ranked import write_fixture; p=Path("build/native_endgame_c1/fixtures"); p.mkdir(exist_ok=True); [write_fixture(p/f"tb{n}.bin", n) for n in (4,5,6)]'
gcc -O1 -g -std=c17 -Wall -Wextra -Werror -fno-omit-frame-pointer -fsanitize=address,undefined native/makhos_endgame_tb.c tests/native_endgame_reader_harness.c -Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=free -o build/native_endgame_c1/reader_sanitize
ASAN_OPTIONS=detect_leaks=0:abort_on_error=1 UBSAN_OPTIONS=halt_on_error=1 build/native_endgame_c1/reader_sanitize build/native_endgame_c1/fixtures/tb4.bin build/native_endgame_c1/fixtures/tb5.bin build/native_endgame_c1/fixtures/tb6.bin
```

ASan/UBSan ตรวจ 100,000 probes: OK 66,036 / INVALID 28,649 / MISS 5,315,
zero allocation ใน probe และ allocation/free counts สมดุลหลัง success/failure
preparation. LeakSanitizer ใช้ไม่ได้ใน container นี้ (`/proc/.../task` ถูกจำกัด);
จึงไม่ได้อ้างว่าได้ผล LSan PASS. เปิด `detect_leaks=1` ได้บน host ที่รองรับ.

ผล cloud แบบผูก source และข้อจำกัด full suite:
`benchmarks/results/endgame_c1_ranked/summary.json`.

| Linux full discovery | พบทั้งหมด | รันจริง | Failures | Errors | Skips |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline `135aafb` | 461 | 418 | 8 | 18 | 64 |
| C1 Part 2 candidate | 474 | 431 | 8 | 18 | 64 |

ชื่อ failures/errors และ skip reasons ตรงกันทุกข้อ; class setup errors ทำให้
จำนวนรันจริงน้อยกว่าที่ค้นพบ. C1 ทั้ง 20 ข้อผ่านใน candidate full discovery.
Source/test inventory คงเดิมและ protected-data opens เป็นศูนย์ทั้งสองรอบ.
Baseline ใช้ source เดิมทั้งหมดและ runner ที่คัดลอกเพิ่มเพื่อบันทึกผล;
isolated baseline library เป็น ELF บน Linux แม้ชื่อ `.dll` ตาม bridge เดิม.

Full Windows suite และ parity บน TB4–6 จริงยังรอ Local; ผล cloud sparse fixture
ไม่ใช่การพิสูจน์ WDL ของฐานข้อมูลจริง. C2 จึงยังต้องรอ acceptance นี้ก่อนเชื่อม
terminal/history-aware WDL bounds เข้า native search. ไม่มีข้อสรุป GUI latency
หรือ Elo จากงาน reader นี้.
