# Start DFBossReminder on the game PC, logging to a file, and print the first lines.
#
# ASCII-only on purpose: PowerShell 5.1 reads a BOM-less script as ANSI, so a single
# non-ASCII character can swallow the next quote and make the error point at the
# wrong line.
#
# Usage (game PC):
#   powershell -ExecutionPolicy Bypass -File tools\pc\run-dfboss.ps1
#   powershell -ExecutionPolicy Bypass -File tools\pc\run-dfboss.ps1 -Radius 20 -Anchor top-left
#   powershell -ExecutionPolicy Bypass -File tools\pc\run-dfboss.ps1 -Once -Json plan.json
#   powershell -ExecutionPolicy Bypass -File tools\pc\run-dfboss.ps1 -Highlight "red=1015,999"

param(
    [string]$Exe = "$env:USERPROFILE\Desktop\DFBossReminder.exe",
    [string]$UserId = "",
    [int]$Radius = 0,
    [string[]]$Highlight = @(),
    [ValidateSet("", "overlay", "panel", "console")][string]$Presentation = "",
    [ValidateSet("", "top-left", "top-right", "bottom-left", "bottom-right", "center")][string]$Anchor = "",
    [int]$Poll = 0,
    [switch]$Once,
    [string]$Json = "",
    [string]$Log = "$env:USERPROFILE\Desktop\dfboss.log"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Exe)) {
    Write-Host "no exe at $Exe - build it first: tools\pc\build-exe.cmd" -ForegroundColor Red
    exit 1
}

$arguments = @()
if ($UserId) { $arguments += @("--user-id", $UserId) }
if ($Radius -gt 0) { $arguments += @("--radius", "$Radius") }
foreach ($rule in $Highlight) { $arguments += @("--highlight", $rule) }
if ($Presentation) { $arguments += @("--presentation", $Presentation) }
if ($Anchor) { $arguments += @("--anchor", $Anchor) }
if ($Poll -gt 0) { $arguments += @("--poll", "$Poll") }
if ($Json) { $arguments += @("--json", $Json) }
if ($Once) { $arguments += @("--once") }

Write-Host "starting $Exe $($arguments -join ' ')"
Write-Host "log: $Log"

if ($Once) {
    & $Exe @arguments 2>&1 | Tee-Object -FilePath $Log
    exit $LASTEXITCODE
}

# Start detached so the shell returns; the tool runs until its window is closed or
# stop-dfboss.ps1 is called.
$process = Start-Process -FilePath $Exe -ArgumentList $arguments -PassThru `
    -RedirectStandardOutput $Log -RedirectStandardError "$Log.err"
Write-Host "started pid $($process.Id); the overlay window should be on screen now"
Write-Host "tail the log with:  Get-Content '$Log' -Wait"
