param(
    [string]$RunDirectory = 'D:\ThaiMakhosEngine\build\nnue_gate_b_resume_25690905_122756',
    [int]$EnginePid = 21944,
    [string]$EngineStarted = '2026-09-05T12:27:56.7983670+07:00',
    [ValidateRange(2, 60)][int]$RefreshSeconds = 5,
    [switch]$Once
)

# Read-only observer. Delete sharing lets the arena atomically replace its JSON.
function Read-SharedJson([string]$Path) {
    $sharing = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    $stream = [IO.FileStream]::new($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, $sharing)
    try {
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8)
        try { return ($reader.ReadToEnd() | ConvertFrom-Json) }
        finally { $reader.Dispose() }
    }
    finally { $stream.Dispose() }
}

function Format-Duration([double]$Seconds) {
    if ($Seconds -lt 0 -or [double]::IsInfinity($Seconds) -or [double]::IsNaN($Seconds)) { return 'unknown' }
    $minutes = [Math]::Ceiling($Seconds / 60)
    return ('{0}h {1:00}m' -f [Math]::Floor($minutes / 60), ($minutes % 60))
}

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$checkpointPath = Join-Path $projectRoot 'build\nnue_phase9_gate_b_seed20261102.json'
$initialPath = Join-Path $RunDirectory 'checkpoint_before_resume.json'
$stderrPath = Join-Path $RunDirectory 'stderr.log'
$expectedStart = [DateTimeOffset]::Parse($EngineStarted)
$bound = [Math]::Log(0.95 / 0.05)
$initial = Read-SharedJson $initialPath
try { $Host.UI.RawUI.WindowTitle = 'ThaiMakhos NNUE - LIVE STATUS (read-only)' } catch {}

do {
    try {
        $snapshot = Read-SharedJson $checkpointPath
        $result = $snapshot.result
        $pairs = [int]$result.pairs
        if ($snapshot.format -ne 'thai-makhos-sprt-result-v2' -or
            $result.games -ne (2 * $pairs) -or
            $result.games -ne ($result.wins + $result.draws + $result.losses) -or
            $pairs -ne (($result.pentanomial | Measure-Object -Sum).Sum)) {
            throw 'Invalid checkpoint; waiting for a valid snapshot.'
        }
        $process = Get-Process -Id $EnginePid -ErrorAction SilentlyContinue
        $live = $false
        if ($null -ne $process) {
            try { $live = [Math]::Abs(($process.StartTime.ToUniversalTime() - $expectedStart.UtcDateTime).TotalSeconds) -lt 1 }
            catch { $live = $false }
        }
        $stderrBytes = if (Test-Path -LiteralPath $stderrPath) { (Get-Item -LiteralPath $stderrPath).Length } else { -1 }
        $state = if ($snapshot.complete) { 'FINISHED: ' + $result.status }
            elseif ($live) { 'RUNNING' } else { 'PAUSED / STOPPED - resume needed' }
        $color = if ($snapshot.complete -and $result.status -eq 'PASS') { 'Green' }
            elseif ($live -and $stderrBytes -eq 0) { 'Cyan' } else { 'Yellow' }
        $llr = [double]$result.llr
        $width = 48
        $index = [int][Math]::Round([Math]::Clamp(($llr + $bound) / (2 * $bound), 0.0, 1.0) * $width)
        $bar = ('-' * ($width + 1)).ToCharArray()
        $bar[[int]($width / 2)] = '|'
        $bar[$index] = '*'
        $elapsed = ([DateTimeOffset]::Now - $expectedStart).TotalSeconds
        $newPairs = $pairs - [int]$initial.result.pairs
        $llrGain = $llr - [double]$initial.result.llr
        $estimate = 'Collecting trend (at least 5 new pairs required)'
        if (-not $live) { $estimate = 'Unavailable while the arena is stopped' }
        elseif ($snapshot.complete) { $estimate = 'Gate B finished' }
        elseif ($newPairs -ge 5 -and $elapsed -ge 60 -and $llrGain -gt 0) {
            $estimate = '~' + (Format-Duration (($bound - $llr) * $elapsed / $llrGain)) + ' IF this run trend continues'
        }
        elseif ($newPairs -ge 5) { $estimate = 'No reliable trend toward PASS yet' }

        if (-not $Once) { Clear-Host }
        Write-Host '  THAI MAKHOS  |  NNUE LIVE STATUS' -ForegroundColor Cyan
        Write-Host ('  Updated: ' + [DateTimeOffset]::Now.ToString('yyyy-MM-dd HH:mm:ss zzz', [Globalization.CultureInfo]::InvariantCulture))
        Write-Host ''
        Write-Host ('  Gate B: ' + $state) -ForegroundColor $color
        Write-Host ('  {0:N0} pairs / {1:N0} games    W {2}   D {3}   L {4}' -f $pairs, $result.games, $result.wins, $result.draws, $result.losses)
        Write-Host ''
        Write-Host ('  FAIL -{0:F2} [{1}] +{0:F2} PASS' -f $bound, (-join $bar))
        Write-Host ('  LLR {0:+0.000;-0.000;0.000}     Distance to PASS: {1:F3}' -f $llr, [Math]::Max(0.0, $bound - $llr))
        Write-Host '  * = evidence now; middle | = zero. The marker can move backwards.'
        Write-Host ('  Trend ETA to PASS: ' + $estimate) -ForegroundColor Yellow
        Write-Host '  ETA is a rough projection, not a deadline or guaranteed PASS.'
        Write-Host ('  Pair limit: {0:N0} maximum (not a target; can finish earlier).' -f $snapshot.config.max_pairs)
        Write-Host ''
        Write-Host ('  Elo vs accepted HCE: {0:+0.0;-0.0;0.0} +/- {1:F1} (reported 95% interval)' -f $result.elo, $result.elo_95_error)
        Write-Host ('  Paired results: ' + ($result.pentanomial -join ' / '))
        Write-Host '  Test: 10s clock + 0.1s/move | 1 thread | 256 MiB Hash/engine'
        Write-Host ('  Arena PID: {0} | confirmed live: {1} | stderr: {2} bytes' -f $EnginePid, $live, $stderrBytes)
        if ($stderrBytes -gt 0) { Write-Host ('  Inspect error log: ' + $stderrPath) -ForegroundColor Red }
        Write-Host ''
        Write-Host '  ROAD TO NNUE IN THE GUI'
        Write-Host '  [DONE] Training, quantization, native inference and correctness'
        Write-Host '  [DONE] Sealed offline report and Gate A strength screen'
        Write-Host ('  [NOW ] Gate B primary strength test: ' + $result.status)
        Write-Host '  [NEXT] Gate C: 1s / 2s per move, 12 threads, 512 MiB Hash'
        Write-Host '  [NEXT] Production smoke checks, reversible switch and rollback'
        Write-Host ''
        Write-Host ('  Refresh: {0} seconds. Closing THIS monitor does not stop the arena.' -f $RefreshSeconds) -ForegroundColor DarkGray
    }
    catch {
        Write-Host ('STATUS READ ERROR: ' + $_.Exception.Message) -ForegroundColor Yellow
        Write-Host 'The monitor has not stopped or changed the engine. Retrying...'
        if ($Once) { throw }
    }
    if (-not $Once) { Start-Sleep -Seconds $RefreshSeconds }
} while (-not $Once)
