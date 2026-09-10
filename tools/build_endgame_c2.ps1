$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$compiler = 'C:\Program Files\LLVM\bin\clang.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'LLVM clang is required' }
$output = Join-Path $repo 'build/native_endgame_c2'
New-Item -ItemType Directory -Force -Path $output | Out-Null
& $compiler -O2 -std=c17 -Wall -Wextra -Werror -Wno-unused-function -shared (Join-Path $repo 'native/makhos_endgame_search.c') (Join-Path $repo 'native/makhos_endgame_tb.c') -o (Join-Path $output 'makhos_endgame_search.dll')
if ($LASTEXITCODE -ne 0) { throw 'Native C2 compilation failed' }
& $compiler -O2 -std=c17 -Wall -Wextra -Werror -Wno-unused-function (Join-Path $repo 'tests/native_endgame_boundaries.c') (Join-Path $repo 'native/makhos_endgame_tb.c') -o (Join-Path $output 'native_endgame_boundaries.exe')
if ($LASTEXITCODE -ne 0) { throw 'Native C2 boundary harness compilation failed' }
Get-FileHash -Algorithm SHA256 (Join-Path $output 'makhos_endgame_search.dll')
