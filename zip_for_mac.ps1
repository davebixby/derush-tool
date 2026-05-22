# =============================================================
#  Derush Tool - Prepare un zip des sources pour le build macOS
# =============================================================
#  Usage : clic droit sur ce fichier -> "Executer avec PowerShell"
#          ou dans un terminal :  .\zip_for_mac.ps1
#
#  Produit : un .zip sur le Bureau, pret a transferer sur le Mac.
#  Voir BUILD_MAC.md pour la suite (lancer ./build_mac.sh sur le Mac).
# =============================================================

$ErrorActionPreference = "Stop"

# --- Chemins -------------------------------------------------
# Le dossier source = le dossier ou se trouve ce script
$src   = $PSScriptRoot
$stage = Join-Path $env:TEMP "derush_tool_stage"
$ver   = (Get-Content (Join-Path $src "VERSION") -Raw).Trim()
$zip   = Join-Path ([Environment]::GetFolderPath("Desktop")) "derush_tool_mac_v$ver.zip"

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  Derush Tool - Zip des sources pour build macOS (v$ver)" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Source : $src"
Write-Host "Sortie : $zip"
Write-Host ""

# --- Nettoyage d'un eventuel run precedent -------------------
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
if (Test-Path $zip)   { Remove-Item $zip -Force }

# --- Copie filtree vers le dossier de staging ----------------
#  /XD = dossiers exclus (par nom, a n'importe quel niveau) :
#        - dist, build, node_modules : artefacts de build, recrees sur Mac
#        - projects        : tes projets perso (facultatif - voir ci-dessous)
#        - .git, __pycache__, thumbnails, waveforms, sync_fingerprints : caches
#  /XF = fichiers exclus :
#        - ffmpeg.exe / ffprobe.exe : binaires Windows (~300 Mo), inutiles sur
#          Mac (build_mac.sh recopie les versions Mac depuis Homebrew)
#
#  >>> Pour EMBARQUER tes projets : retire "projects" de la ligne /XD <<<
Write-Host "Copie des fichiers utiles..." -ForegroundColor Yellow
$rc = Start-Process robocopy -ArgumentList @(
    "`"$src`"", "`"$stage`"", "/E",
    "/XD", "dist", "build", "node_modules", "projects",
           ".git", "__pycache__", "thumbnails", "waveforms", "sync_fingerprints",
    "/XF", "ffmpeg.exe", "ffprobe.exe",
    "/NFL", "/NDL", "/NJH", "/NJS", "/NP"
) -Wait -PassThru -NoNewWindow

# robocopy : code de sortie < 8 = succes (0-7), >= 8 = erreur reelle
if ($rc.ExitCode -ge 8) {
    Write-Host "X Echec de la copie (robocopy code $($rc.ExitCode))" -ForegroundColor Red
    exit 1
}

# --- Verification : les fichiers cles sont-ils la ? ----------
$musts = @(
    "derush_launcher.py", "derush_server.py", "derush.spec",
    "requirements.txt", "VERSION", "build_mac.sh",
    "electron\package.json", "electron\package-lock.json", "electron\main.js"
)
$missing = $musts | Where-Object { -not (Test-Path (Join-Path $stage $_)) }
if ($missing) {
    Write-Host "X Fichiers cles manquants apres copie :" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
    exit 1
}

# --- Compression --------------------------------------------
Write-Host "Compression du zip..." -ForegroundColor Yellow
Compress-Archive -Path "$stage\*" -DestinationPath $zip
Remove-Item $stage -Recurse -Force

# --- Resume --------------------------------------------------
$sizeMB = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  ZIP PRET" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  $zip" -ForegroundColor White
Write-Host "  Taille : $sizeMB Mo"
Write-Host ""
Write-Host "Suite :"
Write-Host "  1. Copie ce .zip sur le Mac (cle USB / AirDrop / iCloud)"
Write-Host "  2. Dezippe-le, puis dans Terminal : cd vers le dossier"
Write-Host "  3. chmod +x build_mac.sh  &&  ./build_mac.sh"
Write-Host "  (details dans BUILD_MAC.md)"
Write-Host ""
