@echo off
title Ultron Automation Server - Pense Rede Lab
color 0A
chcp 65001 >nul

echo ========================================================
echo   ULTRON AUTOMATION SERVER - PENSE REDE LAB (24/7)
echo ========================================================
echo.
echo [*] Verificando ambiente Python e dependencias...

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if exist ".\venv\Scripts\python.exe" (
    set PYTHON_EXE=.\venv\Scripts\python.exe
) else (
    set PYTHON_EXE=python
)

echo [*] Iniciando Ultron Server em 0.0.0.0:7000...
echo [*] Conectando ao TrueConf Server, Milvus e WinRM...
echo.

%PYTHON_EXE% main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] O servidor foi encerrado ou encontrou um erro.
    pause
)
