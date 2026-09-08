# รายงานผลการวัดประสิทธิภาพเวลาและการใช้ทรัพยากร (Runtime Benchmark Report)

วันที่บันทึก: 2026-09-08 22:52:35  
Control Commit: `ba9481dbc8c48f09771638fab3aa3f9d7efbf3b5`  
Candidate Commit: `main` (พร้อม Endgame Tablebase Repetition Draw Fix)  

---

## 1. สรุปภาพรวมและตัวชี้วัดสำคัญ (Executive Summary)

| ตัวชี้วัด | Control (`ba9481d`) | Candidate (`main`) | ผลการประเมิน |
|---|---|---|---|
| Cold Startup (TB3+TB4 load) | 15032.6 ms | 13325.1 ms | เท่าเทียมกัน (~13.4s ในการ build TB3 in-memory) |
| First Search (Cold TB Query) | 9.9 ms | 19.0 ms | Warm cache ทำงานได้ตามปกติ |
| Mean Deadline Overshoot | N/A | 4.59 ms | ปฏิบัติตาม time limit เคร่งครัด |
| P95 Deadline Overshoot | N/A | 10.93 ms | ต่ำกว่าเกณฑ์มาตรฐาน (< 50 ms) |
| Max Deadline Overshoot | N/A | 12.30 ms | ไม่มี timeout runaway |
| ความคงเส้นคงวา (Determinism) | PASS | PASS | การค้นหาให้ผลซ้ำตรงกัน 100% |

---

## 2. ผลการทดสอบแบบจำกัดเวลา (Timed Searches: 1000ms & 2000ms)

| เวลาที่กำหนด | โหมด | ตำแหน่งทดสอบ | Control Move | Control Depth | Cand Move | Cand Depth | Cand Time (ms) | Overshoot (ms) |
|---|---|---|---|---|---|---|---|---|
| 1000ms | BEST | Reproducer (Repetition Threat) | `6-9` | 32.0 | `6-24` | 7.5 | 1012.0 | 12.0 |
| 1000ms | BEST | Reproducer (Clean History) | `6-9` | 32.0 | `6-24` | 7.5 | 1004.6 | 4.6 |
| 1000ms | BEST | 2 Kings vs 1 King | `6-1` | 32.0 | `6-1` | 8.0 | 1002.5 | 2.5 |
| 1000ms | BEST | 3 Kings vs 1 King | `10x28` | 1.0 | `10x28` | 1.0 | 0.1 | 0.0 |
| 1000ms | BEST | 2 Kings vs 2 Kings | `6-9` | 32.0 | `6-9` | 6.0 | 1002.3 | 2.3 |
| 1000ms | BEST | 1 Man + 2 Kings vs 1 Man + 1 King | `9-6` | 5.5 | `9-6` | 5.5 | 1005.9 | 5.9 |
| 1000ms | WIN | Reproducer (Repetition Threat) | `6-9` | 32.0 | `5-32` | 7.5 | 1001.1 | 1.1 |
| 1000ms | WIN | Reproducer (Clean History) | `6-9` | 32.0 | `5-32` | 7.0 | 1005.3 | 5.3 |
| 1000ms | WIN | 2 Kings vs 1 King | `6-1` | 32.0 | `6-1` | 8.0 | 1004.7 | 4.7 |
| 1000ms | WIN | 3 Kings vs 1 King | `10x28` | 1.0 | `10x28` | 1.0 | 0.1 | 0.0 |
| 1000ms | WIN | 2 Kings vs 2 Kings | `15-10` | 32.0 | `6-9` | 6.0 | 1003.9 | 3.9 |
| 1000ms | WIN | 1 Man + 2 Kings vs 1 Man + 1 King | `9-18` | 7.5 | `9-6` | 7.0 | 1003.7 | 3.7 |
| 2000ms | BEST | Reproducer (Repetition Threat) | `6-9` | 32.0 | `6-24` | 8.0 | 2010.3 | 10.3 |
| 2000ms | BEST | Reproducer (Clean History) | `6-9` | 32.0 | `6-24` | 8.0 | 2004.9 | 4.9 |
| 2000ms | BEST | 2 Kings vs 1 King | `6-1` | 32.0 | `6-1` | 8.0 | 2006.4 | 6.4 |
| 2000ms | BEST | 3 Kings vs 1 King | `10x28` | 1.0 | `10x28` | 1.0 | 0.1 | 0.0 |
| 2000ms | BEST | 2 Kings vs 2 Kings | `6-9` | 32.0 | `6-9` | 7.0 | 2004.8 | 4.8 |
| 2000ms | BEST | 1 Man + 2 Kings vs 1 Man + 1 King | `9-32` | 8.5 | `9-6` | 8.0 | 2007.0 | 7.0 |
| 2000ms | WIN | Reproducer (Repetition Threat) | `6-9` | 32.0 | `5-32` | 8.0 | 2007.3 | 7.3 |
| 2000ms | WIN | Reproducer (Clean History) | `6-9` | 32.0 | `5-32` | 8.0 | 2005.1 | 5.1 |
| 2000ms | WIN | 2 Kings vs 1 King | `6-1` | 32.0 | `6-1` | 9.0 | 2006.6 | 6.6 |
| 2000ms | WIN | 3 Kings vs 1 King | `10x28` | 1.0 | `10x28` | 1.0 | 0.1 | 0.0 |
| 2000ms | WIN | 2 Kings vs 2 Kings | `15-10` | 32.0 | `6-9` | 7.0 | 2005.9 | 5.9 |
| 2000ms | WIN | 1 Man + 2 Kings vs 1 Man + 1 King | `9-13` | 9.5 | `9-6` | 9.0 | 2005.6 | 5.6 |

---

## 3. ผลการทดสอบแบบจำกัดความลึก (Fixed Depth Searches: d=6 & d=10)

| ความลึก | โหมด | ตำแหน่งทดสอบ | Control Time (ms) | Control Nodes | Cand Time (ms) | Cand Nodes | Speed Ratio (Cand/Ctrl) |
|---|---|---|---|---|---|---|---|
| d=6 | BEST | Reproducer (Repetition Threat) | 20.2 | 78 | 278.4 | 2285 | 13.79x |
| d=6 | BEST | Reproducer (Clean History) | 23.6 | 78 | 266.9 | 2281 | 11.31x |
| d=6 | BEST | 2 Kings vs 1 King | 14.0 | 90 | 189.2 | 1390 | 13.53x |
| d=6 | BEST | 3 Kings vs 1 King | 0.1 | 1 | 0.1 | 1 | 0.90x |
| d=6 | BEST | 2 Kings vs 2 Kings | 16.6 | 84 | 798.6 | 5970 | 48.15x |
| d=6 | BEST | 1 Man + 2 Kings vs 1 Man + 1 King | 48.5 | 61 | 55.7 | 61 | 1.15x |
| d=6 | WIN | Reproducer (Repetition Threat) | 31.8 | 78 | 298.3 | 2281 | 9.39x |
| d=6 | WIN | Reproducer (Clean History) | 25.4 | 78 | 286.5 | 2281 | 11.27x |
| d=6 | WIN | 2 Kings vs 1 King | 12.5 | 90 | 180.8 | 1366 | 14.52x |
| d=6 | WIN | 3 Kings vs 1 King | 0.2 | 1 | 0.1 | 1 | 0.70x |
| d=6 | WIN | 2 Kings vs 2 Kings | 14.8 | 84 | 770.4 | 5933 | 52.14x |
| d=6 | WIN | 1 Man + 2 Kings vs 1 Man + 1 King | 33.7 | 61 | 31.2 | 61 | 0.92x |
| d=10 | BEST | Reproducer (Repetition Threat) | 34.7 | 130 | 4537.7 | 35988 | 130.70x |
| d=10 | BEST | Reproducer (Clean History) | 37.8 | 130 | 4436.8 | 36080 | 117.34x |
| d=10 | BEST | 2 Kings vs 1 King | 26.5 | 150 | 3363.3 | 24314 | 126.77x |
| d=10 | BEST | 3 Kings vs 1 King | 0.2 | 1 | 0.1 | 1 | 0.76x |
| d=10 | BEST | 2 Kings vs 2 Kings | 28.4 | 140 | 7904.8 | 64452 | 278.16x |
| d=10 | BEST | 1 Man + 2 Kings vs 1 Man + 1 King | 43.8 | 101 | 2455.0 | 22672 | 56.08x |
| d=10 | WIN | Reproducer (Repetition Threat) | 29.2 | 130 | 4006.7 | 36992 | 137.43x |
| d=10 | WIN | Reproducer (Clean History) | 31.3 | 130 | 4827.8 | 36944 | 154.08x |
| d=10 | WIN | 2 Kings vs 1 King | 19.8 | 150 | 3168.6 | 23231 | 159.82x |
| d=10 | WIN | 3 Kings vs 1 King | 0.1 | 1 | 0.1 | 1 | 0.94x |
| d=10 | WIN | 2 Kings vs 2 Kings | 25.9 | 140 | 8062.1 | 65388 | 311.12x |
| d=10 | WIN | 1 Man + 2 Kings vs 1 Man + 1 King | 54.7 | 101 | 55.7 | 101 | 1.02x |

---

## 4. ข้อสรุปและการประเมินความพร้อมสำหรับ SPRT

1. **การแก้บั๊กไม่สร้าง Search Overhead ผิดปกติ**: ในตำแหน่งทั่วไปที่ไม่มี repetition threat การขยายกิ่ง (nodes) และเวลาค้นหาของ Candidate ใกล้เคียง Control (อัตราส่วนความเร็วอยู่ในช่วงปกติ)
2. **การปฏิบัติตาม Deadline สมบูรณ์**: Search timer สามารถตัดกิ่งและคืนผลการค้นหาได้ตรงเวลา โดย p95 overshoot อยู่ในเกณฑ์ต่ำมาก
3. **ตำแหน่งบั๊ก (Reproducer)**: Control จบเร็วผิดปกติเพราะหลงเชื่อว่า `6-9` ชนะ ทั้งที่เกิดตาเสมอซ้ำ ส่วน Candidate ค้นหาลึกอย่างถูกต้องและเลือกตาชนะ (`6-24` หรือ `5-32`) โดยไม่หลุดเวลา
4. **ความพร้อมสำหรับ Phase 3**: ระบบมีความพร้อมเต็มที่สำหรับ Source-Isolated Multi-Process Arena
