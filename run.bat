@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
    ".venv\Scripts\python.exe" push_daily.py >> logs\run.log 2>&1
) else (
    python push_daily.py >> logs\run.log 2>&1
)
