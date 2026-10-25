@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    start "" "venv\Scripts\pythonw.exe" "%~dp0gui.py" 2>nul || "venv\Scripts\python.exe" "%~dp0gui.py"
) else (
    start "" pythonw "%~dp0gui.py" 2>nul || python "%~dp0gui.py"
)
