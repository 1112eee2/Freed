param(
    [Parameter(Mandatory = $true)]
    [string]$CheckpointPath,
    [Parameter(Mandatory = $true)]
    [string]$Position,
    [ValidateRange(0, 126)]
    [int]$Clock,
    [ValidateSet('red', 'black')]
    [string]$Root = 'black',
    [ValidateRange(1, 100)]
    [int]$MaxSteps = 10,
    [UInt64]$ExpansionBudget = 20000000,
    [UInt64]$LiveSlots = 5000000,
    [UInt64]$SolvedSlots = 20000000,
    [int]$Tb3HashPower = 25,
    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$RunPrefix = 'follow',
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$workflowRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildRoot = Join-Path $workflowRoot 'build'
$scratchRoot = Join-Path $workflowRoot 'scratch'
$runner = Join-Path $workflowRoot 'run_dfpn_on_d.ps1'
$native = Join-Path $buildRoot 'makhos_native.exe'
$engine = Join-Path $buildRoot 'makhos_tb6.exe'
$tb4 = Join-Path $buildRoot 'tb4_np80.bin'
$tb5 = Join-Path $buildRoot 'tb5_np80.compact.bin'
$tb6 = Join-Path $buildRoot 'tb6_np80.compact.bin'
$currentCheckpoint = if ([System.IO.Path]::IsPathRooted($CheckpointPath)) {
    $CheckpointPath
}
else {
    Join-Path $workflowRoot $CheckpointPath
}

foreach ($requiredPath in @(
    $runner, $native, $engine, $tb4, $tb5, $tb6, $currentCheckpoint
)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required workflow file is missing: $requiredPath"
    }
}

function Convert-HexStateToPosition {
    param(
        [Parameter(Mandatory = $true)][string]$RedHex,
        [Parameter(Mandatory = $true)][string]$BlackHex,
        [Parameter(Mandatory = $true)][string]$KingsHex,
        [Parameter(Mandatory = $true)][int]$Turn
    )

    [UInt64]$red = [Convert]::ToUInt32($RedHex, 16)
    [UInt64]$black = [Convert]::ToUInt32($BlackHex, 16)
    [UInt64]$kings = [Convert]::ToUInt32($KingsHex, 16)
    $groups = [System.Collections.Generic.List[string]]::new()

    foreach ($side in @(
        @{ Prefix = 'B'; Bits = $black },
        @{ Prefix = 'R'; Bits = $red }
    )) {
        foreach ($kind in @(
            @{ Prefix = 'M'; Bits = ($side.Bits -band (-bnot $kings) -band 0xffffffffL) },
            @{ Prefix = 'K'; Bits = ($side.Bits -band $kings) }
        )) {
            $squares = [System.Collections.Generic.List[string]]::new()
            for ($square = 1; $square -le 32; ++$square) {
                [UInt64]$bit = [UInt64]1 -shl ($square - 1)
                if (($kind.Bits -band $bit) -ne 0) {
                    $squares.Add($square.ToString())
                }
            }
            if ($squares.Count -gt 0) {
                $groups.Add("$($side.Prefix)$($kind.Prefix)$($squares -join ',')")
            }
        }
    }

    $turnPrefix = if ($Turn -eq 1) { 'R' } elseif ($Turn -eq 2) { 'B' } else {
        throw "Invalid turn value from moves-state: $Turn"
    }
    return "$turnPrefix`:$($groups -join ':')"
}

if ($ValidateOnly) {
    [pscustomobject]@{
        WorkflowRoot = $workflowRoot
        Checkpoint = $currentCheckpoint
        Position = $Position
        Clock = $Clock
        Root = $Root
        MaxSteps = $MaxSteps
        ExpansionBudget = $ExpansionBudget
        LiveSlots = $LiveSlots
        SolvedSlots = $SolvedSlots
        Tb3HashPower = $Tb3HashPower
        RunPrefix = $RunPrefix
    }
    return
}

New-Item -ItemType Directory -Force -Path $scratchRoot | Out-Null
$chainLockPath = Join-Path $scratchRoot 'dfpn-follow.lock'
$chainLock = $null
try {
    try {
        $chainLock = [System.IO.File]::Open(
            $chainLockPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        throw "A saturated-line follower may already be active: $chainLockPath"
    }

    $currentPosition = $Position
    $currentClock = $Clock
    for ($step = 0; $step -lt $MaxSteps; ++$step) {
        $stepText = '{0:D2}' -f $step
        $runName = "$RunPrefix-s$stepText"
        Write-Output "FOLLOW step=$step checkpoint=$currentCheckpoint"
        Write-Output "FOLLOW position=$currentPosition clock=$currentClock"

        $runOutput = @(
            & $runner `
                -ExpansionBudget $ExpansionBudget `
                -LiveSlots $LiveSlots `
                -SolvedSlots $SolvedSlots `
                -Tb3HashPower $Tb3HashPower `
                -CheckpointPath $currentCheckpoint `
                -Position $currentPosition `
                -Clock $currentClock `
                -Root $Root `
                -RunName $runName 2>&1
        )
        $runOutput | ForEach-Object { Write-Output $_ }

        $resultLine = @($runOutput | Where-Object { "$_" -match '^result: ' })
        if ($resultLine.Count -ne 1) {
            throw "Expected exactly one DFPN result line, found $($resultLine.Count)"
        }
        if ("$($resultLine[0])" -notmatch '^result: UNKNOWN$') {
            Write-Output "FOLLOW terminal $($resultLine[0])"
            break
        }

        $candidateLines = @($runOutput | Where-Object {
            "$_" -match '^root move (?<move>[^:]+): pn=1000000000 dn=(?<dn>[1-9][0-9]*)(?: |$)'
        })
        if ($candidateLines.Count -ne 1) {
            Write-Output "FOLLOW paused candidates=$($candidateLines.Count); manual choice required"
            break
        }
        [void]("$($candidateLines[0])" -match '^root move (?<move>[^:]+):')
        $move = $Matches.move

        $moveStates = @(& $native moves-state $currentPosition $currentClock)
        $stateLine = @($moveStates | Where-Object { "$($_)".StartsWith("$move`t") })
        if ($stateLine.Count -ne 1) {
            throw "Expected one moves-state row for $move, found $($stateLine.Count)"
        }
        if ("$($stateLine[0])" -notmatch (
            '^\S+\tred=(?<red>[0-9a-fA-F]{8})' +
            '\tblack=(?<black>[0-9a-fA-F]{8})' +
            '\tkings=(?<kings>[0-9a-fA-F]{8})' +
            '\tturn=(?<turn>[12])\tclock=(?<clock>[0-9]+)$'
        )) {
            throw "Unable to parse moves-state row: $($stateLine[0])"
        }
        $nextPosition = Convert-HexStateToPosition `
            -RedHex $Matches.red `
            -BlackHex $Matches.black `
            -KingsHex $Matches.kings `
            -Turn ([int]$Matches.turn)
        $nextClock = [int]$Matches.clock

        $safeMove = $move -replace '[^A-Za-z0-9-]', 'x'
        $nextCheckpoint = Join-Path $buildRoot (
            "dfpn6_$RunPrefix-s$stepText-$safeMove.tt"
        )
        if (Test-Path -LiteralPath $nextCheckpoint) {
            throw "Refusing to overwrite follower checkpoint: $nextCheckpoint"
        }
        Write-Output "FOLLOW move=$move next=$nextPosition clock=$nextClock"
        & $engine retarget-dfpn-solved `
            $tb4 $tb5 $tb6 $currentCheckpoint $nextCheckpoint `
            $nextPosition $nextClock
        if ($LASTEXITCODE -ne 0) {
            throw "retarget-dfpn-solved exited with code $LASTEXITCODE"
        }

        $currentCheckpoint = $nextCheckpoint
        $currentPosition = $nextPosition
        $currentClock = $nextClock
    }

    Write-Output "FOLLOW final checkpoint=$currentCheckpoint"
    Write-Output "FOLLOW final position=$currentPosition clock=$currentClock"
}
finally {
    if ($null -ne $chainLock) {
        $chainLock.Dispose()
    }
    Remove-Item -LiteralPath $chainLockPath -Force -ErrorAction SilentlyContinue
}
