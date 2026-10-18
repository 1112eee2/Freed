# Freed

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Release](https://img.shields.io/badge/release-v1.0.2-green.svg)](https://github.com/1112eee2/Freed/releases)

**Freed** is a strong, rules-exact engine for **Thai Makhos** (หมากฮอสไทย, Thai checkers),
made by Thai people, for Thai people.

> เอนจิ้นหมากฮอสไทย สำหรับคนไทย เพื่อคนไทย โดยคนไทย

- **Exact rules:** forced captures and multi-jumps, flying kings that must land right
  behind the captured piece, immediate piece removal, promotion that ends the move,
  and draws by threefold repetition or 80 plies without progress
- **Native search:** C alpha-beta (PVS, TT, null move, LMR, quiescence on forced captures)
  with multi-threaded root search
- **NNUE evaluation:** an incrementally updated network with AVX2 inference
  ([how it works and how it was trained](docs/NNUE.md))
- **Endgame tablebases:** exact win/draw/loss for every position with 3–6 pieces
  (4.85 billion positions for 6 pieces), built under the 80-ply rule
- **Web GUI:** play in the browser, take back moves, and save games as JSON

## Quick start (Windows)

1. Download `Freed-v1.0.2-windows-x64.zip` from
   [Releases](https://github.com/1112eee2/Freed/releases) and extract it.
2. Download the tablebases from the
   [v1.0.0 release](https://github.com/1112eee2/Freed/releases/tag/v1.0.0) into the `build\` folder next to
   `Freed.exe`, and join the TB6 parts (see [Tablebases](#tablebases)).
3. Run `Freed.exe`. The GUI opens at <http://localhost:8000>.

## From source

Requires Python 3.11+ (no third-party packages for play).

```powershell
git clone https://github.com/1112eee2/Freed.git
cd Freed
python -m makhos perft --depth 6          # move-generation check
python -m makhos bestmove --depth 8       # best move from the start position
python server.py                          # Web GUI (needs the native files below)
python -m makhos uci                      # same engine over a UCI-style text protocol
```

The GUI runs the release that `config/gui_release.json` names and checks every file
against its SHA-256. Copy the `build\` folder from the Windows zip into the
repository, or build the DLLs yourself (they then need their own release manifest).

Build the native libraries with LLVM Clang:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_nnue_search_candidate.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\build_endgame_c4.ps1
```

Install the CLI as a package: `pip install freed-1.0.2-py3-none-any.whl`,
then run `freed --help`.

## Tablebases

| File | Size | SHA-256 |
|---|---|---|
| `tb4_np80.compact.bin` | 12.4 MB | `650B0C86…30E9` |
| `tb5_np80.compact.bin` | 279 MB | `718763FB…F4CC` |
| `tb6_np80.compact.bin` | 4.85 GB | `17A0196F…4A4F` |

GitHub limits release files to 2 GiB, so TB6 is split into three parts. Join them
in `build\`:

```powershell
cmd /c copy /b tb6_np80.compact.bin.part1+tb6_np80.compact.bin.part2+tb6_np80.compact.bin.part3 tb6_np80.compact.bin
```

The full hashes are in [TABLEBASE_PROVENANCE.json](TABLEBASE_PROVENANCE.json).
Tablebase results assume the 80-ply rule and ignore repetition.

## Tests

```powershell
python -m pytest -q
```

Tests that need native binaries or tablebases skip themselves when those files are absent.

## Rules

8×8 board, 32 dark squares, 8 men per side, Black moves first.
Men move and capture forward only. Captures are compulsory and must continue with the
same piece, but any capture chain may be chosen (no maximum-capture rule). Kings move
any distance diagonally but land on the first square behind a captured piece.
Full definition: [RULESET.json](RULESET.json).

## Repository layout

| Path | Contents |
|---|---|
| `makhos/` | Python engine, CLI, GUI server |
| `native/` | C search, NNUE inference, tablebase readers and generators |
| `web/` | Browser GUI |
| `tests/` | Test suite |
| `tools/build/` | Reproducible native build orchestrator |
| `config/`, `releases/` | Hash-bound GUI release selection |
| `docs/` | Design notes ([NNUE](docs/NNUE.md), [text protocol](docs/PROTOCOL.md)) |

Research notes, experiment evidence and SPRT records are on the
[`research-archive`](https://github.com/1112eee2/Freed/tree/research-archive) branch.

## License

[GPL-3.0](LICENSE)

---

**ภาษาไทย:** Freed คือเอนจิ้นหมากฮอสไทยที่ใช้กติกาถูกต้องแม่นยำ ค้นหาด้วย alpha-beta แบบ native
ประเมินกระดานด้วย NNUE และมี tablebase ผลแน่นอนสำหรับหมาก 3–6 ตัว
ดาวน์โหลดไฟล์ Windows จากหน้า Releases แตกไฟล์ วาง tablebase ไว้ใน `build\` แล้วเปิด
`Freed.exe` เพื่อเล่นผ่านเบราว์เซอร์
