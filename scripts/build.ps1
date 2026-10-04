param([switch]$SkipSync)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ((Test-Path -LiteralPath 'docs/PORTABLE_SECURITY_BLOCK.txt') -or (Get-ChildItem -LiteralPath dist -Filter '*policy_violated.txt' -Recurse -ErrorAction SilentlyContinue)) {
    throw 'The organization security scanner blocked a previous portable build. Resolve this with NUS IT before rebuilding or distributing it.'
}
if (-not $SkipSync) {
    uv sync --group dev
    if ($LASTEXITCODE -ne 0) { throw 'Dependency sync failed; close running development instances and retry' }
}
$buildRoot = Join-Path $env:LOCALAPPDATA ('MurMurBuild/' + [guid]::NewGuid().ToString('N'))
$buildDist = Join-Path $buildRoot 'dist'
$buildWork = Join-Path $buildRoot 'work'
$originalBuildPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem"
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --distpath $buildDist --workpath $buildWork MurMur.spec
} finally { $env:PATH = $originalBuildPath }
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
if (-not (Test-Path -LiteralPath (Join-Path $buildDist 'MurMur/MurMur.exe'))) { throw 'Build reported success but MurMur.exe is missing; no usable portable bundle was produced' }
& .venv/Scripts/python.exe scripts/verify_bundle.py (Join-Path $buildDist 'MurMur')
if ($LASTEXITCODE -ne 0) { throw 'Portable startup verification failed; no release archive was produced' }
$bundlePath = 'dist/MurMur-0.4.0'
if (Test-Path -LiteralPath $bundlePath) { $bundlePath += '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') }
New-Item -ItemType Directory -Force dist | Out-Null
Copy-Item -LiteralPath (Join-Path $buildDist 'MurMur') -Destination $bundlePath -Recurse
if (-not (Test-Path -LiteralPath (Join-Path $bundlePath 'MurMur.exe'))) { throw 'Copied portable bundle is missing MurMur.exe' }
Copy-Item README.md,LICENSE,THIRD_PARTY_NOTICES.md $bundlePath
New-Item -ItemType Directory -Force (Join-Path $bundlePath 'docs'),(Join-Path $bundlePath 'licenses') | Out-Null
Copy-Item docs/CapsWriter-Offline-LICENSE.txt,docs/FunASR-MODEL_LICENSE.txt,docs/Silero-VAD-LICENSE.txt,docs/VALIDATION.md (Join-Path $bundlePath 'docs')
Get-ChildItem .venv/Lib/site-packages -Directory -Filter '*.dist-info' | ForEach-Object {
    $destination = Join-Path (Join-Path $bundlePath 'licenses') $_.Name
    New-Item -ItemType Directory -Force $destination | Out-Null
    Get-ChildItem -LiteralPath $_.FullName -Recurse -File | Where-Object { $_.Name -match '^(LICENSE|COPYING|NOTICE)' } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $destination $_.Name)
    }
}
& .venv/Scripts/python.exe -c "import shutil,sys,pathlib; p=pathlib.Path(sys.argv[1]); shutil.make_archive('dist/MurMur-0.4.0-win64', 'zip', p.parent, p.name)" $bundlePath
if ($LASTEXITCODE -ne 0) { throw 'Archive failed' }
Write-Output "Portable bundle: $bundlePath"
