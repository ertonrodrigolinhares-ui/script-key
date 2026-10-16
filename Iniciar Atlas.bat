@echo off
chcp 65001 >nul
title Atlas - assistente de IA
cd /d "%~dp0"

if not exist "requirements.txt" (
  echo Extraia o ZIP inteiro numa pasta antes de abrir o "Iniciar Atlas".
  pause
  exit /b 1
)

rem Procura um Python 3.10+ que funcione de verdade (o atalho da Microsoft Store nao conta).
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto instalar_python

rem Refaz o ambiente se ele foi criado com um Python antigo ou quebrado.
rem Refaz tambem se o pip faltar (ambiente criado pela metade).
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys, pip; sys.exit(sys.version_info < (3,10))" >nul 2>nul
  if errorlevel 1 rmdir /s /q ".venv"
)
if not exist ".venv\Scripts\python.exe" (
  echo Preparando o Atlas pela primeira vez. Isso leva alguns minutos...
  %PY% -m venv .venv
  if errorlevel 1 rmdir /s /q ".venv"
)
if not exist ".venv\Scripts\python.exe" (
  echo Nao consegui criar o ambiente do Python. Reinstale o Python 3.12 e tente de novo.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo.
  echo Falha ao instalar os componentes. Veja a mensagem acima, confira a internet e tente de novo.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m atlas
pause
exit /b

:instalar_python
where winget >nul 2>nul
if errorlevel 1 goto sem_python
echo Python 3.10 ou mais novo nao encontrado. Instalando pelo winget...
rem Os erros do winget sao numeros negativos: "||" pega qualquer codigo diferente de zero.
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements || goto sem_python
echo.
echo Python instalado. Feche esta janela e abra o "Iniciar Atlas" de novo.
pause
exit /b

:sem_python
echo.
echo Nao consegui instalar o Python automaticamente.
echo Baixe em https://www.python.org/downloads/ e, na primeira tela do instalador,
echo marque "Add python.exe to PATH". Depois abra o "Iniciar Atlas" de novo.
pause
exit /b 1
