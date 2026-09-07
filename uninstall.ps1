<#
.SYNOPSIS
    Remove the Startup shortcut and stop the running tray app.

.DESCRIPTION
    Leaves pystray, Pillow and requests installed; they are harmless, and
    install.ps1 needs them again if you change your mind. Delete the repo
    folder afterwards to be rid of it entirely.
#>

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Claude Usage Tray.lnk"

if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
    Write-Host "Removed startup shortcut: $shortcutPath"
} else {
    Write-Host "No startup shortcut found (already removed)."
}

Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*tray_app.pyw*" } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force
        Write-Host "Stopped running tray app (PID $($_.ProcessId))"
    }
