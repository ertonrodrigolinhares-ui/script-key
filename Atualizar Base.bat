@echo off
chcp 65001 >nul
title Atlas - Atualizar Base
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Abra o "Iniciar Atlas" uma vez antes, para preparar o ambiente.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m atlas.atualizar
pause
