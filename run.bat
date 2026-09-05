@echo off
rem Windows 任务计划程序入口：每天定时调用（也可手动运行）
cd /d "%~dp0"
if not exist logs mkdir logs

rem 唤醒后网络可能需要几秒到几十秒才就绪，最多等 3 分钟
set /a tries=0
:waitnet
ping -n 1 -w 2000 www.baidu.com >nul 2>&1
if %errorlevel%==0 goto netok
set /a tries+=1
if %tries% geq 36 goto netok
timeout /t 5 /nobreak >nul
goto waitnet

:netok
if exist .venv\Scripts\python.exe (
    ".venv\Scripts\python.exe" push_daily.py >> logs\run.log 2>&1
) else (
    python push_daily.py >> logs\run.log 2>&1
)
