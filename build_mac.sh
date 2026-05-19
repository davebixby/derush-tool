#!/bin/bash
set -e
echo "========================================="
echo " DERUSH TOOL — Build macOS"
echo "========================================="

pip install -r requirements.txt

pyinstaller derush.spec --clean --noconfirm

if [ -d "dist/DerushTool.app" ]; then
    echo ""
    echo "Build OK : dist/DerushTool.app"
    echo "Copiez DerushTool.app dans /Applications."
else
    echo "Build ECHEC."
    exit 1
fi
