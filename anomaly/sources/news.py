"""M6 DefiLlama hacks and RSS. Telegram is a separate source, off until configured."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import feedparser
from loguru import logger

from anomaly.classify import news_is_incident
from anomaly.models import Event, Signal
from anomaly.settings import interval
from anomaly.symbols import find_tickers
from anomaly.timeutil import parse_unix, utcnow


class NewsSource:
    def __init__(self, settings, http, state, registry, pipeline, stop: asyncio.Event) -> None:
        self.settings = settings
        self.http = http
        self.state = state
        self.registry = registry
        self.pipeline = pipeline
        self.stop = stop

    async def run(self) -> None:
        await asyncio.gather(self._hacks(), self._rss())

    async def _hacks(self) -> None:
        url = (self.settings.raw.get("defillama_hacks") or "https://api.llama.fi/hacks")
        while not self.stop.is_set():
            try:
                payload = await self.http.get_json(url, limiter="defillama")
                items = payload if isinstance(payload, list) else []
                fresh = 0
                recent = 0
                for item in items:
                    moment = parse_unix(item.get("date")) or utcnow()
                    if utcnow() - moment > timedelta(hours=self.settings.news_max_age_hours):
                        continue
                    recent += 1
                    key = f"hack:{item.get('name')}:{item.get('date')}"
                    if await self.state.seen(key, "defillama"):
                        continue
                    fresh += 1
                    await self._emit(
                        item.get("name") or "hack",
                        item.get("name") or "",
                        "defillama",
                        moment,
                        item.get("source") or "https://defillama.com/hacks",
                        trusted=True,
                    )
                self.state.set_module("m6:hacks", "running", f"{recent} in window, {fresh} new")
            except Exception as exc:
                self.state.set_module("m6:hacks", "degraded", str(exc))
                logger.warning("defillama hacks: {}", exc)
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=interval(self.settings, "news_hacks", 120))
                return
            except asyncio.TimeoutError:
                continue

    async def _rss(self) -> None:
        while not self.stop.is_set():
            failures = 0
            for url in self.settings.rss_feeds:
                try:
                    payload = await self.http.get_text(url, limiter="rss")
                except Exception as exc:
                    failures += 1
                    logger.debug("rss {}: {}", url, exc)
                    continue
                feed = await asyncio.to_thread(feedparser.parse, payload)
                source_name = (feed.feed.get("title") if getattr(feed, "feed", None) else None) or url
                trusted = any(token in url for token in self.settings.trusted_sources) or any(
                    token in source_name.lower() for token in ("rekt",)
                )
                for entry in (feed.entries or [])[:15]:
                    title = entry.get("title") or ""
                    summary = entry.get("summary") or entry.get("description") or ""
                    text = f"{title} {summary}"
                    link = entry.get("link") or url
                    key = f"rss:{link or title}"
                    if await self.state.seen(key, "rss"):
                        continue
                    if not news_is_incident(text, self.settings):
                        continue
                    moment = utcnow()
                    await self._emit(title, text, "rss", moment, link, trusted=trusted, source_name=source_name)
            status = "degraded" if failures == len(self.settings.rss_feeds) else "running"
            self.state.set_module("m6:rss", status, f"{failures} feeds failed")
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=interval(self.settings, "news_rss", 180))
                return
            except asyncio.TimeoutError:
                continue

    async def _emit(self, title, text, source, moment, link, trusted: bool, source_name: str = "") -> None:
        tickers = find_tickers(f"{title} {text}", self.registry.known_tickers()) or [None]
        signals = []
        if trusted or source == "defillama":
            signals.append(Signal("trusted_source", detail=source_name or source))
        for ticker in tickers[:3]:
            await self.pipeline.handle(
                Event(
                    type="news",
                    source=source,
                    timestamp=moment,
                    ticker=ticker,
                    name=self.registry.name_of(ticker) if ticker else None,
                    title=title[:180],
                    summary=(text or title)[:400],
                    signals=list(signals),
                    links={"Source": link} if link else {},
                    payload={"dedup": link or title},
                )
            )
