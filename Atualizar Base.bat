@echo off
chcp 65001 >nul
title Atlas - Atualizar Base
cd /d "%~dp0"
rem Com /agendado (Agendador de Tarefas) a janela fecha sozinha no fim.
if not exist ".venv\Scripts\python.exe" (
  echo Abra o "Iniciar Atlas" uma vez antes, para preparar o ambiente.
  if /i not "%~1"=="/agendado" pause
  exit /b 1
)
".venv\Scripts\python.exe" -m atlas.atualizar
if /i not "%~1"=="/agendado" pause
