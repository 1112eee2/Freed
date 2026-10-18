# Text protocol

`python -m makhos uci` (or `freed uci`) runs the same engine as the GUI over
stdin/stdout, for match managers and engine servers. It loads the release that
`config/gui_release.json` names, checks its hashes, and uses the release's
Threads, Hash and play settings as defaults.

The framing is UCI. Positions and moves use the project's own text: a position
is `B:BM25,26:BK29:RM6:RK1` (side to move first, squares 1–32) and a move is
`22-18`, or `11x18x25` for a capture chain.

## Commands

| Command | Reply |
|---|---|
| `uci` | `id name`, `id author`, the `option` lines, `uciok` |
| `isready` | loads the engine and TB3, then `readyok` |
| `setoption name Threads value N` | `1..12` |
| `setoption name Hash value MB` | `4..1024` (total, shared by all threads) |
| `ucinewgame` | clears the hash and search history |
| `position startpos [moves …]` | |
| `position fen <position> [moves …]` | |
| `go …` | one `info` line, `info string wdl …`, `bestmove <move>` |
| `stop`, `quit` | |

`go` takes `depth N`, `movetime MS`, `btime MS`, `wtime MS`, `binc MS`,
`winc MS` and `movestogo N`. `btime`/`binc` belong to side B of the position
text, the side that moves first from `startpos`; `wtime`/`winc` belong to
side R. A clock is turned into a move time the same way as in SPRT matches.
A timed search is not cut short by a fixed depth.

Send the whole game as `position startpos moves …`: repetition and the 80-ply
rule are counted from the moves. A `fen` position starts with an empty history
and a zero clock.

## Refusals

Every `go` ends with a `bestmove`. When there is nothing to search, the reply
is `info string error: …` followed by `bestmove (none)`:

- an illegal move or a bad position in the last `position` command;
- a finished game (no legal move, repetition, 80-ply rule);
- `go infinite`, `go ponder` and other parameters not listed above;
- an endgame root while TB3 is not loaded (as in the GUI, such a root is not
  searched without it);
- a selected NNUE that did not run.

The search cannot be interrupted. `stop` and `quit` wait for it to finish
within its own limits. `isready` is answered at once, even during a search.

The protocol does not take the GUI's interactive lease, so batch work such as
an SPRT match keeps running beside it.
