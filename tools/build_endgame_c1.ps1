<#
.SYNOPSIS
    Backward-compatibility wrapper for C1 endgame build.
    Canonical build implementation has moved to tools/build/build_orchestrator.ps1.
#>
$ErrorActionPreference = 'Stop'
$orchestrator = Join-Path $PSScriptRoot 'build\build_orchestrator.ps1'
& $orchestrator -Variant 'endgame_c1' @args
exit $LASTEXITCODE
