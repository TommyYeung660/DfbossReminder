@echo off
rem Prove the overlay window is really on screen, and record both kinds of evidence.
rem
rem Run through tools\run_on_pc.sh, so it executes inside the interactive desktop
rem session (an SSH command would create the window on session 0's invisible
rem desktop and prove nothing).
rem
rem Two artifacts, on purpose:
rem   * overlay.bmp  - the pixels the overlay itself hands to UpdateLayeredWindow,
rem                    which is the only reliable answer to "what is it drawing";
rem   * a screen PNG - photographed from the desktop, which answers "is it on
rem                    screen at all", a question the dump cannot answer.
rem
rem Usage:  verify-overlay.cmd [panel|overlay] [anchor] [seconds] ["L T W H"]
setlocal enableextensions
set "ROOT=%~dp0..\.."
set "PRESENTATION=%~1"
set "ANCHOR=%~2"
set "DURATION=%~3"
set "RECT=%~4"
if "%PRESENTATION%"=="" set "PRESENTATION=panel"
if "%ANCHOR%"=="" set "ANCHOR=top-left"
if "%DURATION%"=="" set "DURATION=20"
set "RECTFILE=%ROOT%\tools\pc\evidence\client-rect.txt"

cd /d "%ROOT%" || (echo cannot enter %ROOT% & exit /b 1)
if not exist "tools\pc\evidence" mkdir "tools\pc\evidence"
set "BMP=%ROOT%\tools\pc\evidence\overlay.bmp"
if exist "%BMP%" del /q "%BMP%"

echo === case ===
echo presentation=%PRESENTATION% anchor=%ANCHOR% duration=%DURATION% rect=%RECT%
echo cwd=%CD%
echo.

rem Where does the game window actually sit? Reported here so the overlay's own
rem placement can be checked against it, and so the crop below is of the client area.
echo === game window ===
py -3 tools\pc\probe-window.py --list 3 --rect-file "%RECTFILE%"
echo.

rem The overlay draws its own surface once, then keeps running; started in the
rem background so the screenshot below lands while it is still up.
echo === starting the overlay ===
rem Its own log file, not the run log: a process started with ``start /b`` inherits
rem this script's stdout, and while it held the run log open the wrapper's trailing
rem EXITCODE line could not be appended, which made the caller poll until it timed out.
start /b "" cmd /c "py -3 tools\dfboss_main.py --presentation %PRESENTATION% --anchor %ANCHOR% --seconds %DURATION% --dump-frame ""%BMP%"" > tools\pc\evidence\overlay-run.log 2>&1"

rem Long enough for the first fetch and the first draw, short enough to still be up.
timeout /t 9 /nobreak >nul

rem Measure the client rather than trusting a caller-supplied rectangle: the window
rem moves between runs, and a stale rect frames the wrong part of the screen.
if exist "%RECTFILE%" set /p MEASURED=<"%RECTFILE%"
if not "%MEASURED%"=="" set "RECT=%MEASURED%"
echo cropping the client area at "%RECT%"

echo === screen capture (from the desktop) ===
if "%RECT%"=="" (
    powershell -ExecutionPolicy Bypass -NoProfile -File tools\pc\capture-panel.ps1 -Label "dfboss-%PRESENTATION%" -OutDir "tools\pc\evidence"
) else (
    powershell -ExecutionPolicy Bypass -NoProfile -File tools\pc\capture-panel.ps1 -Label "dfboss-%PRESENTATION%" -OutDir "tools\pc\evidence" -ClientRect "%RECT%"
)
set "SHOT=%ERRORLEVEL%"
echo capture exit=%SHOT%

rem Let the overlay finish so its own dump and its log are complete.
timeout /t 16 /nobreak >nul

echo.
echo === the overlay's own report ===
if exist "tools\pc\evidence\overlay-run.log" (type "tools\pc\evidence\overlay-run.log") else (echo no overlay-run.log)

echo === artifacts ===
if exist "%BMP%" (for %%F in ("%BMP%") do echo overlay.bmp %%~zF bytes) else (echo overlay.bmp MISSING)
dir /b "tools\pc\evidence\*.png" 2>nul
echo.
echo === done ===
exit /b 0
