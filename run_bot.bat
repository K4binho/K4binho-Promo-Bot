@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
python -u bot.py >> bot.log 2>&1
