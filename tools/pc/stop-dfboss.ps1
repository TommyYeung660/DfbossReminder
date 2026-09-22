# Stop every running DFBossReminder, however it was started.
#
# Two launchers exist on purpose: the exe the player double-clicks, and the
# run-dfboss.ps1 wrapper used for a logged run. This stops both, and reports how many
# it found so "it did not stop" is visible rather than silent.
#
# ASCII-only: PowerShell 5.1 reads a BOM-less script as ANSI.
#
# Usage (game PC):  powershell -ExecutionPolicy Bypass -File tools\pc\stop-dfboss.ps1

$ErrorActionPreference = "Stop"

$names = @("DFBossReminder", "python", "py")
$targets = @()
foreach ($name in $names) {
    $found = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($found) {
        foreach ($process in $found) {
            # Only the ones actually running this tool: a plain python.exe could be
            # anything, so its command line has to name dfbossreminder.
            $line = (Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)").CommandLine
            if ($line -and ($line -like "*dfbossreminder*" -or $line -like "*DFBossReminder*")) {
                $targets += ,@($process, $line)
            }
        }
    }
}

if (-not $targets) {
    Write-Host "no DFBossReminder process found"
    exit 0
}

foreach ($target in $targets) {
    $process = $target[0]
    Write-Host "stopping pid $($process.Id): $($target[1])"
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
Write-Host "stopped $($targets.Count) process(es)"
