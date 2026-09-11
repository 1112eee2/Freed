<#
.SYNOPSIS
    Backward-compatibility wrapper for NNUE scalar oracle build.
    Canonical build implementation has moved to tools/build/build_orchestrator.ps1.
#>
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'build\nnue_scalar_v1')
)
$ErrorActionPreference = 'Stop'
$orchestrator = Join-Path $PSScriptRoot 'tools\build\build_orchestrator.ps1'
& $orchestrator -Variant 'nnue_scalar' -OutputDirectory $OutputDirectory @args
exit $LASTEXITCODE
