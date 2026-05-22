#!/bin/bash
# sync.sh — Synchronise le code Derush Tool avec GitHub (Mac / Linux).
#
# Fait, dans l'ordre : commit des modifs locales → récupère le distant
# → renvoie le tout. Après ça, cette machine et GitHub sont identiques.
#
# Usage :
#   ./sync.sh                      (message de commit automatique)
#   ./sync.sh "ce que j'ai changé" (message de commit personnalisé)
#
# Première fois seulement : chmod +x sync.sh

cd "$(dirname "$0")" || exit 1

MSG="${1:-sync depuis $(hostname) — $(date '+%Y-%m-%d %H:%M')}"

echo "→ Commit des modifs locales (s'il y en a)..."
git add -A
if git diff --cached --quiet; then
    echo "  (rien de nouveau en local)"
else
    git commit -m "$MSG" || { echo "✗ Échec du commit."; exit 1; }
fi

echo "→ Récupération depuis GitHub..."
if ! git pull --rebase origin main; then
    echo ""
    echo "✗ CONFLIT pendant la fusion."
    echo "  Le même fichier a été modifié ici ET sur une autre machine."
    echo "  → Demande à Claude de résoudre, ou annule avec : git rebase --abort"
    exit 1
fi

echo "→ Envoi vers GitHub..."
if ! git push origin main; then
    echo "✗ Échec du push — souci d'authentification ? Voir GIT_SETUP.md."
    exit 1
fi

echo ""
echo "✓ Synchronisé — cette machine et GitHub sont identiques."
