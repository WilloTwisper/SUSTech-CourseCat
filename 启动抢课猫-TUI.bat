@echo off
title 抢课猫 CourseCat - TUI 版
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
  .venv\Scripts\coursecat-tui --help >nul 2>&1
  if errorlevel 1 (
    echo [x] 依赖安装失败：请检查网络连接后重新双击运行。
    pause
    exit /b 1
  )
  echo [!] 依赖更新被跳过（可能有旧窗口正在运行，请先关闭旧窗口），使用现有环境继续…
)
echo [*] 启动抢课猫 TUI 版…
.venv\Scripts\coursecat-tui
pause
