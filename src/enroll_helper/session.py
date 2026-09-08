from __future__ import annotations

import json
from pathlib import Path

import httpx

from . import constants as C
from .tis.endpoints import Endpoints

TIS_DOMAIN_MARKERS = ("tis.sustech.edu.cn",)


def parse_cookie_pairs_from_header(header: str) -> dict[str, str]:
    text = header.strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1]
    pairs: dict[str, str] = {}
    for part in text.replace("\n", ";").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        if name.lower() == "cookie":
            continue
        pairs[name] = value.strip()
    return pairs


def load_cookies_netscape(path: str | Path, domains: tuple[str, ...] = ()) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain = parts[0].lstrip(".").lower()
        if domains and not any(d in domain for d in domains):
            continue
        pairs[parts[5]] = parts[6]
    return pairs


def load_cookies_har(path: str | Path, domains: tuple[str, ...] = ()) -> dict[str, str]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    pairs: dict[str, str] = {}
    for entry in (data.get("log") or {}).get("entries") or []:
        req = entry.get("request") or {}
        url = str(req.get("url", ""))
        if domains and not any(d in url for d in domains):
            continue
        for c in req.get("cookies") or []:
            if c.get("name") and c.get("value") is not None:
                pairs[str(c["name"])] = str(c["value"])
        for h in req.get("headers") or []:
            if str(h.get("name", "")).lower() == "cookie":
                pairs.update(parse_cookie_pairs_from_header(str(h.get("value", ""))))
    return pairs


def save_cookie_header_file(path: str | Path, pairs: dict[str, str]) -> None:
    header = "Cookie: " + "; ".join(f"{k}={v}" for k, v in pairs.items())
    Path(path).write_text(header + "\n", encoding="utf-8")


def load_cookies_file(path: str | Path, domains: tuple[str, ...] = ()) -> dict[str, str]:
    text = Path(path).read_text(encoding="utf-8-sig")
    stripped = text.lstrip()
    if stripped.startswith("{") and '"log"' in text[:400]:
        return load_cookies_har(path, domains)
    header_like = all("=" in ln and "\t" not in ln for ln in text.splitlines() if ln.strip())
    if header_like and stripped.lower().startswith("cookie"):
        return parse_cookie_pairs_from_header(stripped.split(":", 1)[1])
    if header_like:
        return parse_cookie_pairs_from_header(text)
    return load_cookies_netscape(path, domains)


def build_client(
    base_url: str,
    cookies: dict[str, str] | None = None,
    tls_verify: bool = True,
    timeout_s: float = 10.0,
    endpoints: Endpoints | None = None,
    trust_env: bool = True,
) -> httpx.Client:
    endpoints = endpoints or Endpoints()
    headers = {
        "user-agent": C.USER_AGENT,
        "x-requested-with": "XMLHttpRequest",
        "rolecode": "01",
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": base_url.rstrip("/"),
        "referer": base_url.rstrip("/") + endpoints.referer,
    }
    client = httpx.Client(
        base_url=base_url,
        http2=True,
        verify=tls_verify,
        timeout=timeout_s,
        follow_redirects=True,
        trust_env=trust_env,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1, keepalive_expiry=300.0),
        headers=headers,
    )
    for name, value in (cookies or {}).items():
        client.cookies.set(name, value)
    return client
