from __future__ import annotations

import json

from .models import Status


def classify(http_status: int, text: str, keywords: dict[Status, tuple[str, ...]]) -> Status:
    if http_status == 429:
        return Status.RATE_LIMITED
    if http_status in (401, 403):
        return Status.SESSION_EXPIRED

    message = ""
    jg = ""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            jg = str(data.get("jg", ""))
            message = str(data.get("message", ""))
    except (json.JSONDecodeError, ValueError):
        pass

    if jg == "1":
        return Status.SUCCESS

    haystack = message if message else text
    for status, words in keywords.items():
        if any(w in haystack for w in words):
            return status

    if not message and ("<html" in text.lower() or "请登录" in text or "登录" in text and "jg" not in text):
        return Status.SESSION_EXPIRED
    if http_status >= 500:
        return Status.ERROR
    return Status.FAILED


def extract_message(text: str) -> str:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return str(data.get("message", ""))
    except (json.JSONDecodeError, ValueError):
        pass
    return ""
