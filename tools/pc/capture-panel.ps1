# Capture evidence that the overlay is actually on screen, over the game client.
#
# This is the one thing the development machine cannot produce: a layered window is
# not reproduced by a screen capture on every display configuration, so "it is there"
# has to be recorded on the machine that has a display. Two captures are taken - the
# full screen, and the game's client rectangle - so the overlay's position can be
# checked against the client area as well as its presence.
#
# ASCII-only: PowerShell 5.1 reads a BOM-less script as ANSI.
#
# Usage (game PC, with the overlay running):
#   powershell -ExecutionPolicy Bypass -File tools\pc\capture-panel.ps1 -Label "overlay-top-left"
#
# Output: tools\pc\evidence\<timestamp>-<label>[-client].png

param(
    [string]$Label = "overlay",
    [string]$OutDir = "",
    [string]$ClientRect = ""
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot "evidence" }
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }

function Save-Region {
    param([string]$Path, [int]$X, [int]$Y, [int]$Width, [int]$Height)
    $bitmap = New-Object System.Drawing.Bitmap $Width, $Height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($X, $Y, 0, 0, $bitmap.Size)
    $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
    Write-Host "wrote $Path ($Width x $Height at $X,$Y)"
}

$stamp = Get-Date -Format "yyyyMMddTHHmmssZ"
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$full = Join-Path $OutDir "$stamp-$Label.png"
Save-Region -Path $full -X 0 -Y 0 -Width $screen.Width -Height $screen.Height

if ($ClientRect) {
    $parts = $ClientRect -split "[,\s]+" | Where-Object { $_ -ne "" }
    if ($parts.Count -eq 4) {
        $client = Join-Path $OutDir "$stamp-$Label-client.png"
        Save-Region -Path $client -X ([int]$parts[0]) -Y ([int]$parts[1]) `
                    -Width ([int]$parts[2]) -Height ([int]$parts[3])
    } else {
        Write-Host "ClientRect must be 'L T W H'; skipped the client capture" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Now send the images back, or read them where they are."
Write-Host "On the images check: the readout is above the game, only the readout and its"
Write-Host "backing are visible (no opaque rectangle), and the text is legible."
