# Removes the startup shortcut and stops any running instance.
# Does not uninstall pystray/Pillow/requests (harmless to leave; re-run install_startup.ps1 to reinstall).

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
