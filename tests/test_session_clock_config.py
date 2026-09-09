import json
import struct

from enroll_helper.clocksync import compute_offset, parse_server_time
from enroll_helper.config import clamp_interval_ms
from enroll_helper.session import load_cookies_file, load_cookies_netscape, parse_cookie_pairs_from_header


def test_compute_offset():
    assert compute_offset(0, 15, 15, 30) == 0
    assert compute_offset(0, 25, 25, 30) == 10


def test_imminent_start():
    from datetime import datetime, timedelta

    from enroll_helper.clocksync import imminent_start

    assert imminent_start(None) is False
    assert imminent_start("") is False
    future = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    assert imminent_start(future) is False
    soon = (datetime.now() + timedelta(seconds=30)).strftime("%H:%M:%S")
    assert imminent_start(soon) is True
    past = (datetime.now() - timedelta(hours=1)).strftime("%H:%M")
    assert imminent_start(past) is False
    assert imminent_start("not-a-time") is False


def test_parse_server_time():
    secs = 1_000_000_000 + 2_208_988_800
    frac = int(0.5 * 2 ** 32)
    data = bytearray(48)
    data[40:44] = struct.pack("!I", secs)
    data[44:48] = struct.pack("!I", frac)
    assert abs(parse_server_time(bytes(data)) - 1_000_000_000.5) < 1e-6


def test_clamp_interval():
    assert clamp_interval_ms(500, False) == 500
    assert clamp_interval_ms(100, False) == 300
    assert clamp_interval_ms(2000, False) == 2000
    assert clamp_interval_ms(1, True) == 1
    assert clamp_interval_ms(0, True) == 1


def test_header_pairs():
    assert parse_cookie_pairs_from_header("Cookie: a=1; b=2; JSESSIONID=x y") == {
        "a": "1", "b": "2", "JSESSIONID": "x y",
    }


def test_netscape(tmp_path):
    p = tmp_path / "cookies.txt"
    p.write_text(
        ".tis.sustech.edu.cn\tTRUE\t/\tFALSE\t0\tJSESSIONID\tabc\n"
        ".example.com\tTRUE\t/\tFALSE\t0\tother\tx\n"
        "#HttpOnly_.tis.sustech.edu.cn\tTRUE\t/\tTRUE\t0\troute\tr1\n",
        encoding="utf-8",
    )
    pairs = load_cookies_netscape(p, ("tis.sustech.edu.cn",))
    assert pairs == {"JSESSIONID": "abc", "route": "r1"}


def test_har(tmp_path):
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "url": "https://tis.sustech.edu.cn/Xsxk/query/1",
                        "cookies": [{"name": "route", "value": "r9"}],
                        "headers": [{"name": "Cookie", "value": "JSESSIONID=zz"}],
                    }
                },
                {
                    "request": {
                        "url": "https://www.google.com/",
                        "cookies": [{"name": "NID", "value": "nope"}],
                        "headers": [],
                    }
                },
            ]
        }
    }
    p = tmp_path / "c.har"
    p.write_text(json.dumps(har), encoding="utf-8")
    pairs = load_cookies_file(p, ("tis.sustech.edu.cn",))
    assert pairs == {"route": "r9", "JSESSIONID": "zz"}


def test_cookie_file_header_style(tmp_path):
    p = tmp_path / "cookie.txt"
    p.write_text("Cookie: route=r1; JSESSIONID=j1\n", encoding="utf-8")
    assert load_cookies_file(p, ()) == {"route": "r1", "JSESSIONID": "j1"}
