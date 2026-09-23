param(
    [string]$OutputDirectory = 'build\lazy_smp_candidate_v1',
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $ScriptDir 'build_orchestrator.ps1') -Variant 'lazy_smp_candidate' -OutputDirectory $OutputDirectory -StrictSearchKey -VerifyOnly:$VerifyOnly
