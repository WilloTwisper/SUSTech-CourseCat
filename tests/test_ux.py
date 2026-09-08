import pytest

from enroll_helper.cli import build_run_argv, parse_at
from enroll_helper.engine import EnrollEngine, RunSummary, merge_summaries
from enroll_helper.login import extract_tis_cookies
from enroll_helper.pacer import Pacer
from enroll_helper.picker import filter_catalog, parse_command, render_rows, run_picker
from enroll_helper.tis.models import Course, Status


def test_browser_args_allow_cdp():
    from enroll_helper.login import build_browser_args

    args = build_browser_args("msedge.exe", 19222, "C:\\prof", "https://x/")
    assert "--remote-allow-origins=*" in args
    assert any(a.startswith("--remote-debugging-port=") for a in args)
    assert args[-1] == "https://x/"


def test_extract_tis_cookies():
    cookies = [
        {"name": "SESSION", "value": "abc", "domain": "tis.sustech.edu.cn"},
        {"name": "CAS", "value": "x", "domain": "cas.sustech.edu.cn"},
        {"name": "route", "value": "r", "domain": ".tis.sustech.edu.cn"},
    ]
    assert extract_tis_cookies(cookies) == {"SESSION": "abc", "route": "r"}


def test_parse_command():
    assert parse_command("1 3 2") == ("add", [1, 3, 2])
    assert parse_command("d 2") == ("delete", [2])
    assert parse_command("l") == ("list", [])
    assert parse_command("q") == ("save", [])
    assert parse_command("r") == ("refresh", [])
    assert parse_command("refresh") == ("refresh", [])
    assert parse_command("数据") == ("noop", [])
    assert parse_command("") == ("noop", [])


def test_filter_and_render():
    cat = {
        "B课程": Course("i2", "B课程", "xxxk", "通识选修", capacity=20, enrolled=18),
        "A课程": Course("i1", "A课程", "bxxk", "通识必修", capacity=40, enrolled=32),
    }
    rows = filter_catalog(cat, "")
    assert [c.name for c in rows] == ["A课程", "B课程"]
    assert "余8/40" in render_rows(rows)
    assert [c.name for c in filter_catalog(cat, "B")] == ["B课程"]
    assert [c.name for c in filter_catalog(cat, "", "xxxk")] == ["B课程"]
    assert filter_catalog(cat, "A", "xxxk") == []


def test_run_picker_end_to_end(tmp_path):
    cat = {
        "高数": Course("i1", "高数", "bxxk", "通识必修", 100, 90),
        "大英": Course("i2", "大英", "xxxk", "通识选修", 50, 50),
    }
    inputs = iter(["高", "1", "l", "2", "l", "q"])
    q = run_picker(cat, str(tmp_path / "c.txt"),
                   input_fn=lambda prompt="": next(inputs), print_fn=lambda *a, **k: None)
    assert [c.name for c in q] == ["高数"]
    assert "高数" in (tmp_path / "c.txt").read_text(encoding="utf-8")


def test_parse_at_full_datetime():
    from datetime import datetime, timedelta

    future = (datetime.now() + timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0)
    ts = parse_at(future.strftime("%Y-%m-%d %H:%M:%S"))
    assert abs(ts - future.timestamp()) < 2


def test_parse_at_past_rejected():
    from datetime import datetime, timedelta

    past = (datetime.now() - timedelta(hours=1)).strftime("%H:%M")
    with pytest.raises(SystemExit):
        parse_at(past)


def test_merge_summaries():
    a = RunSummary()
    a.total_requests = 2
    a.status_counts[Status.FULL] += 2
    a.remaining = [Course("X", "课", "xxxk")]
    b = RunSummary()
    b.total_requests = 1
    b.status_counts[Status.SUCCESS] += 1
    b.successes = [Course("Y", "课2", "xxxk")]
    m = merge_summaries([a, b])
    assert m.total_requests == 3
    assert m.status_counts[Status.FULL] == 2
    assert m.status_counts[Status.SUCCESS] == 1
    assert m.successes[0].course_id == "Y"
    assert m.remaining == b.remaining


def test_picker_refresh(tmp_path):
    cat = {"高数": Course("i1", "高数", "bxxk", "通识必修", 100, 99)}

    def fake_refresh(rows):
        return [Course(c.course_id, c.name, c.type_code, c.type_name, 100, 95) for c in rows]

    shown: list[str] = []
    inputs = iter(["高数", "r", "q"])
    q = run_picker(cat, str(tmp_path / "c.txt"),
                   input_fn=lambda prompt="": next(inputs),
                   print_fn=lambda *a, **k: shown.append(" ".join(map(str, a))),
                   refresher=fake_refresh)
    assert [c.name for c in q] == ["高数"]
    assert any("余5/100" in s for s in shown)


def test_build_run_argv():
    assert build_run_argv("1", "")[:6] == ["--cookies", "cookies.txt", "--courses",
                                           "courses.txt", "--report", "report.json"]
    assert "--at" in build_run_argv("2", "10:00")
    assert "--use-ntp" in build_run_argv("2", "10:00")
    assert "--retry-full" in build_run_argv("3", "")
    assert "--rehearse" in build_run_argv("4", "")


def test_doctor_against_mock(mock, tis, make_settings):
    from enroll_helper.cli import run_doctor

    sem = tis.query_semester()
    verdict = run_doctor(tis, sem, make_settings())
    assert verdict["ok"] is True
    assert verdict["seats"] is True


class _InterruptingTis:
    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def enroll(self, course, semester, submit_target):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise KeyboardInterrupt
        from enroll_helper.tis.models import Attempt, Status
        return Attempt(course, Status.SUCCESS, "操作成功", 200, 5.0)


def test_engine_ctrl_c_graceful(make_settings):
    from collections import deque

    course = Course("X1", "测试课", "xxxk")
    tis = _InterruptingTis(fail_times=1)
    engine = EnrollEngine(tis, object(), Pacer(1), make_settings())
    s = engine.run(deque([course]))

    assert s.remaining == [course]
    assert s.total_requests == 0
    assert not s.aborted
    assert engine._stopping


def test_engine_skips_after_stop(make_settings):
    from collections import deque

    tis = _InterruptingTis(fail_times=0)
    engine = EnrollEngine(tis, object(), Pacer(1), make_settings())
    engine._stopping = True
    s = engine.run(deque([Course("X1", "测试课", "xxxk")]))

    assert s.total_requests == 0
    assert tis.calls == 0


def test_engine_second_run_recovers_after_force(make_settings):
    from collections import deque

    course = Course("X1", "测试课", "xxxk")
    tis = _InterruptingTis(fail_times=0)
    engine = EnrollEngine(tis, object(), Pacer(1), make_settings())
    s = engine.run(deque([course]))
    assert s.successes == [course]
