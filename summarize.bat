@echo off
REM ===================================================================
REM  Medford Transcripts -- nightly meeting summaries
REM
REM  WHY THIS RUNS ONCE AND EXITS, unlike transcribe.bat / download.bat.
REM  Those are bounded by CPU: there is always more work and the loop
REM  should never stop. This is bounded by a DAILY API ALLOWANCE, so the
REM  useful unit of work is "burn today's quota, then stop". Looping would
REM  just walk the model ladder for every remaining meeting and fail each
REM  one -- hours of log activity and no output.
REM
REM  summarize_meeting.py detects that itself: a per-day 429 raises
REM  DailyQuotaExhausted and the --all loop returns cleanly instead of
REM  grinding. So this wrapper only has to run it and record the outcome.
REM
REM  WHY IT STARTS AT 3:05 AM EASTERN. Gemini's free-tier daily quotas
REM  reset at midnight PACIFIC, which is 3 AM Eastern. Starting just after
REM  the reset gets the whole day's allowance in one clean window, and it
REM  is also when Google is least congested -- measured in the afternoon,
REM  every flash model returned 503 "high demand" for minutes at a time,
REM  which wastes wall clock and does nothing for throughput.
REM
REM  IT RESUMES BY ITSELF. Each summary is cached on the transcript SHA,
REM  so a meeting already summarised is skipped; the next night simply
REM  continues down the list. No state file, nothing to corrupt.
REM
REM  The interpreter is pinned: six pythons are installed on this box and
REM  only Python311 has dateutil, yt_dlp and whisperx.
REM ===================================================================

setlocal
cd /d "%~dp0"

set "PY=C:\Users\jdeas\AppData\Local\Programs\Python\Python311\python.exe"
set "SCRIPT=summarize_meeting.py"
REM A provider, not a model: the ladder picks whichever one answers today.
REM Pinning a name is what broke this before -- gemini-2.5-pro was the
REM default here and is now a 404.
set "ARGS=--all --model gemini"
set "NAME=summaries"

if not exist "logs" mkdir "logs"

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

REM Count what exists now, so the log answers "is this making progress?"
REM without anyone having to reconstruct it from the run output.
REM No pipe: inside a for /f the ^| escaping reaches PowerShell as a literal
REM caret and the whole command fails. @(...).Count needs no pipe.
for /f %%c in ('powershell -NoProfile -Command "@(Get-ChildItem -Path . -Filter *.summary.json -Recurse -Depth 1 -ErrorAction SilentlyContinue).Count"') do set "TOTAL=%%c"
>> "%LOG%" echo [%NOW%] summaries on disk: %TOTAL%
echo [%NOW%] exited %RC%; summaries on disk: %TOTAL%

endlocal
