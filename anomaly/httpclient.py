"""HTTP helper with per-host token buckets, retries, and endpoint failover."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp
from loguru import logger

from anomaly.ratelimit import TokenBucket

_USER_AGENT = "AnomalyMonitor/1.0 (+https://github.com/Philo11111/Anomaly)"


class HttpClient:
    def __init__(self, limits: dict[str, tuple[float, float]]) -> None:
        self.buckets = {
            name: TokenBucket(rate, per) for name, (rate, per) in limits.items()
        }
        if "default" not in self.buckets:
            self.buckets["default"] = TokenBucket(5, 1)
        self._session: aiohttp.ClientSession | None = None

    async def open(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=25)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _bucket(self, name: str) -> TokenBucket:
        return self.buckets.get(name) or self.buckets["default"]

    async def request_json(
        self,
        method: str,
        urls: list[str] | str,
        *,
        limiter: str = "default",
        weight: float = 1,
        json_body: Any = None,
        headers: dict | None = None,
        retries: int = 1,
    ) -> Any:
        if self._session is None:
            await self.open()
        assert self._session is not None
        targets = [urls] if isinstance(urls, str) else list(urls)
        last_error: str | None = None
        for url in targets:
            for attempt in range(retries + 1):
                await self._bucket(limiter).acquire(weight)
                try:
                    async with self._session.request(
                        method, url, json=json_body, headers=headers
                    ) as response:
                        body = await response.read()
                        if response.status == 429:
                            retry_after = response.headers.get("Retry-After", "2")
                            try:
                                delay = min(float(retry_after), 30)
                            except ValueError:
                                delay = 2
                            last_error = f"429 {url}"
                            logger.debug("rate limited {} sleeping {}s", url, delay)
                            await asyncio.sleep(delay)
                            continue
                        if response.status >= 400:
                            snippet = body[:180].decode("utf-8", "replace")
                            last_error = f"{response.status} {url} {snippet}"
                            break
                        if not body:
                            return None
                        try:
                            return json.loads(body)
                        except json.JSONDecodeError:
                            return body.decode("utf-8", "replace")
                except asyncio.TimeoutError:
                    last_error = f"timeout {url}"
                except aiohttp.ClientError as exc:
                    last_error = f"{type(exc).__name__} {url}: {exc}"
                if attempt < retries:
                    await asyncio.sleep(0.4 * (attempt + 1))
        raise RuntimeError(last_error or "request failed")

    async def get_text(self, url: str, *, limiter: str = "default") -> str:
        if self._session is None:
            await self.open()
        assert self._session is not None
        await self._bucket(limiter).acquire(1)
        async with self._session.get(url) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"{response.status} {url} {text[:160]}")
            return text

    async def get_json(self, urls, **kwargs) -> Any:
        return await self.request_json("GET", urls, **kwargs)

    async def post_json(self, urls, body, **kwargs) -> Any:
        return await self.request_json("POST", urls, json_body=body, **kwargs)
