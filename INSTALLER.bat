@echo off
title DERUSH TOOL - Installation
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0_install.ps1"
if errorlevel 1 (
    echo.
    echo  Une erreur s'est produite. Consulte derush_install.log dans le meme dossier.
    pause
)
