from enroll_helper.pacer import Pacer


def _fake_clock():
    state = {"t": 1000.0, "sleeps": []}

    def clock():
        return state["t"]

    def sleeper(d):
        state["sleeps"].append(d)
        state["t"] += d

    return state, clock, sleeper


def test_no_drift_spacing():
    state, clock, sleeper = _fake_clock()
    p = Pacer(500, clock=clock, sleeper=sleeper)
    p.wait()
    p.wait()
    p.wait()
    assert state["sleeps"] == [0.5, 0.5]


def test_penalize_doubles():
    state, clock, sleeper = _fake_clock()
    p = Pacer(500, clock=clock, sleeper=sleeper)
    p.wait()
    p.wait()
    p.penalize()
    p.wait()
    assert state["sleeps"][-1] == 1.0


def test_recover_restores_base():
    state, clock, sleeper = _fake_clock()
    p = Pacer(500, clock=clock, sleeper=sleeper)
    p.wait()
    p.wait()
    p.penalize()
    p.wait()
    p.recover()
    p.wait()
    assert state["sleeps"] == [0.5, 1.0, 0.5]


def test_late_call_no_extra_sleep():
    state, clock, sleeper = _fake_clock()
    p = Pacer(500, clock=clock, sleeper=sleeper)
    p.wait()
    state["t"] += 5.0
    slept = p.wait()
    assert slept == 0.0
    assert state["sleeps"] == []
