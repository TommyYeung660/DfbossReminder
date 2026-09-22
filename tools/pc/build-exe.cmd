@echo off
REM Build DFBossReminder into a single exe, straight onto the Desktop.
REM
REM The player runs it from there, so the build output goes there directly instead of
REM a dist folder that then has to be copied - a copy step is one more place for a
REM stale build to survive unnoticed.
REM
REM Deliberately a .cmd, not a .ps1: PowerShell 5.1 reads a BOM-less file as ANSI, and
REM a batch file has no such trap.
REM
REM Usage (game PC):  tools\pc\build-exe.cmd
setlocal
set "REPO=C:\DFTools\DfbossReminder"
if not exist "%REPO%" set "REPO=%~dp0..\.."
set "OUT=%USERPROFILE%\Desktop"

cd /d "%REPO%" || (echo cannot enter %REPO% & exit /b 1)

REM --onefile keeps it to one file to hand around. A console build is on purpose:
REM the startup lines and any fetch error are then visible, and the overlay is a
REM separate window either way. Running it with the console minimised is normal use.
py -m PyInstaller --noconfirm --onefile --name DFBossReminder ^
   --paths src --distpath "%OUT%" --workpath build --specpath build ^
   tools\dfboss_main.py || (echo build failed & exit /b 1)

if not exist "%OUT%\DFBossReminder.exe" (echo no exe produced & exit /b 1)
for %%F in ("%OUT%\DFBossReminder.exe") do echo Built %%F  (%%~zF bytes, %%~tF)

REM The settings window is built as its own --windowed exe, so it opens from a desktop
REM shortcut without a console behind it, and so it can be opened with the game shut.
py -m PyInstaller --noconfirm --onefile --windowed --name DFBossReminderConfig ^
   --paths src --distpath "%OUT%" --workpath build-config --specpath build ^
   tools\dfboss_config_main.py || (echo config build failed & exit /b 1)

if not exist "%OUT%\DFBossReminderConfig.exe" (echo no config exe produced & exit /b 1)
for %%F in ("%OUT%\DFBossReminderConfig.exe") do echo Built %%F  (%%~zF bytes, %%~tF)
endlocal
