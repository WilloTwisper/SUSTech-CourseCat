from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    ALREADY_ENROLLED = "ALREADY_ENROLLED"
    CONFLICT = "CONFLICT"
    FULL = "FULL"
    NOT_OPEN = "NOT_OPEN"
    RATE_LIMITED = "RATE_LIMITED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    FAILED = "FAILED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Semester:
    p_xn: str
    p_xq: str
    p_xnxq: str

    def label(self) -> str:
        names = {"1": "秋季", "2": "春季", "3": "小学期"}
        return f"{self.p_xn} 学年 第{names.get(self.p_xq, self.p_xq)}学期"


@dataclass(frozen=True)
class Course:
    course_id: str
    name: str
    type_code: str
    type_name: str = ""
    capacity: int | None = None
    enrolled: int | None = None
    extra: dict = field(default_factory=dict)

    def display(self) -> str:
        return f"{self.name} [{self.type_name or self.type_code}] id={self.course_id}"

    def seats_text(self) -> str:
        if self.capacity is None or self.enrolled is None:
            return "--"
        return f"余{max(self.capacity - self.enrolled, 0)}/{self.capacity}"


@dataclass
class Attempt:
    course: Course
    status: Status
    message: str = ""
    http_status: int = 0
    latency_ms: float = 0.0
    request_start: float = 0.0
    ts: float = field(default_factory=time.time)
