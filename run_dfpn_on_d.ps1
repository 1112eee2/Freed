param(
    [UInt64]$ExpansionBudget = 100000000,
    [UInt64]$LiveSlots = 671088640,
    [UInt64]$SolvedSlots = 160000000,
    [int]$Tb3HashPower = 25,
    [string]$CheckpointPath = 'build\dfpn6_initial_seeded.tt',
    [string]$Position = 'B:BM25,26,27,28,29,30,31,32:RM1,2,3,4,5,6,7,8',
    [ValidateRange(0, 126)]
    [int]$Clock = 0,
    [ValidateSet('red', 'black')]
    [string]$Root = 'black',
    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$RunName = 'dfpn6',
    [switch]$InitializeCheckpoint,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$workflowRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildRoot = Join-Path $workflowRoot 'build'
$scratchRoot = Join-Path $workflowRoot 'scratch'
$logRoot = Join-Path $workflowRoot 'logs'
$engine = Join-Path $buildRoot 'makhos_tb6.exe'
$tb4 = Join-Path $buildRoot 'tb4_np80.bin'
$tb5 = Join-Path $buildRoot 'tb5_np80.compact.bin'
$tb6 = Join-Path $buildRoot 'tb6_np80.compact.bin'
$checkpoint = if ([System.IO.Path]::IsPathRooted($CheckpointPath)) {
    $CheckpointPath
}
else {
    Join-Path $workflowRoot $CheckpointPath
}

foreach ($requiredPath in @($engine, $tb4, $tb5, $tb6)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required workflow file is missing: $requiredPath"
    }
}

$checkpointExists = Test-Path -LiteralPath $checkpoint -PathType Leaf
if ($InitializeCheckpoint) {
    if ($checkpointExists) {
        throw "Refusing to initialize over an existing checkpoint: $checkpoint"
    }
}
elseif (-not $checkpointExists) {
    throw "Required workflow file is missing: $checkpoint"
}

New-Item -ItemType Directory -Force -Path $scratchRoot, $logRoot | Out-Null

[UInt64]$scratchBytes = ($LiveSlots * 13) + ($SolvedSlots * 10)
$checkpointBytes = if ($checkpointExists) {
    (Get-Item -LiteralPath $checkpoint).Length
}
else {
    0
}
$minimumFreeBytes = $scratchBytes + $checkpointBytes + 5GB
$drive = [System.IO.DriveInfo]::new((Split-Path -Qualifier $workflowRoot))
if ($drive.AvailableFreeSpace -lt $minimumFreeBytes) {
    $requiredGB = [math]::Ceiling($minimumFreeBytes / 1GB)
    $availableGB = [math]::Round($drive.AvailableFreeSpace / 1GB, 1)
    throw "Insufficient free space on $($drive.Name): need at least $requiredGB GB, available $availableGB GB"
}

if ($ValidateOnly) {
    [pscustomobject]@{
        WorkflowRoot = $workflowRoot
        CheckpointBytes = $checkpointBytes
        ScratchBytes = $scratchBytes
        AvailableGB = [math]::Round($drive.AvailableFreeSpace / 1GB, 1)
        ExpansionBudget = $ExpansionBudget
        LiveSlots = $LiveSlots
        SolvedSlots = $SolvedSlots
        Checkpoint = $checkpoint
        InitializeCheckpoint = [bool]$InitializeCheckpoint
        Position = $Position
        Clock = $Clock
        Root = $Root
        RunName = $RunName
    }
    return
}

$lockPath = Join-Path $scratchRoot 'dfpn-run.lock'
$lockStream = $null
try {
    try {
        $lockStream = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        throw "A DFPN run may already be active. If no run is active, remove the stale lock: $lockPath"
    }

    $lockWriter = [System.IO.StreamWriter]::new($lockStream)
    $lockWriter.WriteLine("PID=$PID")
    $lockWriter.WriteLine("Started=$([DateTimeOffset]::Now.ToString('o'))")
    $lockWriter.Flush()

    $env:MAKHOS_DFPN_HASH_BACKING = Join-Path $scratchRoot "$RunName-hash"
    $env:MAKHOS_TB3_TRIM_WORKING_SET = '1'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $logPath = Join-Path $logRoot "$RunName-$stamp.log"

    Write-Host "Workflow root: $workflowRoot"
    Write-Host "Checkpoint:    $checkpoint"
    Write-Host "Scratch:       $scratchRoot"
    Write-Host "Log:           $logPath"

    & $engine dfpn-clock-slots $tb4 $tb5 $tb6 $Position $Clock $Root $ExpansionBudget $LiveSlots $SolvedSlots $Tb3HashPower $checkpoint - - 0 2>&1 |
        Tee-Object -FilePath $logPath
    $engineExit = $LASTEXITCODE

    $forcedLoss = $engineExit -eq 1 -and [bool](
        Select-String -LiteralPath $logPath -Pattern '^result: FORCED LOSS$' -Quiet
    )
    if ($forcedLoss) {
        Write-Host 'DFPN proved the root is a forced loss; the checkpoint was saved.'
    }
    elseif ($engineExit -eq 3) {
        Write-Host 'DFPN budget exhausted; the checkpoint was saved and remains UNKNOWN.'
    }
    elseif ($engineExit -ne 0) {
        throw "DFPN exited with code $engineExit. See $logPath"
    }
}
finally {
    Remove-Item Env:MAKHOS_DFPN_HASH_BACKING -ErrorAction SilentlyContinue
    Remove-Item Env:MAKHOS_TB3_TRIM_WORKING_SET -ErrorAction SilentlyContinue
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}
