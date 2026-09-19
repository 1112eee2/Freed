# Local ↔ Astra Web coordination — 2026-09-20

เอกสารนี้เป็นจุดประสานงานสำหรับงาน Lazy SMP G2 เท่านั้น ไม่ใช่ผล gate และไม่อนุญาตให้ merge, promote หรือเปิด SPRT

## Local snapshot

- Repository: `1112eee2/ThaiMakhosEngine`
- Local branch: `local/strict-key-acceptance-a0f7964`
- Local HEAD: `34217f3` (`test(lazy-smp): cover terminal-root reasons and stop/clear lifecycle`)
- Worktree มี WIP ที่ไม่ได้ commitอยู่จำนวนมาก; ห้าม `reset`, `clean`, `add -A` หรือ force-push ทับ branch นี้
- Invariants ที่ตรวจใน local:
  - `RULESET.json` = `77528ADDC0E08B17217346C511C7C4084BAD4AF48789955C3EC85EF76A64871F`
  - `makhos/core.py` = `03152E513BD360E6C2C97ECDF08DC58A290DCA0AE6E28889AE70585A381292AB`
  - `build/makhos_native_accepted.dll` = `FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD`

## Astra Web work in progress

อ่านผลจาก branch เหล่านี้ตาม commit จริงเท่านั้น:

1. `codex/astra-g2-r4-pthread-handoff` @ `117c22aa3cf47d1175e1758c70f9af1ab8daa709`
2. `codex/astra-g2-r4-tsan-results-20260916` @ `4c566c9cac6117061285eed8d42765e4da8da7cb`
3. `codex/astra-g2-r4-liveness-measurement` @ `757847a9583824c32265efd4ce0b19dc3c78fc08`

สถานะล่าสุดที่ local ยืนยัน: TSan pthread runtime ใช้งานได้และ negative control ตรวจ race ได้ แต่ G2 ยัง `NOT_PASSED`; มีทั้ง liveness abort และ `move.captured_low == ~move.path_low` payload assertion abort. สาเหตุ payload ยังไม่ถูกระบุว่าเป็น production defect

## งานที่แบ่งกัน

- **Astra Web:** ตรวจ seed-state initialization ใน frozen probe, ทำ diagnostic revision ใหม่โดยไม่แก้ production atomics และส่งหลักฐาน/PR ใหม่
- **Local:** ไม่ทำ probe ซ้ำเพื่อไล่ผลเดียวกัน; รักษา frozen evidence, ตรวจ hash/ขอบเขต PR, เตรียม Round2 time-attribution หลัง correctness gate ชัดเจน
- ผลจาก Astra ต้องผ่านการตรวจ commit, diff, hashes, commands, stdout/stderr และ exit codes ก่อนใช้เป็นหลักฐาน

## เกณฑ์รับผลจาก Astra

- ไม่รับผลจากชื่อ branch หรือข้อความสรุปเพียงอย่างเดียว
- ต้องแยก `confirmed`, `not established`, และ `NOT_RUN/NOT_PASSED`
- ห้ามแก้ assertion หรือ workload เพียงเพื่อให้ PASS; หากเปลี่ยน contract ต้องเป็น revision ใหม่และอธิบาย safety/liveness แยกกัน
- ห้ามอ้างผลนี้เป็น G2–G6 closure, Elo evidence หรือ production approval

## Local next action หลังผลกลับมา

1. ตรวจ PR ใหม่กับเอกสารนี้และ frozen r3/r4 แบบ byte/hash bound
2. ถ้า correctness ยังไม่ผ่าน ให้ปิดงาน Lazy SMP ไว้ที่ `NOT_PROMOTED` และไม่เปิด SPRT
3. ถ้าผ่านตาม contract ใหม่ ค่อยตรวจ current-state ให้ตรง แล้วจึงทำ Round2 profiling แบบ diagnostic-only (elapsed/CPU, overhead, fixed-depth parity) ก่อนเลือก candidate ใหม่

เอกสารนี้ไม่อัปโหลด binary, tablebase, model, checkpoint หรือ secret ใด ๆ
