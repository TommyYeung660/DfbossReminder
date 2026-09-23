@echo off
rem Open the DFBossReminder settings window (styles, font size, colours, position).
rem
rem This is the same exe as the readout: with no arguments it opens the settings window,
rem and 開始 in that window starts the overlay. It needs no game, no network and no
rem overlay to open, so it can be run any time.
rem
rem Usage (game PC):  tools\pc\config-gui.cmd

setlocal
set "REPO=%~dp0..\.."
if not exist "%REPO%\src" set "REPO=C:\DFTools\DfbossReminder"
cd /d "%REPO%" || (echo cannot enter %REPO% & exit /b 1)

if exist "%USERPROFILE%\Desktop\DFBossReminder.exe" (
    echo starting the settings window...
    start "" "%USERPROFILE%\Desktop\DFBossReminder.exe"
    exit /b 0
)

echo no DFBossReminder.exe on the Desktop; running from source instead.
echo build it with: tools\pc\build-exe.cmd
py -3 tools\dfboss_main.py
endlocal
