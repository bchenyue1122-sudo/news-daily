@echo off
rem Windows 任务计划程序入口：每天定时调用（也可手动运行）
cd /d "%~dp0"
if not exist logs mkdir logs
if exist .venv\Scripts\python.exe (
    ".venv\Scripts\python.exe" push_daily.py >> logs\run.log 2>&1
) else (
    python push_daily.py >> logs\run.log 2>&1
)
