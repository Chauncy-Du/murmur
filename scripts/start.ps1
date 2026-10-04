param([switch]$SkipSync)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not $SkipSync) {
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Dependency sync failed. MurMur was not started.' }
}
uv run --no-sync python run.py
if ($LASTEXITCODE -ne 0) { throw 'MurMur exited with an error. Check D:\LocalProjects\MurMur\data\startup-error.log.' }
