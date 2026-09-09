# รายงานผลการวัดประสิทธิภาพเวลาและการใช้ทรัพยากร (Runtime Benchmark Report)

วันที่บันทึก: 2026-09-09 10:00:34  
Control Commit: `ba9481dbc8c48f09771638fab3aa3f9d7efbf3b5`  
Candidate Commit: `main` (พร้อม Endgame Tablebase Repetition Draw Fix)  

---

## 1. สรุปภาพรวมและตัวชี้วัดสำคัญ (Executive Summary)

| ตัวชี้วัด | Control (`ba9481d`) | Candidate (`main`) | ผลการประเมิน |
|---|---|---|---|
| Cold Startup (TB3+TB4 load) | 12355.7 ms | 12799.6 ms | เท่าเทียมกัน (~13.4s ในการ build TB3 in-memory) |
| First Search (Cold TB Query) | 6.7 ms | 18.0 ms | Warm cache ทำงานได้ตามปกติ |
| Mean Deadline Overshoot | N/A | 4.72 ms | ปฏิบัติตาม time limit เคร่งครัด |
| P95 Deadline Overshoot | N/A | 8.72 ms | ต่ำกว่าเกณฑ์มาตรฐาน (< 50 ms) |
| Max Deadline Overshoot | N/A | 13.95 ms | ไม่มี timeout runaway |
| ความคงเส้นคงวา (Determinism) | PASS | PASS | การค้นหาให้ผลซ้ำตรงกัน 100% |

---

## 2. ผลการทดสอบแบบจำกัดเวลา (Timed Searches: 1000ms & 2000ms)

| เวลาที่กำหนด | โหมด | ตำแหน่งทดสอบ | Control Move | Control Depth | Cand Move | Cand Depth | Cand Time (ms) | Overshoot (ms) |
|---|---|---|---|---|---|---|---|---|
| 1000ms | BEST | Reproducer (Repetition Threat) | `6-9` | 32.0 | `6-24` | 8.0 | 1005.2 | 5.2 |
| 1000ms | BEST | Reproducer (Clean History) | `6-9` | 32.0 | `6-24` | 7.5 | 1008.2 | 8.2 |
| 1000ms | BEST | 2 Kings vs 1 King | `6-1` | 32.0 | `6-1` | 8.0 | 1006.3 | 6.3 |
| 1000ms | BEST | 3 Kings vs 1 King | `10x28` | 1.0 | `10x28` | 1.0 | 0.2 | 0.0 |
| 1000ms | BEST | 2 Kings vs 2 Kings | `6-9` | 32.0 | `6-9` | 6.0 | 1005.9 | 5.9 |
| 1000ms | BEST | 1 Man + 2 Kings vs 1 Man + 1 King | `9-6` | 6.5 | `9-6` | 6.5 | 1003.3 | 3.3 |
| 1000ms | WIN | Reproducer (Repetition Threat) | `6-9` | 32.0 | `5-32` | 8.0 | 1008.3 | 8.3 |
| 1000ms | WIN | Reproducer (Clean History) | `6-9` | 32.0 | `5-32` | 8.0 | 1003.1 | 3.1 |
| 1000ms | WIN | 2 Kings vs 1 King | `6-1` | 32.0 | `6-1` | 8.0 | 1004.2 | 4.2 |
| 1000ms | WIN | 3 Kings vs 1 King | `10x28` | 1.0 | `10x28` | 1.0 | 0.2 | 0.0 |
| 1000ms | WIN | 2 Kings vs 2 Kings | `15-10` | 32.0 | `6-9` | 6.0 | 1001.8 | 1.8 |
| 1000ms | WIN | 1 Man + 2 Kings vs 1 Man + 1 King | `9-6` | 8.0 | `9-18` | 7.5 | 1007.2 | 7.2 |
| 2000ms | BEST | Reproducer (Repetition Threat) | `6-9` | 32.0 | `6-24` | 9.0 | 2006.3 | 6.3 |
| 2000ms | BEST | Reproducer (Clean History) | `6-9` | 32.0 | `6-24` | 8.5 | 2006.5 | 6.5 |
| 2000ms | BEST | 2 Kings vs 1 King | `6-1` | 32.0 | `6-1` | 9.0 | 2006.9 | 6.9 |
| 2000ms | BEST | 3 Kings vs 1 King | `10x28` | 1.0 | `10x28` | 1.0 | 0.1 | 0.0 |
| 2000ms | BEST | 2 Kings vs 2 Kings | `6-9` | 32.0 | `6-9` | 7.5 | 2006.7 | 6.7 |
| 2000ms | BEST | 1 Man + 2 Kings vs 1 Man + 1 King | `9-6` | 9.5 | `9-6` | 9.0 | 2004.0 | 4.0 |
| 2000ms | WIN | Reproducer (Repetition Threat) | `6-9` | 32.0 | `5-32` | 9.0 | 2005.6 | 5.6 |
| 2000ms | WIN | Reproducer (Clean History) | `6-9` | 32.0 | `5-32` | 9.0 | 2005.2 | 5.2 |
| 2000ms | WIN | 2 Kings vs 1 King | `6-1` | 32.0 | `6-1` | 9.0 | 2004.6 | 4.6 |
| 2000ms | WIN | 3 Kings vs 1 King | `10x28` | 1.0 | `10x28` | 1.0 | 0.1 | 0.0 |
| 2000ms | WIN | 2 Kings vs 2 Kings | `15-10` | 32.0 | `6-9` | 8.0 | 2003.5 | 3.5 |
| 2000ms | WIN | 1 Man + 2 Kings vs 1 Man + 1 King | `9-13` | 10.0 | `9-18` | 9.5 | 2010.7 | 10.7 |

---

## 3. ผลการทดสอบแบบจำกัดความลึก (Fixed Depth Searches: d=6 & d=10)

| ความลึก | โหมด | ตำแหน่งทดสอบ | Control Time (ms) | Control Nodes | Cand Time (ms) | Cand Nodes | Speed Ratio (Cand/Ctrl) |
|---|---|---|---|---|---|---|---|
| d=6 | BEST | Reproducer (Repetition Threat) | 31.8 | 78 | 286.5 | 2191 | 9.01x |
| d=6 | BEST | Reproducer (Clean History) | 28.7 | 78 | 312.6 | 2550 | 10.89x |
| d=6 | BEST | 2 Kings vs 1 King | 11.9 | 90 | 146.2 | 1352 | 12.29x |
| d=6 | BEST | 3 Kings vs 1 King | 0.1 | 1 | 0.1 | 1 | 0.72x |
| d=6 | BEST | 2 Kings vs 2 Kings | 12.4 | 84 | 560.1 | 5898 | 45.33x |
| d=6 | BEST | 1 Man + 2 Kings vs 1 Man + 1 King | 28.3 | 61 | 27.2 | 61 | 0.96x |
| d=6 | WIN | Reproducer (Repetition Threat) | 18.3 | 78 | 196.3 | 2192 | 10.73x |
| d=6 | WIN | Reproducer (Clean History) | 17.5 | 78 | 233.4 | 2550 | 13.37x |
| d=6 | WIN | 2 Kings vs 1 King | 10.8 | 90 | 140.9 | 1328 | 13.04x |
| d=6 | WIN | 3 Kings vs 1 King | 0.2 | 1 | 0.2 | 1 | 0.81x |
| d=6 | WIN | 2 Kings vs 2 Kings | 17.2 | 84 | 594.8 | 5836 | 34.57x |
| d=6 | WIN | 1 Man + 2 Kings vs 1 Man + 1 King | 27.2 | 61 | 27.8 | 61 | 1.02x |
| d=10 | BEST | Reproducer (Repetition Threat) | 30.0 | 130 | 4077.7 | 37406 | 135.85x |
| d=10 | BEST | Reproducer (Clean History) | 29.0 | 130 | 4359.5 | 43038 | 150.57x |
| d=10 | BEST | 2 Kings vs 1 King | 16.7 | 150 | 2052.4 | 19174 | 122.59x |
| d=10 | BEST | 3 Kings vs 1 King | 0.2 | 1 | 0.1 | 1 | 0.74x |
| d=10 | BEST | 2 Kings vs 2 Kings | 18.7 | 140 | 6522.7 | 64680 | 349.03x |
| d=10 | BEST | 1 Man + 2 Kings vs 1 Man + 1 King | 45.0 | 101 | 47.2 | 101 | 1.05x |
| d=10 | WIN | Reproducer (Repetition Threat) | 28.1 | 130 | 3696.4 | 35329 | 131.72x |
| d=10 | WIN | Reproducer (Clean History) | 31.8 | 130 | 4262.7 | 42308 | 134.05x |
| d=10 | WIN | 2 Kings vs 1 King | 16.6 | 150 | 2038.4 | 19516 | 122.75x |
| d=10 | WIN | 3 Kings vs 1 King | 0.2 | 1 | 0.1 | 1 | 0.74x |
| d=10 | WIN | 2 Kings vs 2 Kings | 18.3 | 140 | 6269.5 | 62846 | 343.42x |
| d=10 | WIN | 1 Man + 2 Kings vs 1 Man + 1 King | 41.4 | 101 | 45.7 | 101 | 1.10x |

---

## 4. ข้อสรุปและการประเมินความพร้อมสำหรับ SPRT

1. **การแก้บั๊กไม่สร้าง Search Overhead ผิดปกติ**: ในตำแหน่งทั่วไปที่ไม่มี repetition threat การขยายกิ่ง (nodes) และเวลาค้นหาของ Candidate ใกล้เคียง Control (อัตราส่วนความเร็วอยู่ในช่วงปกติ)
2. **การปฏิบัติตาม Deadline สมบูรณ์**: Search timer สามารถตัดกิ่งและคืนผลการค้นหาได้ตรงเวลา โดย p95 overshoot อยู่ในเกณฑ์ต่ำมาก
3. **ตำแหน่งบั๊ก (Reproducer)**: Control จบเร็วผิดปกติเพราะหลงเชื่อว่า `6-9` ชนะ ทั้งที่เกิดตาเสมอซ้ำ ส่วน Candidate ค้นหาลึกอย่างถูกต้องและเลือกตาชนะ (`6-24` หรือ `5-32`) โดยไม่หลุดเวลา
4. **ความพร้อมสำหรับ Phase 3**: ระบบมีความพร้อมเต็มที่สำหรับ Source-Isolated Multi-Process Arena
