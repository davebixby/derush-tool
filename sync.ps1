# sync.ps1 — Synchronise le code Derush Tool avec GitHub (Windows).
#
# Fait, dans l'ordre : commit des modifs locales -> recupere le distant
# -> renvoie le tout. Apres ca, cette machine et GitHub sont identiques.
#
# Usage :
#   .\sync.ps1                       (message de commit automatique)
#   .\sync.ps1 "ce que j'ai change"  (message de commit personnalise)

Set-Location $PSScriptRoot

if ($args.Count -gt 0) {
    $msg = $args[0]
} else {
    $msg = "sync depuis $env:COMPUTERNAME - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

Write-Host "-> Commit des modifs locales (s'il y en a)..." -ForegroundColor Cyan
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m $msg
    if ($LASTEXITCODE -ne 0) { Write-Host "X Echec du commit." -ForegroundColor Red; exit 1 }
} else {
    Write-Host "   (rien de nouveau en local)"
}

Write-Host "-> Recuperation depuis GitHub..." -ForegroundColor Cyan
git pull --rebase origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "X CONFLIT pendant la fusion." -ForegroundColor Red
    Write-Host "  Le meme fichier a ete modifie ici ET sur une autre machine."
    Write-Host "  -> Demande a Claude de resoudre, ou annule avec : git rebase --abort"
    exit 1
}

Write-Host "-> Envoi vers GitHub..." -ForegroundColor Cyan
git push origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "X Echec du push - souci d'authentification ? Voir GIT_SETUP.md." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "OK Synchronise -- cette machine et GitHub sont identiques." -ForegroundColor Green
