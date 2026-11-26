"""Reconnecting WebSocket with endpoint failover and backoff."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable

import websockets
from loguru import logger

from anomaly.ratelimit import next_backoff

MessageHandler = Callable[[dict | list], Awaitable[None]]


class Resubscribe(Exception):
    """The caller should rebuild its subscription set."""


def connect_websocket(url: str, **kwargs):
    """websockets 13 uses extra_headers; 14 uses additional_headers."""
    params = inspect.signature(websockets.connect).parameters
    headers = kwargs.pop("headers", None) or {"User-Agent": "AnomalyMonitor/1.0"}
    if "additional_headers" in params:
        kwargs["additional_headers"] = headers
    elif "extra_headers" in params:
        kwargs["extra_headers"] = headers
    if "user_agent_header" in params:
        kwargs.setdefault("user_agent_header", "AnomalyMonitor/1.0")
    return websockets.connect(url, **kwargs)


async def run_websocket(
    urls: list[str],
    handler: MessageHandler,
    *,
    name: str,
    subscribe: list[dict] | Callable[[], list[dict]] | None = None,
    stop: asyncio.Event,
    ping_interval: float = 20,
) -> None:
    if not urls:
        raise RuntimeError(f"{name}: no websocket endpoints configured")
    backoff = 1.0
    index = 0
    while not stop.is_set():
        url = urls[index % len(urls)]
        try:
            async with connect_websocket(
                url,
                ping_interval=ping_interval,
                open_timeout=15,
                close_timeout=5,
                max_size=8 * 1024 * 1024,
            ) as socket:
                messages = subscribe() if callable(subscribe) else (subscribe or [])
                for message in messages:
                    await socket.send(json.dumps(message))
                logger.info("{} connected {}", name, url)
                backoff = 1.0
                async for raw in socket:
                    if stop.is_set():
                        return
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    try:
                        await handler(payload)
                    except Resubscribe:
                        raise
                    except Exception as exc:
                        logger.warning("{} handler error: {}", name, exc)
        except Resubscribe:
            logger.info("{} resubscribe requested", name)
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            index += 1
            logger.warning("{} websocket {} failed: {}", name, url, exc)
            if stop.is_set():
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
                return
            except asyncio.TimeoutError:
                pass
            backoff = next_backoff(backoff)
