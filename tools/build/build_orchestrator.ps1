<#
.SYNOPSIS
    Shared build orchestrator and variant configuration for ThaiMakhosEngine.
.DESCRIPTION
    Consolidates build logic, compiler detection, prerequisite verification,
    A/B reproducible compilation, and manifest generation across all engine variants.
#>
param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('native', 'nnue_scalar', 'nnue_incremental', 'nnue_avx2', 'nnue_avx2_update', 'nnue_search_candidate', 'endgame_c1', 'endgame_c2', 'endgame_c3', 'endgame_c4')]
    [string]$Variant,

    [Parameter(Mandatory=$false, Position=1)]
    [string]$OutputDirectory,

    [Parameter(Mandatory=$false)]
    [switch]$VerifyOnly,

    [Parameter(Mandatory=$false)]
    [switch]$StrictSearchKey,

    [Parameter(Mandatory=$false)]
    [switch]$TablebaseDrawCutoff,

    [Parameter(Mandatory=$false)]
    [switch]$ReverseFutility,

    [Parameter(Mandatory=$false)]
    [switch]$IterPartial
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir '..\..')).Path
$BuildRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'build'))

# The strict key repair, the tablebase draw cutoff, reverse futility and the
# interrupted-iteration root move are isolated strength candidates: each builds
# only nnue_search_candidate into its own directory.
$CandidateSwitches = @()
if ($StrictSearchKey) { $CandidateSwitches += 'StrictSearchKey' }
if ($TablebaseDrawCutoff) { $CandidateSwitches += 'TablebaseDrawCutoff' }
if ($ReverseFutility) { $CandidateSwitches += 'ReverseFutility' }
if ($IterPartial) { $CandidateSwitches += 'IterPartial' }
foreach ($CandidateSwitch in $CandidateSwitches) {
    if ($Variant -ne 'nnue_search_candidate') {
        throw "$CandidateSwitch is supported only for nnue_search_candidate."
    }
    if (-not $OutputDirectory) {
        throw "$CandidateSwitch requires an explicit candidate OutputDirectory."
    }
    $CandidateDir = [IO.Path]::GetFullPath($OutputDirectory)
    $ReleaseDir = [IO.Path]::GetFullPath((Join-Path $BuildRoot 'nnue_search_v1_r5'))
    if ($CandidateDir.TrimEnd([IO.Path]::DirectorySeparatorChar).Equals($ReleaseDir, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$CandidateSwitch must not target the production NNUE directory."
    }
}

$ClangCompiler = 'C:\Program Files\LLVM\bin\clang.exe'
$GccCompiler = 'C:\msys64\mingw64\bin\gcc.exe'

$ExpectedAcceptedSha256 = 'FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD'
$ExpectedModelSha256 = '07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C'
$ExpectedContractSha256 = '68CCA3E4FB46B1C6FA9F45FF34875E0D1ACE396881BB1D2E175CBA5D43E91FBF'

function Assert-Prerequisites {
    param([string]$VariantName)

    if (-not (Test-Path -LiteralPath $ClangCompiler -PathType Leaf)) {
        throw "LLVM Clang is unavailable: $ClangCompiler"
    }

    $Accepted = Join-Path $ProjectRoot 'build\makhos_native_accepted.dll'
    $Model = Join-Path $ProjectRoot 'build\nnue_quantized_v1\model_a.mknnue'
    $Contract = Join-Path $ProjectRoot 'build\nnue_phase1_evidence\quantization_contract_v2.json'

    if (-not (Test-Path -LiteralPath $Accepted -PathType Leaf)) {
        throw "Accepted DLL is missing: $Accepted"
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Accepted).Hash -ne $ExpectedAcceptedSha256) {
        throw "Accepted DLL identity differs; refusing $VariantName build."
    }

    if (-not (Test-Path -LiteralPath $Model -PathType Leaf)) {
        throw "Quantized KEEP model is missing: $Model"
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Model).Hash -ne $ExpectedModelSha256) {
        throw "Quantized KEEP model identity differs; refusing $VariantName build."
    }

    if (-not (Test-Path -LiteralPath $Contract -PathType Leaf)) {
        throw "Quantization contract is missing: $Contract"
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Contract).Hash -ne $ExpectedContractSha256) {
        throw "Quantization contract identity differs; refusing $VariantName build."
    }
}

function Invoke-NativeBuild {
    $Compilers = @($ClangCompiler, $GccCompiler)
    $Compiler = $Compilers | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $Compiler) {
        throw 'No supported C compiler found (looked for MinGW GCC and LLVM Clang).'
    }

    if ($VerifyOnly) {
        Write-Output "Native compiler verified: $Compiler"
        return
    }

    $Source = Join-Path $ProjectRoot 'native\makhos_native.c'
    $Output = Join-Path $BuildRoot 'makhos_native.exe'
    $Library = Join-Path $BuildRoot 'makhos_native.dll'
    $TablebaseSource = Join-Path $ProjectRoot 'native\makhos_tb4.c'
    $TablebaseOutput = Join-Path $BuildRoot 'makhos_tb4.exe'
    $FiveTablebaseSource = Join-Path $ProjectRoot 'native\makhos_tb5.c'
    $FiveTablebaseOutput = Join-Path $BuildRoot 'makhos_tb5.exe'
    $SixTablebaseSource = Join-Path $ProjectRoot 'native\makhos_tb6.c'
    $SixTablebaseOutput = Join-Path $BuildRoot 'makhos_tb6.exe'

    New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null

    & $Compiler -O3 -march=native -std=c17 -Wall -Wextra -Werror -Wno-unused-function $Source -o $Output
    if ($LASTEXITCODE -ne 0) { throw "Native build failed with exit code $LASTEXITCODE" }

    & $Compiler -O3 -march=native -std=c17 -Wall -Wextra -Werror -Wno-unused-function -shared -DMAKHOS_NO_MAIN $Source -o $Library
    if ($LASTEXITCODE -ne 0) { throw "Native library build failed with exit code $LASTEXITCODE" }

    & $Compiler -O3 -std=c17 -Wall -Wextra -Werror -Wno-unused-function $TablebaseSource -o $TablebaseOutput
    if ($LASTEXITCODE -ne 0) { throw "Four-piece tablebase build failed with exit code $LASTEXITCODE" }

    & $Compiler -O3 -std=c17 -Wall -Wextra -Werror -Wno-unused-function -fopenmp $FiveTablebaseSource -o $FiveTablebaseOutput
    if ($LASTEXITCODE -ne 0) { throw "Five-piece tablebase build failed with exit code $LASTEXITCODE" }

    & $Compiler -O3 -std=c17 -Wall -Wextra -Werror -Wno-unused-function -fopenmp $SixTablebaseSource -o $SixTablebaseOutput
    if ($LASTEXITCODE -ne 0) { throw "Six-piece tablebase build failed with exit code $LASTEXITCODE" }

    Write-Output "Built $Output"
    Write-Output "Built $Library"
    Write-Output "Built $TablebaseOutput"
    Write-Output "Built $FiveTablebaseOutput"
    Write-Output "Built $SixTablebaseOutput"
}

function Invoke-NnueReproducibleBuild {
    param(
        [string]$VariantName,
        [string]$DefaultDir,
        [string]$FileName,
        [string]$Format,
        [string]$SourcePath,
        [string[]]$Flags,
        [scriptblock]$BuildPayload
    )

    Assert-Prerequisites -VariantName $VariantName

    $EffectiveOutDir = if ($OutputDirectory) { $OutputDirectory } else { Join-Path $ProjectRoot $DefaultDir }
    $ResolvedOutput = [IO.Path]::GetFullPath($EffectiveOutDir)
    if (-not $ResolvedOutput.StartsWith($BuildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$VariantName output must stay inside the project build directory."
    }

    if ($VerifyOnly) {
        Write-Output "$VariantName prerequisites and path verified: $ResolvedOutput"
        return
    }

    $ReproA = Join-Path $ResolvedOutput 'repro_a'
    $ReproB = Join-Path $ResolvedOutput 'repro_b'
    $CandidateA = Join-Path $ReproA $FileName
    $CandidateB = Join-Path $ReproB $FileName
    $Final = Join-Path $ResolvedOutput $FileName
    $Manifest = Join-Path $ResolvedOutput 'build_manifest.json'

    New-Item -ItemType Directory -Force -Path $ReproA, $ReproB | Out-Null

    foreach ($Candidate in @($CandidateA, $CandidateB)) {
        & $ClangCompiler @Flags $SourcePath '-o' $Candidate
        if ($LASTEXITCODE -ne 0) {
            throw "$VariantName build failed with exit code $LASTEXITCODE"
        }
    }

    $HashA = (Get-FileHash -Algorithm SHA256 -LiteralPath $CandidateA).Hash
    $HashB = (Get-FileHash -Algorithm SHA256 -LiteralPath $CandidateB).Hash
    if ($HashA -ne $HashB) {
        throw "Reproducible $VariantName builds are not byte-identical."
    }

    if (Test-Path -LiteralPath $Final -PathType Leaf) {
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Final).Hash -ne $HashA) {
            throw "Existing $VariantName binary differs; refusing to overwrite it."
        }
    } else {
        Copy-Item -LiteralPath $CandidateA -Destination $Final
    }

    $Payload = & $BuildPayload $Final $HashA
    if ($StrictSearchKey) {
        $Payload['search_key_encoding'] = 'strict-xor-v1'
        $Payload['candidate_reason'] = 'Reject deterministic king/clock TT aliases'
    }
    if ($TablebaseDrawCutoff) {
        $Payload['tablebase_draw_cutoff'] = 'exact-draw-v1'
        $Payload['tablebase_draw_reason'] = 'Return exact TB4-6 draws at non-root main-search nodes'
    }
    if ($ReverseFutility) {
        $Payload['reverse_futility'] = 'guarded-rfp-v1'
        $Payload['reverse_futility_reason'] = 'Return beta at guarded shallow null-window nodes whose static evaluation clears it by a depth margin'
    }
    if ($IterPartial) {
        $Payload['root_partial_iteration'] = 'partial-best-v1'
        $Payload['root_partial_iteration_reason'] = 'Return a root move that finished an interrupted deeper iteration above the first move''s completed score'
    }
    if ($CandidateSwitches.Count -gt 0) {
        $CandidateSources = @('native/makhos_native_nnue.c', 'native/makhos_native.c', 'native/makhos_types.h', 'native/makhos_format.h', 'native/makhos_nnue_scalar.c', 'native/makhos_nnue_incremental.c', 'native/makhos_nnue_avx2.c', 'native/makhos_nnue_avx2_update.c')
        # Only the draw cutoff includes the tablebase header; the other
        # candidates keep the original source list.
        if ($TablebaseDrawCutoff) { $CandidateSources += 'native/makhos_endgame_tb.h' }
        $Payload['source_files_sha256'] = [ordered]@{}
        foreach ($RelativeSource in $CandidateSources) {
            $Payload['source_files_sha256'][$RelativeSource] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $ProjectRoot $RelativeSource)).Hash
        }
    }
    $Encoded = ($Payload | ConvertTo-Json -Depth 4) + "`n"

    if (Test-Path -LiteralPath $Manifest -PathType Leaf) {
        $existingRaw = [IO.File]::ReadAllText($Manifest)
        if ($existingRaw -ne $Encoded) {
            $existingObj = $existingRaw | ConvertFrom-Json
            $currentObj = $Encoded | ConvertFrom-Json
            $differs = $false
            foreach ($prop in $Payload.Keys) {
                $valExisting = ($existingObj.$prop | ConvertTo-Json -Compress)
                $valCurrent = ($currentObj.$prop | ConvertTo-Json -Compress)
                if ($valExisting -ne $valCurrent) {
                    $differs = $true
                    break
                }
            }
            if ($differs) {
                throw "Existing $VariantName build manifest differs; refusing to overwrite it."
            }
        }
    } else {
        [IO.File]::WriteAllText($Manifest, $Encoded, [Text.UTF8Encoding]::new($false))
    }

    $Payload | ConvertTo-Json -Depth 4
}

function Invoke-EndgameBuild {
    param(
        [string]$Subdir,
        [string]$DllName,
        [string[]]$Sources,
        [string]$Define = $null
    )

    if (-not (Test-Path -LiteralPath $ClangCompiler -PathType Leaf)) {
        throw 'LLVM clang is required'
    }

    $OutDir = Join-Path $BuildRoot $Subdir
    if ($VerifyOnly) {
        Write-Output "Endgame build verified: $OutDir"
        return
    }

    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $DllPath = Join-Path $OutDir $DllName

    $Flags = @('-O2', '-std=c17', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-shared')
    if ($Define) {
        $Flags += $Define
    }

    $ResolvedSources = $Sources | ForEach-Object { Join-Path $ProjectRoot $_ }
    & $ClangCompiler @Flags $ResolvedSources -o $DllPath
    if ($LASTEXITCODE -ne 0) {
        throw "Endgame build $Subdir failed with exit code $LASTEXITCODE"
    }

    Get-FileHash -Algorithm SHA256 $DllPath
}

switch ($Variant) {
    'native' {
        Invoke-NativeBuild
    }
    'nnue_scalar' {
        $Src = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_scalar.c')).Path
        $Flags = @('-O3', '-march=native', '-std=c17', '-Wall', '-Wextra', '-Werror', '-shared', '-Wl,/Brepro')
        Invoke-NnueReproducibleBuild -VariantName 'scalar' -DefaultDir 'build\nnue_scalar_v1' -FileName 'makhos_nnue_scalar_oracle_v1.dll' -Format 'thai-makhos-nnue-scalar-build-v1' -SourcePath $Src -Flags $Flags -BuildPayload {
            param($Final, $Hash)
            [ordered]@{
                format = 'thai-makhos-nnue-scalar-build-v1'
                verdict = 'PASS'
                source = $Src
                source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Src).Hash
                compiler = $ClangCompiler
                compiler_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ClangCompiler).Hash
                compiler_version = (& $ClangCompiler --version | Select-Object -First 1).Trim()
                flags = $Flags
                reproducible_builds = 2
                byte_identical = $true
                scalar_oracle = $Final
                scalar_oracle_bytes = (Get-Item -LiteralPath $Final).Length
                scalar_oracle_sha256 = $Hash
                accepted_library_sha256 = $ExpectedAcceptedSha256
                quantization_contract_sha256 = $ExpectedContractSha256
                quantized_model_sha256 = $ExpectedModelSha256
                playing_path_changed = $false
            }
        }
    }
    'nnue_incremental' {
        $Src = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_incremental.c')).Path
        $ScalarSrc = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_scalar.c')).Path
        $Flags = @('-O3', '-march=native', '-std=c17', '-Wall', '-Wextra', '-Werror', '-shared', '-Wl,/Brepro')
        Invoke-NnueReproducibleBuild -VariantName 'incremental' -DefaultDir 'build\nnue_incremental_v1' -FileName 'makhos_nnue_incremental_oracle_v1.dll' -Format 'thai-makhos-nnue-incremental-build-v1' -SourcePath $Src -Flags $Flags -BuildPayload {
            param($Final, $Hash)
            [ordered]@{
                format = 'thai-makhos-nnue-incremental-build-v1'
                verdict = 'PASS'
                source = $Src
                source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Src).Hash
                scalar_source = $ScalarSrc
                scalar_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ScalarSrc).Hash
                compiler = $ClangCompiler
                compiler_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ClangCompiler).Hash
                compiler_version = (& $ClangCompiler --version | Select-Object -First 1).Trim()
                flags = $Flags
                reproducible_builds = 2
                byte_identical = $true
                incremental_oracle = $Final
                incremental_oracle_bytes = (Get-Item -LiteralPath $Final).Length
                incremental_oracle_sha256 = $Hash
                accepted_library_sha256 = $ExpectedAcceptedSha256
                quantization_contract_sha256 = $ExpectedContractSha256
                quantized_model_sha256 = $ExpectedModelSha256
                playing_path_changed = $false
            }
        }
    }
    'nnue_avx2' {
        $Src = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_avx2.c')).Path
        $IncSrc = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_incremental.c')).Path
        $ScalarSrc = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_scalar.c')).Path
        $Flags = @('-O3', '-march=x86-64', '-std=c17', '-Wall', '-Wextra', '-Werror', '-shared', '-Wl,/Brepro')
        Invoke-NnueReproducibleBuild -VariantName 'avx2' -DefaultDir 'build\nnue_avx2_v1' -FileName 'makhos_nnue_avx2_oracle_v1.dll' -Format 'thai-makhos-nnue-avx2-build-v1' -SourcePath $Src -Flags $Flags -BuildPayload {
            param($Final, $Hash)
            [ordered]@{
                format = 'thai-makhos-nnue-avx2-build-v1'
                verdict = 'PASS'
                source = $Src
                source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Src).Hash
                incremental_source = $IncSrc
                incremental_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $IncSrc).Hash
                scalar_source = $ScalarSrc
                scalar_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ScalarSrc).Hash
                compiler = $ClangCompiler
                compiler_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ClangCompiler).Hash
                compiler_version = (& $ClangCompiler --version | Select-Object -First 1).Trim()
                flags = $Flags
                vector_target = 'avx2 function attribute; baseline x86-64 DLL'
                reproducible_builds = 2
                byte_identical = $true
                avx2_oracle = $Final
                avx2_oracle_bytes = (Get-Item -LiteralPath $Final).Length
                avx2_oracle_sha256 = $Hash
                accepted_library_sha256 = $ExpectedAcceptedSha256
                quantization_contract_sha256 = $ExpectedContractSha256
                quantized_model_sha256 = $ExpectedModelSha256
                playing_path_changed = $false
            }
        }
    }
    'nnue_avx2_update' {
        $Src = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_avx2_update.c')).Path
        $Avx2Src = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_avx2.c')).Path
        $IncSrc = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_incremental.c')).Path
        $Flags = @('-O3', '-march=x86-64', '-std=c17', '-Wall', '-Wextra', '-Werror', '-shared', '-Wl,/Brepro')
        Invoke-NnueReproducibleBuild -VariantName 'avx2_update' -DefaultDir 'build\nnue_avx2_update_v1' -FileName 'makhos_nnue_avx2_update_oracle_v1.dll' -Format 'thai-makhos-nnue-avx2-update-build-v1' -SourcePath $Src -Flags $Flags -BuildPayload {
            param($Final, $Hash)
            [ordered]@{
                format = 'thai-makhos-nnue-avx2-update-build-v1'
                verdict = 'PASS'
                source = $Src
                source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Src).Hash
                avx2_dense_source = $Avx2Src
                avx2_dense_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Avx2Src).Hash
                incremental_source = $IncSrc
                incremental_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $IncSrc).Hash
                compiler = $ClangCompiler
                compiler_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ClangCompiler).Hash
                compiler_version = (& $ClangCompiler --version | Select-Object -First 1).Trim()
                flags = $Flags
                vector_target = 'avx2 function attribute; baseline x86-64 DLL'
                reproducible_builds = 2
                byte_identical = $true
                avx2_update_oracle = $Final
                avx2_update_oracle_bytes = (Get-Item -LiteralPath $Final).Length
                avx2_update_oracle_sha256 = $Hash
                accepted_library_sha256 = $ExpectedAcceptedSha256
                quantization_contract_sha256 = $ExpectedContractSha256
                quantized_model_sha256 = $ExpectedModelSha256
                playing_path_changed = $false
            }
        }
    }
    'nnue_search_candidate' {
        $Src = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_native_nnue.c')).Path
        $NatSrc = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_native.c')).Path
        $UpdSrc = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_avx2_update.c')).Path
        $Flags = @('-O3', '-march=x86-64', '-std=c17', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-shared', '-Wl,/Brepro')
        if ($StrictSearchKey) { $Flags += '-DMAKHOS_STRICT_SEARCH_POSITION_KEY=1' }
        if ($TablebaseDrawCutoff) { $Flags += '-DMAKHOS_SEARCH_TB_DRAW=1' }
        if ($ReverseFutility) { $Flags += '-DMAKHOS_REVERSE_FUTILITY=1' }
        if ($IterPartial) { $Flags += '-DMAKHOS_ITER_PARTIAL=1' }
        Invoke-NnueReproducibleBuild -VariantName 'search_candidate' -DefaultDir 'build\nnue_search_v1_r5' -FileName 'makhos_native_nnue_candidate_v1.dll' -Format 'thai-makhos-nnue-search-build-v1' -SourcePath $Src -Flags $Flags -BuildPayload {
            param($Final, $Hash)
            [ordered]@{
                format = 'thai-makhos-nnue-search-build-v1'
                verdict = 'PASS'
                source = $Src
                source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Src).Hash
                native_source = $NatSrc
                native_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $NatSrc).Hash
                update_source = $UpdSrc
                update_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $UpdSrc).Hash
                compiler = $ClangCompiler
                compiler_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ClangCompiler).Hash
                compiler_version = (& $ClangCompiler --version | Select-Object -First 1).Trim()
                flags = $Flags
                vector_target = 'AVX2 function attributes in a baseline x86-64 DLL'
                reproducible_builds = 2
                byte_identical = $true
                candidate = $Final
                candidate_bytes = (Get-Item -LiteralPath $Final).Length
                candidate_sha256 = $Hash
                accepted_library_sha256 = $ExpectedAcceptedSha256
                quantization_contract_sha256 = $ExpectedContractSha256
                quantized_model_sha256 = $ExpectedModelSha256
                feature_abi = 'thai-makhos-shared-137-v1'
                evaluator = 'incremental AVX2 NNUE at non-terminal native search leaves'
                playing_path_changed = $true
                promotion_status = 'UNTESTED'
            }
        }
    }
    'endgame_c1' {
        Invoke-EndgameBuild -Subdir 'native_endgame_c1' -DllName 'makhos_endgame_tb.dll' -Sources @('native/makhos_endgame_tb.c')
    }
    'endgame_c2' {
        Invoke-EndgameBuild -Subdir 'native_endgame_c2' -DllName 'makhos_endgame_search.dll' -Sources @('native/makhos_endgame_search.c', 'native/makhos_endgame_tb.c')
    }
    'endgame_c3' {
        Invoke-EndgameBuild -Subdir 'native_endgame_c3' -DllName 'makhos_endgame_search_nnue.dll' -Sources @('native/makhos_endgame_search_nnue.c', 'native/makhos_endgame_tb.c')
    }
    'endgame_c4' {
        Invoke-EndgameBuild -Subdir 'native_endgame_c4' -DllName 'makhos_endgame_search_nnue.dll' -Sources @('native/makhos_endgame_search_nnue.c', 'native/makhos_endgame_tb.c')
    }
    default {
        throw "Unknown variant: $Variant"
    }
}
