param(
    [ValidateRange(2, 60)][int]$RefreshSeconds = 5,
    [switch]$Once
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$python = 'C:\Python314\python.exe'
$controller = Join-Path $PSScriptRoot 'nnue_gate_c_control.py'
$invariant = [Globalization.CultureInfo]::InvariantCulture
try { $Host.UI.RawUI.WindowTitle = 'ThaiMakhos NNUE Gate C - LIVE STATUS' } catch {}

do {
    try {
        $raw = & $python -B $controller status
        if ($LASTEXITCODE -ne 0) { throw 'Status validation failed; inspect controller output.' }
        $snapshot = $raw | ConvertFrom-Json
        if (-not $Once) { Clear-Host }
        Write-Host '  THAI MAKHOS | NNUE GATE C LIVE' -ForegroundColor Cyan
        Write-Host ('  Refreshed: ' + [DateTimeOffset]::Now.ToString('yyyy-MM-dd HH:mm:ss zzz', $invariant))
        Write-Host '  Gate A: PASS | Gate B: PASS | GUI default: HCE (not promoted)'
        Write-Host ''
        foreach ($match in $snapshot.matches) {
            $color = if ($match.state -eq 'FINISHED_PASS') { 'Green' }
                elseif ($match.state -eq 'RUNNING') { 'Cyan' } else { 'Yellow' }
            Write-Host ('  {0:N1} SECOND / MOVE: {1}' -f ($match.budget_ms / 1000),$match.state) -ForegroundColor $color
            if ($null -ne $match.result) {
                $result = $match.result
                Write-Host ('  {0:N0} pairs / {1:N0} games | W {2} D {3} L {4}' -f $result.pairs,$result.games,$result.wins,$result.draws,$result.losses)
                Write-Host ('  LLR {0:+0.000;-0.000;0.000} | FAIL -{1:F3} / PASS +{1:F3}' -f $result.llr,$snapshot.llr_bound)
                Write-Host ('  Elo vs HCE {0:+0.0;-0.0;0.0} +/- {1:F1} (95%, this time control only)' -f $result.elo,$result.elo_95_error)
                $lastPair = [DateTimeOffset]::FromUnixTimeSeconds([long]$match.last_pair_unix).ToLocalTime()
                Write-Host ('  Last completed pair: {0} | {1:N1} minutes ago' -f $lastPair.ToString('yyyy-MM-dd HH:mm:ss zzz', $invariant),([DateTimeOffset]::Now - $lastPair).TotalMinutes)
                Write-Host ('  Buckets: ' + ($result.pentanomial -join ' / '))
            } else {
                Write-Host '  No completed pair yet; startup/first pair is not counted as progress.'
            }
            if ($null -ne $match.process) {
                Write-Host ('  PID {0} | PID/start identity confirmed: {1} | stderr {2} bytes' -f $match.process.pid,$match.identity_confirmed,$match.stderr_bytes)
            }
            if ($match.stderr_bytes -gt 0) { Write-Host ('  Inspect: ' + $match.stderr) -ForegroundColor Yellow }
            Write-Host ''
        }
        Write-Host '  Both time controls must PASS independently, then production smoke + rollback.'
        Write-Host '  Next after promotion: NNUE 1/2/4/6/8/12-thread audit; no SMP gain claimed yet.'
        Write-Host '  LLR can move backwards. It is not a completion percentage; no reliable ETA.' -ForegroundColor Yellow
        Write-Host ('  GUI priority active: ' + $snapshot.gui_active)
        Write-Host ('  Refresh every {0}s. Closing this display does not stop the arena.' -f $RefreshSeconds) -ForegroundColor DarkGray
    } catch {
        Write-Host ('STATUS READ ERROR: ' + $_.Exception.Message) -ForegroundColor Yellow
        if ($Once) { throw }
    }
    if (-not $Once) { Start-Sleep -Seconds $RefreshSeconds }
} while (-not $Once)
