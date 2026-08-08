@echo off
:: Launch Blade power switcher with admin elevation
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process -FilePath py -ArgumentList '-3','-m','app.main' -WorkingDirectory '%cd%' -Verb RunAs"
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Start-Process -FilePath python -ArgumentList '-m','app.main' -WorkingDirectory '%cd%' -Verb RunAs"
)
