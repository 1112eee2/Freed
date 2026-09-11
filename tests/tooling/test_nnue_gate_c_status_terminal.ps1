# Integration check against the immutable Gate C predecessor and live status.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$statusScript = Join-Path $repoRoot 'tools/arena/nnue_gate_c_status_terminal.ps1'
$checkpoint = Join-Path $repoRoot 'build/nnue_gate_c_1000ms_seed20261105.json'
$invariant = [Globalization.CultureInfo]::InvariantCulture
$expectedTime = ([DateTimeOffset](Get-Item -LiteralPath $checkpoint).LastWriteTime).ToString('yyyy-MM-dd HH:mm:ss zzz', $invariant)
$originalCulture = [Threading.Thread]::CurrentThread.CurrentCulture
try {
    foreach ($testCulture in @('th-TH', 'en-US')) {
        [Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::GetCultureInfo($testCulture)
        $monitorOutput = (& $statusScript -Once 6>&1 | Out-String)
        if (-not $monitorOutput.Contains('Last completed pair: ' + $expectedTime)) {
            throw ('Timestamp/culture regression: ' + $testCulture + $monitorOutput)
        }
        if ($monitorOutput -notmatch '2.0 SECOND / MOVE:') { throw 'Second time control missing' }
        if ($monitorOutput -notmatch '1.0 SECOND / MOVE: FINISHED_PASS') { throw 'Predecessor PASS missing' }
        Write-Output ('Monitor integration PASS: ' + $testCulture)
    }
} finally {
    [Threading.Thread]::CurrentThread.CurrentCulture = $originalCulture
}
