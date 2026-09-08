# แผนปฏิบัติการแก้บั๊ก: Endgame Tablebase Repetition Draw

## วัตถุประสงค์
แก้ปัญหาที่ Tablebase Endgames (TB4–TB6) เดินวนจนเสมอซ้ำ 3 ครั้ง (Threefold Repetition) หรือติด 80-ply draw ทั้งที่มีตาบังคับชนะ (เช่น ตำแหน่ง B:BK1,5,6:RK28 เดิน 6-9 แทนที่จะเดินตาชนะ เช่น 6-24, 5-32, 6-10, 6-15, 6-19)

## กฎเหล็ก (Non-Negotiable Invariants)
1. **ห้ามแตะ RULESET.json และ makhos/core.py โดยเด็ดขาด**
2. **ห้ามยุ่งหรือทำลาย checkpoint SPRT 6T vs 12T** (uild/nnue_sprt_6t_vs_12t/sprt_6t_vs_12t_1000ms_seed20261108.json)
3. ทำงานใน worktree D:\ThaiMakhosEngine_tb_fix บน branch ix/tb-repetition-v1

---

## รายละเอียดการแก้ไขใน makhos/search.py

### 1. Unified Terminal Check ใน _negamax() และ _quiescence()
เรียก 	erminal_status(state, repetition_count=counts[state.position_key], rules=self.rules) ที่จุดเริ่มต้นของทั้ง _negamax และ _quiescence ก่อน:
`python
status = terminal_status(state, repetition_count=counts[state.position_key], rules=self.rules)
if status.terminal:
    if status.winner is None:
        return 0, (), WDLBound.exact(Outcome.DRAW)
    return -MATE_SCORE + ply_from_root, (), WDLBound.exact(Outcome.LOSS)
`

### 2. History-Aware Tablebase Cutoff & Bound Narrowing
เมื่อ probe tablebase ผ่าน exact_value = self._probe_exact(state):
- ถ้า exact_bound.exact_outcome is not None (เช่น DRAW หรือเมื่อไม่มีกฎ repetition): คืนค่าได้ทันที 
eturn exact_score, (), exact_bound
- ถ้า exact_bound.exact_outcome is None (เป็นขอบเขต DRAW..WIN หรือ LOSS..DRAW ภายใต้กฎ repetition):
  - **ห้าม** ทำ cutoff ด้วย MATE_SCORE ทันทีเด็ดขาด
  - ให้นำ bound มาจำกัด alpha/beta:
    - ถ้า exact_bound.lower == Outcome.DRAW (ฝ่ายเดินชนะใน TB รับประกันผลอย่างน้อยเสมอ): if alpha < 0: alpha = 0
    - ถ้า exact_bound.upper == Outcome.DRAW (ฝ่ายเดินแพ้ใน TB ปิดโอกาสชนะ): if beta > 0: beta = 0
    - ถ้า lpha >= beta: คืนค่า cutoff ด้วย (alpha if exact_bound.lower == Outcome.DRAW else beta), (), exact_bound
  - ปล่อยให้ search ขยายค้นหาตาตอบของคู่แข่งและตาเดินจริงตามประวัติเกม
  - ใน _quiescence() สำหรับ quiet leaves (
ot moves[0].is_capture):
    - คืนค่า eval ที่ปรับตาม bound (max(eval, 0) ถ้า lower=DRAW, min(eval, 0) ถ้า upper=DRAW) พร้อม exact_bound แทนที่จะตกไปเป็น UNKNOWN_WDL

### 3. TT Isolation ใน Repetition Endgames
ใน _negamax() ป้องกัน TT score cutoff ไม่ให้ตัดคะแนนข้ามประวัติเกมใน endgame ที่อยู่ภายใต้กฎ repetition:
`python
in_repetition_endgame = (
    self.rules.repetition_limit is not None
    and (
        counts[state.position_key] > 1
        or sum(p != EMPTY for p in state.board) <= max(
            self.exact_piece_limit,
            self.native_tablebase.max_pieces if self.native_tablebase is not None else 0,
            max(self.ranked_tablebases, default=0),
        )
    )
)
`
หาก in_repetition_endgame เป็นจริง ให้ข้ามการ return จาก TT score cutoff แต่ยังคงเก็บ TT entry และใช้ 	t_entry.best_move สำหรับ move ordering ตามปกติ

### 4. Exception-Safe Repetition Counting
ครอบ counts[child.position_key] += 1 และ -= 1 ด้วย 	ry...finally ทั้งใน _search_root(), _negamax(), และ _quiescence() ป้องกัน counter ค้างเมื่อติด timeout

### 5. Proved-Win Candidate Prioritization ใน _choose()
- ปรับ _safety_rank(bound) ให้คืน (int(bound.lower), int(bound.upper)) เพื่อจัดอันดับ WIN..WIN > DRAW..WIN > DRAW..DRAW > LOSS..DRAW > LOSS..LOSS
- ใน _choose() สำหรับ Mode.WIN: ตาที่เป็น **Proved Win** (ound.exact_outcome == Outcome.WIN หรือ score >= MATE_SCORE - 10000) ต้องอยู่ก่อนและมีความสำคัญเหนือค่ากดดันคู่แข่ง (pressure) เสมอ

---

## แผนการทดสอบและการตรวจรับ (Verification)
1. รัน python -B work/endgame_diagnosis_20260908/reproduce.py -> ต้องได้ exit 0 (แก้บั๊กผ่าน)
2. ปรับปรุง assertion ใน 
eproduce.py ให้ตรวจว่าตาที่เลือกไม่เปิดให้คู่แข่งเสมอซ้ำสามครั้ง และอยู่ในกลุ่มตาชนะ {5-32, 6-10, 6-15, 6-19, 6-24}
3. เพิ่ม unit test ใน 	ests/test_endgame_repetition.py ให้ครอบคลุม:
   - ป้องกันการเดินวนเสมอใน TB4 ทั้ง Mode BEST และ WIN ที่ depth 1, 2, 3, 8
   - การหาทางดึงเสมอซ้ำ 3 ครั้งเมื่อฝ่ายตนเองเสียเปรียบใน TB
   - กรณีนาฬิกาใกล้ 80 พลาย (
eversible_plies = 78, 79)
4. รัน python -m unittest tests/test_search.py tests/test_endgame_repetition.py -> ต้องผ่าน 100%
5. Commit ลง branch ix/tb-repetition-v1 แล้ว push ขึ้น GitHub
