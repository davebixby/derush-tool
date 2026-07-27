#!/bin/bash
# Derush Tool — Build script pour macOS Apple Silicon (M1/M2/M3)
#
# Usage : depuis le dossier racine du projet (celui qui contient derush_server.py)
#   chmod +x build_mac.sh
#   ./build_mac.sh
#
# Produit : electron/dist/DerushTool-X.Y.Z-mac-arm64.zip

set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
VERSION=$(cat VERSION 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")

echo ""
echo "========================================================"
echo "  Derush Tool — Build macOS arm64 (v${VERSION})"
echo "========================================================"
echo ""

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
fail() { echo -e "${RED}X $1${NC}"; echo -e "${YELLOW}  -> $2${NC}"; exit 1; }
ok()   { echo -e "${GREEN}OK $1${NC}"; }
warn() { echo -e "${YELLOW}!! $1${NC}"; }

echo "-- Verification des prerequis --"

ARCH=$(uname -m)
if [ "$ARCH" != "arm64" ]; then
    warn "Architecture detectee : $ARCH (le build cible arm64). Tournera via Rosetta sur Intel."
fi
ok "Architecture : $ARCH"

if ! xcode-select -p &>/dev/null; then
    fail "Xcode Command Line Tools manquants" "Installe avec : xcode-select --install"
fi
ok "Xcode Command Line Tools"

if ! command -v brew &>/dev/null; then
    fail "Homebrew manquant" 'Installe : /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
fi
ok "Homebrew $(brew --version | head -1 | awk '{print $2}')"

if ! command -v python3 &>/dev/null; then
    fail "Python 3 manquant" "Installe avec : brew install python@3.11"
fi
ok "Python $(python3 --version | awk '{print $2}')"

if ! command -v node &>/dev/null; then
    fail "Node.js manquant" "Installe avec : brew install node"
fi
ok "Node $(node --version)"

if ! command -v npm &>/dev/null; then
    fail "npm manquant" "Re-installe : brew reinstall node"
fi
ok "npm $(npm --version)"

if ! command -v ffmpeg &>/dev/null; then
    fail "ffmpeg manquant" "Installe avec : brew install ffmpeg"
fi
FFMPEG_PATH=$(which ffmpeg)
ok "ffmpeg ($FFMPEG_PATH)"

if ! command -v ffprobe &>/dev/null; then
    fail "ffprobe manquant" "brew reinstall ffmpeg"
fi
FFPROBE_PATH=$(which ffprobe)
ok "ffprobe ($FFPROBE_PATH)"
echo ""

echo "-- Bundling des binaires ffmpeg/ffprobe --"
# rm -f d'abord : les binaires Homebrew sont en lecture seule, donc une copie
# precedente est non-inscriptible et 'cp' echouerait avec "Permission denied".
rm -f "$ROOT/ffmpeg" "$ROOT/ffprobe"
cp "$FFMPEG_PATH"  "$ROOT/ffmpeg"
cp "$FFPROBE_PATH" "$ROOT/ffprobe"
chmod +x "$ROOT/ffmpeg" "$ROOT/ffprobe"
ok "ffmpeg + ffprobe copies a la racine"
echo ""

echo "-- Icone (.icns) --"
if [ ! -f "$ROOT/derush_icon.icns" ]; then
    if [ -f "$ROOT/derush_icon.png" ]; then
        warn "derush_icon.icns absent, generation depuis derush_icon.png..."
        ICONSET="$ROOT/.tmp_iconset.iconset"
        rm -rf "$ICONSET"
        mkdir -p "$ICONSET"
        for size in 16 32 64 128 256 512 1024; do
            sips -z $size $size "$ROOT/derush_icon.png" --out "$ICONSET/icon_${size}x${size}.png" &>/dev/null || true
        done
        iconutil -c icns "$ICONSET" -o "$ROOT/derush_icon.icns"
        rm -rf "$ICONSET"
        ok "derush_icon.icns genere"
    else
        warn "Pas d'icone PNG, l'app utilisera l'icone Electron par defaut"
    fi
else
    ok "derush_icon.icns deja present"
fi
echo ""

echo "-- Environnement Python (venv) --"
if [ ! -d "$ROOT/.venv" ]; then
    python3 -m venv "$ROOT/.venv"
    ok ".venv cree"
else
    ok ".venv deja present"
fi
source "$ROOT/.venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Deps Python installees"
echo ""

echo "-- PyInstaller --"
pyinstaller derush.spec --clean --noconfirm 2>&1 | tail -15
if [ ! -d "dist/DerushTool.app" ]; then
    fail "Build PyInstaller a echoue" "Verifie les logs ci-dessus"
fi
ok "dist/DerushTool.app cree"
echo ""

echo "-- Electron builder --"
cd "$ROOT/electron"
# On teste la presence du binaire electron-builder, pas juste du dossier :
# un node_modules existant mais incomplet (run precedent interrompu) ne
# declenchait pas la reinstallation -> "electron-builder: command not found".
if [ ! -x "node_modules/.bin/electron-builder" ]; then
    npm install
fi
npm run build:mac 2>&1 | tail -15
echo ""

echo ""
echo "========================================================"
echo "  BUILD TERMINE"
echo "========================================================"
echo ""
ZIP=$(ls -t "$ROOT/electron/dist/"*.zip 2>/dev/null | head -1)
DMG=$(ls -t "$ROOT/electron/dist/"*.dmg 2>/dev/null | head -1)
if [ -n "$ZIP" ]; then
    SIZE=$(du -h "$ZIP" | awk '{print $1}')
    ok "Zip pret : $ZIP ($SIZE)"
fi
if [ -n "$DMG" ]; then
    SIZE=$(du -h "$DMG" | awk '{print $1}')
    ok "DMG pret : $DMG ($SIZE)"
fi
if [ -n "$ZIP" ] || [ -n "$DMG" ]; then
    echo ""
    echo "Pour tester (zip) :"
    echo "  1. Decompresse le zip dans /Applications ou un dossier"
    echo "  2. Premier lancement : clic droit sur DerushTool.app -> Ouvrir"
    echo "     (sinon Gatekeeper refuse car app non-signee)"
    echo "  3. Confirme 'Ouvrir' dans la popup"
    echo "  4. Pour le MBP M2 : copie simplement le .zip et refais clic droit -> Ouvrir"
    echo ""
    echo "Pour tester (dmg) :"
    echo "  1. Double-clic sur le .dmg, glisse DerushTool.app dans Applications"
    echo "  2. Premier lancement : clic droit sur DerushTool.app -> Ouvrir (meme raison, app non-signee)"
else
    fail "Aucun zip ni dmg trouve dans electron/dist/" "Verifie les logs Electron"
fi
