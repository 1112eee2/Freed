# Goal: เพิ่มความแข็งแกร่งจาก baseline ด้วยหลักฐาน

สถานะ 2026-09-23: งานหลักคือ strength research บน NNUE baseline ที่ใช้อยู่
พักการขยาย Lazy SMP move-hints; G2 = NOT_PASSED และ candidate =
REJECT_FOR_PERFORMANCE / NOT_PROMOTED ตาม [PR #26](https://github.com/1112eee2/ThaiMakhosEngine/pull/26).
การพักนี้ไม่เปลี่ยน gate เป็น PASS และไม่ลบหลักฐานใด

## วงจรสั้น

หนึ่งสมมติฐาน → หนึ่งแพตช์/การวัดที่จำเป็น → correctness → benchmark →
KEEP / REJECT / INCONCLUSIVE → งานถัดไปหนึ่งงาน
รายงาน Elo เฉพาะเมื่อมีหลักฐาน paired match ตาม contract.
จำนวน tests, depth, NPS และ loss ไม่ใช่ Elo.

ผู้ใช้ให้ทำต่อเป็น loop. งานอัตโนมัติทำงานเป็นรอบทุกชั่วโมง อ่านสถานะจริงและ
commit ก่อนเริ่ม ไม่รันซ้อน ไม่สร้าง PR/แผนซ้ำระหว่างรอ dependency.
ส่งผลเมื่อมีความคืบหน้าจริง; ถ้าติด Local ให้ระบุสิ่งที่ต้องใช้ครั้งเดียวและรอผล.
ไม่ merge/promote หรือเปิด SPRT ตามข้อห้ามที่ยังมีผล.

## สิ่งที่ตรวจแล้วในรอบเริ่มต้น

- Main ที่ตรวจ: `a0f79645d9803680a6aa42ae910d49dee1d89f52`; PR #25 head `7cca706377f5e963431fc0f251b91add8673a136`.
- ไม่เปิด qsearch optimization เก่าซ้ำ: ledger หัวข้อ
  `2026-08-23 qsearch production SPRT closure and telemetry refresh`
  บันทึก 500 เกมผล INCONCLUSIVE; single-capture fastpath ถูกเปิดที่ source แล้ว.
- Profile Local รุ่น NNUE รายงาน qsearch 51.4–64.7% ของ nodes.
  นี่ไม่ใช่ CPU-time attribution และไม่พิสูจน์ว่ามีงานที่ตัดทิ้งได้.
  Raw Round 1 Windows profile ไม่ได้ตรวจซ้ำจากไฟล์ Local ในรอบนี้.
- [analysis ของเกม 6ef62f9998d12db4](https://github.com/1112eee2/ThaiMakhosEngine/blob/7cca706377f5e963431fc0f251b91add8673a136/benchmarks/game_reviews/saved_games_corpus_audit_20260923/analysis_6ef_ply8_10_12_12t.json)
  มีอยู่จริง แม้ README/current-state บางย่อหน้ายังบอกว่ารอรัน.
  ใช้ JSON ที่ตรึง commit เป็นหลักฐาน; ไม่เขียนทับผลเดิม.
- สรุปที่คำนวณจาก JSON อยู่ใน [reviewed_game_signal.json](reviewed_game_signal.json).
  Ply 8 เลือกตาเดิมทั้งสองเวลา; ply 10 ตา `3-7` ต่ำกว่าตาที่เลือกใหม่
  60/69 หน่วยใน search เดียวกัน; ply 12 เปลี่ยนตาเมื่อเพิ่มเวลา.
  คะแนนเหล่านี้เป็น engine-score units ไม่ใช่ Elo/solved labels.
- Ply 10 ถูกเครื่องมือจัด `settings-or-version-mismatch` แต่รายการ
  provenance mismatches ว่าง จึงยังอ้างว่าโหลด DLL/model ผิดไม่ได้.
  และ 5s ที่บันทึกกับ 5s ที่ค้นใหม่จบคนละ depth.

## งานถัดไปเพียงงานเดียว: BASELINE_HORIZON_01

สมมติฐานที่หักล้างได้: ความแตกต่างที่ ply 10/12 เกี่ยวกับขอบเขตการค้นหาและ
iteration ที่จบ ซึ่งอาจให้เป้าหมายแก้ search บน baseline ได้ โดยไม่ต้องใช้ SMP ใหม่.
ยังไม่สรุปว่าเป็น selective-search defect, evaluator defect หรือ blunder ที่พิสูจน์แล้ว.

ใช้เครื่องมือ `analyze-game` ที่มีอยู่ ไม่เพิ่ม backend/flag/entrypoint.
รอบนี้ไม่มี engine/source change และไม่มีการฝึกโมเดล.

Inputs:
- Tooling checkout แยกที่ `7cca706377f5e963431fc0f251b91add8673a136` (มี `--nnue-model`).
  ใช้เพื่อเรียก analysis เท่านั้น; ห้าม build หรือเปิด Lazy SMP จาก checkout นี้.
- DLL เกมเดิม SHA-256 `32c323026a7f78ccd9c4013fc3067422a564ee3d0a6ade4f1ce5c62356747e79`.
- NNUE v1 model SHA-256 `07b9ab0f83e253cb74b2acd2bd5291f5f91eb086e042790f33ea0a8c0914164c`.
- เกมและ history/clock ตาม manifest ใน audit directory เดิม.
- 512 MiB ต่อ search, project rules, plies 8/10/12.
  Ply 8 เป็น control ภายในเกม; ทั้งสามจุดเป็น development ไม่ใช่ acceptance set.

ก่อนเริ่ม Local ต้องตรวจ GUI/workload lease และ hashes.
ห้ามหยุด Arena/เกมผู้ใช้เพื่อรันงานนี้. หากไม่ว่างให้รอ ไม่เพิ่มงานซ้อน.
ใช้ Low/BelowNormal และ output ใหม่ `build/strength_horizon_01/<unique-run-id>/`.
ตรวจว่า output ยังไม่มี; เก็บ compiler/DLL/model/tooling identities และทุก stdout/stderr/exit/time.

Matrix ตรึงก่อนรัน: 8 fresh processes, 2 repeats × 2 thread settings × 2 modes:
1. Timed: threads 1 และ 12, depth cap 64, budgets 5000/10000 ms.
2. Depth-capped control: threads 1 และ 12, depth cap 22, budgets 20000/30000 ms
   (CLI ต้องการอย่างน้อยสอง budget ที่ต่างกัน; คาดว่าจบ depth เดียวกันก่อน timeout).
แต่ละ process อ่าน plies 8/10/12 ครบ. ลำดับ repeat แรก 1T→12T,
repeat ที่สอง 12T→1T; ภายใน role ให้ timed ก่อน depth-capped.
จำกัด 180s/process และ 25 นาทีรวม. ไม่เพิ่ม repeat หรือเปลี่ยน seed เพื่อหา PASS.
หาก process timeout ให้เก็บ partial evidence และยุติเฉพาะ process ที่งานนี้สร้าง;
หาก GUI ขอทรัพยากรให้พักที่ขอบเขตปลอดภัยและบันทึก slot ที่ยังไม่ได้รัน.

คำสั่งต่อ process (แทนค่าตาม matrix; ทุก output ต้องใหม่):

```powershell
python -B -m makhos analyze-game --game <absolute-game-path> --library <verified-existing-nnue-dll> --nnue-model <verified-v1-model> --side engine --rules-profile project --ply 8 --ply 10 --ply 12 --threads <1-or-12> --hash-mb 512 --depth 64 --budget-ms 5000 --budget-ms 10000 --max-positions 3 --output <new-timed-json>
python -B -m makhos analyze-game --game <absolute-game-path> --library <verified-existing-nnue-dll> --nnue-model <verified-v1-model> --side engine --rules-profile project --ply 8 --ply 10 --ply 12 --threads <1-or-12> --hash-mb 512 --depth 22 --budget-ms 20000 --budget-ms 30000 --max-positions 3 --output <new-depth-json>
```

นี่ไม่ใช่ strict fixed-depth หากไม่จบ depth 22:
สำหรับ 12T ต้องตรวจ common_depth และทุก root row; 1T อาจไม่มี root_moves
จึงตรวจ completed depth ของผลหลัก. หากไม่ครบให้ TIME_LIMITED/INCONCLUSIVE
แทนการอ้าง parity.
อย่าคาดว่า 1T และ root-split ต้อง node/score-identical โดยนิยาม.
ตรวจ implementation แล้ว: analyze-game เรียก searcher.clear() ก่อนแต่ละ budget.
แต่ละ process แยกจากเกม GUI. การเทียบ 1T กับ metadata เกม 12T ย่อมมี
threads mismatch ตามที่ตั้งใจ ไม่ตีความ classification ที่เครื่องมือสร้างเป็น defect.

Decision:
- ถ้า within-role fixed-depth ไม่ซ้ำเดิม ให้ตรวจ state/provenance ก่อนเสนอ heuristic.
- ถ้า fixed-depth ซ้ำเดิม แต่ timed เปลี่ยนตาม completed depth:
  เก็บเป็น horizon signal; ดู root alternatives/critical line เพื่อเลือกแพตช์หนึ่งจุด.
- ถ้า 1T/12T ต่างกัน ให้แยก root scheduling/strength scope ก่อนอ้าง NNUE ผิด.
- ถ้าผลไม่สนับสนุนสมมติฐาน ให้ REJECT/INCONCLUSIVE และเลือกงานใหม่จากหลักฐาน;
  ไม่ขยาย matrix ต่ออัตโนมัติ.
- ห้ามปรับ weights จากสามตำแหน่งนี้. NNUE v2 ต้องมี independent development
  data/learning curve และ fresh sealed split ของตัวเอง.

## Boundary และการรับช่วง

Web รอบนี้ตรวจ source/JSON และคำนวณ score gaps เท่านั้น ไม่ได้รัน Windows engine.
สถานะ execution: BLOCKED_ON_LOCAL_DLL_MODEL_AND_WINDOWS.
Local คืน 8 slot records + raw logs/results + manifest ผ่าน PR โดยไม่อัปโหลด DLL/model/TB.
Astra อ่านผลแล้วเลือกแพตช์ strength หนึ่งแนวคิดบน isolated baseline;
ไม่ต้องปิด G2 ของ candidate ที่พักไว้ก่อน.

Invariants เดิมทั้งหมดคงอยู่: RULESET.json, makhos/core.py, accepted DLL,
production profile/model, checkpoints และ frozen r3/r4/r5/results.
ไม่แก้ production atomics. การยืนยัน strength/promotion ยังต้องผ่าน contract
ที่ได้รับอนุญาตต่างหาก; รอบนี้ไม่มี match launch.
