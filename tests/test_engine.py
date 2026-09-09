from collections import deque

from enroll_helper.engine import EnrollEngine
from enroll_helper.pacer import Pacer
from enroll_helper.session import build_client
from enroll_helper.tis.client import TisClient
from enroll_helper.tis.endpoints import Endpoints
from enroll_helper.config import DEFAULT_KEYWORDS


def _catalog(tis):
    sem = tis.query_semester()
    cat = tis.query_courses(sem, Pacer(1))
    return sem, cat


def test_priority_skip_and_success(mock, tis, make_settings):
    sem, cat = _catalog(tis)
    q = deque([cat["数据结构（mock）"], cat["量子力学（mock）"], cat["中国古代史（mock）"]])
    engine = EnrollEngine(tis, sem, Pacer(10), make_settings())
    s = engine.run(q)

    assert not s.aborted and not s.remaining
    assert [c.course_id for c in s.successes] == ["MOCK-103"]
    assert {c.course_id for c, _ in s.skipped} == {"MOCK-104", "MOCK-102"}
    assert s.total_requests == 5

    gaps = [b - a for a, b in zip(s.request_times, s.request_times[1:])]
    assert all(g >= 0.009 for g in gaps)


def test_rate_limit_backoff(mock, tis, make_settings):
    sem, cat = _catalog(tis)
    q = deque([cat["大学英语重修（mock）"]])
    engine = EnrollEngine(tis, sem, Pacer(20), make_settings())
    s = engine.run(q)

    assert s.total_requests == 3
    assert [c.course_id for c in s.successes] == ["MOCK-105"]
    gaps = [b - a for a, b in zip(s.request_times, s.request_times[1:])]
    assert gaps[0] >= 0.035
    assert gaps[1] >= 0.07


def test_session_expired_aborts(mock, make_settings):
    client = build_client(mock.url, {}, timeout_s=5)
    tis = TisClient(client, Endpoints(), DEFAULT_KEYWORDS)
    sem, cat = _catalog(tis)
    q = deque([cat["高等数学B（mock）"]])
    engine = EnrollEngine(tis, sem, Pacer(5), make_settings())
    s = engine.run(q)

    assert s.aborted
    assert s.total_requests == 1
    assert [c.course_id for c in s.remaining] == ["MOCK-101"]
    assert s.status_counts["SESSION_EXPIRED"] == 1


def test_retry_full_keeps_waiting(mock, tis, make_settings):
    sem, cat = _catalog(tis)
    q = deque([cat["量子力学（mock）"]])
    engine = EnrollEngine(tis, sem, Pacer(5), make_settings(retry_full=True), )
    s = engine.run(q, max_requests=4)

    assert s.total_requests == 4
    assert [c.course_id for c in s.remaining] == ["MOCK-104"]
    assert s.status_counts["FULL"] == 4


def test_cascade_rotates_full(mock, tis, make_settings):
    sem, cat = _catalog(tis)
    q = deque([cat["量子力学（mock）"], cat["高等数学B（mock）"]])
    engine = EnrollEngine(tis, sem, Pacer(5),
                          make_settings(retry_full=True, cascade_on_full=True))
    s = engine.run(q, max_requests=2)

    assert [c.course_id for c in s.successes] == ["MOCK-101"]
    assert [c.course_id for c in s.remaining] == ["MOCK-104"]
    assert s.total_requests == 2


def test_no_cascade_starves_backup(mock, tis, make_settings):
    sem, cat = _catalog(tis)
    q = deque([cat["量子力学（mock）"], cat["高等数学B（mock）"]])
    engine = EnrollEngine(tis, sem, Pacer(5), make_settings(retry_full=True))
    s = engine.run(q, max_requests=3)

    assert s.successes == []
    assert [c.course_id for c in s.remaining] == ["MOCK-104", "MOCK-101"]
    assert s.status_counts["FULL"] == 3


def test_conflict_no_skip_rotates(mock, tis, make_settings):
    sem, cat = _catalog(tis)
    q = deque([cat["中国古代史（mock）"], cat["高等数学B（mock）"]])
    engine = EnrollEngine(tis, sem, Pacer(5),
                          make_settings(auto_skip_conflict=False))
    s = engine.run(q, max_requests=2)

    assert [c.course_id for c in s.successes] == ["MOCK-101"]
    assert [c.course_id for c in s.remaining] == ["MOCK-102"]
    assert s.status_counts["CONFLICT"] == 1


def test_conflict_no_skip_single_keeps_head(mock, tis, make_settings):
    sem, cat = _catalog(tis)
    q = deque([cat["中国古代史（mock）"]])
    engine = EnrollEngine(tis, sem, Pacer(5),
                          make_settings(auto_skip_conflict=False))
    s = engine.run(q, max_requests=2)

    assert s.successes == []
    assert [c.course_id for c in s.remaining] == ["MOCK-102"]
    assert s.status_counts["CONFLICT"] == 2


def test_full_with_stale_seats_note(make_settings, capsys):
    from collections import deque

    from enroll_helper.engine import EnrollEngine
    from enroll_helper.pacer import Pacer
    from enroll_helper.tis.models import Attempt, Course, Status

    course = Course("X1", "测试课", "xxxk", capacity=10, enrolled=7,
                    extra={"cq_sybksrl": "0", "rl1": "40"})
    engine = EnrollEngine(object(), object(), Pacer(1), make_settings())
    q = deque([course])
    engine._handle(q, Attempt(course, Status.FULL, "人数已满", 200, 5.0))

    assert list(q) == []
    out = capsys.readouterr().out
    assert "快照余3" in out
    assert "cq_sybksrl=0" in out


def test_refresh_seats(mock, tis):
    from enroll_helper.tis.models import Course

    sem = tis.query_semester()
    rows = [Course("MOCK-103", "数据结构（mock）", "kzyxk", "培养方案内")]
    out = tis.refresh_seats(rows, sem, Pacer(1))

    assert (out[0].capacity, out[0].enrolled) == (25, 23)
    assert out[0].seats_text() == "余2/25"
