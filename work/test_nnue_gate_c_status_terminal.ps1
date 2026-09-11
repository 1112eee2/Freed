# Backward-compatibility wrapper for test_nnue_gate_c_status_terminal.ps1
# Canonical test has moved to tests/tooling/test_nnue_gate_c_status_terminal.ps1
$ErrorActionPreference = 'Stop'
$target = Join-Path (Split-Path $PSScriptRoot -Parent) 'tests/tooling/test_nnue_gate_c_status_terminal.ps1'
& $target @args
exit $LASTEXITCODE

