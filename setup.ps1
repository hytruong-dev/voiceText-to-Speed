$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Uv = Join-Path $ProjectRoot ".tools\uv\bin\uv.exe"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $ProjectRoot ".tools\python"
$env:UV_CACHE_DIR = Join-Path $ProjectRoot ".cache\uv"

if (-not (Test-Path -LiteralPath $Uv)) {
    Write-Host "Installing uv inside this project..." -ForegroundColor Cyan
    $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $PythonCommand) {
        $PythonCommand = Get-Command python -ErrorAction Stop
    }
    & $PythonCommand.Source -m pip install --disable-pip-version-check --target (Join-Path $ProjectRoot ".tools\uv") uv
}

Write-Host "Creating an isolated Python 3.13 environment..." -ForegroundColor Cyan
& $Uv sync --python 3.13 --extra dev

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Run .\run.ps1 to start Tếu Voice Studio."
Write-Host "The first synthesis downloads the local model into .cache/."
