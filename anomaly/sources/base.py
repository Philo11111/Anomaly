"""Source lifecycle. A failing source is restarted; it does not stop the process."""

from __future__ import annotations

import asyncio

from loguru import logger

from anomaly.ratelimit import next_backoff
from anomaly.state import State


async def guard(name: str, factory, state: State, stop: asyncio.Event) -> None:
    delay = 1.0
    while not stop.is_set():
        try:
            await factory()
            if stop.is_set():
                return
            logger.warning("{} returned; restarting", name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.set_module(name, "degraded", f"{type(exc).__name__}: {exc}")
            logger.warning("{} failed: {}", name, exc)
        if stop.is_set():
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return
        except asyncio.TimeoutError:
            pass
        delay = next_backoff(delay)
