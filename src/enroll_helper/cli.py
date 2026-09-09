from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from . import constants as C
from .cas import cas_login, prompt_credentials
from .clocksync import Clock, imminent_start, sntp_offset, wait_until
from .config import Settings, clamp_interval_ms, load_settings
from .engine import EnrollEngine, merge_summaries
from .login import run_login
from .notify import Notifier, save_report
from .pacer import Pacer
from .picker import run_picker
from .session import TIS_DOMAIN_MARKERS, build_client, load_cookies_file, parse_cookie_pairs_from_header
from .tis.client import TisApiError, TisClient
from .tis.models import Course


def _console_setup() -> None:
    if os.name == "nt":
        os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="enroll-helper",
        description=f"SUSTech TIS 选课辅助工具 v{__version__}（串行限速版）",
        epilog="直接运行 enroll-helper（不带参数）= 一键向导：登录 → 选课 → 模式选择",
    )
    p.add_argument("--login", action="store_true", help="拉起浏览器自动登录并保存会话（一键登录）")
    p.add_argument("--pick", action="store_true", help="交互式选课器（搜索/余量/优先级队列），写入课程清单后退出")
    p.add_argument("--use-env-proxy", action="store_true", help="强制使用系统代理（sustech 域名默认已自动直连）")
    p.add_argument("--config", default="config.toml", help="TOML/JSON 配置文件路径")
    p.add_argument("--courses", dest="courses_file", help="课程优先级列表文件（每行一个课程任务名）")
    p.add_argument("--cookies", dest="cookies_file", help="Cookie 文件（Netscape cookies.txt / HAR / 原始 Cookie 头）")
    p.add_argument("--cookie", dest="inline_cookies", action="append", default=[], metavar="K=V", help="直接注入单个 Cookie，可重复")
    p.add_argument("--cas-login", action="store_true", help="实验性：用 CAS 账号密码登录（不落盘）")
    p.add_argument("--base-url", help="覆盖 TIS 地址")
    p.add_argument("--interval-ms", type=int, help="抢课请求间隔（非本机目标强制 ≥1500ms）")
    p.add_argument("--discovery-interval-ms", type=int, help="课程目录下载间隔")
    p.add_argument("--at", dest="at_time", help="定时开抢 HH:MM[:SS]（配合 --use-ntp 校准）")
    p.add_argument("--use-ntp", action="store_true", help="用 SNTP 校准时钟")
    p.add_argument("--ntp-server")
    p.add_argument("--retry-full", action="store_true", help="人数已满时持续重试（等待退课）")
    p.add_argument("--cascade", action="store_true", help="配合 --retry-full：满员课程转到队尾轮询，不阻塞后备课程")
    p.add_argument("--max-requests", type=int, default=0, help="最大请求次数（0=不限）")
    p.add_argument("--no-auto-skip", action="store_true", help="冲突时不自动跳过，改为交互确认")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--submit-target", choices=["rwtjzyx", "rwtjzgwc"], help="提交目标：已选/购物车")
    p.add_argument("--list", dest="list_only", nargs="?", const="", metavar="KEYWORD", help="只查询课程目录（可带过滤关键字）")
    p.add_argument("--refresh-cache", action="store_true")
    p.add_argument("--webhook", dest="webhook_url", help="成功时 POST 通知的 webhook")
    p.add_argument("--no-toast", action="store_true")
    p.add_argument("--tls-no-verify", action="store_true", help="禁用 TLS 校验（学期初证书异常时的兜底）")
    p.add_argument("--timeout", type=float, dest="timeout_s", help="请求超时秒数（默认 20）")
    p.add_argument("--no-env-proxy", action="store_true", help="忽略系统代理直连 TIS（国内站点推荐）")
    p.add_argument("--report", help="运行报告 JSON 输出路径")
    p.add_argument("--rehearse", action="store_true", help="使用内置 Mock 服务器演练全流程")
    p.add_argument("--doctor", action="store_true", help="一键诊断：会话/目录/余量字段/连通性")
    return p


def resolve_cookies(settings: Settings) -> dict[str, str]:
    pairs: dict[str, str] = {}
    if settings.inline_cookies:
        for kv in settings.inline_cookies:
            pairs.update(parse_cookie_pairs_from_header(kv))
    if not pairs and settings.cookies_file:
        domains = () if settings.is_local_target else TIS_DOMAIN_MARKERS
        pairs = load_cookies_file(settings.cookies_file, domains)
    if not pairs and settings.cas_login:
        username, password = prompt_credentials()
        pairs = cas_login(username, password, tls_verify=settings.tls_verify)
    if not pairs:
        raise SystemExit(
            "[x] 未提供任何会话凭证。三种方式任选：\n"
            "    1) 浏览器登录 TIS 后导出 Cookie（cookies.txt / HAR / 复制原始 Cookie 头），用 --cookies 传入\n"
            "    2) 用 --cookie MOCKSESSION=ok 之类直接注入\n"
            "    3) --cas-login 实验性账号登录（不落盘）"
        )
    return pairs


def load_catalog(tis: TisClient, semester, settings: Settings,
                 emit=print, confirm_refresh: bool = True,
                 use_cache: bool = True) -> dict[str, Course]:
    cache = Path(f"catalog_{semester.p_xnxq}.json")
    if use_cache and cache.exists() and not settings.refresh_cache:
        age_h = (time.time() - cache.stat().st_mtime) / 3600
        if (confirm_refresh and age_h > 12 and sys.stdin.isatty()
                and not settings.non_interactive):
            try:
                ans = input(f"[?] 目录缓存已 {age_h:.0f} 小时，刷新余量/课程? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans == "y":
                settings.refresh_cache = True
        if not settings.refresh_cache:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("p_xnxq") == semester.p_xnxq:
                if any("capacity" not in c or "extra" not in c
                       for c in data["courses"].values()):
                    emit("[!] 目录缓存为旧格式（无余量/详情字段），重新下载…")
                else:
                    emit(f"[+] 使用课程目录缓存 {cache}"
                         f"（{cache_age_text(data.get('fetched_at'))}）")
                    return {n: Course(**c) for n, c in data["courses"].items()}
    emit("[*] 从服务器下载课程目录（6 类，逐类限速）...")
    catalog = tis.query_courses(semester, Pacer(settings.discovery_interval_ms),
                                progress=lambda msg: emit(f"    {msg}"))
    if use_cache:
        dump_catalog(catalog, semester)
        emit("[+] 课程目录已缓存")
    return catalog


def dump_catalog(catalog: dict[str, Course], semester) -> None:
    cache = Path(f"catalog_{semester.p_xnxq}.json")
    data = {"p_xnxq": semester.p_xnxq,
            "fetched_at": time.time(),
            "courses": {n: {"course_id": c.course_id, "name": c.name, "type_code": c.type_code,
                            "type_name": c.type_name, "capacity": c.capacity,
                            "enrolled": c.enrolled, "extra": c.extra}
                        for n, c in catalog.items()}}
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def cache_age_text(ts: float | None) -> str:
    if not ts:
        return "未知时间"
    mins = max(int((time.time() - ts) // 60), 0)
    if mins < 60:
        return f"{mins}分钟前"
    return f"{mins // 60}小时{mins % 60:02d}分钟前"


def parse_wanted(path: str) -> list[str]:
    wanted = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            wanted.append(s)
    return wanted


def resolve_queue(wanted: list[str], catalog: dict[str, Course]) -> tuple[deque, list[str]]:
    queue: deque = deque()
    missing = []
    for name in wanted:
        c = catalog.get(name)
        if c is None:
            missing.append(name)
        else:
            queue.append(c)
    return queue, missing


def run_doctor(tis: TisClient, semester, settings: Settings) -> dict:
    report: dict = {"ok": True}
    print(f"[√] 会话有效，学期: {semester.label()} ({semester.p_xnxq})")
    cache = Path(f"catalog_{semester.p_xnxq}.json")
    if not cache.exists():
        print("[!] 本地无目录缓存（首次运行会自动下载）")
        report["cache"] = "missing"
    else:
        data = json.loads(cache.read_text(encoding="utf-8"))
        courses = data.get("courses", {})
        stale = any("capacity" not in c for c in courses.values())
        print(f"[{'!' if stale else '√'}] 目录缓存 {len(courses)} 门"
              + ("（旧格式，下次运行自动刷新）" if stale else ""))
        report["cache"] = {"count": len(courses), "stale": stale}
    try:
        items = tis.fetch_category("xxxk", semester)
        ok = bool(items) and any(it.get("bksrl") is not None for it in items[:5])
        print(f"[{'√' if ok else '!'}] 余量字段抽查: {len(items)} 门"
              + ("，含 bksrl/bksyxrs" if ok else "（无余量字段或查询被限频）"))
        report["seats"] = ok
        if not ok:
            report["ok"] = False
    except Exception as e:
        print(f"[x] 抽查失败: {type(e).__name__}: {e}")
        report["seats"] = False
        report["ok"] = False
    print("[i] 若怀疑 TUN/代理干扰：关闭 TUN 或将 tis.sustech.edu.cn 加入直连规则后重试")
    return report


def parse_at(s: str) -> float:
    s = s.strip()
    try:
        target = datetime.fromisoformat(s)
        if target <= datetime.now() + timedelta(seconds=2):
            raise SystemExit(f"[x] 定时时间 {s} 已过或过近")
        return target.timestamp()
    except ValueError:
        pass
    parts = [int(x) for x in re.findall(r"\d+", s)]
    while len(parts) < 3:
        parts.append(0)
    h, m, sec = parts[:3]
    now = datetime.now()
    target = now.replace(hour=h, minute=m, second=sec, microsecond=0)
    if target <= now + timedelta(seconds=2):
        raise SystemExit(f"[x] 定时时间 {s} 已过或过近，请指定今天稍晚的时间")
    return target.timestamp()


def print_queue(queue: deque) -> None:
    print("=" * 60)
    for i, c in enumerate(queue, 1):
        print(f"  {i}. {c.display()} {c.seats_text()}")
    print("=" * 60)


def build_run_argv(mode: str, at: str) -> list[str]:
    argv = ["--cookies", "cookies.txt", "--courses", "courses.txt", "--report", "report.json"]
    if mode == "2" and at:
        argv += ["--at", at, "--use-ntp"]
    elif mode == "3":
        argv += ["--retry-full"]
    elif mode == "4":
        argv += ["--rehearse"]
    return argv


def wizard() -> None:
    print(f"[*] SUSTech enroll-helper v{__version__} 一键向导")
    if Path("cookies.txt").exists():
        print("[向导 1/3] 发现 cookies.txt（若已过期可运行: enroll-helper --login 重新登录）")
    else:
        print("[向导 1/3] 未发现登录会话，拉起浏览器自动登录…")
        if not run_login():
            raise SystemExit("登录未完成；也可手动导出 Cookie 存为 cookies.txt（首行 Cookie: ...）")
    if Path("courses.txt").exists() and parse_wanted("courses.txt"):
        print("[向导 2/3] 课程清单:", "、".join(parse_wanted("courses.txt")))
    else:
        print("[向导 2/3] 没有课程清单，进入交互选课器…")
        main(["--cookies", "cookies.txt", "--pick"])
        if not (Path("courses.txt").exists() and parse_wanted("courses.txt")):
            raise SystemExit("未选择课程，退出")
    print("[向导 3/3] 选择运行模式:")
    print("  [1] 立即开抢   [2] 定时开抢   [3] 蹲退课   [4] 演练(Mock)")
    try:
        mode = input("模式 [1]: ").strip() or "1"
        at = ""
        if mode == "2":
            at = input("开抢时间 HH:MM[:SS]: ").strip()
            if not at:
                mode = "1"
    except KeyboardInterrupt:
        print("\n[!] 已取消（不会开始任何选课）")
        return
    except EOFError:
        print("\n[!] 输入已关闭，退出向导")
        return
    main(build_run_argv(mode, at))


def make_args(**kw):
    import types
    base = dict(config=None, courses_file="courses.txt", cookies_file="cookies.txt",
                inline_cookies=[], cas_login=False, base_url=None, interval_ms=1600,
                discovery_interval_ms=None, at_time=None, use_ntp=False, ntp_server=None,
                retry_full=False, cascade=False, max_requests=0, no_auto_skip=False,
                non_interactive=True, submit_target=None, list_only=None,
                refresh_cache=False, webhook_url=None, no_toast=False, tls_no_verify=False,
                timeout_s=None, no_env_proxy=False, use_env_proxy=False, report=None,
                rehearse=False, login=False, pick=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def apply_cli_overrides(s: Settings, args) -> Settings:
    if args.retry_full:
        s.retry_full = True
    if args.cascade:
        s.cascade_on_full = True
    if args.max_requests:
        s.max_requests = args.max_requests
    if args.no_auto_skip:
        s.auto_skip_conflict = False
    if args.tls_no_verify:
        s.tls_verify = False
        print("[!] TLS 校验已禁用（仅建议学期初证书异常时使用）")
    if args.no_toast:
        s.toast = False
    if args.use_ntp:
        s.use_ntp = True
    if args.ntp_server:
        s.ntp_server = args.ntp_server
    if args.discovery_interval_ms:
        s.discovery_interval_ms = args.discovery_interval_ms
    if args.submit_target:
        s.submit_target = args.submit_target
    if getattr(args, "timeout_s", None):
        s.timeout_s = float(args.timeout_s)
    if getattr(args, "no_env_proxy", False):
        s.no_env_proxy = True
    host = (urlparse(s.base_url).hostname or "").lower()
    if not getattr(args, "use_env_proxy", False) and host.endswith("sustech.edu.cn"):
        if not s.no_env_proxy:
            print("[i] sustech 域名默认直连（忽略系统代理，--use-env-proxy 可关闭）")
        s.no_env_proxy = True
    s.interval_ms = clamp_interval_ms(s.interval_ms, s.is_local_target)
    return s


def main(argv=None) -> None:
    _console_setup()
    if argv is None and len(sys.argv) <= 1:
        wizard()
        return
    args = build_parser().parse_args(argv)

    if args.login:
        run_login()
        return

    if args.rehearse:
        from .mockserver import mock_catalog, start_background
        args.base_url = args.base_url or "http://127.0.0.1:8765"
        start_background(int(args.base_url.rsplit(":", 1)[1]))
        if not args.inline_cookies:
            args.inline_cookies = ["MOCKSESSION=ok"]

    settings = load_settings(args.config if Path(args.config).exists() else None, args)
    settings = apply_cli_overrides(settings, args)

    print(f"[*] 抢课猫 CourseCat v{__version__}")
    print(f"    目标: {settings.base_url} | 间隔: {settings.interval_ms}ms | 模式: 严格优先级/串行")
    print("    合规: 遵守服务端限频，不做流量伪装，仅单账号本工具")

    try:
        cookies = resolve_cookies(settings)
    except SystemExit as e:
        print(str(e))
        raise
    print(f"[+] 会话 Cookie: {', '.join(cookies.keys())}")

    client = build_client(settings.base_url, cookies, settings.tls_verify,
                          settings.timeout_s, settings.endpoints,
                          trust_env=not settings.no_env_proxy)
    tis = TisClient(client, settings.endpoints, settings.keywords)

    semester = None
    for attempt in range(2):
        try:
            semester = tis.query_semester()
            break
        except TisApiError as e:
            cookie_path = settings.cookies_file or "cookies.txt"
            retryable = (attempt == 0 and not args.rehearse
                         and not settings.non_interactive and sys.stdin.isatty()
                         and Path(cookie_path).exists())
            if retryable:
                try:
                    ans = input("[!] 会话疑似失效，拉起浏览器重新登录? [Y/n]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    ans = "n"
                if ans != "n" and run_login(cookie_path):
                    domains = () if settings.is_local_target else TIS_DOMAIN_MARKERS
                    cookies = load_cookies_file(cookie_path, domains)
                    client = build_client(settings.base_url, cookies, settings.tls_verify,
                                          settings.timeout_s, settings.endpoints,
                                          trust_env=not settings.no_env_proxy)
                    tis = TisClient(client, settings.endpoints, settings.keywords)
                    continue
            raise SystemExit(f"[x] {e}\n    可运行 enroll-helper --login 重新登录；"
                             f"若接口变更请更新 config 的 [endpoints] 段")
        except Exception as e:
            raise SystemExit(f"[x] 无法连接 TIS: {e}")
    if semester is None:
        raise SystemExit("[x] 学期查询失败")
    print(f"[+] 当前学期: {semester.label()} ({semester.p_xnxq})")

    if args.doctor:
        verdict = run_doctor(tis, semester, settings)
        raise SystemExit(0 if verdict["ok"] else 1)

    if args.rehearse:
        from .mockserver import mock_catalog
        catalog = mock_catalog()
    else:
        catalog = load_catalog(tis, semester, settings)
    print(f"[+] 课程目录: {len(catalog)} 门")

    if args.list_only is not None:
        kw = (args.list_only or "").strip()
        hits = [c for n, c in catalog.items() if kw in n]
        for c in sorted(hits, key=lambda x: x.name):
            print(f"  {c.display()} {c.seats_text()}")
        print(f"[i] 共 {len(hits)} 条匹配")
        return

    if args.pick:
        refresher = lambda rows: tis.refresh_seats(  # noqa: E731
            rows, semester, Pacer(settings.discovery_interval_ms))
        run_picker(catalog, settings.courses_file, refresher=refresher)
        return

    wanted = parse_wanted(settings.courses_file)
    if not wanted:
        raise SystemExit(f"[x] 课程列表为空，请编辑 {settings.courses_file}（每行一个课程任务名，按优先级排序）")
    queue, missing = resolve_queue(wanted, catalog)
    for name in missing:
        print(f"[!] 未在目录中找到: {name}")
    if not queue:
        raise SystemExit("[x] 没有可用的待选课程，请核对课程名称（用 --list 查询精确名称）")

    print(f"[+] 待选队列（严格按优先级）:")
    print_queue(queue)
    print("[i] 余量取自目录缓存（--pick 里输入 r 可刷新）")

    if imminent_start(settings.at_time):
        print("[i] 临近开抢时刻，跳过余量刷新（以实时请求为准）")
    else:
        print("[*] 刷新队列余量…")
        queue = deque(tis.refresh_seats(list(queue), semester,
                                        Pacer(settings.discovery_interval_ms)))
        print_queue(queue)

    warm = tis.warmup()
    print(f"[+] 连接预热完成 HTTP {warm}（TLS/HTTP2 已就绪）")

    clock = Clock(0.0)
    if settings.use_ntp:
        try:
            offset = sntp_offset(settings.ntp_server)
            clock = Clock(offset)
            print(f"[+] NTP 校准完成，本机时钟偏差 {offset * 1000:+.0f}ms")
        except (OSError, ValueError) as e:
            print(f"[!] NTP 校准失败（{e}），使用本机时钟")

    if settings.at_time:
        target = parse_at(settings.at_time)
        try:
            from .tui import countdown as tui_countdown
            if target - clock.time() > 10:
                wait_until(clock, target - 2)
                print(f"[+] 二次预热 HTTP {tis.warmup()}")
            tui_countdown(clock, target)
        except KeyboardInterrupt:
            raise SystemExit("\n[!] 定时已取消，未发出任何请求")
        print("[+] 时间到，开始")

    notifier = Notifier(settings.webhook_url, settings.toast)
    cookie_path = settings.cookies_file or "cookies.txt"
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
    from .tui import print_note as _log_note, set_log_file as _set_log
    _set_log(open(log_path, "w", encoding="utf-8"))
    _log_note(f"本次运行日志: {log_path}")

    queue = deque(queue)
    summaries: list = []
    relogins = 0
    while True:
        engine = EnrollEngine(tis, semester, Pacer(settings.interval_ms), settings, notifier)
        try:
            summary = engine.run(queue, settings.max_requests)
        except KeyboardInterrupt:
            raise SystemExit("\n[x] 强制退出")
        summaries.append(summary)
        if not (summary.aborted and summary.remaining and not args.rehearse
                and relogins < 3 and sys.stdin.isatty() and not settings.non_interactive):
            break
        try:
            ans = input(f"[!] 会话已失效，剩余 {len(summary.remaining)} 门未完成。"
                        f"拉起浏览器重新登录并继续? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if ans == "n" or not run_login(cookie_path):
            break
        relogins += 1
        domains = () if settings.is_local_target else TIS_DOMAIN_MARKERS
        cookies = load_cookies_file(cookie_path, domains)
        client = build_client(settings.base_url, cookies, settings.tls_verify,
                              settings.timeout_s, settings.endpoints,
                              trust_env=not settings.no_env_proxy)
        tis = TisClient(client, settings.endpoints, settings.keywords)
        queue = deque(summary.remaining)
    summary = merge_summaries(summaries)

    print("=" * 60)
    from .tui import summary_table
    table = summary_table(summary)
    if table is not None:
        from .tui import console
        console.print(table)
    else:
        print("[i] 运行结束:", summary.line())
    if summary.successes:
        print("[+] 成功:")
        for c in summary.successes:
            print(f"    {c.display()}")
    if summary.skipped:
        print("[-] 跳过:")
        for c, r in summary.skipped:
            print(f"    {c.display()} ({r})")
    if summary.remaining:
        print("[!] 未完成（会话失效或手动停止）:")
        for c in summary.remaining:
            print(f"    {c.display()}")
    if args.report:
        save_report(args.report, summary)
        print(f"[+] 报告已写入 {args.report}")
    raise SystemExit(0 if not summary.remaining and not summary.aborted else 1)


if __name__ == "__main__":
    main()
