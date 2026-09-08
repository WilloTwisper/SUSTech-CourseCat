from __future__ import annotations

import time

from .tis.models import Status

try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    console = Console(highlight=False)
    HAS_RICH = True
except Exception:
    console = None
    HAS_RICH = False

try:
    import prompt_toolkit  # noqa: F401
    HAS_PTK = True
except Exception:
    HAS_PTK = False

_STYLE = {
    Status.SUCCESS: "bold green",
    Status.ALREADY_ENROLLED: "green",
    Status.CONFLICT: "red",
    Status.FULL: "dark_orange",
    Status.NOT_OPEN: "dark_cyan",
    Status.RATE_LIMITED: "blue",
    Status.SESSION_EXPIRED: "bold red",
    Status.FAILED: "default",
    Status.ERROR: "red",
}


_LOG = None


def set_log_file(fh) -> None:
    global _LOG
    _LOG = fh
    import atexit
    atexit.register(_close_log)


def _close_log() -> None:
    global _LOG
    if _LOG:
        try:
            _LOG.close()
        except Exception:
            pass
        _LOG = None


def _log(line: str) -> None:
    if _LOG:
        try:
            _LOG.write(line + "\n")
            _LOG.flush()
        except Exception:
            pass


def style_for(status: Status) -> str:
    return _STYLE.get(status, "default")


def print_attempt(attempt, index: int) -> None:
    ts = time.strftime("%H:%M:%S")
    msg = attempt.message.replace("\n", " ")[:80]
    _log(f"[{ts}] #{index} {attempt.course.name} -> {attempt.status.value} {msg}")
    if HAS_RICH:
        console.print(f"[dim]{ts}[/dim] #{index} {attempt.course.name} → "
                      f"[{style_for(attempt.status)}]{attempt.status.value}[/] {msg}")
    else:
        print(f"[{ts}] #{index} {attempt.course.name} -> {attempt.status.value} {msg}")


def print_note(msg: str) -> None:
    _log(f"[i] {msg}")
    if HAS_RICH:
        console.print(f"[cyan]i[/cyan] {msg}")
    else:
        print(f"[i] {msg}")


def bell() -> None:
    try:
        import sys
        sys.stdout.write("\a")
        sys.stdout.flush()
    except OSError:
        pass


def success_panel(text: str, border: str = "bold green") -> None:
    bell()
    _log(text)
    if HAS_RICH:
        console.print(Panel(text, border_style=border, padding=(0, 2)))
    else:
        bar = "=" * max(len(text), 24)
        print(bar)
        print(text)
        print(bar)


def summary_table(summary):
    if not HAS_RICH:
        return None
    t = Table(title="运行汇总")
    t.add_column("指标")
    t.add_column("值")
    t.add_row("请求总数", str(summary.total_requests))
    for st, n in summary.status_counts.most_common():
        t.add_row(st.value, str(n))
    if summary.latencies_ms:
        t.add_row("平均延迟", f"{sum(summary.latencies_ms) / len(summary.latencies_ms):.0f}ms")
    return t


def countdown(clock, target_epoch: float, label: str = "距离开抢") -> None:
    from .clocksync import wait_until

    if not HAS_RICH:
        wait_until(clock, target_epoch)
        return
    with Live(console=console, refresh_per_second=5) as live:
        while True:
            rem = target_epoch - clock.time()
            if rem <= 3:
                break
            mm, ss = int(rem // 60), int(rem % 60)
            live.update(Panel(f"[bold]{label} {mm:02d}:{ss:02d}[/bold]", border_style="cyan"))
            time.sleep(min(rem - 3, 0.2))
    wait_until(clock, target_epoch)
