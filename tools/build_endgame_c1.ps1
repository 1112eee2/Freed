$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$compiler = 'C:\Program Files\LLVM\bin\clang.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'LLVM clang is required for the isolated C1 build' }
$output = Join-Path $repo 'build/native_endgame_c1'
New-Item -ItemType Directory -Force -Path $output | Out-Null
& $compiler -O2 -std=c17 -Wall -Wextra -Werror -shared (Join-Path $repo 'native/makhos_endgame_tb.c') -o (Join-Path $output 'makhos_endgame_tb.dll')
if ($LASTEXITCODE -ne 0) { throw 'Native endgame reader compilation failed' }
Get-FileHash -Algorithm SHA256 (Join-Path $output 'makhos_endgame_tb.dll')
