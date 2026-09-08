from __future__ import annotations

import re
from dataclasses import dataclass, field

WEEKDAYS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
            "日": 7, "天": 7}

_SEG_RE = re.compile(
    r"(\d+-\d+单周|\d+-\d+双周|\d+-\d+周|\d+周)\s*[,，]?\s*"
    r"(?:星期|周)([一二三四五六日天])第(\d+)(?:\s*-\s*(\d+))?节"
)
_WEEK_RE = re.compile(r"(\d+)(?:-(\d+))?(单|双)?周")


@dataclass(frozen=True)
class Slot:
    weeks: frozenset = field(default_factory=frozenset)
    weekday: int = 0
    start: int = 0
    end: int = 0


def parse_weeks(spec: str) -> set[int]:
    m = _WEEK_RE.fullmatch(spec.strip())
    if not m:
        return set()
    a, b, odd_even = int(m.group(1)), m.group(2), m.group(3)
    lo, hi = (a, int(b)) if b else (a, a)
    lo, hi = max(lo, 1), min(hi, 30)
    weeks = set(range(lo, hi + 1))
    if odd_even == "单":
        weeks = {w for w in weeks if w % 2 == 1}
    elif odd_even == "双":
        weeks = {w for w in weeks if w % 2 == 0}
    return weeks


def parse_schedule(text: str) -> list[Slot]:
    slots: list[Slot] = []
    for m in _SEG_RE.finditer(text or ""):
        weeks = parse_weeks(m.group(1))
        weekday = WEEKDAYS.get(m.group(2), 0)
        start = int(m.group(3))
        end = int(m.group(4)) if m.group(4) else start
        if weeks and weekday and start <= end:
            slots.append(Slot(frozenset(weeks), weekday, start, end))
    return slots


def slots_from_extra(extra: dict) -> list[Slot]:
    tags = extra.get("sched_tags") or []
    src = tags if tags else ([extra.get("schedule")] if extra.get("schedule") else [])
    slots: list[Slot] = []
    for t in src:
        slots.extend(parse_schedule(t))
    return slots


def slots_overlap(a: Slot, b: Slot) -> bool:
    return bool(a.weeks & b.weeks) and a.weekday == b.weekday \
        and a.start <= b.end and b.start <= a.end


def courses_conflict(slots_a: list[Slot], slots_b: list[Slot]) -> bool:
    return any(slots_overlap(a, b) for a in slots_a for b in slots_b)


def find_conflicts(my_slots: list[Slot], enrolled: list[tuple[str, list[Slot]]]) -> list[str]:
    return [name for name, slots in enrolled
            if slots and my_slots and courses_conflict(my_slots, slots)]
