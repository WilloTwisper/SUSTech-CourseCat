from __future__ import annotations

import threading
import time
from collections import Counter, deque

from .tis.client import TisClient
from .tis.models import Attempt, Course, Status
from .tui import print_attempt, print_note


class RunSummary:
    def __init__(self):
        self.total_requests = 0
        self.status_counts: Counter = Counter()
        self.successes: list[Course] = []
        self.skipped: list[tuple[Course, str]] = []
        self.remaining: list[Course] = []
        self.aborted = False
        self.request_times: list[float] = []
        self.latencies_ms: list[float] = []
        self.attempts: list[Attempt] = []
        self.watchlist: list[Course] = []
        self.started_at = time.time()

    def line(self) -> str:
        parts = [f"请求总数={self.total_requests}"]
        for st, n in self.status_counts.most_common():
            parts.append(f"{st.value}={n}")
        if self.latencies_ms:
            avg = sum(self.latencies_ms) / len(self.latencies_ms)
            parts.append(f"平均延迟={avg:.0f}ms")
        return " ".join(parts)


def merge_summaries(summaries: list) -> RunSummary:
    merged = RunSummary()
    for s in summaries:
        merged.total_requests += s.total_requests
        merged.status_counts.update(s.status_counts)
        merged.successes += s.successes
        merged.skipped += s.skipped
        merged.request_times += s.request_times
        merged.latencies_ms += s.latencies_ms
        merged.attempts += s.attempts
        for c in s.watchlist:
            if c not in merged.watchlist:
                merged.watchlist.append(c)
    if summaries:
        merged.remaining = summaries[-1].remaining
        merged.aborted = summaries[-1].aborted
    return merged


class EnrollEngine:
    """Strict-priority serial enrollment loop.

    One request in flight at any time; pacing enforced by Pacer; interactive
    skip/quit commands are read from stdin when attached to a TTY."""

    def __init__(self, tis: TisClient, semester, pacer, settings, notifier=None, quiet: bool = False):
        self.tis = tis
        self.semester = semester
        self.pacer = pacer
        self.settings = settings
        self.notifier = notifier
        self.quiet = quiet
        self.summary = RunSummary()
        self._commands: deque[str] = deque()
        self._stdin_thread: threading.Thread | None = None
        self._stopping = False
        self.on_attempt = None
        self._full_streak: dict[str, int] = {}

    def run(self, queue: deque[Course], max_requests: int = 0) -> RunSummary:
        self._maybe_start_stdin()
        try:
            while queue and not self._stopping and (
                    max_requests <= 0 or self.summary.total_requests < max_requests):
                self._drain_commands(queue)
                if self.summary.aborted:
                    break
                course = queue[0]
                self.pacer.wait()
                start = time.perf_counter()
                attempt = self.tis.enroll(course, self.semester, self.settings.submit_target)
                attempt.request_start = start
                self._record(attempt)
                self._handle(queue, attempt)
                self._maybe_drop_enrolled(queue)
        except KeyboardInterrupt:
            if self._stopping:
                raise
            self._stopping = True
            print_note("已请求停止（再按一次 Ctrl+C 强制退出）")
        finally:
            self.summary.remaining = list(queue)
        return self.summary

    def _record(self, attempt: Attempt) -> None:
        s = self.summary
        s.total_requests += 1
        s.status_counts[attempt.status] += 1
        s.latencies_ms.append(attempt.latency_ms)
        s.request_times.append(attempt.request_start or time.perf_counter())
        s.attempts.append(attempt)
        if attempt.status is not Status.FULL:
            self._full_streak.pop(attempt.course.course_id, None)
        if not self.quiet:
            print_attempt(attempt, s.total_requests)
        cb = getattr(self, "on_attempt", None)
        if callable(cb):
            try:
                cb(attempt, s.total_requests)
            except Exception:
                pass

    def _handle(self, queue: deque[Course], attempt: Attempt) -> None:
        st = attempt.status
        if st is Status.SUCCESS:
            queue.popleft()
            self.summary.successes.append(attempt.course)
            self.pacer.recover()
            if self.notifier:
                self.notifier.success(attempt.course)
            return
        if st is Status.ALREADY_ENROLLED:
            queue.popleft()
            self.summary.skipped.append((attempt.course, "已在课表中"))
            if self.notifier:
                self.notifier.success(attempt.course, already=True)
            return
        if st is Status.CONFLICT:
            if self.settings.auto_skip_conflict:
                queue.popleft()
                self.summary.skipped.append((attempt.course, "时间冲突"))
            elif not self.settings.non_interactive:
                self._pause_for_decision(queue, attempt, "时间冲突")
            elif len(queue) > 1:
                queue.append(queue.popleft())
            return
        if st is Status.FULL:
            cap, enr = attempt.course.capacity, attempt.course.enrolled
            if cap is not None and enr is not None and cap - enr > 0:
                print_note(f"{attempt.course.name} 快照余{cap - enr}，"
                           f"但服务端判定已满（可能刚被抢完），以服务端为准")
                quota = {k: v for k, v in (attempt.course.extra or {}).items()
                         if k in ("cq_sybksrl", "cq_sydwrl", "rl1", "rl2",
                                  "rl1xkrs", "rl2xkrs", "zrl", "rwrs",
                                  "ybksrl", "dnrl", "dnyxrlrs") and v is not None}
                if quota:
                    print_note("服务端配额快照：" +
                               " ".join(f"{k}={v}" for k, v in quota.items()))
            streak = self._full_streak.get(attempt.course.course_id, 0) + 1
            self._full_streak[attempt.course.course_id] = streak
            if streak == 5:
                print_note(f"{attempt.course.name} 已连续满员5次：显示余量可能滞后"
                           f"或受子配额限制；若本地是定时释放规则，建议等下一释放点再试")
                if cap is not None and enr is not None and cap - enr > 0 \
                        and attempt.course not in self.summary.watchlist:
                    self.summary.watchlist.append(attempt.course)
                    print_note(f"{attempt.course.name} 已加入待释放观察名单"
                               f"（快照余{cap - enr}，开闸时优先）")
            if not self.settings.retry_full:
                queue.popleft()
                self.summary.skipped.append((attempt.course, "人数已满"))
            elif getattr(self.settings, "cascade_on_full", False) and len(queue) > 1:
                queue.append(queue.popleft())
            return
        if st is Status.RATE_LIMITED:
            self.pacer.penalize()
            return
        if st is Status.SESSION_EXPIRED:
            self.summary.aborted = True
            if self.notifier:
                self.notifier.aborted("登录会话已失效，请刷新 Cookie 后重试")
            return

    def _maybe_drop_enrolled(self, queue: deque[Course]) -> None:
        every = getattr(self.settings, "enrolled_check_every", 0) or 0
        if every <= 0 or not queue:
            return
        if self.summary.total_requests % every != 0:
            return
        try:
            items = self.tis.query_enrolled(self.semester)
        except Exception:
            return
        ids = {str(it.get("id") or "") for it in items}
        names = {str(it.get("rwmc") or it.get("kcmc") or "") for it in items}
        for course in [c for c in queue]:
            if (course.course_id and course.course_id in ids) or course.name in names:
                queue.remove(course)
                self.summary.skipped.append((course, "已在课表中（自动检测）"))
                print_note(f"{course.name} 已在课表中，自动跳过")
                if self.notifier:
                    self.notifier.success(course, already=True)

    def _pause_for_decision(self, queue: deque[Course], attempt: Attempt, reason: str) -> None:
        if self.settings.non_interactive:
            queue.popleft()
            self.summary.skipped.append((attempt.course, reason))
            return
        try:
            ans = input(f"  {attempt.course.name} {reason}：回车跳过 / c 继续重试: ").strip().lower()
        except EOFError:
            ans = ""
        if ans != "c":
            queue.popleft()
            self.summary.skipped.append((attempt.course, reason))

    def _drain_commands(self, queue: deque[Course]) -> None:
        while self._commands:
            cmd = self._commands.popleft()
            if cmd in ("s", "skip", ""):
                if queue:
                    c = queue.popleft()
                    self.summary.skipped.append((c, "手动跳过"))
            elif cmd in ("q", "quit", "exit"):
                self.summary.aborted = True
                return

    def _maybe_start_stdin(self) -> None:
        import sys

        if self.settings.non_interactive or not sys.stdin.isatty():
            return

        def reader():
            while True:
                line = sys.stdin.readline()
                if not line:
                    return
                self._commands.append(line.strip().lower())

        self._stdin_thread = threading.Thread(target=reader, daemon=True)
        self._stdin_thread.start()
