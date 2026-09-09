from __future__ import annotations

import time


class Pacer:
    """Serial request scheduler with AIMD adaptive rate control.

    Spacing is measured from the moment a request is sent to the next
    allowed send moment, so timing does not drift. On any rate-limit
    signal the interval doubles (up to cap); after a streak of clean
    responses it steps back down toward the floor, converging on the
    limit the server actually enforces.
    """

    def __init__(self, interval_ms: float, clock=time.perf_counter,
                 sleeper=time.sleep, min_ms: float = 300.0,
                 clean_to_recover: int = 5):
        self.base_interval = max(interval_ms, 0.0) / 1000.0
        self.interval = self.base_interval
        self.min_interval = max(min_ms, 0.0) / 1000.0
        self.cap = max(self.base_interval * 16, 60.0)
        self.clean_to_recover = max(clean_to_recover, 1)
        self._clean = 0
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
        self._clean = 0
        if self._next_due is not None:
            self._next_due += self.interval - old

    def recover(self) -> None:
        self._clean += 1
        if self._clean >= self.clean_to_recover and self.interval > self.min_interval:
            old = self.interval
            self.interval = max(self.min_interval, self.interval / 2)
            self._clean = 0
            if self._next_due is not None:
                self._next_due -= old - self.interval
