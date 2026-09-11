param(
    [string]$LanAddress
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project environment is missing. Run .\setup.ps1 first."
}

$env:PYTHONUTF8 = "1"
Set-Location -LiteralPath $ProjectRoot
if ($LanAddress) {
    $env:TEU_VOICE_HOST = $LanAddress
}
$TeuHost = if ($env:TEU_VOICE_HOST) { $env:TEU_VOICE_HOST } else { "127.0.0.1" }
$TeuPort = if ($env:TEU_VOICE_PORT) { $env:TEU_VOICE_PORT } else { "8765" }
$IsLoopback = $TeuHost -in @("127.0.0.1", "localhost", "::1")

if (-not $IsLoopback) {
    if (-not $env:TEU_VOICE_ACCESS_KEY) {
        $TokenBytes = [byte[]]::new(24)
        [System.Security.Cryptography.RandomNumberGenerator]::Fill($TokenBytes)
        $env:TEU_VOICE_ACCESS_KEY = [Convert]::ToBase64String($TokenBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    }
    Write-Host "Tếu Voice Studio (LAN có khóa): http://${TeuHost}:$TeuPort/?access_key=$($env:TEU_VOICE_ACCESS_KEY)" -ForegroundColor Green
} else {
    Write-Host "Tếu Voice Studio: http://127.0.0.1:$TeuPort" -ForegroundColor Green
}

& $Python -m teu_voice --host $TeuHost --port $TeuPort
