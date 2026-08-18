@echo off
title Derush Tool - Claude Code
rem Se place dans le dossier de ce fichier (le projet), quel que soit l'endroit du double-clic
cd /d "%~dp0"

rem Verifie que Claude Code est installe et accessible
where claude >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERREUR] La commande "claude" est introuvable dans le PATH.
  echo Verifie que Claude Code est bien installe.
  echo.
  pause
  exit /b 1
)

echo.
echo ====================================================
echo   Derush Tool - lancement de Claude Code
echo   Dossier : %CD%
echo ====================================================
echo.

claude
