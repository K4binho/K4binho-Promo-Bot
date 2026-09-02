@echo off
cd /d "%~dp0"
set PYTHONUTF8=1

set "PYTHON_EXE=python"
where python >nul 2>nul
if errorlevel 1 (
    for /d %%D in ("%LocalAppData%\Python\pythoncore-*") do (
        if exist "%%~fD\python.exe" set "PYTHON_EXE=%%~fD\python.exe"
    )
)

"%PYTHON_EXE%" -u bot.py >> bot.log 2>&1
