@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem "start" her zaman basarili doner; bu yuzden pythonw'nin varligi once kontrol edilir.
if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" "%~dp0gui.py"
    goto :eof
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0gui.py"
    goto :eof
)
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" "%~dp0gui.py"
) else (
    python "%~dp0gui.py"
)
if errorlevel 1 pause
