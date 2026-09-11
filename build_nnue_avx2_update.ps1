<#
.SYNOPSIS
    Backward-compatibility wrapper for NNUE AVX2 update oracle build.
    Canonical build implementation has moved to tools/build/build_orchestrator.ps1.
#>
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'build\nnue_avx2_update_v1')
)
$ErrorActionPreference = 'Stop'
$orchestrator = Join-Path $PSScriptRoot 'tools\build\build_orchestrator.ps1'
& $orchestrator -Variant 'nnue_avx2_update' -OutputDirectory $OutputDirectory @args
exit $LASTEXITCODE
