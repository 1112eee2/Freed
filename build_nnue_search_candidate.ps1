param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'build\nnue_search_v1_r5')
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$Source = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_native_nnue.c')).Path
$NativeSource = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_native.c')).Path
$UpdateSource = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'native\makhos_nnue_avx2_update.c')).Path
$Compiler = 'C:\Program Files\LLVM\bin\clang.exe'
$Accepted = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'build\makhos_native_accepted.dll')).Path
$Model = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'build\nnue_quantized_v1\model_a.mknnue')).Path
$Contract = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot 'build\nnue_phase1_evidence\quantization_contract_v2.json')).Path
$ExpectedAcceptedSha256 = 'FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD'
$ExpectedModelSha256 = '07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C'
$ExpectedContractSha256 = '68CCA3E4FB46B1C6FA9F45FF34875E0D1ACE396881BB1D2E175CBA5D43E91FBF'

if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) { throw "LLVM Clang is unavailable: $Compiler" }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Accepted).Hash -ne $ExpectedAcceptedSha256) { throw 'Accepted DLL identity differs; refusing NNUE-search build.' }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Model).Hash -ne $ExpectedModelSha256) { throw 'Quantized KEEP model identity differs; refusing NNUE-search build.' }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Contract).Hash -ne $ExpectedContractSha256) { throw 'Quantization contract identity differs; refusing NNUE-search build.' }

$ResolvedOutput = [IO.Path]::GetFullPath($OutputDirectory)
$BuildRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'build'))
if (-not $ResolvedOutput.StartsWith($BuildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'NNUE-search output must stay inside the project build directory.' }
$ReproA = Join-Path $ResolvedOutput 'repro_a'
$ReproB = Join-Path $ResolvedOutput 'repro_b'
$FileName = 'makhos_native_nnue_candidate_v1.dll'
$CandidateA = Join-Path $ReproA $FileName
$CandidateB = Join-Path $ReproB $FileName
$Final = Join-Path $ResolvedOutput $FileName
$Manifest = Join-Path $ResolvedOutput 'build_manifest.json'
New-Item -ItemType Directory -Force -Path $ReproA, $ReproB | Out-Null
$Flags = @('-O3','-march=x86-64','-std=c17','-Wall','-Wextra','-Werror','-Wno-unused-function','-shared','-Wl,/Brepro')
foreach ($Candidate in @($CandidateA, $CandidateB)) {
    & $Compiler @Flags $Source '-o' $Candidate
    if ($LASTEXITCODE -ne 0) { throw "NNUE-search build failed with exit code $LASTEXITCODE" }
}
$HashA = (Get-FileHash -Algorithm SHA256 -LiteralPath $CandidateA).Hash
$HashB = (Get-FileHash -Algorithm SHA256 -LiteralPath $CandidateB).Hash
if ($HashA -ne $HashB) { throw 'Reproducible NNUE-search builds are not byte-identical.' }
if (Test-Path -LiteralPath $Final -PathType Leaf) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Final).Hash -ne $HashA) { throw 'Existing NNUE-search candidate differs; refusing to overwrite it.' }
} else { Copy-Item -LiteralPath $CandidateA -Destination $Final }

$Payload = [ordered]@{
    format = 'thai-makhos-nnue-search-build-v1'; verdict = 'PASS'
    source = $Source; source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Source).Hash
    native_source = $NativeSource; native_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $NativeSource).Hash
    update_source = $UpdateSource; update_source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $UpdateSource).Hash
    compiler = $Compiler; compiler_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Compiler).Hash
    compiler_version = (& $Compiler --version | Select-Object -First 1).Trim(); flags = $Flags
    vector_target = 'AVX2 function attributes in a baseline x86-64 DLL'; reproducible_builds = 2; byte_identical = $true
    candidate = $Final; candidate_bytes = (Get-Item -LiteralPath $Final).Length; candidate_sha256 = $HashA
    accepted_library_sha256 = $ExpectedAcceptedSha256; quantization_contract_sha256 = $ExpectedContractSha256; quantized_model_sha256 = $ExpectedModelSha256
    feature_abi = 'thai-makhos-shared-137-v1'; evaluator = 'incremental AVX2 NNUE at non-terminal native search leaves'
    playing_path_changed = $true; promotion_status = 'UNTESTED'
}
$Encoded = ($Payload | ConvertTo-Json -Depth 4) + "`n"
if (Test-Path -LiteralPath $Manifest -PathType Leaf) {
    if ([IO.File]::ReadAllText($Manifest) -ne $Encoded) { throw 'Existing NNUE-search build manifest differs; refusing to overwrite it.' }
} else { [IO.File]::WriteAllText($Manifest, $Encoded, [Text.UTF8Encoding]::new($false)) }
$Payload | ConvertTo-Json -Depth 4
