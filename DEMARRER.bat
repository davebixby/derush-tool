@echo off
chcp 65001 >nul
title DERUSH TOOL

:: Ajouter ffmpeg local au PATH si present
if exist "%~dp0ffmpeg\bin\ffmpeg.exe" (
    set "PATH=%~dp0ffmpeg\bin;%PATH%"
)

python --version >nul 2>&1
if errorlevel 1 (
    echo Python introuvable. Lance d'abord INSTALLER.bat
    pause
    exit /b 1
)

start "" python "%~dp0derush_launcher.py"
