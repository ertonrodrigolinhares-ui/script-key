@echo off
rem Analisar Script: arraste um ou mais scripts em cima deste arquivo.
rem Aberto com dois cliques, ele pergunta o caminho do script.
setlocal
title Analisador de Scripts

rem Procura o Python: py (lancador do Windows), python ou o py da pasta WindowsApps.
set "PY="
py --version >nul 2>&1 && set "PY=py"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\py.exe" set "PY="%LOCALAPPDATA%\Microsoft\WindowsApps\py.exe""
if not defined PY (
    echo Python nao encontrado neste computador.
    echo Instale em https://www.python.org/downloads e marque "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

%PY% "%~dp0analisador_scripts.py" %*
echo.
pause
