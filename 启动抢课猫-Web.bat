@echo off
title 抢课猫 CourseCat - Web 版
chcp 65001 >nul
cd /d %~dp0
if not exist pyproject.toml (
  echo [x] 找不到 pyproject.toml。
  echo     请先把 ZIP 完整解压到一个文件夹，再双击运行，不要在压缩包里直接打开。
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo [*] 首次运行，创建虚拟环境…
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
echo [*] 安装/更新依赖（首次约1-3分钟，请勿关闭窗口）…
.venv\Scripts\python -m pip install -e ".[dev]" --quiet --disable-pip-version-check
if errorlevel 1 (
  echo [x] 依赖安装失败：请检查网络连接后重新双击运行。
  pause
  exit /b 1
)
echo [*] 启动抢课猫 Web 版，浏览器会自动打开一个页面…
echo     要停止时直接关闭本窗口即可。
.venv\Scripts\coursecat-web
pause
