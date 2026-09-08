from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import constants as C
from .tis.endpoints import Endpoints
from .tis.models import Status

DEFAULT_KEYWORDS: dict[Status, tuple[str, ...]] = {
    Status.CONFLICT: ("冲突", "时间冲突", "上课时间冲突"),
    Status.FULL: ("已满", "人数已满", "容量已满", "名额已满"),
    Status.ALREADY_ENROLLED: ("已选", "重复选课"),
    Status.RATE_LIMITED: ("频繁", "稍后", "过快", "休息一下", "频率过高", "请稍后重试"),
    Status.NOT_OPEN: ("未开始", "不在选课", "未开放", "不在时间"),
}


def clamp_interval_ms(value: int, is_local_target: bool) -> int:
    if is_local_target:
        return max(1, value)
    return max(int(value), C.MIN_INTERVAL_MS)


@dataclass
class Settings:
    base_url: str = C.DEFAULT_BASE_URL
    tls_verify: bool = True
    timeout_s: float = 20.0
    no_env_proxy: bool = False
    interval_ms: int = C.DEFAULT_INTERVAL_MS
    discovery_interval_ms: int = C.DEFAULT_DISCOVERY_INTERVAL_MS
    auto_skip_conflict: bool = True
    retry_full: bool = False
    cascade_on_full: bool = False
    max_requests: int = 0
    use_ntp: bool = False
    ntp_server: str = "ntp.aliyun.com"
    webhook_url: str = ""
    toast: bool = True
    submit_target: str = "rwtjzyx"
    endpoints: Endpoints = field(default_factory=Endpoints)
    keywords: dict[Status, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_KEYWORDS))
    courses_file: str = "courses.txt"
    cookies_file: str = ""
    inline_cookies: list[str] = field(default_factory=list)
    at_time: str = ""
    non_interactive: bool = False
    refresh_cache: bool = False
    list_only: str = ""
    cas_login: bool = False
    dry_run: bool = False

    @property
    def is_local_target(self) -> bool:
        from urllib.parse import urlparse

        return (urlparse(self.base_url).hostname or "").lower() in C.LOCAL_HOSTS

    @property
    def effective_interval_ms(self) -> int:
        return clamp_interval_ms(self.interval_ms, self.is_local_target)


def _coerce(kwargs: dict) -> dict:
    int_keys = {"interval_ms", "discovery_interval_ms", "max_requests"}
    float_keys = {"timeout_s"}
    bool_keys = {"tls_verify", "auto_skip_conflict", "retry_full", "cascade_on_full", "use_ntp",
                 "toast", "non_interactive", "refresh_cache", "cas_login", "dry_run", "no_env_proxy"}
    out = {}
    for k, v in kwargs.items():
        if k in int_keys:
            out[k] = int(v)
        elif k in float_keys:
            out[k] = float(v)
        elif k in bool_keys:
            out[k] = bool(v)
        else:
            out[k] = v
    return out


def load_settings(config_path: str | None, args) -> Settings:
    data: dict = {}
    if config_path:
        text = Path(config_path).read_text(encoding="utf-8-sig")
        data = json.loads(text) if str(config_path).lower().endswith(".json") else _read_toml(text)
    kwargs: dict = {}
    tis = dict(data.get("tis") or {})
    engine = dict(data.get("engine") or {})
    network = dict(data.get("network") or {})
    notify = dict(data.get("notify") or {})
    for section in (tis, engine, network, notify):
        kwargs.update(section)
    endpoints_data = dict(data.get("endpoints") or {})
    keywords_data = dict(data.get("keywords") or {})
    kwargs["endpoints"] = Endpoints.from_dict(endpoints_data) if endpoints_data else Endpoints()
    if keywords_data:
        kwargs["keywords"] = {
            Status[k]: tuple(v) for k, v in keywords_data.items()
        }
    kwargs.update(_coerce(kwargs))
    settings = Settings(**{k: v for k, v in kwargs.items() if k in Settings.__dataclass_fields__})
    _apply_cli_overrides(settings, args)
    return settings


def _read_toml(text: str) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        raise SystemExit("config.toml 需要 Python 3.11+ 或改用 JSON 配置")
    return tomllib.loads(text)


def _apply_cli_overrides(s: Settings, args) -> None:
    for attr in ("base_url", "courses_file", "cookies_file", "at_time", "webhook_url", "list_only"):
        val = getattr(args, attr, None)
        if val:
            setattr(s, attr, val)
    if args.interval_ms:
        s.interval_ms = int(args.interval_ms)
    if getattr(args, "inline_cookies", None):
        s.inline_cookies = list(args.inline_cookies)
    if getattr(args, "cas_login", False):
        s.cas_login = True
    if getattr(args, "non_interactive", False):
        s.non_interactive = True
    if getattr(args, "refresh_cache", False):
        s.refresh_cache = True
    if getattr(args, "rehearse", False):
        s.base_url = getattr(args, "base_url", "") or "http://127.0.0.1:8765"
        s.tls_verify = False
    if s.interval_ms < C.MIN_INTERVAL_MS and not s.is_local_target:
        print(f"[!] 请求间隔 {s.interval_ms}ms 低于服务端限制下限，已强制为 {C.MIN_INTERVAL_MS}ms（仅对非本机目标）")
    s.interval_ms = s.effective_interval_ms


def new_pacer_from(settings: Settings, discovery: bool = False):
    from .pacer import Pacer

    ms = settings.discovery_interval_ms if discovery else settings.interval_ms
    return Pacer(ms)
