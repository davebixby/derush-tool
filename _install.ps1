# DERUSH TOOL - Installeur automatique
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile   = Join-Path $scriptDir "derush_install.log"

# Toute erreur non geree affiche un message et garde la fenetre ouverte
trap {
    $msg = "ERREUR : $_"
    Write-Host "`n  $msg" -ForegroundColor Red
    Add-Content $logFile "[$(Get-Date)] $msg"
    Read-Host "`n  Appuie sur Entree pour fermer"
    exit 1
}

function Log  { param($m) Add-Content $logFile "[$(Get-Date -f 'HH:mm:ss')] $m" }
function Step { param($m) Write-Host "`n  >> $m" -ForegroundColor Cyan;   Log "STEP: $m" }
function OK   { param($m) Write-Host "  OK  $m" -ForegroundColor Green;  Log "OK:   $m" }
function Warn { param($m) Write-Host "  !!  $m" -ForegroundColor Yellow; Log "WARN: $m" }
function Fail { param($m) Write-Host "  XX  $m" -ForegroundColor Red;    Log "FAIL: $m" }

# Init log
"" | Set-Content $logFile
Log "=== Installation demarree ==="
Log "scriptDir = $scriptDir"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Write-Host ""
Write-Host "  ==========================================" -ForegroundColor Magenta
Write-Host "      DERUSH TOOL  --  Installation         " -ForegroundColor Magenta
Write-Host "  ==========================================" -ForegroundColor Magenta

# ─────────────────────────────────────────────
# PYTHON
# ─────────────────────────────────────────────
Step "Verification de Python..."

$pythonExe = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = (& $candidate --version 2>&1 | Out-String).Trim()
        Log "Essai $candidate : $ver"
        if ($ver -match "Python (\d+)\.(\d+)") {
            if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 8)) {
                $pythonExe = $candidate
                OK "Python $($Matches[1]).$($Matches[2]) detecte ($candidate)"
                break
            }
        }
    } catch { Log "Echec $candidate : $_" }
}

if (-not $pythonExe) {
    Step "Telechargement de Python 3.12.9..."
    $pyUrl  = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"
    $pyInst = "$env:TEMP\python-3.12.9-amd64.exe"
    Log "Download: $pyUrl"

    Write-Host "  Telechargement en cours..." -ForegroundColor DarkCyan
    Invoke-WebRequest -Uri $pyUrl -OutFile $pyInst -UseBasicParsing
    OK "Telechargement termine"

    Step "Installation de Python 3.12 (quelques secondes)..."
    $proc = Start-Process -FilePath $pyInst `
        -ArgumentList "/quiet","InstallAllUsers=0","PrependPath=1","Include_launcher=0","Include_test=0","Include_doc=0" `
        -Wait -PassThru
    Remove-Item $pyInst -ErrorAction SilentlyContinue

    if ($proc.ExitCode -ne 0) {
        throw "L'installeur Python a retourne le code $($proc.ExitCode)"
    }
    OK "Python 3.12 installe"

    # Rafraichir PATH dans la session courante
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
    Log "PATH rafraichi"
    $pythonExe = "python"
}

# ─────────────────────────────────────────────
# FFMPEG
# ─────────────────────────────────────────────
Step "Verification de FFmpeg..."

$ffmpegOk  = $false
$ffmpegBin = ""

try {
    $fver = (& ffmpeg -version 2>&1 | Select-Object -First 1 | Out-String).Trim()
    Log "ffmpeg system: $fver"
    OK "FFmpeg detecte dans le PATH"
    $ffmpegOk = $true
} catch { Log "ffmpeg non trouve dans PATH" }

if (-not $ffmpegOk) {
    $localBin = Join-Path $scriptDir "ffmpeg\bin"
    if (Test-Path (Join-Path $localBin "ffmpeg.exe")) {
        $env:PATH = "$localBin;$env:PATH"
        $ffmpegBin = $localBin
        OK "FFmpeg local detecte (.\ffmpeg\bin\)"
        $ffmpegOk = $true
        Log "FFmpeg local: $localBin"
    }
}

if (-not $ffmpegOk) {
    Step "Telechargement de FFmpeg (environ 75 MB)..."

    $ffmpegZip     = "$env:TEMP\ffmpeg-essentials.zip"
    $ffmpegExtract = "$env:TEMP\ffmpeg_extract_derush"
    $ffmpegTarget  = Join-Path $scriptDir "ffmpeg"

    # Trouver la derniere version
    $dlUrl = $null
    try {
        $gh    = Invoke-RestMethod -Uri "https://api.github.com/repos/GyanD/codexffmpeg/releases/latest" `
                 -Headers @{"User-Agent"="DerushTool"} -UseBasicParsing
        $asset = $gh.assets | Where-Object { $_.name -like "*essentials_build.zip" } | Select-Object -First 1
        $dlUrl = $asset.browser_download_url
        Log "GitHub release: $($gh.tag_name) -> $dlUrl"
    } catch {
        Log "GitHub API echec : $_"
    }

    if (-not $dlUrl) {
        $dlUrl = "https://github.com/GyanD/codexffmpeg/releases/download/7.1.1/ffmpeg-7.1.1-essentials_build.zip"
        Log "Fallback URL: $dlUrl"
    }

    Write-Host "  Telechargement en cours (patiente ~1 minute)..." -ForegroundColor DarkCyan
    Invoke-WebRequest -Uri $dlUrl -OutFile $ffmpegZip -UseBasicParsing
    OK "FFmpeg telecharge"

    Step "Extraction de FFmpeg..."
    if (Test-Path $ffmpegExtract) { Remove-Item $ffmpegExtract -Recurse -Force }
    New-Item -ItemType Directory -Path $ffmpegExtract | Out-Null
    Expand-Archive -Path $ffmpegZip -DestinationPath $ffmpegExtract -Force

    $ffExe = Get-ChildItem $ffmpegExtract -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    if (-not $ffExe) { throw "ffmpeg.exe introuvable dans l'archive telechargee" }

    if (Test-Path $ffmpegTarget) { Remove-Item $ffmpegTarget -Recurse -Force }
    New-Item -ItemType Directory -Path "$ffmpegTarget\bin" | Out-Null
    Copy-Item "$($ffExe.DirectoryName)\*" "$ffmpegTarget\bin\" -Force
    Log "FFmpeg copie dans $ffmpegTarget\bin\"

    Remove-Item $ffmpegZip     -ErrorAction SilentlyContinue
    Remove-Item $ffmpegExtract -Recurse -ErrorAction SilentlyContinue

    # Ajouter au PATH utilisateur (permanent)
    $ffmpegBin = "$ffmpegTarget\bin"
    $userPath  = [System.Environment]::GetEnvironmentVariable("PATH","User")
    if ($userPath -notlike "*$ffmpegBin*") {
        [System.Environment]::SetEnvironmentVariable("PATH", "$userPath;$ffmpegBin", "User")
        Log "PATH utilisateur mis a jour"
    }
    $env:PATH = "$ffmpegBin;$env:PATH"

    OK "FFmpeg installe dans .\ffmpeg\bin\"
    $ffmpegOk = $true
}

# ─────────────────────────────────────────────
# PIP PACKAGES
# ─────────────────────────────────────────────
Step "Installation des packages Python (pystray, Pillow)..."
Log "pip install pystray Pillow"

& $pythonExe -m pip install --upgrade pip --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "pip upgrade a echoue (code $LASTEXITCODE)" }

& $pythonExe -m pip install pystray Pillow --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install pystray Pillow a echoue (code $LASTEXITCODE)" }

OK "pystray et Pillow installes"

# ─────────────────────────────────────────────
# FIN
# ─────────────────────────────────────────────
Log "=== Installation reussie ==="
Write-Host ""
Write-Host "  ==========================================" -ForegroundColor Green
Write-Host "       Installation terminee !              " -ForegroundColor Green
Write-Host "  ==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Double-clique sur DEMARRER.bat pour lancer l'outil." -ForegroundColor White
Write-Host ""

$rep = Read-Host "  Lancer DERUSH TOOL maintenant ? (O/N)"
if ($rep -match "^[oOyY]") {
    Start-Process -FilePath $pythonExe -ArgumentList "`"$(Join-Path $scriptDir 'derush_launcher.py')`"" -WorkingDirectory $scriptDir
    Write-Host "  Lance ! Le navigateur va s'ouvrir dans quelques secondes." -ForegroundColor Green
}

Write-Host ""
Read-Host "  Appuie sur Entree pour fermer"
