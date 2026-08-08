@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo  BladePower 一键打包
echo ========================================
echo.

set "PY=python"
where py >nul 2>&1 && set "PY=py -3"

echo [1/4] 安装打包依赖...
%PY% -m pip install -q -r requirements.txt pyinstaller
if errorlevel 1 (
  echo pip 安装失败
  pause
  exit /b 1
)

if not exist "vendor\winring0\WinRing0x64.dll" (
  echo 缺少 vendor\winring0\WinRing0x64.dll
  echo 请先放入 WinRing0 驱动文件
  pause
  exit /b 1
)
if not exist "vendor\winring0\WinRing0x64.sys" (
  echo 缺少 vendor\winring0\WinRing0x64.sys
  pause
  exit /b 1
)

if not exist "Synapse.ico" (
  echo 缺少 Synapse.ico（程序/托盘/exe 图标）
  pause
  exit /b 1
)

echo [2/4] PyInstaller 打包 onefile...
%PY% -m PyInstaller --noconfirm --clean BladePower.spec
if errorlevel 1 (
  echo 打包失败
  pause
  exit /b 1
)

set "OUT=dist\BladePower_Release"
echo [3/4] 组装输出目录 %OUT% ...
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

copy /Y "dist\BladePower.exe" "%OUT%\BladePower.exe" >nul
copy /Y "vendor\winring0\WinRing0x64.dll" "%OUT%\WinRing0x64.dll" >nul
copy /Y "vendor\winring0\WinRing0x64.sys" "%OUT%\WinRing0x64.sys" >nul
copy /Y "vendor\winring0\WinRing0.dll" "%OUT%\WinRing0.dll" >nul 2>nul
copy /Y "vendor\winring0\WinRing0.sys" "%OUT%\WinRing0.sys" >nul 2>nul
copy /Y "profiles.json" "%OUT%\profiles.json" >nul
copy /Y "Synapse.ico" "%OUT%\Synapse.ico" >nul
copy /Y "README.md" "%OUT%\README.md" >nul

(
echo BladePower 使用说明
echo ==================
echo 1. 右键 BladePower.exe -^> 以管理员身份运行
echo 2. 本目录必须保留 WinRing0x64.dll / WinRing0x64.sys
echo 3. 首次运行若杀软拦截，请将本目录加入白名单
echo 4. 配置文件: profiles.json
) > "%OUT%\使用说明.txt"

echo [4/4] 完成
echo.
echo 输出目录:
echo   %CD%\%OUT%
echo.
dir /b "%OUT%"
echo.
pause
