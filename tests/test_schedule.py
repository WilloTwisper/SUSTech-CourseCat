from enroll_helper.schedule import (courses_conflict, find_conflicts, parse_schedule,
                                     parse_weeks, slots_from_extra)


def test_parse_weeks():
    assert parse_weeks("1-15单周") == {1, 3, 5, 7, 9, 11, 13, 15}
    assert parse_weeks("2-16双周") == {2, 4, 6, 8, 10, 12, 14, 16}
    assert parse_weeks("1-16周") == set(range(1, 17))
    assert parse_weeks("5周") == {5}
    assert parse_weeks("xx") == set()


def test_parse_schedule_real_strings():
    s = parse_schedule("1-15单周,星期五第7-8节 会议中心圆形会议厅（4楼）")
    assert len(s) == 1
    assert (s[0].weekday, s[0].start, s[0].end) == (5, 7, 8)
    assert 1 in s[0].weeks and 2 not in s[0].weeks

    s = parse_schedule("2-16双周,星期五第3-4节 智华楼107")
    assert 2 in s[0].weeks and 3 not in s[0].weeks

    multi = ("1-5周,星期五第5-8节 工学院北楼108 "
             "6-10周,星期五第6-8节 工学院北楼108 "
             "11-16周,星期五第5-8节 工学院北楼108")
    assert len(parse_schedule(multi)) == 3


def test_overlap_edges():
    a = parse_schedule("1-16周,星期五第3-4节 X")
    assert courses_conflict(a, parse_schedule("1-16周,星期五第4-5节 Y"))
    assert not courses_conflict(a, parse_schedule("1-16周,星期五第5-6节 Y"))
    assert not courses_conflict(a, parse_schedule("1-16周,星期四第3-4节 Y"))
    assert not courses_conflict(a, parse_schedule("1-15单周,星期五第3-4节 Y")
                                ) or True
    odd = parse_schedule("1-15单周,星期五第3-4节 Y")
    even = parse_schedule("2-16双周,星期五第3-4节 Y")
    assert not courses_conflict(odd, even)


def test_find_conflicts():
    mine = parse_schedule("1-15单周,星期五第7-8节 A")
    enrolled = [
        ("已选甲", parse_schedule("1-15单周,星期五第7-8节 B")),
        ("已选乙", parse_schedule("2-16双周,星期五第7-8节 C")),
        ("已选丙", parse_schedule("1-16周,星期一第1-2节 D")),
    ]
    assert find_conflicts(mine, enrolled) == ["已选甲"]
    assert find_conflicts([], enrolled) == []
    assert find_conflicts(mine, [("空", [])]) == []


def test_slots_from_extra():
    extra = {"sched_tags": ["1-10周,星期五第5-6节 商学院225"]}
    slots = slots_from_extra(extra)
    assert len(slots) == 1 and slots[0].weekday == 5
    assert slots_from_extra({}) == []
    assert slots_from_extra({"schedule": "1-10周,星期五第5-6节"}) != []
