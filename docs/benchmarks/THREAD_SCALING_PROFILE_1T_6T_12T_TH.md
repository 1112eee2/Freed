# รายงานผลการ Profile Baseline การทำงานแบบ Multi-Thread (1T / 6T / 12T)

บันทึก ณ วันที่: 2026-09-11  
Git Commit Head: `e41a2469f2e5cdeb9158a36d0a511f392bac293e`  
สภาพแวดล้อมทดสอบ: Host AMD Ryzen 5 5600H (6 Cores / 12 Logical Threads, Windows x64)  
Binary ที่ใช้:
- Native Search (HCE): `build/makhos_native.dll` (`6F18F2AAD57C...`)
- Endgame C4 Search: `build/native_endgame_c4/makhos_endgame_search_nnue.dll` (`EB8AF04596...`)
- NNUE Model: `build/nnue_quantized_v1/model_a.mknnue` (`07B9AB0F83...`)

---

## 1. ข้อมูลการวัดเชิงประจักษ์ (Empirical Profile Data)

### 1.1 การทดสอบ Middlegame แบบ Fixed Time (งบเวลา 1,000 ms, Total Hash 512 MiB)

| Position | Threads | Depth Reached | Total Nodes | Effective NPS | Wall Time (ms) | CPU Utilization |
|---|---|---|---|---|---|---|
| **Initial Position**<br>(7 legal moves) | 1T | **d=18** | 3,818,496 | 3,806,442 | 1003.2 | 0.99T |
| | 2T | d=16 | 5,008,720 | 5,003,897 | 1001.0 | 1.56T |
| | 4T | d=17 | 8,762,076 | 8,733,268 | 1003.3 | 2.90T |
| | 6T | d=17 | 9,643,531 | 9,616,897 | 1002.8 | 3.09T |
| | 8T | d=17 | 10,488,501 | 10,479,628 | 1000.8 | 3.89T |
| | **12T (Prod)** | d=17 | **10,925,454** | **10,897,532** | 1002.6 | **3.71T** |
| **Middlegame Ply 8**<br>(11 legal moves) | 1T | **d=20** | 3,994,624 | 3,982,080 | 1003.1 | 1.00T |
| | 2T | d=18 | 6,307,942 | 6,305,211 | 1000.4 | 1.83T |
| | 4T | d=19 | 9,857,029 | 9,849,230 | 1000.8 | 3.04T |
| | 6T | d=19 | 9,806,907 | 9,773,304 | 1003.4 | 3.35T |
| | 8T | d=19 | 12,167,415 | 12,155,281 | 1001.0 | 4.00T |
| | **12T (Prod)** | d=19 | **12,618,418** | **12,578,757** | 1003.2 | **4.52T** |

---

### 1.2 การทดสอบ Endgame C4 Multi-Thread Scaling

| Case & Depth | 1T ms (nodes) | 2T Speedup | 4T Speedup | 6T Speedup | 8T Speedup | 12T Speedup |
|---|---|---|---|---|---|---|
| **repetition_win (d=6)** | 16.05 ms (9,941) | 1.11x | 1.38x | 1.31x | 1.38x | 1.25x |
| **4_pieces_kings (d=6)** | 67.78 ms (46,770) | 1.63x | 2.77x | 2.24x | 3.66x | **3.22x** |
| **5_pieces_pawns (d=6)** | 0.08 ms (63) | 0.60x | 0.66x | 0.42x | 0.65x | 0.66x |

---

## 2. หลักฐานการวิเคราะห์คอขวด (Bottleneck Analysis)

จากข้อมูลที่บันทึกได้ ชี้ให้เห็นถึงคอขวดหลัก 5 ประการของระบบ Multi-threading ในปัจจุบัน:

### คอขวดที่ 1: Branch Starvation (การขาดแคลนกิ่งที่ระดับ Root)
- **หลักฐาน**: ในหมากฮอสไทย ตำแหน่งกระดานส่วนใหญ่มีตาเดินถูกต้องตามกฎ (Legal moves) เฉลี่ยเพียง 4–8 ตาเดิน (ตัวอย่าง: ตำแหน่งเริ่มต้นมี 7 ตาเดิน)
- **ผลกระทบ**: เมื่อตั้งค่า `Threads=12` บนตำแหน่งที่มี 7 ตาเดิน จะมี Worker ถึง 5 ตัวที่ **ว่างงานโดยสิ้นเชิง (0% utilization)** ตลอดการค้นหา ทำให้ CPU utilization เฉลี่ยที่ 12T สูงสุดได้เพียง **3.71T** (จากความจุ 12T)

### คอขวดที่ 2: Root-Synchronous Barrier & Slowest-Branch Bottleneck
- **หลักฐาน**: สถาปัตยกรรม `ParallelNativeSearch` บังคับให้ **ทุกกิ่งต้องเสร็จที่ Depth D พร้อมกัน** จึงจะยอมรับผลและก้าวขึ้นสู่ Depth D+1
- **ผลกระทบ**: กิ่งที่มีความซับซ้อนสูง (Tactical branch) จะกลายเป็นตัวถ่วง (Straggler) ทำให้ Worker อื่นๆ ที่คิดกิ่งที่ตื้นกว่าเสร็จแล้วต้องหยุดรอที่ Barrier เกิดการสูญเสียรอบประมวลผลไปอย่างมหาศาล

### คอขวดที่ 3: Search Inefficiency จากการแยก Tree (Depth Reached Paradox)
- **หลักฐาน**: 
  - ที่งบเวลา 1,000 ms:
    * 1T ไปถึง **Depth 18** (initial) และ **Depth 20** (ply 8) ด้วยการค้นหาเพียง ~3.9M nodes
    * 12T แม้จะค้นหาได้ถึง **10.9M – 12.6M nodes** (สูงกว่า 1T เกือบ 3 เท่า) แต่กลับไปถึงได้เพียง **Depth 17 และ Depth 19** เท่านั้น!
- **สาเหตุ**: 
  * 1T ใช้ **Principal Variation Search (PVS)** เต็มรูปแบบ โดยกิ่งแรกค้นด้วยช่วงกว้าง `[alpha, beta]` และกิ่งถัดไปทั้งหมดค้นด้วย Zero-window `[alpha, alpha+1]` ซึ่งตัดต้นไม้ค้นหา (Beta cutoff) ทิ้งได้อย่างมหาศาล
  * Root Split ในปัจจุบันให้แต่ละ Worker แยกกิ่งไปค้นหาแบบอิสระ ไม่ได้รับรู้ Alpha bound หรือ PV จากกิ่งข้างเคียง ทำให้โหนดที่เพิ่มขึ้นใน 12T เป็น **โหนดส่วนเกิน (Speculative / Wasteful work)**

### คอขวดที่ 4: Python Coordinator / GIL Dispatch Latency
- **หลักฐาน**: ในตำแหน่งที่ต้นไม้ค้นหาเล็กมาก เช่น `5_pieces_pawns` การเปิด 12T ทำให้ความเร็วถดถอย (Speedup 0.66x คือช้าลงกว่า 1T)
- **สาเหตุ**: การจัดการ Thread Pool ใน Python ผ่าน `concurrent.futures` และการ Marshalling ข้อมูล ctypes ข้าม boundary ก่อให้เกิด Latency คงที่ (Fixed overhead) ทุกครั้งที่มีการกระจายงาน

### คอขวดที่ 5: SMT Saturation (6 Cores จริง vs 12 Threads เสมือน)
- **หลักฐาน**: การเพิ่ม Thread จาก 6T ไปเป็น 12T ช่วยเพิ่ม Total Nodes ได้เพียง 10%–28% (จาก 9.8M เป็น 12.6M nodes) และ CPU Utilization เพิ่มจาก 3.35T เป็น 4.52T
- **ข้อสรุป**: บนสถาปัตยกรรม 6-core Zen 3 (Ryzen 5 5600H) คอร์เสมือน (Hyperthreads) จะเริ่มชนข้อจำกัดของ Execution Units และ Cache ทันทีที่เกิน 6 Threads

---

## 3. สรุปเกณฑ์เสร็จสิ้นของ Step 3 (Completion Criteria)

- [x] เก็บข้อมูล Profile ที่ 1T, 2T, 4T, 6T, 8T, 12T ครบถ้วนทั้ง Middlegame และ Endgame
- [x] ระบุตัวเลข Wall time, Nodes, NPS, Depth, และ CPU Utilization ชัดเจน
- [x] มีหลักฐานเชิงประจักษ์ระบุสาเหตุคอขวด 5 ประการอย่างเป็นรูปธรรม พร้อมใช้เป็นฐานในการออกแบบ SMP ใน Step 4
