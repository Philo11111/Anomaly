"""Async token buckets. `rate` tokens are allowed each `per_seconds` window."""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self, rate: float, per_seconds: float) -> None:
        if rate <= 0 or per_seconds <= 0:
            raise ValueError("rate and per_seconds must be positive")
        self.capacity = float(rate)
        self.per_seconds = float(per_seconds)
        self._per_second = self.capacity / self.per_seconds
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, amount: float = 1.0) -> None:
        if amount <= 0:
            return
        if amount > self.capacity:
            amount = self.capacity
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._updated
                self._updated = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self._per_second)
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
                wait = (amount - self._tokens) / self._per_second
            await asyncio.sleep(min(max(wait, 0.01), 1.0))


def next_backoff(previous: float, *, cap: float = 60.0, factor: float = 2.0) -> float:
    if previous <= 0:
        return 1.0
    return min(cap, max(1.0, previous * factor))
