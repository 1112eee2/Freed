<#
.SYNOPSIS
    Backward-compatibility wrapper for C4 endgame build.
    Canonical build implementation has moved to tools/build/build_orchestrator.ps1.
#>
$ErrorActionPreference = 'Stop'
$orchestrator = Join-Path $PSScriptRoot 'build\build_orchestrator.ps1'
& $orchestrator -Variant 'endgame_c4' @args
exit $LASTEXITCODE
