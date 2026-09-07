$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$Source = Join-Path $ProjectRoot 'native\makhos_native.c'
$BuildDir = Join-Path $ProjectRoot 'build'
$Output = Join-Path $BuildDir 'makhos_native.exe'
$Library = Join-Path $BuildDir 'makhos_native.dll'
$TablebaseSource = Join-Path $ProjectRoot 'native\makhos_tb4.c'
$TablebaseOutput = Join-Path $BuildDir 'makhos_tb4.exe'
$FiveTablebaseSource = Join-Path $ProjectRoot 'native\makhos_tb5.c'
$FiveTablebaseOutput = Join-Path $BuildDir 'makhos_tb5.exe'
$SixTablebaseSource = Join-Path $ProjectRoot 'native\makhos_tb6.c'
$SixTablebaseOutput = Join-Path $BuildDir 'makhos_tb6.exe'

$Compilers = @(
    'C:\Program Files\LLVM\bin\clang.exe',
    'C:\msys64\mingw64\bin\gcc.exe'
)
$Compiler = $Compilers | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Compiler) {
    throw 'No supported C compiler found (looked for MinGW GCC and LLVM Clang).'
}

New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
& $Compiler -O3 -march=native -std=c17 -Wall -Wextra -Werror $Source -o $Output
if ($LASTEXITCODE -ne 0) {
    throw "Native build failed with exit code $LASTEXITCODE"
}
& $Compiler -O3 -march=native -std=c17 -Wall -Wextra -Werror -Wno-unused-function -shared -DMAKHOS_NO_MAIN $Source -o $Library
if ($LASTEXITCODE -ne 0) {
    throw "Native library build failed with exit code $LASTEXITCODE"
}
& $Compiler -O3 -std=c17 -Wall -Wextra -Werror -Wno-unused-function $TablebaseSource -o $TablebaseOutput
if ($LASTEXITCODE -ne 0) {
    throw "Four-piece tablebase build failed with exit code $LASTEXITCODE"
}
& $Compiler -O3 -std=c17 -Wall -Wextra -Werror -Wno-unused-function -fopenmp $FiveTablebaseSource -o $FiveTablebaseOutput
if ($LASTEXITCODE -ne 0) {
    throw "Five-piece tablebase build failed with exit code $LASTEXITCODE"
}
& $Compiler -O3 -std=c17 -Wall -Wextra -Werror -Wno-unused-function -fopenmp $SixTablebaseSource -o $SixTablebaseOutput
if ($LASTEXITCODE -ne 0) {
    throw "Six-piece tablebase build failed with exit code $LASTEXITCODE"
}

Write-Output "Built $Output"
Write-Output "Built $Library"
Write-Output "Built $TablebaseOutput"
Write-Output "Built $FiveTablebaseOutput"
Write-Output "Built $SixTablebaseOutput"
