<#
.SYNOPSIS
    Khoi dong Teu Voice Studio + ngrok tunnel de truy cap qua Internet.

.PARAMETER NgrokAuthToken
    Auth token ngrok (lay tai https://dashboard.ngrok.com/get-started/your-authtoken).
    Chi can truyen mot lan - token duoc luu vao config ngrok.

.PARAMETER Port
    Cong server (mac dinh 8765).

.EXAMPLE
    # Lan dau - luu token va chay:
    .\run-ngrok.ps1 -NgrokAuthToken "2abc123..."

    # Tu lan sau:
    .\run-ngrok.ps1
#>

param(
    [string]$NgrokAuthToken,
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# Reload PATH
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("PATH","User")

# ── Kiem tra Python env ──────────────────────────────────────────────────
if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "ERROR: Moi truong Python chua co. Hay chay: .\setup.ps1" -ForegroundColor Red
    exit 1
}

# ── Tim ngrok ────────────────────────────────────────────────────────────
$candidatePaths = @(
    "$env:USERPROFILE\Downloads\ngrok.exe",
    "$env:USERPROFILE\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe",
    (Join-Path $ProjectRoot ".tools\ngrok\ngrok.exe")
)
$NgrokExe = $null
foreach ($p in $candidatePaths) {
    if (Test-Path $p) {
        # Kiem tra Defender chua block bang cach thu chay
        try {
            $t = Start-Process -FilePath $p -ArgumentList "version" -NoNewWindow -PassThru -Wait -ErrorAction Stop
            $NgrokExe = $p
            break
        } catch { }
    }
}
if (-not $NgrokExe) {
    $ngrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($ngrokCmd) {
        try {
            $t = Start-Process -FilePath $ngrokCmd.Source -ArgumentList "version" -NoNewWindow -PassThru -Wait -ErrorAction Stop
            $NgrokExe = $ngrokCmd.Source
        } catch { }
    }
}
if (-not $NgrokExe) {
    Write-Host "ERROR: Khong tim thay ngrok hoac bi Windows Defender block." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Cach fix:" -ForegroundColor Yellow
    Write-Host "  1. Tai ngrok moi tai: https://ngrok.com/download" -ForegroundColor Cyan
    Write-Host "  2. Giai nen va dat ngrok.exe vao: $env:USERPROFILE\Downloads\" -ForegroundColor Cyan
    Write-Host "  3. Trong Windows Security > Virus & threat protection > Protection history" -ForegroundColor Cyan
    Write-Host "     -> Tim ngrok.exe -> Actions -> Restore (neu muon dung ban cu)" -ForegroundColor Cyan
    exit 1
}
Write-Host "Dung ngrok: $NgrokExe" -ForegroundColor DarkGray

# ── Xu ly auth token ─────────────────────────────────────────────────────
if ($NgrokAuthToken) {
    Write-Host "Dang luu ngrok authtoken..." -ForegroundColor Cyan
    & $NgrokExe config add-authtoken $NgrokAuthToken
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Khong luu duoc authtoken." -ForegroundColor Red
        exit 1
    }
    Write-Host "Token da luu." -ForegroundColor Green
}

# Kiem tra token da co trong config chua
$ngrokConfigFile = "$env:LOCALAPPDATA\ngrok\ngrok.yml"
$hasToken = $false
if (Test-Path $ngrokConfigFile) {
    $cfg = Get-Content $ngrokConfigFile -Raw -ErrorAction SilentlyContinue
    if ($cfg -match "authtoken\s*:") { $hasToken = $true }
}

if (-not $hasToken) {
    Write-Host ""
    Write-Host "========================================================" -ForegroundColor Yellow
    Write-Host "  ngrok yeu cau tai khoan mien phi de tao tunnel." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1. Dang ky tai: https://ngrok.com" -ForegroundColor Cyan
    Write-Host "  2. Lay token tai: https://dashboard.ngrok.com/get-started/your-authtoken" -ForegroundColor Cyan
    Write-Host "  3. Chay lai: .\run-ngrok.ps1 -NgrokAuthToken ""YOUR_TOKEN""" -ForegroundColor Cyan
    Write-Host "========================================================" -ForegroundColor Yellow
    exit 1
}

# ── Tao access key ───────────────────────────────────────────────────────
if (-not $env:TEU_VOICE_ACCESS_KEY) {
    $TokenBytes = [byte[]]::new(24)
    $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
    $rng.GetBytes($TokenBytes)
    $rng.Dispose()
    $env:TEU_VOICE_ACCESS_KEY = [Convert]::ToBase64String($TokenBytes).TrimEnd('=').Replace('+','-').Replace('/','_')
}
$AccessKey = $env:TEU_VOICE_ACCESS_KEY

# ── Khoi dong ngrok tunnel truoc ─────────────────────────────────────────
Write-Host ""
Write-Host "Dang mo ngrok tunnel..." -ForegroundColor Cyan

$NgrokProcess = Start-Process -FilePath $NgrokExe `
    -ArgumentList "http", "$Port", "--log", "stdout" `
    -NoNewWindow -PassThru

# Cho ngrok lay URL (toi da 20 giay) - thu ca port 4040 va 4041
Write-Host "Dang cho ngrok" -NoNewline -ForegroundColor Yellow
$PublicUrl = $null
$NgrokApiPort = $null
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline -ForegroundColor Yellow
    if ($NgrokProcess.HasExited) {
        Write-Host ""
        Write-Host "ERROR: ngrok thoat som. Kiem tra authtoken." -ForegroundColor Red
        exit 1
    }
    foreach ($apiPort in @(4040, 4041, 4042)) {
        try {
            $api = Invoke-RestMethod -Uri "http://127.0.0.1:$apiPort/api/tunnels" -ErrorAction Stop
            $url = ($api.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1).public_url
            if ($url) { $PublicUrl = $url; $NgrokApiPort = $apiPort; break }
        } catch { }
    }
    if ($PublicUrl) { break }
}
Write-Host ""

if (-not $PublicUrl) {
    Write-Host "ERROR: Khong lay duoc URL tu ngrok." -ForegroundColor Red
    if (-not $NgrokProcess.HasExited) { $NgrokProcess.Kill() }
    exit 1
}

# Trich hostname tu ngrok URL (vd: abc123.ngrok-free.app)
$NgrokHostname = ([System.Uri]$PublicUrl).Host
Write-Host "Ngrok hostname: $NgrokHostname" -ForegroundColor DarkGray

# Set env cho server biet ngrok host duoc phep
$env:TEU_VOICE_NGROK_HOST  = $NgrokHostname
$env:PYTHONUTF8            = "1"
$env:TEU_VOICE_PORT        = "$Port"

# ── Khoi dong FastAPI server ─────────────────────────────────────────────
Write-Host "Dang khoi dong server..." -ForegroundColor Cyan

$ServerProcess = Start-Process -FilePath $Python `
    -ArgumentList "-m", "teu_voice", "--host", "127.0.0.1", "--port", "$Port" `
    -WorkingDirectory $ProjectRoot `
    -NoNewWindow -PassThru

# Cho server san sang (toi da 45 giay)
# Dung /api/config thay vi / vi endpoint nay khong can access_key (chi can host hop le)
Write-Host "Dang cho server" -NoNewline -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline -ForegroundColor Yellow
    if ($ServerProcess.HasExited) {
        Write-Host ""
        Write-Host "ERROR: Server thoat som (exit $($ServerProcess.ExitCode))." -ForegroundColor Red
        if (-not $NgrokProcess.HasExited) { $NgrokProcess.Kill() }
        exit 1
    }
    try {
        # Kiem tra bang cach connect TCP den port - tranh bi 401 block health check
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", $Port)
        $tcp.Close()
        $ready = $true
        Write-Host " OK" -ForegroundColor Green
        break
    } catch { }
}

if (-not $ready) {
    Write-Host " TIMEOUT" -ForegroundColor Red
    $ServerProcess.Kill()
    $NgrokProcess.Kill()
    exit 1
}

# ── In URL ───────────────────────────────────────────────────────────────
$FullUrl = "${PublicUrl}/?access_key=${AccessKey}"
Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host "  Teu Voice Studio - truy cap qua Internet:" -ForegroundColor Green
Write-Host ""
Write-Host "  $FullUrl" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Gui URL tren cho bat ky ai can dung." -ForegroundColor Green
Write-Host "  URL thay doi moi lan chay (tai khoan Free)." -ForegroundColor DarkGray
Write-Host "  Nhan Ctrl+C de dong server va tunnel." -ForegroundColor DarkGray
Write-Host "========================================================" -ForegroundColor Green
Write-Host ""

# ── Giu chay, don dep khi Ctrl+C ─────────────────────────────────────────
try {
    while ($true) {
        Start-Sleep -Seconds 3
        if ($ServerProcess.HasExited) {
            Write-Host "Server da dung." -ForegroundColor Red
            break
        }
        if ($NgrokProcess.HasExited) {
            Write-Host "ngrok da dung." -ForegroundColor Yellow
            break
        }
    }
} finally {
    Write-Host ""
    Write-Host "Dang dung..." -ForegroundColor Cyan
    if (-not $ServerProcess.HasExited) { $ServerProcess.Kill() }
    if (-not $NgrokProcess.HasExited)  { $NgrokProcess.Kill()  }
    Write-Host "Da dung server va tunnel." -ForegroundColor Green
}
