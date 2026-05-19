@echo off
echo =========================================
echo  DERUSH TOOL — Build Windows
echo =========================================

pip install -r requirements.txt

pyinstaller derush.spec --clean --noconfirm

if exist "dist\DerushTool\DerushTool.exe" (
    echo.
    echo Build OK : dist\DerushTool\DerushTool.exe
    echo Lancez DerushTool.exe pour demarrer le serveur.
) else (
    echo Build ECHEC.
    exit /b 1
)
