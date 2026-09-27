<#
.SYNOPSIS
    Backward-compatibility wrapper for NNUE search candidate build.
    Canonical build implementation has moved to tools/build/build_orchestrator.ps1.
#>
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'build\nnue_search_v1_r5'),
    [switch]$StrictSearchKey,
    [switch]$TablebaseDrawCutoff,
    [switch]$ReverseFutility,
    [switch]$HistoryMalus
)
$ErrorActionPreference = 'Stop'
$orchestrator = Join-Path $PSScriptRoot 'tools\build\build_orchestrator.ps1'
& $orchestrator -Variant 'nnue_search_candidate' -OutputDirectory $OutputDirectory -StrictSearchKey:$StrictSearchKey -TablebaseDrawCutoff:$TablebaseDrawCutoff -ReverseFutility:$ReverseFutility -HistoryMalus:$HistoryMalus @args
exit $LASTEXITCODE
