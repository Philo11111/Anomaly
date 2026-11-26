"""M7 exchange notices. Unknown or blocked feeds degrade and keep retrying."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from loguru import logger

from anomaly.classify import notice_signals
from anomaly.models import Event
from anomaly.settings import interval
from anomaly.symbols import find_tickers
from anomaly.timeutil import parse_unix, utcnow


class NoticeSource:
    def __init__(self, settings, http, state, registry, pipeline, stop: asyncio.Event) -> None:
        self.settings = settings
        self.http = http
        self.state = state
        self.registry = registry
        self.pipeline = pipeline
        self.stop = stop
        self._gate_flags: dict[str, tuple[bool, bool]] = {}
        self._failures: dict[str, int] = {}

    async def run(self) -> None:
        tasks = [
            self._loop("upbit", self._upbit, 12),
            self._loop("okx", self._okx, 20),
            self._loop("bybit", self._bybit, 20),
            self._loop("bitget", self._bitget, 30),
            self._loop("bithumb", self._bithumb, 30),
            self._loop("gate", self._gate, 60),
            self._loop("bingx", self._bingx, 60),
        ]
        await asyncio.gather(*tasks)

    async def _loop(self, name: str, method, every: float) -> None:
        while not self.stop.is_set():
            base = interval(self.settings, f"notice_{name}", every)
            try:
                count = await method()
                self._failures[name] = 0
                self.state.set_module(f"m7:{name}", "running", f"{count} notices scanned")
                delay = base
            except Exception as exc:
                self._failures[name] = self._failures.get(name, 0) + 1
                fails = self._failures[name]
                self.state.set_module(f"m7:{name}", "degraded", str(exc)[:240])
                logger.warning("notice {}: {}", name, exc)
                delay = min(900.0, base * (2 ** min(fails, 6)))
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=delay)
                return
            except asyncio.TimeoutError:
                continue

    async def _emit(self, exchange: str, notice_id: str, title: str, url: str, moment) -> None:
        key = f"notice:{exchange}:{notice_id}"
        if await self.state.seen(key, exchange):
            return
        if moment and utcnow() - moment > timedelta(hours=self.settings.news_max_age_hours):
            return
        signals = notice_signals(title, exchange, self.settings)
        if not signals:
            return
        tickers = find_tickers(title, self.registry.known_tickers()) or [None]
        for ticker in tickers[:3]:
            await self.pipeline.handle(
                Event(
                    type="notice",
                    source=f"notice:{exchange}",
                    timestamp=moment or utcnow(),
                    ticker=ticker,
                    name=self.registry.name_of(ticker) if ticker else None,
                    chain=None,
                    title=title[:180],
                    summary=f"{exchange}: {title[:240]}",
                    signals=signals,
                    links={exchange: url} if url else {},
                    payload={"dedup": key, "risks": "біржа могла зупинити депозити, увімкнути reduce-only або відкотити угоди"},
                )
            )

    async def _upbit(self) -> int:
        cfg = self.settings.venues.get("upbit") or {}
        payload = await self.http.get_json(
            cfg.get("announcements"),
            limiter="upbit",
            headers={"Origin": "https://upbit.com", "Referer": "https://upbit.com/"},
        )
        notices = []
        if isinstance(payload, dict):
            data = payload.get("data") or payload
            notices = data.get("notices") or data.get("announcements") or []
        elif isinstance(payload, list):
            notices = payload
        for item in notices:
            await self._emit(
                "upbit",
                str(item.get("id") or item.get("title")),
                item.get("title") or "",
                item.get("url") or f"https://upbit.com/service_center/notice?id={item.get('id')}",
                parse_unix(item.get("listed_at") or item.get("first_listed_at") or item.get("created_at")),
            )
        return len(notices)

    async def _okx(self) -> int:
        url = (self.settings.venues.get("okx") or {}).get("announcements")
        payload = await self.http.get_json(url, limiter="okx")
        count = 0
        for group in (payload or {}).get("data") or []:
            for item in group.get("details") or []:
                count += 1
                await self._emit(
                    "okx",
                    str(item.get("url") or item.get("title")),
                    item.get("title") or "",
                    item.get("url") or "",
                    parse_unix(item.get("pTime")),
                )
        return count

    async def _bybit(self) -> int:
        url = (self.settings.venues.get("bybit") or {}).get("announcements")
        payload = await self.http.get_json(url, limiter="bybit")
        if isinstance(payload, dict) and payload.get("retCode") not in (0, "0", None):
            raise RuntimeError(payload.get("retMsg") or payload)
        items = ((payload or {}).get("result") or {}).get("list") or []
        for item in items:
            await self._emit(
                "bybit",
                str(item.get("url") or item.get("title")),
                item.get("title") or item.get("description") or "",
                item.get("url") or "",
                parse_unix(item.get("dateTimestamp") or item.get("publishTime")),
            )
        return len(items)

    async def _bitget(self) -> int:
        url = (self.settings.venues.get("bitget") or {}).get("announcements")
        payload = await self.http.get_json(url, limiter="bitget")
        if str((payload or {}).get("code")) not in {"00000", "0"}:
            raise RuntimeError((payload or {}).get("msg") or "bitget announcements")
        items = (payload or {}).get("data") or []
        for item in items:
            await self._emit(
                "bitget",
                str(item.get("annId") or item.get("annTitle")),
                item.get("annTitle") or "",
                item.get("annUrl") or "",
                parse_unix(item.get("cTime")),
            )
        return len(items)

    async def _bithumb(self) -> int:
        url = (self.settings.venues.get("bithumb") or {}).get("notices")
        payload = await self.http.get_json(url, limiter="bithumb")
        items = payload if isinstance(payload, list) else (payload or {}).get("data") or []
        for item in items:
            await self._emit(
                "bithumb",
                str(item.get("pc_url") or item.get("title")),
                item.get("title") or "",
                item.get("pc_url") or "",
                parse_unix(item.get("published_at")),
            )
        return len(items)

    async def _gate(self) -> int:
        """Deposit and withdraw flags. Gate's HTML notice API is geo-blocked."""
        url = (self.settings.venues.get("gate") or {}).get("currencies")
        payload = await self.http.get_json(url, limiter="gate")
        if not isinstance(payload, list):
            raise RuntimeError("gate currencies unexpected payload")
        wanted = self.registry.known_tickers()
        changes = 0
        for item in payload:
            currency = str(item.get("currency") or "").upper()
            if currency not in wanted:
                continue
            flags = (bool(item.get("deposit_disabled")), bool(item.get("withdraw_disabled")))
            previous = self._gate_flags.get(currency)
            self._gate_flags[currency] = flags
            if previous is None or previous == flags:
                continue
            changes += 1
            deposit, withdraw = flags
            if not deposit and not withdraw:
                continue
            bits = []
            if deposit:
                bits.append("deposits suspended")
            if withdraw:
                bits.append("withdrawals suspended")
            title = f"{currency} " + " and ".join(bits)
            await self._emit("gate", f"{currency}:{flags}", title, "https://www.gate.io", utcnow())
        if not payload:
            raise RuntimeError("gate currency list empty")
        return len(payload)

    async def _bingx(self) -> int:
        url = (self.settings.venues.get("bingx") or {}).get("announcements")
        if not url:
            raise RuntimeError("bingx announcements URL is not configured")
        payload = await self.http.get_json(url, limiter="bingx")
        if isinstance(payload, dict) and payload.get("code") not in (0, "0", None):
            raise RuntimeError(payload.get("msg") or "bingx announcements")
        data = (payload or {}).get("data") if isinstance(payload, dict) else payload
        items = data if isinstance(data, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            await self._emit(
                "bingx",
                str(item.get("id") or item.get("title") or item.get("annTitle")),
                item.get("title") or item.get("annTitle") or "",
                item.get("url") or item.get("annUrl") or "",
                parse_unix(item.get("time") or item.get("cTime")),
            )
        return len(items)
