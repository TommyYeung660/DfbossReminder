@echo off
rem Executed by the DFB-Interactive scheduled task, which runs in the user's
rem interactive desktop session. The overlay window cannot be created from an SSH
rem session, because those run in session 0 and session 0 has no visible desktop;
rem this wrapper is how it is driven remotely.
rem
rem tools/run_on_pc.sh writes ..\..\.run.cmd over SSH, then triggers the task and
rem reads ..\..\.run-out.txt back.
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"

if not exist ".run.cmd" (
    > ".run-out.txt" echo ERROR: .run.cmd was not found in %ROOT%
    exit /b 2
)

> ".run-out.txt" echo DFB interactive run %DATE% %TIME%
>> ".run-out.txt" echo session: interactive desktop (scheduled task)
>> ".run-out.txt" echo.
call ".run.cmd" >> ".run-out.txt" 2>&1
set "RC=%ERRORLEVEL%"
>> ".run-out.txt" echo.
>> ".run-out.txt" echo EXITCODE=%RC%
exit /b 0
