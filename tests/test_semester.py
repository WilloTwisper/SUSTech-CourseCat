import json

import httpx
import pytest

from enroll_helper.config import DEFAULT_KEYWORDS
from enroll_helper.tis.client import TisApiError, TisClient
from enroll_helper.tis.endpoints import Endpoints

SEM = {"p_xn": "2026-2027", "p_xq": "1", "p_xnxq": "2026-20271"}
LIMITED = {"jg": "-1", "message": "查询请求频率过高 请稍后重试！"}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)


def _client(script):
    calls = {"n": 0}

    def handler(request):
        body = script[min(calls["n"], len(script) - 1)]
        calls["n"] += 1
        return httpx.Response(200, json=body)

    http = httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="http://127.0.0.1:9")
    return TisClient(http, Endpoints(), DEFAULT_KEYWORDS), calls


def test_semester_retries_on_rate_limit():
    tis, calls = _client([LIMITED, LIMITED, SEM])
    sem = tis.query_semester()
    assert (sem.p_xn, sem.p_xq, sem.p_xnxq) == ("2026-2027", "1", "2026-20271")
    assert calls["n"] == 3


def test_semester_missing_field_shows_server_message():
    tis, _ = _client([{"jg": "0", "message": "请重新登录"}])
    with pytest.raises(TisApiError) as e:
        tis.query_semester()
    assert "请重新登录" in str(e.value)
    assert "p_xn" in str(e.value)


def test_semester_gives_up_after_retries():
    tis, calls = _client([LIMITED] * 10)
    with pytest.raises(TisApiError, match="限频"):
        tis.query_semester()
    assert calls["n"] == 4
