@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Gercek piksel kapaklar icin Windows Terminal (Sixel) tercih edilir.
rem Zaten Terminal icindeysek yeni pencere acma.
if defined WT_SESSION goto run
where wt.exe >nul 2>nul
if errorlevel 1 goto run
if exist "venv\Scripts\python.exe" (
    wt.exe -w new --maximized -d "%~dp0." "%~dp0venv\Scripts\python.exe" "%~dp0main.py"
) else (
    wt.exe -w new --maximized -d "%~dp0." python "%~dp0main.py"
)
if not errorlevel 1 exit /b 0
:run
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" main.py
) else (
    python main.py
)
if errorlevel 1 pause
