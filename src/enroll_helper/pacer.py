from __future__ import annotations

import time


class Pacer:
    """Serial request scheduler. Spacing is measured from the moment a request
    is sent to the next allowed send moment, so timing does not drift."""

    def __init__(self, interval_ms: float, clock=time.perf_counter, sleeper=time.sleep):
        self.interval = max(interval_ms, 0.0) / 1000.0
        self.base_interval = self.interval
        self.cap = max(self.interval * 16, 60.0)
        self._clock = clock
        self._sleep = sleeper
        self._next_due: float | None = None

    def wait(self) -> float:
        now = self._clock()
        if self._next_due is None:
            self._next_due = now + self.interval
            return 0.0
        slept = 0.0
        if now < self._next_due:
            slept = self._next_due - now
            self._sleep(slept)
            now = self._next_due
        self._next_due = max(now, self._next_due) + self.interval
        return slept

    def penalize(self) -> None:
        old = self.interval
        self.interval = min(max(self.interval * 2.0, 0.1), self.cap)
        if self._next_due is not None:
            self._next_due += self.interval - old

    def recover(self) -> None:
        if self._next_due is not None:
            self._next_due -= max(self.interval - self.base_interval, 0.0)
        self.interval = self.base_interval
