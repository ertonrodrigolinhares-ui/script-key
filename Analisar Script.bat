@echo off
rem Analisar Script: arraste um ou mais scripts em cima deste arquivo.
rem Aberto com dois cliques, ele pergunta o caminho do script.
setlocal
title Analisador de Scripts

rem Usa o lancador "py" do Windows; se nao existir, tenta "python".
set "PY=python"
where py >/dev/null 2>/dev/null && set "PY=py"
where %PY% >/dev/null 2>/dev/null || (
    echo Python nao encontrado neste computador.
    echo Instale em https://www.python.org/downloads e marque "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

%PY% "%~dp0analisador_scripts.py" %*
echo.
pause
