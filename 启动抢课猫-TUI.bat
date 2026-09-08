@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv (
  echo [*] 首次运行，创建虚拟环境…
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
echo [*] 安装/更新依赖…
.venv\Scripts\python -m pip install -e ".[dev]" --quiet --disable-pip-version-check
echo [*] 启动抢课猫 TUI 版…
.venv\Scripts\coursecat-tui
pause
