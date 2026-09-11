<#
.SYNOPSIS
    Backward-compatibility wrapper for native engine and tablebase builds.
    Canonical build implementation has moved to tools/build/build_orchestrator.ps1.
#>
$ErrorActionPreference = 'Stop'
$orchestrator = Join-Path $PSScriptRoot 'tools\build\build_orchestrator.ps1'
& $orchestrator -Variant 'native' @args
exit $LASTEXITCODE
