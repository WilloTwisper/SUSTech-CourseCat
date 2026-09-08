from __future__ import annotations

import json

from .tis.models import Course


class Notifier:
    def __init__(self, webhook_url: str = "", toast: bool = True, quiet: bool = False):
        self.webhook_url = webhook_url
        self.toast = toast
        self.quiet = quiet

    def success(self, course: Course, already: bool = False) -> None:
        what = "已在课表" if already else "选课成功"
        banner = f"█ {what}：{course.name} [{course.type_name}]"
        if not self.quiet:
            from .tui import success_panel
            success_panel(banner)
        if self.toast:
            self._win_toast("选课助手", banner)
        if self.webhook_url:
            self._post_webhook(banner)

    def aborted(self, message: str) -> None:
        if not self.quiet:
            from .tui import success_panel
            success_panel(f"█ 已中止：{message}", border="bold red")
        if self.toast:
            self._win_toast("选课助手已中止", message)
        if self.webhook_url:
            self._post_webhook(f"选课助手已中止：{message}")

    def _win_toast(self, title: str, message: str) -> None:
        try:
            from winotify import Notification, audio

            Notification(app_id="enroll-helper", title=title, msg=message).set_audio(audio.Default, loop=False).show()
        except Exception:
            pass

    def _post_webhook(self, text: str) -> None:
        try:
            import httpx

            httpx.post(self.webhook_url, json={"content": text}, timeout=5.0)
        except Exception:
            pass


def save_report(path: str, summary) -> None:
    data = {
        "total_requests": summary.total_requests,
        "status_counts": {k.value: v for k, v in summary.status_counts.items()},
        "successes": [c.display() for c in summary.successes],
        "skipped": [{"course": c.display(), "reason": r} for c, r in summary.skipped],
        "remaining": [c.display() for c in summary.remaining],
        "aborted": summary.aborted,
        "avg_latency_ms": round(sum(summary.latencies_ms) / len(summary.latencies_ms), 1) if summary.latencies_ms else 0,
        "attempts": [{"course": a.course.name, "status": a.status.value, "message": a.message,
                      "http_status": a.http_status, "latency_ms": round(a.latency_ms, 1),
                      "ts": a.ts} for a in getattr(summary, "attempts", [])],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
