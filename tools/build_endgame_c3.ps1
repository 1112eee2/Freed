$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$compiler = 'C:\Program Files\LLVM\bin\clang.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'LLVM clang is required' }

# C3 is a disposable candidate artifact.  It never writes the accepted
# production DLL or the frozen NNUE v1 release directory.
$output = Join-Path $repo 'build/native_endgame_c3'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$search = Join-Path $repo 'native/makhos_endgame_search_nnue.c'
$tb = Join-Path $repo 'native/makhos_endgame_tb.c'
$dll = Join-Path $output 'makhos_endgame_search_nnue.dll'

& $compiler -O2 -std=c17 -Wall -Wextra -Werror -Wno-unused-function -shared $search $tb -o $dll
if ($LASTEXITCODE -ne 0) { throw 'Native C3 NNUE endgame compilation failed' }
Get-FileHash -Algorithm SHA256 $dll
