from __future__ import annotations

import contextlib
import io
import itertools
import json
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import constants as C
from .cli import (apply_cli_overrides, load_catalog, load_settings, make_args,
                  parse_at, parse_wanted, resolve_cookies)
from .clocksync import Clock, imminent_start, sntp_offset
from .config import Settings
from .engine import EnrollEngine
from .login import run_login
from .notify import Notifier
from .pacer import Pacer
from .picker import write_queue
from .schedule import find_conflicts, slots_from_extra
from .session import build_client
from .tis.client import TisApiError, TisClient, summarize_kcxx


def web_dir() -> Path:
    try:
        from importlib.resources import files
        p = files("enroll_helper").joinpath("web")
        if p.is_dir():
            return Path(str(p))
    except Exception:
        pass
    return Path(__file__).resolve().parent / "web"


def row_dict(c) -> dict:
    ex = c.extra or {}
    cap, enr = c.capacity, c.enrolled
    seats = max(cap - enr, 0) if cap is not None and enr is not None else None
    teachers = ex.get("teachers") or []
    tags = ex.get("sched_tags") or ([ex.get("schedule")] if ex.get("schedule") else [])
    return {
        "id": c.course_id,
        "task": c.name,
        "code": ex.get("kcdm") or "",
        "title": ex.get("kcmc") or c.name,
        "title_en": ex.get("kcmc_en") or "",
        "nature": ex.get("kcxzmc") or "",
        "category": ex.get("kclbmc") or c.type_name,
        "lang": ex.get("skyymc") or "",
        "grade": ex.get("jfzlbmc") or "",
        "credit": ex.get("xf") or "",
        "hours": ex.get("zxs") or "",
        "teachers": teachers,
        "teacher": "、".join(teachers),
        "schedule": ex.get("schedule") or "",
        "cap": cap,
        "enrolled": enr,
        "seats": seats,
        "sched_tags": tags,
        "school": ex.get("kkyxmc") or "",
        "type_code": c.type_code,
    }


def summary_dict(s) -> dict:
    return {
        "total_requests": s.total_requests,
        "status_counts": {k.value: v for k, v in s.status_counts.items()},
        "successes": [c.display() for c in s.successes],
        "skipped": [{"course": c.display(), "reason": r} for c, r in s.skipped],
        "remaining": [c.display() for c in s.remaining],
        "watchlist": [c.name for c in s.watchlist],
        "aborted": s.aborted,
        "avg_latency_ms": round(sum(s.latencies_ms) / len(s.latencies_ms), 1) if s.latencies_ms else 0,
    }


class _EventWriter(io.TextIOBase):
    def __init__(self, emit):
        self._emit = emit
        self._buf = ""

    def write(self, s):
        self._buf += str(s)
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._emit("log", text=line)
        return len(s)


class Hub:
    def __init__(self, base_url=None, cookie_path="cookies.txt", cookies=None,
                 interval_ms=1600, discovery_ms=5000):
        self.base_url = base_url
        self.cookie_path = cookie_path
        self.inline_cookies = dict(cookies or {})
        self.interval_ms = interval_ms
        self.discovery_ms = discovery_ms
        self._lock = threading.Lock()
        self._events: list = []
        self._counter = itertools.count(1)
        self.tis: TisClient | None = None
        self.semester = None
        self.catalog: dict = {}
        self.catalog_ts = None
        self.queue: list[str] = []
        self.status_map: dict[str, dict] = {}
        self.watchlist: list[str] = []
        self.running = False
        self.phase = "idle"
        self.target = None
        self.summary = None
        self._stop = threading.Event()
        self._engine: EnrollEngine | None = None
        self._enrolled_cache: tuple = (0.0, [])
        self._load_local()

    def emit(self, kind: str, **kw) -> int:
        with self._lock:
            eid = next(self._counter)
            self._events.append({"id": eid, "kind": kind, **kw})
            if len(self._events) > 2000:
                del self._events[:1000]
            return eid

    def events_since(self, since: int) -> list:
        with self._lock:
            return [e for e in self._events if e["id"] > since]

    def _load_local(self) -> None:
        for cache in sorted(Path(".").glob("catalog_*.json")):
            if "mock" in cache.name.lower():
                continue
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                courses = data.get("courses", {})
                if any("capacity" not in c or "extra" not in c
                       for c in courses.values()):
                    continue
                from .tis.models import Course
                self.catalog = {n: Course(**c) for n, c in courses.items()}
                self.catalog_ts = data.get("fetched_at")
                break
            except (OSError, ValueError):
                continue
        if Path("courses.txt").exists():
            try:
                self.queue = parse_wanted("courses.txt")
            except OSError:
                pass

    def has_session_source(self) -> bool:
        return bool(self.inline_cookies) or Path(self.cookie_path).exists()

    def _settings(self, **over) -> Settings:
        kw: dict = dict(non_interactive=True, interval_ms=self.interval_ms,
                        discovery_interval_ms=self.discovery_ms)
        if self.inline_cookies:
            kw["inline_cookies"] = [f"{k}={v}" for k, v in self.inline_cookies.items()]
        else:
            kw["cookies_file"] = self.cookie_path
        if self.base_url:
            kw["base_url"] = self.base_url
        kw.update(over)
        args = make_args(**kw)
        return apply_cli_overrides(load_settings(None, args), args)

    def ensure_tis(self) -> TisClient:
        if self.tis is not None:
            return self.tis
        settings = self._settings()
        try:
            cookies = resolve_cookies(settings)
        except SystemExit as e:
            raise RuntimeError(str(e))
        client = build_client(settings.base_url, cookies, settings.tls_verify,
                              settings.timeout_s, settings.endpoints,
                              trust_env=not settings.no_env_proxy)
        self.tis = TisClient(client, settings.endpoints, settings.keywords)
        self._tis_settings = settings
        return self.tis

    def ensure_semester(self):
        if self.semester is not None:
            return self.semester
        tis = self.ensure_tis()
        try:
            self.semester = tis.query_semester()
        except TisApiError as e:
            raise RuntimeError(str(e))
        return self.semester

    def ensure_catalog(self, force: bool = False) -> dict:
        if self.catalog and not force:
            return self.catalog
        tis = self.ensure_tis()
        sem = self.ensure_semester()
        settings = self._settings(refresh_cache=force)
        self.catalog = load_catalog(tis, sem, settings,
                                    emit=lambda m: self.emit("log", text=m),
                                    confirm_refresh=False,
                                    use_cache=not settings.is_local_target)
        try:
            data = json.loads(Path(f"catalog_{sem.p_xnxq}.json").read_text(
                encoding="utf-8"))
            self.catalog_ts = data.get("fetched_at") or time.time()
        except (OSError, ValueError):
            self.catalog_ts = time.time()
        return self.catalog

    def set_queue(self, names: list[str]) -> tuple[list[str], list[str]]:
        with self._lock:
            known = [n for n in names if n in self.catalog]
            unknown = [n for n in names if n not in self.catalog]
            self.queue = known
        try:
            from .tis.models import Course  # noqa: F401
            write_queue("courses.txt", [self.catalog[n] for n in known])
        except OSError:
            pass
        return known, unknown

    def _fetch_enrolled_raw(self) -> list:
        tis = self.ensure_tis()
        sem = self.ensure_semester()
        return tis.query_enrolled(sem)

    def enrolled_detailed(self) -> list:
        now = time.time()
        if now - self._enrolled_cache[0] < 60:
            return self._enrolled_cache[1]
        out = []
        for it in self._fetch_enrolled_raw():
            name = str(it.get("rwmc") or it.get("kcmc") or "")
            if not name:
                continue
            teachers, schedule, tags = summarize_kcxx(str(it.get("kcxx") or ""))
            extra = {"sched_tags": tags, "schedule": schedule}
            out.append({"name": name, "id": str(it.get("id") or ""),
                        "teachers": teachers, "schedule": schedule,
                        "slots": slots_from_extra(extra)})
        self._enrolled_cache = (now, out)
        return out

    def start_job(self, opts: dict) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("已在运行中")
            self.running = True
            self.phase = "preparing"
            self.summary = None
            self.status_map = {}
            self.watchlist = []
            if opts.get("queue") is not None:
                self.set_queue(list(opts["queue"]))
        self._stop.clear()
        threading.Thread(target=self._job, args=(opts,), daemon=True).start()

    def stop_job(self) -> None:
        self._stop.set()
        if self._engine is not None:
            self._engine._commands.append("q")

    def _note_attempt(self, attempt, idx: int) -> None:
        with self._lock:
            self.status_map[attempt.course.name] = {
                "status": attempt.status.value,
                "message": attempt.message,
                "latency_ms": round(attempt.latency_ms, 1),
            }
        self.emit("attempt", index=idx, course=attempt.course.name,
                  status=attempt.status.value, message=attempt.message,
                  latency_ms=round(attempt.latency_ms, 1))

    def _job(self, opts: dict) -> None:
        try:
            tis = self.ensure_tis()
            sem = self.ensure_semester()
            self.emit("log", text=f"[+] 当前学期: {sem.label()} ({sem.p_xnxq})")
            self.ensure_catalog()
            queue = [self.catalog[n] for n in self.queue if n in self.catalog]
            missing = [n for n in self.queue if n not in self.catalog]
            for n in missing:
                self.emit("log", text=f"[!] 目录中未找到: {n}")
            if not queue:
                raise RuntimeError("队列为空：先在课程表中点“选课”加入")
            mode = opts.get("mode", "now")
            interval = int(opts.get("interval_ms") or self.interval_ms)
            settings = self._settings(
                interval_ms=interval,
                retry_full=bool(opts.get("retry") or mode == "retry"),
                cascade=bool(opts.get("cascade")),
                submit_target=opts.get("target") or "rwtjzyx",
                use_ntp=bool(opts.get("ntp")),
                at_time=opts.get("at") if mode == "at" else None)
            settings.auto_skip_conflict = bool(opts.get("ignore_conflict", True))
            at_text = opts.get("at") if mode == "at" else None
            if imminent_start(at_text):
                self.emit("log", text="[i] 临近开抢时刻，跳过余量刷新")
            else:
                self.emit("log", text="[*] 刷新队列余量…")
                queue = tis.refresh_seats(queue, sem, Pacer(self.discovery_ms))
            self.emit("log", text=f"[+] 连接预热完成 HTTP {tis.warmup()}")
            if settings.at_time:
                from .cli import parse_at
                target = parse_at(settings.at_time)
                self.target = datetime.fromtimestamp(target).strftime("%H:%M:%S")
                self.phase = "waiting"
                offset = 0.0
                if settings.use_ntp:
                    try:
                        offset = sntp_offset(settings.ntp_server)
                        self.emit("log", text=f"[+] NTP 校准完成，偏差 {offset * 1000:+.0f}ms")
                    except (OSError, ValueError) as e:
                        self.emit("log", text=f"[!] NTP 失败（{e}），使用本机时钟")
                clock = Clock(offset)
                while clock.time() < target:
                    if self._stop.is_set():
                        self.emit("log", text="[!] 定时已取消")
                        return
                    time.sleep(0.2)
                while clock.time() < target:
                    if self._stop.is_set():
                        return
                    pass
                self.emit("log", text="[+] 时间到，开始")
            self.phase = "running"
            notifier = Notifier("", False, quiet=True)
            engine = EnrollEngine(tis, sem, Pacer(settings.interval_ms),
                                  settings, notifier, quiet=True)
            self._engine = engine
            engine.on_attempt = self._note_attempt
            summary = engine.run(deque(queue), 0)
            self.summary = summary_dict(summary)
            self.watchlist = list(self.summary.get("watchlist", []))
            self.emit("done", summary=self.summary)
            self.phase = "done"
        except (RuntimeError, SystemExit) as e:
            self.emit("error", text=str(e))
            self.phase = "error"
        except Exception as e:
            self.emit("error", text=f"{type(e).__name__}: {e}")
            self.phase = "error"
        finally:
            with self._lock:
                self.running = False
            self._engine = None

    def login_job(self) -> None:
        threading.Thread(target=self._login, daemon=True).start()

    def _login(self) -> None:
        with contextlib.redirect_stdout(_EventWriter(self.emit)):
            pairs = run_login(self.cookie_path)
        if pairs:
            self.tis = None
            self.semester = None
            self.emit("log", text=f"[+] 登录成功: {', '.join(pairs.keys())}")
        else:
            self.emit("error", text="登录未完成")

    def refresh_job(self) -> None:
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self) -> None:
        try:
            self.ensure_catalog(force=True)
            self.emit("log", text=f"[+] 目录已刷新：{len(self.catalog)} 门")
        except (RuntimeError, SystemExit) as e:
            self.emit("error", text=str(e))
        except Exception as e:
            self.emit("error", text=f"{type(e).__name__}: {e}")

    def status(self) -> dict:
        with self._lock:
            queue = list(self.queue)
            smap = dict(self.status_map)
        rows = []
        for i, n in enumerate(queue, 1):
            c = self.catalog.get(n)
            st = smap.get(n, {})
            rows.append({
                "index": i, "name": n,
                "type": c.type_name if c else "",
                "seats": c.seats_text() if c else "--",
                "cap": c.capacity if c else None,
                "enrolled": c.enrolled if c else None,
                "status": st.get("status", "等待"),
                "message": st.get("message", ""),
                "watch": n in self.watchlist,
            })
        ts = self.catalog_ts
        if ts:
            snap = datetime.fromtimestamp(ts).strftime("%H:%M")
        else:
            snap = ""
        return {
            "session": self.has_session_source(),
            "semester": self.semester.label() if self.semester else "",
            "semester_code": self.semester.p_xnxq if self.semester else "",
            "catalog_count": len(self.catalog),
            "cache_snap": snap,
            "queue": rows,
            "running": self.running,
            "phase": self.phase,
            "target": self.target,
        }


def make_handler(hub: Hub):
    class Handler(BaseHTTPRequestHandler):
        server_version = "EnrollWeb/0.1"

        def log_message(self, *a):
            pass

        def _send(self, code: int, obj, ctype: str = "application/json"):
            if isinstance(obj, bytes):
                data = obj
            elif isinstance(obj, str):
                data = obj.encode("utf-8")
                ctype = "text/plain; charset=utf-8"
            else:
                data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8"
                             if "charset" not in ctype else ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_file(self, name: str, ctype: str):
            try:
                data = (web_dir() / name).read_bytes()
            except OSError:
                self._send(404, {"error": "not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8"
                             if "charset" not in ctype else ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = 0
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/":
                    self._send_file("index.html", "text/html")
                elif path == "/app.js":
                    self._send_file("app.js", "application/javascript")
                elif path == "/api/status":
                    self._send(200, hub.status())
                elif path == "/api/courses":
                    qs = parse_qs(parsed.query)
                    self._send(200, courses_view(
                        hub, qs.get("tab", ["all"])[0], qs.get("q", [""])[0],
                        qs.get("hide_full", ["0"])[0] == "1",
                        qs.get("school", [""])[0], qs.get("category", [""])[0],
                        qs.get("page", ["1"])[0], qs.get("size", ["30"])[0],
                        qs.get("hide_conflict", ["0"])[0] == "1"))
                elif path == "/api/facets":
                    self._send(200, facets_view(hub))
                elif path == "/api/events":
                    qs = parse_qs(parsed.query)
                    try:
                        since = int(qs.get("since", ["0"])[0])
                    except ValueError:
                        since = 0
                    self._send(200, {"events": hub.events_since(since)})
                elif path == "/api/report":
                    self._send(200, hub.summary or {})
                elif path == "/api/enrolled":
                    detailed = hub.enrolled_detailed()
                    self._send(200, {"enrolled": [
                        {"name": e["name"], "id": e["id"],
                         "teachers": e["teachers"], "schedule": e["schedule"]}
                        for e in detailed]})
                else:
                    self._send(404, {"error": "not found"})
            except (RuntimeError, SystemExit) as e:
                self._send(500, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/queue":
                    names = self._body().get("names", [])
                    known, unknown = hub.set_queue([str(n) for n in names])
                    self._send(200, {"queue": known, "unknown": unknown})
                elif path == "/api/start":
                    hub.start_job(self._body())
                    self._send(200, {"started": True})
                elif path == "/api/stop":
                    hub.stop_job()
                    self._send(200, {"stopped": True})
                elif path == "/api/refresh":
                    hub.refresh_job()
                    self._send(200, {"refreshing": True})
                elif path == "/api/login":
                    hub.login_job()
                    self._send(200, {"login_started": True})
                else:
                    self._send(404, {"error": "not found"})
            except (RuntimeError, SystemExit) as e:
                self._send(500, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def courses_view(hub: Hub, tab: str, q: str, hide_full: bool, school: str = "",
                 category: str = "", page=1, size=30, hide_conflict: bool = False) -> dict:
    if not hub.catalog:
        return {"courses": [], "total": 0, "page": 1, "size": size, "needs_refresh": True}
    q = (q or "").strip()
    matched = []
    for c in hub.catalog.values():
        if tab != "all" and c.type_code != tab:
            continue
        if q and q not in c.name:
            continue
        ex = c.extra or {}
        if school and (ex.get("kkyxmc") or "") != school:
            continue
        if category and (ex.get("kclbmc") or c.type_name) != category:
            continue
        if hide_full:
            cap, enr = c.capacity, c.enrolled
            if cap is not None and enr is not None and cap - enr <= 0:
                continue
        matched.append(c)
    matched.sort(key=lambda c: c.name)
    try:
        enrolled = hub.enrolled_detailed()
    except Exception:
        enrolled = []
    emap = [(e["name"], e["slots"]) for e in enrolled]
    rows = []
    for c in matched:
        r = row_dict(c)
        r["conflicts"] = find_conflicts(slots_from_extra(c.extra or {}), emap)
        if hide_conflict and r["conflicts"]:
            continue
        rows.append(r)
    total = len(rows)
    try:
        page = max(int(page), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        size = min(max(int(size), 1), 200)
    except (TypeError, ValueError):
        size = 30
    pages = max((total + size - 1) // size, 1)
    page = min(page, pages)
    start = (page - 1) * size
    return {"courses": rows[start:start + size], "total": total, "page": page,
            "pages": pages, "size": size, "needs_refresh": False}


def facets_view(hub: Hub) -> dict:
    if not hub.catalog:
        return {"schools": [], "categories": []}
    schools = sorted({(c.extra or {}).get("kkyxmc") or ""
                      for c in hub.catalog.values()} - {""})
    cats = sorted({(c.extra or {}).get("kclbmc") or c.type_name
                   for c in hub.catalog.values()})
    return {"schools": schools, "categories": cats}


def main(argv=None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="coursecat-web", description="抢课猫 CourseCat Web 版（本机）")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--cookies", default="cookies.txt")
    args = p.parse_args(argv)
    hub = Hub(cookie_path=args.cookies)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(hub))
    server.hub = hub
    url = f"http://127.0.0.1:{args.port}/"
    print(f"[enroll-web] {url}（仅本机监听，Ctrl+C 停止）")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
