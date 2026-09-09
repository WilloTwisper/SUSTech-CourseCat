from enroll_helper.config import DEFAULT_KEYWORDS
from enroll_helper.tis.models import Status
from enroll_helper.tis.parser import classify, extract_message

K = DEFAULT_KEYWORDS


def test_success():
    assert classify(200, '{"jg":"1","message":"选课成功：课程：X"}', K) == Status.SUCCESS


def test_keyword_statuses():
    assert classify(200, '{"jg":"0","message":"上课时间冲突"}', K) == Status.CONFLICT
    assert classify(200, '{"jg":"0","message":"该课程已选"}', K) == Status.ALREADY_ENROLLED
    assert classify(200, '{"jg":"0","message":"人数已满"}', K) == Status.FULL
    assert classify(200, '{"jg":"0","message":"不在选课时间内"}', K) == Status.NOT_OPEN
    assert classify(200, '{"jg":"0","message":"操作过于频繁，请稍后再试"}', K) == Status.RATE_LIMITED


def test_http_status_semantics():
    assert classify(429, "anything", K) == Status.RATE_LIMITED
    assert classify(401, "{}", K) == Status.SESSION_EXPIRED
    assert classify(403, "{}", K) == Status.SESSION_EXPIRED
    assert classify(500, '{"jg":"0","message":"服务器内部错误"}', K) == Status.ERROR


def test_login_page_html():
    assert classify(200, "<html><body>统一身份认证 请登录</body></html>", K) == Status.SESSION_EXPIRED


def test_unknown_failed():
    assert classify(200, '{"jg":"0","message":"系统繁忙或未知错误"}', K) == Status.FAILED
    assert classify(200, '{"jg":"0","message":""}', K) == Status.FAILED


def test_extract_message():
    assert extract_message('{"jg":"0","message":"人数已满"}') == "人数已满"
    assert extract_message("<html></html>") == ""


def test_build_extra_keeps_quota_keys():
    from enroll_helper.tis.client import build_extra

    ex = build_extra({"kcdm": "X", "cq_sybksrl": "5", "rl1": "40",
                      "rl1xkrs": "38", "zrl": "100", "kcxx": ""})
    assert ex["cq_sybksrl"] == "5"
    assert ex["rl1"] == "40"
    assert ex["teachers"] == [] and ex["sched_tags"] == []
