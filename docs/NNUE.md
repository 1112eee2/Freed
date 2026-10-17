# NNUE in Freed

Freed scores positions with a small NNUE (efficiently updatable neural network).
The shipped network is **NNUE v1** (`build/nnue_quantized_v1/model_a.mknnue`,
SHA-256 `07B9AB0F…164C`). In SPRT gates against the hand-written evaluation (HCE)
at 12 threads it gained about **+80 Elo**, at both 1 s and 2 s per move
(see [`releases/nnue-v1-20260908`](../releases/nnue-v1-20260908/)).

This page covers the network's inputs, its shape, how the engine runs it, and how v1
was trained.

## Input features

The feature set is called `thai-makhos-shared-137-v1`. The reference
implementation is [`makhos/nnue_features.py`](../makhos/nnue_features.py), and
every native path must produce the same indices.

Each position is seen from two points of view, the side to move and the opponent.
Each view has its own accumulator and 137 inputs:

| Inputs | Count | Meaning |
|---|---|---|
| Piece on square | 128 | 4 piece kinds × 32 playable squares |
| Reversible clock | 9 | 0, 1–9, 10–19, … 70–79 plies without a capture or man move |

- **Piece kinds are relative to the viewer:** own man, own king, opponent man,
  opponent king. Index = `kind × 32 + square`.
- **Squares are mirrored for red:** black reads squares as 0–31 and red reads
  them as `31 − square`, so both colours see the board from their own side.
- **Exactly one clock input is on.** Its index is `128 + bucket`, where bucket
  0 is a clock of 0 and bucket `1 + plies / 10` covers the rest. At 80 plies the
  game is drawn by rule, so the network is never asked.
- **Few inputs are active:** at most 16 pieces plus 1 clock input, which is
  17 per view. There is no side-to-move input. The order of the two
  accumulators carries that information.

## Network shape

```
side to move: 137 sparse inputs ─► 128 ─┐
                                        ├─► concat 256 ─► 32 ─► 1
opponent:     137 sparse inputs ─► 128 ─┘
```

- Both views share one feature layer (137 × 128 weights plus 128 biases).
- The 128-wide accumulators pass through a clipped ReLU (clamped to 0…1) and are
  joined into 256 values, side to move first.
- A dense layer of 256 → 32 follows, with another clipped ReLU, then a dense
  layer of 32 → 1.
- The output is trained to predict `tanh(cp / 600)`. The engine turns it back
  into centipawns with `600 × atanh(output)` and clips the result to ±2000 cp.

## Quantization and the `.mknnue` file

The engine runs integer arithmetic only. The float model is quantized once,
offline, with these types and scales:

| Part | Type | Scale |
|---|---|---|
| Feature weights, biases, accumulator | int16 | 2048 (1.0 = 2048) |
| Activations after clipped ReLU | int8 | 127 |
| Hidden weights | int8 | 256 |
| Hidden biases and sums | int32 | 127 × 256 |
| Output weights | int8 | 192 |
| Output bias and sum | int32 | 127 × 192 |

A `.mknnue` file is exactly 43,872 bytes: a 188-byte header followed by a
43,684-byte payload.

- **Header:** starts with the magic `MKNNUE1\0` and holds the format version,
  the four dimensions (137, 128, 32, 1), the four scales and the non-terminal
  score bound. It also carries SHA-256 digests that bind the file to the feature
  spec, to [`RULESET.json`](../RULESET.json) and to the float model it was
  exported from.
- **Payload:** little-endian, in this order: feature weights `[137][128]`,
  feature biases, hidden weights `[32][256]`, hidden biases, output weights,
  output bias.

The loader rejects the file if any size, scale, digest or overflow bound is wrong.

## How the engine runs it

- [`native/makhos_nnue_scalar.c`](../native/makhos_nnue_scalar.c) is the plain C
  reference evaluator. It loads and validates the file and defines the exact
  integer results.
- [`native/makhos_nnue_incremental.c`](../native/makhos_nnue_incremental.c)
  holds the accumulators per search ply. After a move it subtracts the inputs
  that turned off and adds those that turned on, so most nodes skip the full
  137 × 128 refresh. A full refresh happens only at the root of a search.
- [`native/makhos_nnue_avx2.c`](../native/makhos_nnue_avx2.c) and
  [`native/makhos_nnue_avx2_update.c`](../native/makhos_nnue_avx2_update.c) do the
  same work with AVX2 and must give bit-identical results. The search build
  requires a CPU with AVX2.
- A build flag (`MAKHOS_NNUE_PARITY_GUARD`) checks every incremental result
  against a full refresh and stops the search on any difference.

Terminal positions, the 80-ply draw, proofs and endgame tablebases are handled by
the search before the network is asked.

## How v1 was trained

The training tools live on the
[`research-archive`](https://github.com/1112eee2/Freed/tree/research-archive)
branch, under `scratch/`. They are research tooling, not part of the engine
package, and the trainer needs PyTorch.

1. **Data** (`nnue_quiet_leaf_acquire.py`): positions were sampled from
   self-play games of the classical engine, each starting with 2–12 random
   opening plies. Each game goes wholly into the training or the validation set,
   and colour-mirrored copies of a position never cross between them. Each
   position was labelled by the classical engine's search at 100, 500 and
   2000 ms. Game outcome and exact tablebase WDL were kept as extra targets.
   v1 used 199,923 training rows and 23,550 validation rows.
2. **Contract** (`nnue_trainer_contract_freezer.py`,
   `nnue_trainer_contract_gate.py`): the data inventories, targets, loss mix and
   optimiser settings are frozen and hashed before training. The trainer refuses
   to run without a passing gate, and the sealed test set stays unopened.
3. **Float training** (`nnue_float_trainer.py`): the main target is the teacher
   score as `tanh(cp / 600)` with a Huber loss, mixed with MSE losses on game
   outcome and WDL. It uses AdamW (peak learning rate 0.001 after a warm-up) and
   checkpoints on validation loss. The released run stopped after 12 epochs and
   kept epoch 7.
4. **Quantization** (`nnue_quantized_export.py`): the float model is exported to
   `.mknnue` with the scales above, and its outputs are checked against the float
   model on the validation set.
5. **Native parity:** the `nnue_*_parity.py` scripts check that the scalar,
   incremental and AVX2 paths agree exactly.
6. **Strength gate:** a search DLL built with `build_nnue_search_candidate.ps1`
   has to pass SPRT against the current release before it ships.

To train a different network, check out `research-archive` and follow the same
steps. A model with new features or a new shape needs a new feature spec and a
new header version, because the loader rejects anything that does not match v1.
