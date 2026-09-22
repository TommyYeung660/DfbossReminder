@echo off
rem Open the DFBossReminder settings window (whitelist, font size, colours).
rem
rem Needs no game, no network and no overlay, so it can be run any time. It writes the
rem same settings file the overlay reads on its next start.
rem
rem Usage (game PC):  tools\pc\config-gui.cmd

setlocal
set "REPO=%~dp0..\.."
if not exist "%REPO%\src" set "REPO=C:\DFTools\DfbossReminder"
cd /d "%REPO%" || (echo cannot enter %REPO% & exit /b 1)

if exist "%USERPROFILE%\Desktop\DFBossReminderConfig.exe" (
    echo starting the settings window...
    start "" "%USERPROFILE%\Desktop\DFBossReminderConfig.exe"
    exit /b 0
)

echo no DFBossReminderConfig.exe on the Desktop; running from source instead.
echo build it with: tools\pc\build-exe.cmd
py -3 tools\dfboss_config_main.py
endlocal
