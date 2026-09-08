from __future__ import annotations

import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

from . import constants as C
from .session import save_cookie_header_file

TIS_MARKER = "tis.sustech.edu.cn"
CAS_LOGIN_URL = (C.DEFAULT_CAS_BASE + "/cas/login?service="
                 + quote(C.DEFAULT_CAS_SERVICE, safe=""))

_BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/microsoft-edge",
]


def find_browser() -> str:
    for p in _BROWSER_CANDIDATES:
        if p and Path(p).exists():
            return p
    for name in ("msedge", "chrome"):
        which = shutil.which(name)
        if which:
            return which
    return ""


def extract_tis_cookies(cookies: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in cookies or []:
        if TIS_MARKER in str(c.get("domain", "")).lower():
            name = str(c.get("name", "")).strip()
            value = str(c.get("value", ""))
            if name:
                out[name] = value
    return out


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def build_browser_args(exe: str, port: int, profile, url: str) -> list[str]:
    return [exe, f"--remote-debugging-port={port}", "--remote-allow-origins=*",
            f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--window-size=1100,850", url]


def _wait_ws_url(port: int, timeout_s: float) -> str | None:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                data = json.loads(r.read().decode())
                ws = data.get("webSocketDebuggerUrl")
                if ws:
                    return ws
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    return None


class _Cdp:
    def __init__(self, ws_url: str):
        import websocket

        self.ws = websocket.create_connection(ws_url, timeout=8)
        self._id = 0

    def get_cookies(self) -> list[dict]:
        for method in ("Storage.getCookies", "Network.getAllCookies"):
            self._id += 1
            want = self._id
            try:
                self.ws.send(json.dumps({"id": want, "method": method, "params": {}}))
                deadline = time.time() + 8
                while time.time() < deadline:
                    msg = json.loads(self.ws.recv())
                    if msg.get("id") != want:
                        continue
                    result = msg.get("result") or {}
                    cookies = result.get("cookies") or result.get("allCookies")
                    if cookies is not None:
                        return cookies
                    break
            except Exception:
                continue
        return []

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def capture_cookies_via_browser(timeout_s: float = 300.0) -> dict[str, str] | None:
    exe = find_browser()
    if not exe:
        return None
    port = _free_port()
    profile = Path(tempfile.mkdtemp(prefix="enroll-helper-profile-"))
    print(f"[*] 启动浏览器: {Path(exe).name}（临时隔离配置，用完即删）")
    proc = subprocess.Popen(
        build_browser_args(exe, port, profile, CAS_LOGIN_URL),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("[*] 请在弹出的浏览器里完成统一身份认证登录（验证码/二次验证照常操作）")
    print(f"[*] 正在等待 TIS 会话 Cookie…（最长 {int(timeout_s)} 秒）")
    try:
        ws_url = _wait_ws_url(port, timeout_s)
        if not ws_url:
            print("[x] 浏览器调试端口未就绪")
            return None
        deadline = time.time() + timeout_s
        cdp = _Cdp(ws_url)
        try:
            while time.time() < deadline:
                pairs = extract_tis_cookies(cdp.get_cookies())
                if pairs:
                    return pairs
                time.sleep(2)
        finally:
            cdp.close()
        return None
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        time.sleep(0.5)
        shutil.rmtree(profile, ignore_errors=True)


def run_login(cookie_path: str = "cookies.txt") -> dict[str, str] | None:
    if find_browser() == "":
        print("[x] 未找到 Edge/Chrome，请手动导出 Cookie 到", cookie_path)
        print("    浏览器登录 TIS → F12 → Network → 任意请求 → 复制 Cookie 请求头 → 存入文件，首行 Cookie: ...")
        return None
    try:
        pairs = capture_cookies_via_browser()
    except Exception as e:
        print(f"[x] 浏览器自动化失败（{type(e).__name__}: {e}）")
        print("    可改用手动导出 Cookie 存为", cookie_path)
        return None
    if not pairs:
        print("[x] 未捕获到 TIS 会话 Cookie（超时或登录未完成）")
        return None
    save_cookie_header_file(cookie_path, pairs)
    print(f"[+] 已捕获并保存会话到 {cookie_path}: {', '.join(pairs.keys())}")
    return pairs
