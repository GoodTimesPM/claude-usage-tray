@echo off
setlocal
set "here=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-ChildItem -LiteralPath '%here%' -Recurse | Unblock-File -ErrorAction SilentlyContinue; & '%here%install.ps1'"

echo.
echo Press any key to close this window...
pause >nul
