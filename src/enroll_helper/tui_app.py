from __future__ import annotations

import contextlib
import io
import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from queue import SimpleQueue

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (Button, Checkbox, DataTable, Footer, Input,
                              Label, ListItem, ListView, Tab, Tabs, RichLog)

from .cli import (apply_cli_overrides, load_catalog, load_settings, make_args,
                  parse_at, parse_wanted, resolve_cookies)
from .clocksync import Clock, sntp_offset
from .engine import EnrollEngine
from .login import run_login
from .notify import Notifier
from .pacer import Pacer
from .picker import filter_catalog, write_queue
from .session import build_client
from .tis.client import TisApiError, TisClient
from .tis.models import Course, Status
from .tui import style_for


def move_item(items: list, index: int, delta: int) -> int:
    j = index + delta
    if 0 <= index < len(items) and 0 <= j < len(items):
        items[index], items[j] = items[j], items[index]
        return j
    return index


TIS_THEME = Theme(
    name="tis",
    primary="#8f000b",
    secondary="#b71c28",
    accent="#2db7f5",
    warning="#FF9900",
    error="#ED4014",
    success="#19BE6B",
    foreground="#515A6E",
    background="#f5f7f9",
    surface="#FFFFFF",
    panel="#FFFFFF",
    dark=False,
)

TIS_DARK_THEME = Theme(
    name="tis-dark",
    primary="#8f000b",
    secondary="#b71c28",
    accent="#2db7f5",
    warning="#FF9900",
    error="#FF7875",
    success="#25D07D",
    foreground="#E5E5E5",
    background="#141414",
    surface="#1F1F1F",
    panel="#1F1F1F",
    dark=True,
)


class _EventWriter(io.TextIOBase):
    def __init__(self, put):
        self._put = put
        self._buf = ""

    def write(self, s):
        self._buf += str(s)
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._put(("log", line))
        return len(s)


class CourseSearchScreen(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss_none", "返回")]

    def __init__(self, get_catalog):
        super().__init__()
        self._get_catalog = get_catalog
        self._rows: list[Course] = []

    def action_dismiss_none(self) -> None:
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical(id="search-box"):
            yield Label("添加课程（输入过滤，单击直接加入，Esc/点外面返回）")
            yield Input(placeholder="如：体系结构", id="search-input")
            yield Tabs(
                Tab("全部", id="cat-all"),
                Tab("通识必修", id="cat-bxxk"),
                Tab("通识选修", id="cat-xxxk"),
                Tab("培养方案内", id="cat-kzyxk"),
                Tab("非培养方案内", id="cat-zynknjxk"),
                id="cat-tabs",
            )
            yield ListView(id="search-list")
            yield Label("", id="search-status")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()
        self._refresh("")

    def _selected_code(self):
        try:
            active = self.query_one("#cat-tabs", Tabs).active
        except Exception:
            return None
        if not active or active == "cat-all":
            return None
        return active.replace("cat-", "")

    def _refresh(self, kw: str) -> None:
        catalog = self._get_catalog()
        self._rows = filter_catalog(catalog, kw.strip(), self._selected_code())[:40]
        lv = self.query_one("#search-list", ListView)
        lv.clear()
        for c in self._rows:
            lv.append(ListItem(
                Label(f"{c.name}  [{c.type_name or c.type_code}]  {c.seats_text()}")))
        try:
            status = self.query_one("#search-status", Label)
            if not catalog:
                status.update("目录为空：检查网络（TUN/代理）后按 s 开始，或先跑一次下载目录")
            elif not self._rows:
                status.update("无匹配：换个关键字试试")
            else:
                status.update(f"共 {len(catalog)} 门，匹配 {len(self._rows)}")
        except Exception:
            pass

    @on(Input.Changed)
    def _on_change(self, event: Input.Changed) -> None:
        self._refresh(event.value)

    @on(Tabs.TabActivated)
    def _on_cat_change(self, event: Tabs.TabActivated) -> None:
        try:
            kw = self.query_one("#search-input", Input).value
        except Exception:
            kw = ""
        self._refresh(kw)

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        lv = self.query_one("#search-list", ListView)
        try:
            idx = lv.index
        except Exception:
            idx = None
        if idx is not None and 0 <= idx < len(self._rows):
            self.dismiss(self._rows[idx])
        elif self._rows:
            self.dismiss(self._rows[0])

    @on(ListView.Selected)
    def _on_select(self, event: ListView.Selected) -> None:
        try:
            idx = event.index
        except Exception:
            idx = None
        if idx is not None and 0 <= idx < len(self._rows):
            self.dismiss(self._rows[idx])

    @on(Click)
    def _on_click(self, event: Click) -> None:
        try:
            inside = self.query_one("#search-box").region.contains(
                event.screen_x, event.screen_y)
        except Exception:
            return
        if not inside:
            self.dismiss(None)


class EnrollApp(App):
    TITLE = "(=^･ω･^=) 抢课猫 · 南科大 TIS 助手"

    CSS = """
    Screen { background: #f5f7f9; color: #333333; }
    #status { height: 3; background: #E6F7FF; color: #17233D; border: solid #91D5FF; padding: 0 1; }
    #main { height: 1fr; }
    #left { width: 2fr; background: #FFFFFF; border: solid #DCDEE2; padding: 0 1; }
    #right { width: 40; background: #FFFFFF; border: solid #DCDEE2; padding: 0 1; }
    #queue-table { height: 1fr; }
    DataTable > .datatable--header { background: #ededed; color: #303030; text-style: bold; }
    #log { height: 11; background: #FFFFFF; border: solid #DCDEE2; }
    #buttons { height: 3; }
    #tis-topbar { height: 3; background: #8f000b; color: white; text-style: bold; padding: 1 2; }
    #tis-footer { width: 1fr; height: 1; background: #8f000b; color: white; padding: 0 1; text-align: center; }
    #seats-btn { background: #2db7f5; color: white; }
    Button { margin: 0 1; }
    Button:hover { text-style: bold; }
    CourseSearchScreen { align: center middle; }
    #search-box { width: 90%; height: 92%; max-width: 96; background: #FFFFFF; border: thick #8f000b; padding: 1; }
    #search-list { height: 1fr; }
    #cat-radio { layout: horizontal; height: 3; }
    Tab.-active { color: #2d8cf0; text-style: bold; }
    Underline > .underline--bar { background: #2d8cf0; }
    """

    BINDINGS = [
        Binding("q", "quit_app", "退出"),
        Binding("s", "start_run", "开始"),
        Binding("x", "stop_run", "停止"),
        Binding("a", "add_course", "加课"),
        Binding("d", "remove_course", "删课"),
        Binding("u", "move_up", "上移"),
        Binding("j", "move_down", "下移"),
        Binding("r", "refresh_seats", "刷新余量"),
        Binding("l", "login", "登录"),
        Binding("t", "rehearse", "演练"),
        Binding("v", "toggle_mode", "夜间"),
    ]

    def __init__(self):
        super().__init__()
        self.register_theme(TIS_THEME)
        self.register_theme(TIS_DARK_THEME)
        self.theme = "tis"
        self._events: SimpleQueue = SimpleQueue()
        self._queue: list[Course] = []
        self._catalog: dict[str, Course] = {}
        self._row_status: dict[str, tuple[str, str]] = {}
        self._job_running = False
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._engine: EnrollEngine | None = None
        self._tis: TisClient | None = None
        self._semester = None
        self._pending_start = False

    def compose(self) -> ComposeResult:
        yield Label("(=^･ω･^=) 抢课猫  南科大 TIS 助手", id="tis-topbar")
        yield Label("会话 … | 学期 … | 模式 立即 | 节拍 …", id="status")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Label("待选队列（按优先级从上到下）")
                yield DataTable(id="queue-table")
            with Vertical(id="right"):
                yield Label("模式")
                yield Tabs(
                    Tab("立即开抢", id="mode-now"),
                    Tab("定时开抢", id="mode-at"),
                    Tab("蹲退课", id="mode-retry"),
                    id="mode-tabs",
                )
                yield Label("开抢时间（定时模式）")
                yield Input(placeholder="HH:MM 或 YYYY-MM-DD HH:MM:SS", id="at-input")
                yield Label("请求间隔ms（≥1500）")
                yield Input(value="1600", id="interval-input")
                yield Label("提交目标")
                yield Tabs(
                    Tab("直接进已选", id="tgt-yx"),
                    Tab("进购物车", id="tgt-gwc"),
                    id="target-tabs",
                )
                yield Checkbox("NTP 校时", id="cb-ntp", value=True)
                yield Checkbox("满员轮询后备（cascade）", id="cb-cascade", value=True)
                yield Checkbox("冲突自动跳过", id="cb-autoskip", value=True)
                yield Checkbox("桌面通知", id="cb-toast", value=True)
        with Horizontal(id="buttons"):
            yield Button("开始 (s)", id="start-btn", variant="success")
            yield Button("停止 (x)", id="stop-btn", variant="error")
            yield Button("加课 (a)", id="add-btn")
            yield Button("上移 (u)", id="up-btn")
            yield Button("下移 (j)", id="down-btn")
            yield Button("删课 (d)", id="del-btn")
            yield Button("刷新余量 (r)", id="seats-btn")
            yield Button("登录 (l)", id="login-btn")
        yield RichLog(id="log", markup=False, wrap=True)
        yield Label("主 页      我要选课      ·      教学管理与服务平台", id="tis-footer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.zebra_stripes = True
        table.add_column("#", key="idx")
        table.add_column("课程", key="name")
        table.add_column("类别", key="type")
        table.add_column("余量", key="seats")
        table.add_column("状态", key="status")
        self._load_local_state()
        self.set_interval(0.2, self._drain_events)
        self.set_interval(1.0, self._tick)
        self.ui_log("欢迎使用 SUSTech 抢课助手 TUI。按 s 开始，a 加课，l 登录，q 退出。")
        if Path("cookies.txt").exists():
            threading.Thread(target=self._semester_worker, daemon=True).start()

    def _semester_worker(self) -> None:
        ev = self._events.put
        try:
            args = make_args(cookies_file="cookies.txt", non_interactive=True)
            settings = apply_cli_overrides(load_settings(None, args), args)
            self._prepare_tis(settings, ev)
            ev(("semester", None))
        except SystemExit:
            ev(("log", "[!] 会话已失效，按 l 重新登录"))
        except Exception as e:
            ev(("log", f"[!] 学期查询失败：{type(e).__name__}"))

    def ui_log(self, text: str) -> None:
        self.query_one("#log", RichLog).write(Text(text))

    def ui_log_rich(self, markup: str) -> None:
        self.query_one("#log", RichLog).write(Text.from_markup(markup))

    def set_status(self, text: str) -> None:
        self.query_one("#status", Label).update(text)

    def _load_local_state(self) -> None:
        for cache in sorted(Path(".").glob("catalog_*.json")):
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                courses = data["courses"]
                self._catalog = {n: Course(**c) for n, c in courses.items()}
                if any("capacity" not in c for c in courses.values()):
                    self.ui_log(f"{cache} 为旧格式（无余量），开始运行时会自动刷新")
                else:
                    self.ui_log(f"已载入目录缓存 {cache}（{len(self._catalog)} 门）")
                break
            except (OSError, ValueError):
                continue
        if Path("courses.txt").exists():
            try:
                names = parse_wanted("courses.txt")
                self._queue = [self._catalog[n] for n in names if n in self._catalog]
                if self._queue:
                    self.ui_log(f"已载入课程清单 {len(self._queue)} 门")
                elif names:
                    self.ui_log("课程清单存在但目录未匹配（按 a 重新添加）")
            except OSError:
                pass
        sess = "✓" if Path("cookies.txt").exists() else "✗（按 l 登录）"
        self.set_status(f"会话 {sess} | 学期 … | 模式 立即 | 节拍 …")
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.clear()
        for i, c in enumerate(self._queue, 1):
            stext, sstyle = self._row_status.get(c.course_id, ("等待", "default"))
            table.add_row(str(i), c.name, c.type_name or c.type_code, c.seats_text(),
                          Text(stext, style=sstyle), key=c.course_id)

    def _persist_queue(self) -> None:
        try:
            write_queue("courses.txt", self._queue)
        except OSError:
            pass

    def _drain_events(self) -> None:
        while not self._events.empty():
            try:
                ev = self._events.get_nowait()
            except Exception:
                return
            kind = ev[0]
            if kind == "log":
                self.ui_log(ev[1])
            elif kind == "status":
                self.set_status(ev[1])
            elif kind == "attempt":
                _, attempt, idx = ev
                text = f"{attempt.status.value} {attempt.message[:32]}"
                self._row_status[attempt.course.course_id] = (text, style_for(attempt.status))
                table = self.query_one("#queue-table", DataTable)
                try:
                    table.update_cell(attempt.course.course_id, "status",
                                      Text(text, style=style_for(attempt.status)))
                except Exception:
                    self._refresh_table()
                ts = time.strftime("%H:%M:%S")
                self.ui_log_rich(f"[dim]{ts}[/dim] #{idx} {attempt.course.name} → "
                              f"[{style_for(attempt.status)}]{attempt.status.value}[/] "
                              f"{attempt.message[:60]}")
            elif kind == "refresh_table":
                self._refresh_table()
            elif kind == "semester":
                self.set_status(self._status_base())
            elif kind == "done":
                self._on_done(ev[1])
            elif kind == "error":
                self.ui_log(f"[bold red]✗ {ev[1]}[/bold red]")
                self._job_running = False
                self.set_status(self._status_base() + " | 空闲")

    def _tick(self) -> None:
        if self._job_running and self._engine is not None:
            try:
                ms = int(self._engine.pacer.interval * 1000)
                self.set_status(self._status_base() + f" | 节拍 {ms}ms")
            except Exception:
                pass

    def _status_base(self) -> str:
        sess = "✓" if Path("cookies.txt").exists() else "✗"
        sem = self._semester.label() if self._semester else "…"
        mode = self._mode()
        names = {"now": "立即", "at": "定时", "retry": "蹲退课", "rehearse": "演练"}
        return (f"会话 {sess} | 学期 {sem} | 模式 {names.get(mode, mode)}"
                f" | 节拍 {self._interval_ms()}ms")

    def _interval_ms(self) -> int:
        try:
            return max(int(self.query_one("#interval-input", Input).value.strip() or 1600), 1)
        except Exception:
            return 1600

    def _mode(self) -> str:
        try:
            active = self.query_one("#mode-tabs", Tabs).active or "mode-now"
            return active.replace("mode-", "")
        except Exception:
            return "now"

    def _ui(self) -> dict:
        def val(widget_id, default=""):
            try:
                return self.query_one(widget_id, Input).value.strip()
            except Exception:
                return default

        def checked(widget_id, default=True):
            try:
                return bool(self.query_one(widget_id, Checkbox).value)
            except Exception:
                return default

        tgt = "rwtjzyx"
        try:
            if self.query_one("#target-tabs", Tabs).active == "tgt-gwc":
                tgt = "rwtjzgwc"
        except Exception:
            pass
        return {
            "mode": self._mode(),
            "at": val("#at-input"),
            "interval": val("#interval-input", "1600"),
            "submit_target": tgt,
            "use_ntp": checked("#cb-ntp", True),
            "cascade": checked("#cb-cascade", True),
            "auto_skip": checked("#cb-autoskip", True),
            "toast": checked("#cb-toast", True),
        }

    def _build_settings(self, ui: dict, rehearse: bool = False):
        from .mockserver import mock_catalog, start_background

        if rehearse:
            start_background(8765)
            args = make_args(base_url="http://127.0.0.1:8765",
                             inline_cookies=["MOCKSESSION=ok"],
                             interval_ms=int(ui["interval"] or 10),
                             non_interactive=True)
            settings = apply_cli_overrides(load_settings(None, args), args)
            return settings, True
        try:
            interval = max(int(ui["interval"] or 1600), 1)
        except ValueError:
            raise SystemExit("请求间隔必须是数字")
        args = make_args(cookies_file="cookies.txt", courses_file="courses.txt",
                         interval_ms=interval,
                         retry_full=(ui["mode"] == "retry"),
                         cascade=bool(ui["cascade"]),
                         non_interactive=True,
                         submit_target=ui["submit_target"],
                         use_ntp=bool(ui["use_ntp"]),
                         at_time=ui["at"] if ui["mode"] == "at" else None,
                         webhook_url=None, toast=bool(ui["toast"]))
        settings = load_settings(None, args)
        settings.auto_skip_conflict = bool(ui["auto_skip"])
        settings = apply_cli_overrides(settings, args)
        return settings, False

    def _prepare_tis(self, settings, ev):
        cookies = resolve_cookies(settings)
        client = build_client(settings.base_url, cookies, settings.tls_verify,
                              settings.timeout_s, settings.endpoints,
                              trust_env=not settings.no_env_proxy)
        tis = TisClient(client, settings.endpoints, settings.keywords)
        try:
            semester = tis.query_semester()
        except TisApiError as e:
            raise SystemExit(f"{e}（按 l 重新登录）")
        self._tis, self._semester = tis, semester
        return tis

    def action_quit_app(self) -> None:
        self._request_stop()
        self.exit()

    def action_toggle_mode(self) -> None:
        self.theme = "tis-dark" if self.theme == "tis" else "tis"
        self.ui_log(f"已切换{'夜间' if self.theme == 'tis-dark' else '日间'}模式")

    def action_start_run(self) -> None:
        if self._job_running:
            self.ui_log("已在运行中")
            return
        if not self._queue:
            self.ui_log("[yellow]队列为空：按 a 添加课程[/yellow]")
            return
        if not Path("cookies.txt").exists():
            self.ui_log("[yellow]未登录：先自动打开浏览器登录，成功后自动继续[/yellow]")
            self._pending_start = True
            self.action_login()
            return
        self._spawn_worker()

    def action_rehearse(self) -> None:
        if self._job_running:
            return
        self._spawn_worker(force_rehearse=True)

    def _spawn_worker(self, force_rehearse: bool = False) -> None:
        self._job_running = True
        self._stop_event.clear()
        self._row_status = {}
        self._refresh_table()
        self._persist_queue()
        t = threading.Thread(target=self._worker, args=(force_rehearse,), daemon=True)
        t.start()

    def _worker(self, force_rehearse: bool = False) -> None:
        ev = self._events.put
        try:
            ui = self._ui_snapshot()
            settings, is_rehearse = self._build_settings(ui, rehearse=force_rehearse)
            tis = self._prepare_tis(settings, ev)
            ev(("log", f"[+] 当前学期: {self._semester.label()}"))
            if is_rehearse:
                from .mockserver import mock_catalog
                catalog = mock_catalog()
            else:
                catalog = load_catalog(tis, self._semester, settings,
                                       emit=lambda m: ev(("log", m)),
                                       confirm_refresh=False)
            self._catalog = catalog
            ev(("status", self._status_base()))
            names = [c.name for c in self._queue_snapshot()]
            queue = [catalog[n] for n in names if n in catalog]
            missing = [n for n in names if n not in catalog]
            for n in missing:
                ev(("log", f"[!] 目录中未找到: {n}"))
            if not queue:
                ev(("error", "没有可用的待选课程（用 a 重新添加）"))
                return
            ev(("log", "[+] 连接预热完成 "
                       f"HTTP {tis.warmup()}（TLS/HTTP2 已就绪）"))
            if settings.at_time:
                from .cli import parse_at
                target = parse_at(settings.at_time)
                offset = 0.0
                if settings.use_ntp:
                    try:
                        offset = sntp_offset(settings.ntp_server)
                        ev(("log", f"[+] NTP 校准完成，偏差 {offset * 1000:+.0f}ms"))
                    except (OSError, ValueError) as e:
                        ev(("log", f"[!] NTP 失败（{e}），使用本机时钟"))
                clock = Clock(offset)
                if target - clock.time() > 10:
                    ev(("log", "[+] 等待至开抢前 2 秒做二次预热…"))
                    while clock.time() < target - 2:
                        if self._stop_event.is_set():
                            ev(("log", "[!] 定时已取消"))
                            return
                        ev(("status", self._status_base() +
                            f" | 开抢倒计时 {target - clock.time():.0f}s"))
                        time.sleep(0.5)
                    ev(("log", f"[+] 二次预热 HTTP {tis.warmup()}"))
                while clock.time() < target:
                    if self._stop_event.is_set():
                        ev(("log", "[!] 定时已取消"))
                        return
                    ev(("status", self._status_base() +
                        f" | 开抢倒计时 {max(target - clock.time(), 0):.1f}s"))
                    time.sleep(0.1)
                while clock.time() < target:
                    pass
                ev(("log", "[+] 时间到，开始"))
            notifier = Notifier("", settings.toast, quiet=True)
            engine = EnrollEngine(tis, self._semester, Pacer(settings.interval_ms),
                                  settings, notifier, quiet=True)
            self._engine = engine
            engine.on_attempt = lambda a, i: ev(("attempt", a, i))
            summary = engine.run(deque(queue), settings.max_requests)
            ev(("done", summary))
        except SystemExit as e:
            ev(("error", str(e)))
        except Exception as e:
            ev(("error", f"{type(e).__name__}: {e}"))
        finally:
            self._engine = None

    def _ui_snapshot(self) -> dict:
        return self.call_from_thread(self._ui)

    def _queue_snapshot(self) -> list:
        return self.call_from_thread(lambda: list(self._queue))

    def action_stop_run(self) -> None:
        self._request_stop()

    def _request_stop(self) -> None:
        self._stop_event.set()
        if self._engine is not None:
            self._engine._commands.append("q")

    def _on_done(self, summary) -> None:
        self._job_running = False
        self.ui_log("=" * 40)
        self.ui_log(f"[i] 运行结束: {summary.line()}")
        if summary.successes:
            self.ui_log_rich("[bold green]成功:[/bold green]")
            for c in summary.successes:
                self.ui_log(f"    {c.display()}")
        if summary.remaining:
            self.ui_log_rich("[yellow]未完成:[/yellow]")
            for c in summary.remaining:
                self.ui_log(f"    {c.display()}")
        self.set_status(self._status_base() + " | 空闲")

    def action_add_course(self) -> None:
        self.push_screen(CourseSearchScreen(lambda: self._catalog),
                         callback=self._course_chosen)

    def _course_chosen(self, course: Course | None) -> None:
        if course is None:
            return
        if any(c.course_id == course.course_id for c in self._queue):
            self.ui_log(f"已在队列: {course.name}")
            return
        self._queue.append(course)
        self._refresh_table()
        self._persist_queue()
        self.ui_log(f"+ {course.name} {course.seats_text()}")

    def _cursor_index(self) -> int:
        try:
            return self.query_one("#queue-table", DataTable).cursor_coordinate.row
        except Exception:
            return -1

    def action_remove_course(self) -> None:
        idx = self._cursor_index()
        if 0 <= idx < len(self._queue):
            removed = self._queue.pop(idx)
            self.ui_log(f"已移除 {removed.name}")
            self._refresh_table()
            self._persist_queue()

    def action_move_up(self) -> None:
        self._move_cursor(-1)

    def action_move_down(self) -> None:
        self._move_cursor(1)

    def _move_cursor(self, delta: int) -> None:
        table = self.query_one("#queue-table", DataTable)
        idx = self._cursor_index()
        if idx < 0:
            return
        new_idx = move_item(self._queue, idx, delta)
        self._refresh_table()
        self._persist_queue()
        try:
            table.move_cursor(row=new_idx, animate=False)
        except Exception:
            pass

    def action_refresh_seats(self) -> None:
        if self._job_running or not self._queue:
            return
        if self._tis is None or self._semester is None:
            self.ui_log("[yellow]尚未建立会话：按 s 开始一次（会自动加载）[/yellow]")
            return
        self.ui_log("刷新余量中…")
        t = threading.Thread(target=self._seats_worker, daemon=True)
        t.start()

    def _seats_worker(self) -> None:
        ev = self._events.put
        try:
            snapshot = self._queue_snapshot()
            rows = self._tis.refresh_seats(list(snapshot), self._semester,
                                           Pacer(5000))
            by_id = {c.course_id: c for c in rows}

            def _apply():
                for i, c in enumerate(self._queue):
                    if c.course_id in by_id:
                        self._queue[i] = by_id[c.course_id]
                self._refresh_table()

            self.call_from_thread(_apply)
            ev(("log", "[+] 余量已刷新"))
        except Exception as e:
            ev(("error", f"刷新失败 {type(e).__name__}: {e}"))

    def action_login(self) -> None:
        if self._job_running:
            return
        self.ui_log("正在打开浏览器，请完成统一身份认证登录…")
        t = threading.Thread(target=self._login_worker, daemon=True)
        t.start()

    def _login_worker(self) -> None:
        ev = self._events.put
        try:
            with contextlib.redirect_stdout(_EventWriter(ev)):
                pairs = run_login("cookies.txt")
            if pairs:
                ev(("log", f"[+] 登录成功: {', '.join(pairs.keys())}"))
                self._tis, self._semester = None, None
                if self._pending_start:
                    self._pending_start = False
                    ev(("log", "[*] 自动继续开始流程…"))
                    self.call_from_thread(self.action_start_run)
            else:
                ev(("log", "[x] 登录未完成"))
                self._pending_start = False
        except Exception as e:
            ev(("error", f"登录失败 {type(e).__name__}: {e}"))
            self._pending_start = False

    @on(Button.Pressed, "#start-btn")
    def _btn_start(self, event: Button.Pressed) -> None:
        self.action_start_run()

    @on(Button.Pressed, "#stop-btn")
    def _btn_stop(self, event: Button.Pressed) -> None:
        self.action_stop_run()

    @on(Button.Pressed, "#add-btn")
    def _btn_add(self, event: Button.Pressed) -> None:
        self.action_add_course()

    @on(Button.Pressed, "#del-btn")
    def _btn_del(self, event: Button.Pressed) -> None:
        self.action_remove_course()

    @on(Button.Pressed, "#up-btn")
    def _btn_up(self, event: Button.Pressed) -> None:
        self.action_move_up()

    @on(Button.Pressed, "#down-btn")
    def _btn_down(self, event: Button.Pressed) -> None:
        self.action_move_down()

    @on(Button.Pressed, "#seats-btn")
    def _btn_seats(self, event: Button.Pressed) -> None:
        self.action_refresh_seats()

    @on(Button.Pressed, "#login-btn")
    def _btn_login(self, event: Button.Pressed) -> None:
        self.action_login()


def main() -> None:
    EnrollApp().run()
