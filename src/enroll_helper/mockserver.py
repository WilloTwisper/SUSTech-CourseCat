from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import constants as C
from .tis.models import Course

SEMESTER = {"p_xn": "2026", "p_xq": "1", "p_xnxq": "2026-1", "mxpylx": 1}

CATALOG: dict[str, list[dict]] = {
    "bxxk": [{"id": "MOCK-101", "rwmc": "高等数学B（mock）", "bksrl": 40, "bksyxrs": 32,
              "kcdm": "MA101", "kcmc": "高等数学B", "skyymc": "中文",
              "kkyxmc": "数学系", "jfzlbmc": "十三级制", "xf": "4.0", "zxs": "64.0",
              "kclbmc": "通识必修课", "kcxzmc": "必修"}],
    "xxxk": [{"id": "MOCK-102", "rwmc": "中国古代史（mock）", "bksrl": 30, "bksyxrs": 30,
              "kcdm": "HSS201", "kcmc": "中国古代史", "skyymc": "中文",
              "kkyxmc": "人文中心", "jfzlbmc": "十三级制", "xf": "2.0", "zxs": "32.0",
              "kclbmc": "通识选修课", "kcxzmc": "选修"}],
    "kzyxk": [{"id": "MOCK-103", "rwmc": "数据结构（mock）", "bksrl": 25, "bksyxrs": 23,
              "kcdm": "CS203", "kcmc": "数据结构", "skyymc": "双语",
              "kkyxmc": "计算机系", "jfzlbmc": "十三级制", "xf": "3.0", "zxs": "48.0",
              "kclbmc": "专业选修课", "kcxzmc": "选修"}],
    "zynknjxk": [{"id": "MOCK-104", "rwmc": "量子力学（mock）", "bksrl": 20, "bksyxrs": 20,
              "kcdm": "PHY204", "kcmc": "量子力学", "skyymc": "双语",
              "kkyxmc": "物理系", "jfzlbmc": "十三级制", "xf": "3.0", "zxs": "48.0"}],
    "cxxk": [{"id": "MOCK-105", "rwmc": "大学英语重修（mock）", "bksrl": 60, "bksyxrs": 58,
              "kcdm": "E003", "kcmc": "大学英语", "skyymc": "英文",
              "kkyxmc": "语言中心", "jfzlbmc": "十三级制", "xf": "2.0", "zxs": "32.0"}],
    "jhnxk": [],
}

_LOGIN_HTML = "<html><body>统一身份认证 请登录</body></html>"
_OK_HTML = "<html><body>选课</body></html>"


def mock_catalog() -> dict[str, Course]:
    out: dict[str, Course] = {}
    for code, lst in CATALOG.items():
        for it in lst:
            out[it["rwmc"]] = Course(
                it["id"], it["rwmc"], code, C.COURSE_TYPES.get(code, code),
                it.get("bksrl"), it.get("bksyxrs"))
    return out


class MockTisState:
    def __init__(self):
        self.counters: dict[str, int] = {}
        self.requests: list[tuple[float, str, dict]] = []
        self._lock = threading.Lock()

    def hit(self, path: str, body: dict, cookie: str) -> tuple[int, str]:
        with self._lock:
            self.requests.append((time.perf_counter(), path, dict(body)))
            n = self.counters.get(body.get("p_id", path), 0) + 1
            self.counters[body.get("p_id", path)] = n
        if path == "/Xsxk/queryXkdqXnxq":
            return 200, json.dumps(SEMESTER)
        if path == "/Xsxk/queryKxrw":
            code = body.get("p_xkfsdm", "")
            return 200, json.dumps({"kxrwList": {"list": CATALOG.get(code, [])}})
        if path == "/Xsxk/addGouwuche":
            if "MOCKSESSION=ok" not in cookie:
                return 200, _LOGIN_HTML
            pid = body.get("p_id", "")
            if pid == "MOCK-101":
                return 200, json.dumps({"jg": "1", "message": "选课成功：课程：高等数学B（mock）"})
            if pid == "MOCK-102":
                return 200, json.dumps({"jg": "0", "message": "上课时间冲突：与已选课程冲突"})
            if pid == "MOCK-103":
                if n < 3:
                    return 200, json.dumps({"jg": "0", "message": "不在选课时间内"})
                return 200, json.dumps({"jg": "1", "message": "选课成功：课程：数据结构（mock）"})
            if pid == "MOCK-104":
                return 200, json.dumps({"jg": "0", "message": "人数已满"})
            if pid == "MOCK-105":
                if n < 3:
                    return 429, "too many requests"
                return 200, json.dumps({"jg": "1", "message": "选课成功：课程：大学英语重修（mock）"})
            return 200, json.dumps({"jg": "0", "message": "未知错误"})
        return 404, json.dumps({"message": "not found"})


def make_handler(state: MockTisState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _respond(self, code: int, text: str, ctype: str = "application/json"):
            data = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.startswith("/Xsxk/query/1"):
                self._respond(200, _OK_HTML, "text/html")
            else:
                self._respond(404, json.dumps({"message": "not found"}))

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", "replace")
            body = {k: v[0] for k, v in parse_qs(raw).items()}
            code, text = state.hit(self.path, body, self.headers.get("Cookie", ""))
            ctype = "text/html" if text.lstrip().startswith("<") else "application/json"
            self._respond(code, text, ctype)

    return Handler


class MockServerHandle:
    def __init__(self, server: ThreadingHTTPServer, state: MockTisState):
        self.server = server
        self.state = state
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def start_mock(port: int = 8765) -> MockServerHandle:
    state = MockTisState()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    return MockServerHandle(server, state).start()


def start_background(port: int = 8765) -> MockServerHandle:
    return start_mock(port)


def main():
    handle = start_mock(8765)
    print("[mock-tis] http://127.0.0.1:8765 （Ctrl+C 停止）")
    print('[mock-tis] 演练: enroll-helper --rehearse --courses courses.txt')
    print('[mock-tis] 剧本: MOCK-101 恒成功 | MOCK-102 恒冲突 | MOCK-103 第3次成功(未开放)'
          ' | MOCK-104 恒满员 | MOCK-105 前两次429后成功')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handle.stop()


if __name__ == "__main__":
    main()
