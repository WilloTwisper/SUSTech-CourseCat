import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from enroll_helper.mockserver import MockTisState, make_handler
from enroll_helper.webserver import Hub, make_handler as make_web_handler


def _srv(hub):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_web_handler(hub))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture()
def mock():
    state = MockTisState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def web(mock, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hub = Hub(base_url=mock, cookies={"MOCKSESSION": "ok"},
              interval_ms=20, discovery_ms=5)
    server = _srv(hub)
    try:
        yield f"http://127.0.0.1:{server.server_port}", hub
    finally:
        server.shutdown()
        server.server_close()


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=15) as r:
        return json.loads(r.read().decode())


def _post(base, path, obj):
    req = urllib.request.Request(
        base + path, data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def test_status_bootstraps(mock, web):
    base, hub = web
    s = _get(base, "/api/status")
    assert s["session"] is True
    assert s["semester"] == ""
    assert s["catalog_count"] == 0


def test_refresh_and_courses(mock, web):
    import pathlib

    base, hub = web
    _post(base, "/api/refresh", {})
    deadline = time.time() + 30
    while time.time() < deadline:
        if _get(base, "/api/status")["catalog_count"] >= 5:
            break
        time.sleep(0.5)
    assert list(pathlib.Path(".").glob("catalog_*.json")) == []
    d = _get(base, "/api/courses?tab=kzyxk&q=")
    assert d["total"] == 1
    row = d["courses"][0]
    assert row["task"] == "数据结构（mock）"
    assert row["code"] == "CS203"
    assert row["title"] == "数据结构"
    assert row["seats"] == 2
    assert row["sched_tags"] == ["1-16周,星期二第3-4节 智华楼502机房"]


def test_facets_filters_paging(mock, web):
    base, hub = web
    _post(base, "/api/refresh", {})
    deadline = time.time() + 30
    while time.time() < deadline:
        if _get(base, "/api/status")["catalog_count"] >= 5:
            break
        time.sleep(0.5)
    f = _get(base, "/api/facets")
    assert "计算机系" in f["schools"]
    assert "专业选修课" in f["categories"]
    d = _get(base, "/api/courses?tab=all&q=&school=%E8%AE%A1%E7%AE%97%E6%9C%BA%E7%B3%BB")
    assert d["total"] == 1 and d["courses"][0]["code"] == "CS203"
    d = _get(base, "/api/courses?tab=all&q=&category=%E4%B8%93%E4%B8%9A%E9%80%89%E4%BF%AE%E8%AF%BE")
    assert d["total"] == 2
    assert {r["code"] for r in d["courses"]} == {"CS203", "PHY204"}
    d = _get(base, "/api/courses?tab=all&q=&page=2&size=2")
    assert d["total"] == 5 and len(d["courses"]) == 2 and d["page"] == 2
    d = _get(base, "/api/courses?tab=all&q=&hide_full=1")
    assert all(r["seats"] != 0 for r in d["courses"])


def _wait_done(base, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        evs = _get(base, "/api/events?since=0")["events"]
        dones = [e for e in evs if e["kind"] == "done"]
        if dones:
            return dones[-1]["summary"]
        time.sleep(0.5)
    raise AssertionError("engine did not finish: " + json.dumps(evs[-3:], ensure_ascii=False))


def test_e2e_enroll_success(mock, web):
    base, hub = web
    _post(base, "/api/refresh", {})
    deadline = time.time() + 30
    while time.time() < deadline:
        if _get(base, "/api/status")["catalog_count"] >= 5:
            break
        time.sleep(0.5)
    r = _post(base, "/api/queue", {"names": ["数据结构（mock）", "不存在的课"]})
    assert r["queue"] == ["数据结构（mock）"]
    assert r["unknown"] == ["不存在的课"]
    _post(base, "/api/start", {"mode": "now", "interval_ms": 20})
    summary = _wait_done(base)
    assert any("MOCK-103" in s for s in summary["successes"])
    st = _get(base, "/api/status")
    assert st["running"] is False
    assert st["phase"] == "done"


def test_stop_mid_run(mock, web):
    base, hub = web
    _post(base, "/api/refresh", {})
    deadline = time.time() + 30
    while time.time() < deadline:
        if _get(base, "/api/status")["catalog_count"] >= 5:
            break
        time.sleep(0.5)
    _post(base, "/api/queue", {"names": ["量子力学（mock）"]})
    _post(base, "/api/start", {"mode": "retry", "interval_ms": 20})
    deadline = time.time() + 20
    seen_attempt = False
    last = 0
    while time.time() < deadline:
        evs = _get(base, f"/api/events?since={last}")["events"]
        for e in evs:
            last = max(last, e["id"])
            if e["kind"] == "attempt":
                seen_attempt = True
        if seen_attempt:
            break
        time.sleep(0.3)
    assert seen_attempt
    _post(base, "/api/stop", {})
    summary = _wait_done(base)
    assert summary["aborted"] is True
    assert _get(base, "/api/status")["running"] is False


def test_status_watch_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from enroll_helper.webserver import Hub

    hub = Hub()
    hub.queue = ["A"]
    hub.watchlist = ["A"]
    rows = hub.status()["queue"]
    assert rows[0]["watch"] is True


def test_enrolled_shape(mock, web):
    base, hub = web
    d = _get(base, "/api/enrolled")
    assert isinstance(d["enrolled"], list)


def test_conflict_annotation(mock, web):
    from enroll_helper.tis.models import Course

    base, hub = web
    hub.catalog = {
        "目标课": Course("T1", "目标课", "xxxk", "通识选修", 20, 18, extra={
            "sched_tags": ["1-15单周,星期五第7-8节 某楼"],
            "kclbmc": "通识选修课", "kkyxmc": "测试学院"}),
    }
    raw = {"rwmc": "已选课-01班", "id": "E1",
           "kcxx": '<p><a>张三</a></p><div class="ivu-tag ivu-tag-cyan">'
                   '<span><p>1-15单周,星期五第7-8节 另一楼</p></span></div>'}
    hub._fetch_enrolled_raw = lambda: [raw]
    d = _get(base, "/api/courses?tab=all&q=")
    assert d["total"] == 1
    assert d["courses"][0]["conflicts"] == ["已选课-01班"]
    e = _get(base, "/api/enrolled")
    assert e["enrolled"][0]["teachers"] == ["张三"]

    d = _get(base, "/api/courses?tab=all&q=&hide_conflict=1")
    assert d["total"] == 0 and d["courses"] == []

    hub._fetch_enrolled_raw = lambda: [dict(raw, kcxx="1-16周,星期一第1-2节 某楼")]
    hub._enrolled_cache = (0.0, [])
    d = _get(base, "/api/courses?tab=all&q=")
    assert d["courses"][0]["conflicts"] == []
