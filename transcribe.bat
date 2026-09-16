@echo off
REM ===================================================================
REM  Medford Transcripts -- transcription loop
REM
REM  Previously this ran python once and ended with `pause`, which kept
REM  the error on screen but meant a dead pipeline looked ALIVE to Task
REM  Scheduler (cmd.exe sat at "Press any key" forever, so State stayed
REM  Running and restart-on-failure never fired).
REM
REM  This keeps the error -- permanently, in logs\ -- and restarts.
REM
REM  The interpreter is pinned: six pythons are installed on this box and
REM  only Python311 has dateutil, yt_dlp and whisperx.
REM ===================================================================

setlocal
cd /d "%~dp0"

set "PY=C:\Users\jdeas\AppData\Local\Programs\Python\Python311\python.exe"
set "SCRIPT=create_subtitles.py"
set "ARGS=-t"
set "NAME=transcribe"
set "RESTART_SECONDS=60"

if not exist "logs" mkdir "logs"

:loop

REM one log file per day, so it stays findable and does not grow forever
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "TODAY=%%i"
set "LOG=logs\%NAME%_%TODAY%.log"

for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-ddTHH:mm:ss"') do set "NOW=%%t"

echo.>> "%LOG%"
echo ============================================================>> "%LOG%"
echo [%NOW%] starting %SCRIPT% %ARGS%>> "%LOG%"
echo ============================================================>> "%LOG%"

echo [%NOW%] starting %SCRIPT% %ARGS%  (logging to %LOG%)

"%PY%" -u "%SCRIPT%" %ARGS% >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"

for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-ddTHH:mm:ss"') do set "NOW=%%t"
>> "%LOG%" echo [%NOW%] EXITED with code %RC%

REM Surface the failure on the console too, so it is visible at a glance
REM if someone happens to be watching -- the log keeps it either way.
echo.
echo [%NOW%] %SCRIPT% %ARGS% EXITED with code %RC%. Last 40 log lines:
echo ------------------------------------------------------------
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 40"
echo ------------------------------------------------------------
echo Restarting in %RESTART_SECONDS%s.  Full log: %LOG%
echo.

powershell -NoProfile -Command "Start-Sleep -Seconds %RESTART_SECONDS%"
goto loop
