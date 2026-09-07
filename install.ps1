<#
.SYNOPSIS
    Install the Claude usage tray icons and start them at login.

.DESCRIPTION
    Installs the three Python dependencies for the current user, then drops a
    shortcut in your Startup folder pointing pythonw.exe at app\tray_app.pyw.

    A Startup shortcut is deliberate: it is one file you can see and delete, so
    getting rid of this app never means hunting through the registry or Task
    Scheduler. Safe to re-run; it overwrites the shortcut it made last time.

.PARAMETER SkipDeps
    Do not touch pip. Use this if you manage the dependencies yourself.

.PARAMETER NoStart
    Install the shortcut but do not launch the app now.
#>

[CmdletBinding()]
param(
    [switch]$SkipDeps,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

$scriptDir = $PSScriptRoot
$appScript = Join-Path $scriptDir "app\tray_app.pyw"
$requirements = Join-Path $scriptDir "requirements.txt"

if (-not (Test-Path $appScript)) {
    throw "Could not find $appScript. Run this from inside the repo."
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "python was not found on PATH. Install Python 3.9+ and try again."
}
$pythonExe = $python.Source
$pythonwExe = $pythonExe -replace "python\.exe$", "pythonw.exe"
if (-not (Test-Path $pythonwExe)) {
    throw "Could not find pythonw.exe next to $pythonExe. This app needs it to run without a console window."
}

if (-not $SkipDeps) {
    Write-Host "Installing dependencies for the current user..."
    & $pythonExe -m pip install --user --quiet -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "pip install failed. See the output above." }
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

if ($NoStart) {
    Write-Host ""
    Write-Host "Not started. It will launch at your next login, or run it now with:"
    Write-Host "  & `"$pythonwExe`" `"$appScript`""
    return
}

$already = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*tray_app.pyw*" }

if ($already) {
    Write-Host "Already running (PID $($already.ProcessId)). Leaving it alone."
} else {
    Start-Process -FilePath $pythonwExe -ArgumentList "`"$appScript`"" -WorkingDirectory (Split-Path $appScript)
    Write-Host "Started. Two numbers should appear in your tray within a few seconds."
}
