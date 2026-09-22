@echo off
rem Executed by the DFB-Interactive scheduled task, which runs in the user's
rem interactive desktop session. The overlay window cannot be created from an SSH
rem session, because those run in session 0 and session 0 has no visible desktop;
rem this wrapper is how it is driven remotely.
rem
rem tools/run_on_pc.sh writes ..\..\.run.cmd over SSH, then triggers the task and
rem reads ..\..\.run-out-<run token>.txt back. Which output file that is cannot be
rem passed as an argument - the task runs a fixed command line - so the token travels
rem in ..\..\.run-token.txt.
rem
rem The output file is per run on purpose. It used to be one shared .run-out.txt, and a
rem command that left a background process behind (an overlay started so that it keeps
rem running) handed that process the inherited stdout handle: the file could then be
rem neither deleted nor rewritten, and every later run timed out reporting a stale
rem result. A per-run name means an earlier run's leftovers cannot affect this one.
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"

if not exist ".run.cmd" (
    > ".run-out-missing.txt" echo ERROR: .run.cmd was not found in %ROOT%
    exit /b 2
)
if not exist ".run-token.txt" (
    > ".run-out-missing.txt" echo ERROR: .run-token.txt was not found in %ROOT%
    exit /b 2
)

set "TOKEN="
set /p TOKEN=<".run-token.txt"
if "%TOKEN%"=="" (
    > ".run-out-missing.txt" echo ERROR: .run-token.txt held no token
    exit /b 2
)
set "OUT=.run-out-%TOKEN%.txt"

> "%OUT%" echo DFB interactive run %DATE% %TIME%
>> "%OUT%" echo session: interactive desktop (scheduled task)
>> "%OUT%" echo.
call ".run.cmd" >> "%OUT%" 2>&1
set "RC=%ERRORLEVEL%"
>> "%OUT%" echo.
>> "%OUT%" echo EXITCODE=%RC%
exit /b 0
