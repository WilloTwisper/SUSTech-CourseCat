from __future__ import annotations

import email.utils
import json
import re
import time
from urllib.parse import urlencode

import httpx

from .. import constants as C
from .endpoints import Endpoints
from .models import Attempt, Course, Semester, Status
from .parser import classify, extract_message

ROW_KEEP = ("kcdm", "kcmc", "kcmc_en", "rwh", "kclb", "kclbmc", "kcxz", "kcxzmc",
            "rwlxmc", "skyymc", "kkyxmc", "jfzlbmc", "xf", "zxs", "xiaoqumc",
            "cq_sybksrl", "cq_sydwrl", "rl1", "rl2", "rl1xkrs", "rl2xkrs",
            "zrl", "rwrs", "ybksrl", "dnrl", "dnyxrlrs")


class TisApiError(RuntimeError):
    pass


def _to_int(v) -> int | None:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def summarize_kcxx(html: str) -> tuple[list[str], str, list[str]]:
    if not html:
        return [], "", []
    teachers: list[str] = []
    for m in re.finditer(r"<a[^>]*>([^<>]+)</a>", html):
        name = m.group(1).strip()
        if name and name not in teachers:
            teachers.append(name)
    segments: list[str] = []
    for m in re.finditer(r"<div[^>]*ivu-tag-cyan[^>]*>(.*?)</div>", html, re.S):
        seg = re.sub(r"<[^>]+>", " ", m.group(1))
        seg = re.sub(r"\s+", " ", seg).strip(" -|")
        if seg and seg not in segments:
            segments.append(seg)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return teachers, text[:600], segments


def build_extra(item: dict) -> dict:
    extra = {k: item.get(k) for k in ROW_KEEP if item.get(k) is not None}
    teachers, schedule, segments = summarize_kcxx(str(item.get("kcxx") or ""))
    extra["teachers"] = teachers
    extra["schedule"] = schedule
    extra["sched_tags"] = segments
    return extra


class TisClient:
    def __init__(self, http: httpx.Client, endpoints: Endpoints | None = None,
                 keywords: dict[Status, tuple[str, ...]] | None = None):
        self.http = http
        self.endpoints = endpoints or Endpoints()
        self.keywords = keywords or {}

    def query_semester(self) -> Semester:
        backoff = 2.0
        last_text = ""
        for _ in range(4):
            r = self.http.post(self.endpoints.semester, content=b"mxpylx=1")
            try:
                data = r.json()
            except (json.JSONDecodeError, ValueError):
                raise TisApiError(f"学期接口返回非 JSON (HTTP {r.status_code})，"
                                  f"会话可能已失效，请重新登录")
            last_text = r.text[:200]
            message = str(data.get("message", "")) if isinstance(data, dict) else ""
            if str(data.get("jg", "")) == "-1" or "频率过高" in message:
                time.sleep(backoff)
                backoff = min(backoff * 2, 16.0)
                continue
            try:
                return Semester(str(data["p_xn"]), str(data["p_xq"]), str(data["p_xnxq"]))
            except KeyError as e:
                raise TisApiError(
                    f"学期接口缺少字段 {e}，服务端返回：{message or last_text}。"
                    f"若提示登录/失效请重新登录；若接口变更请检查 endpoints 配置")
        raise TisApiError(f"学期接口被限频，请稍后重试（最后返回：{last_text}）")

    def fetch_category(self, code: str, semester: Semester, progress=None) -> list[dict]:
        body = urlencode({
            "p_xn": semester.p_xn,
            "p_xq": semester.p_xq,
            "p_xnxq": semester.p_xnxq,
            "p_pylx": "1",
            "mxpylx": "1",
            "p_xkfsdm": code,
            "pageNum": "1",
            "pageSize": "1000",
        }).encode()
        backoff = 2.0
        for attempt_no in range(5):
            try:
                r = self.http.post(self.endpoints.courses, content=body)
                data = r.json()
                message = str(data.get("message", "")) if isinstance(data, dict) else ""
                if str(data.get("jg", "")) == "-1" or "频率过高" in message:
                    if progress:
                        progress(f"查询被限频({message})，{backoff:.0f}s 后重试")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                return (data.get("kxrwList") or {}).get("list") or []
            except (httpx.HTTPError, json.JSONDecodeError, ValueError) as e:
                if progress:
                    progress(f"查询失败: {type(e).__name__}，{backoff:.0f}s 后重试")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        return []

    def fetch_course_map(self, codes, semester, pacer=None, progress=None) -> dict[str, dict]:
        items: dict[str, dict] = {}
        for i, code in enumerate(sorted(codes)):
            if i and pacer is not None:
                pacer.wait()
            for item in self.fetch_category(code, semester, progress=progress):
                cid = str(item.get("id", ""))
                if cid:
                    items[cid] = item
        return items

    def refresh_seats(self, courses: list, semester: Semester,
                      pacer=None, progress=None) -> list:
        fmap = self.fetch_course_map(
            {c.type_code for c in courses}, semester, pacer, progress)
        updated: dict[str, Course] = {}
        for c in courses:
            item = fmap.get(c.course_id)
            if item is not None:
                extra = dict(c.extra or {})
                extra.update(build_extra(item))
                updated[c.course_id] = Course(
                    c.course_id, c.name, c.type_code, c.type_name,
                    _to_int(item.get("bksrl")), _to_int(item.get("bksyxrs")), extra)
        return [updated.get(c.course_id, c) for c in courses]

    def verify_queue(self, courses: list, semester: Semester,
                     pacer=None, progress=None) -> tuple[list, list]:
        """用新鲜目录核对队列：返回 (存活courses[含刷新余量], 失踪courses)。
        失踪指 id 在对应类别 fresh 列表里找不到（课程可能已关闭/改名）。"""
        fmap = self.fetch_course_map(
            {c.type_code for c in courses}, semester, pacer, progress)
        alive, ghosts = [], []
        for c in courses:
            item = fmap.get(c.course_id)
            if item is None:
                ghosts.append(c)
                continue
            extra = dict(c.extra or {})
            extra.update(build_extra(item))
            alive.append(Course(
                c.course_id, c.name, c.type_code, c.type_name,
                _to_int(item.get("bksrl")), _to_int(item.get("bksyxrs")), extra))
        return alive, ghosts

    def query_courses(self, semester: Semester, discovery_pacer=None, progress=None) -> dict[str, Course]:
        found: dict[str, Course] = {}
        for i, (code, cname) in enumerate(C.COURSE_TYPES.items()):
            if i and discovery_pacer is not None:
                discovery_pacer.wait()
            items = self.fetch_category(code, semester, progress=progress)
            added = 0
            for item in items:
                name = str(item.get("rwmc", "")).strip()
                cid = str(item.get("id", ""))
                if name and cid:
                    found[name] = Course(
                        course_id=cid, name=name, type_code=code, type_name=cname,
                        capacity=_to_int(item.get("bksrl")),
                        enrolled=_to_int(item.get("bksyxrs")),
                        extra=build_extra(item),
                    )
                    added += 1
            if progress:
                progress(f"{cname}: {added} 门")
        return found

    def query_list_view(self, path: str, semester: Semester, code: str,
                        prefer: tuple = ()) -> list[dict]:
        body = urlencode({
            "p_xn": semester.p_xn,
            "p_xq": semester.p_xq,
            "p_xnxq": semester.p_xnxq,
            "p_pylx": "1",
            "mxpylx": "1",
            "p_xkfsdm": code,
        }).encode()
        r = self.http.post(path, content=body)
        try:
            data = r.json()
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(data, dict):
            return []
        keys = list(prefer) + [k for k in data.keys() if k not in prefer]
        fallback: list = []
        for key in keys:
            v = data.get(key)
            lst = v.get("list") if isinstance(v, dict) else v
            if isinstance(lst, list):
                items = [it for it in lst if isinstance(it, dict)]
                if items:
                    return items
                fallback = fallback or items
        return fallback

    def query_cart(self, semester: Semester) -> list[dict]:
        return self.query_list_view("/Xsxk/queryXkgwc", semester, "gouwuche",
                                    prefer=("xkgwcList",))

    def query_enrolled(self, semester: Semester) -> list[dict]:
        return self.query_list_view("/Xsxk/queryYxkc", semester, "yixuan",
                                    prefer=("yxkcList",))
    def build_enroll_body(self, course: Course, semester: Semester, submit_target: str) -> bytes:
        form = {
            "p_pylx": "1",
            "p_xktjz": submit_target,
            "p_xn": semester.p_xn,
            "p_xq": semester.p_xq,
            "p_xnxq": semester.p_xnxq,
            "p_xkfsdm": course.type_code,
            "p_id": course.course_id,
            "p_sfxsgwckb": "1",
        }
        return urlencode(form).encode()

    def enroll(self, course: Course, semester: Semester, submit_target: str = "rwtjzyx") -> Attempt:
        body = self.build_enroll_body(course, semester, submit_target)
        start = time.perf_counter()
        try:
            r = self.http.post(self.endpoints.enroll, content=body)
        except httpx.HTTPError as e:
            latency = (time.perf_counter() - start) * 1000
            return Attempt(course, Status.ERROR, f"{type(e).__name__}: {e}", 0, latency)
        latency = (time.perf_counter() - start) * 1000
        status = classify(r.status_code, r.text, self.keywords)
        return Attempt(course, status, extract_message(r.text) or r.text[:120], r.status_code, latency)

    def warmup(self) -> tuple[int, float | None]:
        r = self.http.get(self.endpoints.referer)
        server_ts = None
        try:
            server_ts = email.utils.parsedate_to_datetime(
                r.headers.get("date", "")).timestamp()
        except (TypeError, ValueError):
            pass
        return r.status_code, server_ts

    def warmup_checked(self) -> tuple[int, str | None]:
        status, server_ts = self.warmup()
        note = None
        if server_ts:
            skew = server_ts - time.time()
            if abs(skew) > 5:
                note = (f"本机时钟与服务器相差 {skew:+.0f}s；"
                        f"定时抢课请先校准，否则首发可能偏晚")
        return status, note
