# Registers the Claude usage tray app to launch silently on Windows login.
# Safe to re-run - just overwrites the existing shortcut.

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appScript = Join-Path $scriptDir "app\tray_app.pyw"

if (-not (Test-Path $appScript)) {
    throw "Could not find $appScript"
}

$pythonExe = (Get-Command python -ErrorAction Stop).Source
$pythonwExe = $pythonExe -replace "python\.exe$", "pythonw.exe"
if (-not (Test-Path $pythonwExe)) {
    throw "Could not find pythonw.exe next to $pythonExe"
}

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Claude Usage Tray.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonwExe
$shortcut.Arguments = "`"$appScript`""
$shortcut.WorkingDirectory = Split-Path $appScript
$shortcut.Description = "Claude token usage - system tray"
$shortcut.Save()

Write-Host "Installed startup shortcut: $shortcutPath"
Write-Host "Target: $pythonwExe `"$appScript`""
Write-Host ""
Write-Host "It will launch automatically at your next login."
Write-Host "To start it right now without logging out, run:"
Write-Host "  & `"$pythonwExe`" `"$appScript`""
