"""M8 open interest, funding, mark and volume. One venue failing does not stop the others."""

from __future__ import annotations

import asyncio

from loguru import logger

from anomaly.models import MarketRow
from anomaly.settings import interval
from anomaly.symbols import base_symbol
from anomaly.timeutil import utcnow


def _f(value, default=None):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_hyperliquid(payload) -> list[MarketRow]:
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    meta, contexts = payload[0], payload[1]
    rows = []
    now = utcnow()
    for asset, ctx in zip(meta.get("universe") or [], contexts):
        if asset.get("isDelisted"):
            continue
        mark = _f(ctx.get("markPx"))
        oi = _f(ctx.get("openInterest"), 0.0) or 0.0
        rows.append(
            MarketRow(
                venue="hyperliquid",
                symbol=asset.get("name") or "",
                base=base_symbol(asset.get("name") or ""),
                mark=mark,
                index=_f(ctx.get("oraclePx")),
                funding=_f(ctx.get("funding")),
                funding_hours=1,
                oi_usd=(oi * mark) if mark else None,
                volume_usd=_f(ctx.get("dayNtlVlm")),
                updated_at=now,
            )
        )
    return rows


def hyperliquid_names(payload) -> dict[str, bool]:
    if not isinstance(payload, list) or not payload:
        return {}
    universe = (payload[0] or {}).get("universe") or []
    return {item.get("name"): bool(item.get("isDelisted")) for item in universe if item.get("name")}


def parse_variational(payload) -> list[MarketRow]:
    rows = []
    now = utcnow()
    for item in (payload or {}).get("listings") or []:
        if item.get("contract_type") not in (None, "perpetual"):
            continue
        mark = _f(item.get("mark_price"))
        oi = item.get("open_interest") or {}
        long_oi = _f(oi.get("long_open_interest"), 0.0) or 0.0
        short_oi = _f(oi.get("short_open_interest"), 0.0) or 0.0
        # Live payloads are quote notional. BTC long interest is tens of millions
        # of USD, which cannot be a base-token amount.
        oi_usd = max(long_oi, short_oi)
        funding = (item.get("funding") or {}).get("last") or {}
        seconds = _f((item.get("funding") or {}).get("interval_seconds"))
        ticker = item.get("ticker") or ""
        rows.append(
            MarketRow(
                venue="variational",
                symbol=ticker,
                base=base_symbol(ticker),
                mark=mark,
                index=mark,
                funding=_f(funding.get("interval_rate")),
                funding_hours=(seconds / 3600.0) if seconds else None,
                oi_usd=oi_usd,
                volume_usd=_f(item.get("volume_24h")),
                updated_at=now,
            )
        )
    return rows


def parse_lighter_books(payload) -> list[MarketRow]:
    rows = []
    now = utcnow()
    books = (payload or {}).get("order_book_details") or []
    for item in books:
        if item.get("market_type") not in (None, "perp"):
            continue
        if item.get("status") not in (None, "active"):
            continue
        mark = _f(item.get("mark_price"))
        oi = _f(item.get("open_interest"))
        oi_usd = _f(item.get("open_interest_usd"))
        if oi_usd is None and oi is not None and mark:
            oi_usd = oi * mark
        symbol = item.get("symbol") or ""
        rows.append(
            MarketRow(
                venue="lighter",
                symbol=symbol,
                base=base_symbol(symbol),
                mark=mark,
                index=_f(item.get("index_price")),
                funding=None,
                funding_hours=1,
                oi_usd=oi_usd,
                volume_usd=_f(item.get("daily_quote_token_volume")),
                updated_at=now,
            )
        )
    return rows


def lighter_funding_map(payload) -> dict[tuple[str, str], float]:
    found = {}
    for item in (payload or {}).get("funding_rates") or []:
        exchange = str(item.get("exchange") or "").lower()
        symbol = base_symbol(item.get("symbol") or "")
        rate = _f(item.get("rate"))
        if exchange and symbol and rate is not None:
            found[(exchange, symbol)] = rate
    return found


def parse_binance_premium(payload) -> list[MarketRow]:
    rows = payload if isinstance(payload, list) else [payload]
    now = utcnow()
    parsed = []
    for item in rows:
        if not isinstance(item, dict) or not item.get("symbol"):
            continue
        symbol = item["symbol"]
        parsed.append(
            MarketRow(
                venue="binance",
                symbol=symbol,
                base=base_symbol(symbol),
                mark=_f(item.get("markPrice")),
                index=_f(item.get("indexPrice")),
                funding=_f(item.get("lastFundingRate")),
                funding_hours=8,
                updated_at=now,
            )
        )
    return parsed


def parse_bybit_tickers(payload) -> list[MarketRow]:
    result = (payload or {}).get("result") or {}
    now = utcnow()
    rows = []
    for item in result.get("list") or []:
        symbol = item.get("symbol") or ""
        mark = _f(item.get("markPrice"))
        oi = _f(item.get("openInterest"))
        rows.append(
            MarketRow(
                venue="bybit",
                symbol=symbol,
                base=base_symbol(symbol),
                mark=mark,
                index=_f(item.get("indexPrice")),
                funding=_f(item.get("fundingRate")),
                funding_hours=8,
                oi_usd=(oi * mark) if (oi is not None and mark) else None,
                volume_usd=_f(item.get("turnover24h")),
                updated_at=now,
            )
        )
    return rows


def parse_okx_oi(payload) -> dict[str, float]:
    found = {}
    for item in (payload or {}).get("data") or []:
        inst = item.get("instId") or ""
        usd = _f(item.get("oiUsd"))
        if inst and usd is not None:
            found[inst] = usd
    return found


def parse_okx_mark(payload) -> list[MarketRow]:
    now = utcnow()
    rows = []
    for item in (payload or {}).get("data") or []:
        inst = item.get("instId") or ""
        if not inst.endswith("-SWAP"):
            continue
        rows.append(
            MarketRow(
                venue="okx",
                symbol=inst,
                base=base_symbol(inst),
                mark=_f(item.get("markPx")),
                funding_hours=8,
                updated_at=now,
            )
        )
    return rows


def parse_aster_premium(payload) -> list[MarketRow]:
    rows = payload if isinstance(payload, list) else []
    now = utcnow()
    parsed = []
    for item in rows:
        symbol = item.get("symbol") or ""
        if not symbol:
            continue
        parsed.append(
            MarketRow(
                venue="aster",
                symbol=symbol,
                base=base_symbol(symbol),
                mark=_f(item.get("markPrice")),
                index=_f(item.get("indexPrice")),
                funding=_f(item.get("lastFundingRate")),
                funding_hours=8,
                updated_at=now,
            )
        )
    return parsed


def parse_bingx_premium(payload) -> list[MarketRow]:
    data = (payload or {}).get("data") or []
    if isinstance(data, dict):
        data = [data]
    now = utcnow()
    rows = []
    for item in data:
        symbol = item.get("symbol") or ""
        hours = _f(item.get("fundingIntervalHours"), 8)
        rows.append(
            MarketRow(
                venue="bingx",
                symbol=symbol,
                base=base_symbol(symbol),
                mark=_f(item.get("markPrice")),
                index=_f(item.get("indexPrice")),
                funding=_f(item.get("lastFundingRate")),
                funding_hours=hours,
                updated_at=now,
            )
        )
    return rows


def parse_mexc(payload, sizes: dict | None = None) -> list[MarketRow]:
    data = (payload or {}).get("data")
    if isinstance(data, dict):
        data = [data]
    now = utcnow()
    rows = []
    for item in data or []:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol") or ""
        mark = _f(item.get("fairPrice")) or _f(item.get("lastPrice"))
        hold = _f(item.get("holdVol"))
        meta = (sizes or {}).get(symbol) or {}
        size = _f(meta.get("size")) or 0.0
        if hold is None or not size:
            oi_usd = None
        elif meta.get("linear") and mark:
            oi_usd = hold * size * mark
        else:
            # Inverse contracts are quoted in USD face value (contractSize is dollars).
            oi_usd = hold * size
        rows.append(
            MarketRow(
                venue="mexc",
                symbol=symbol,
                base=base_symbol(symbol),
                mark=mark,
                index=_f(item.get("indexPrice")),
                funding=_f(item.get("fundingRate")),
                funding_hours=8,
                oi_usd=oi_usd,
                volume_usd=_f(item.get("amount24")),
                updated_at=now,
            )
        )
    return rows


class MarketSource:
    def __init__(self, settings, http, state, registry, pipeline, stop: asyncio.Event) -> None:
        self.settings = settings
        self.http = http
        self.state = state
        self.registry = registry
        self.pipeline = pipeline
        self.stop = stop
        self._aster_symbols: list[str] = []
        self._aster_cursor = 0
        self._bingx_symbols: list[str] = []
        self._mexc_sizes: dict[str, float] = {}

    async def run(self) -> None:
        jobs = [
            ("m8:hyperliquid", "markets_hyperliquid", 15, self._hyperliquid),
            ("m8:aster", "markets_aster", 20, self._aster),
            ("m8:lighter", "markets_lighter", 20, self._lighter),
            ("m8:variational", "markets_variational", 5, self._variational),
            ("m8:bingx", "markets_bingx", 20, self._bingx),
            ("m8:bybit", "markets_bybit", 25, self._bybit),
            ("m8:okx", "markets_okx", 25, self._okx),
            ("m8:binance", "markets_binance", 25, self._binance),
            ("m8:mexc", "markets_mexc", 30, self._mexc),
        ]
        await asyncio.gather(*(self._steady(*job) for job in jobs))

    async def _steady(self, module: str, key: str, default: float, func) -> None:
        while not self.stop.is_set():
            try:
                await func()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.set_module(module, "degraded", str(exc)[:240])
                logger.warning("{}: {}", module, exc)
            if self.stop.is_set():
                return
            await self._sleep(key, default)

    async def _sleep(self, name: str, default: float) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=interval(self.settings, name, default))
        except asyncio.TimeoutError:
            return

    def _cfg(self, venue: str) -> dict:
        return self.settings.venues.get(venue) or {}

    async def _hyperliquid(self) -> None:
        url = self._cfg("hyperliquid").get("info") or "https://api.hyperliquid.xyz/info"
        while not self.stop.is_set():
            payload = await self.http.post_json(
                url, {"type": "metaAndAssetCtxs"}, limiter="hyperliquid", weight=20
            )
            rows = parse_hyperliquid(payload)
            self.state.upsert_markets("hyperliquid", rows)
            await self._sleep("markets_hyperliquid", 15)

    async def _variational(self) -> None:
        url = self._cfg("variational").get("stats")
        while not self.stop.is_set():
            payload = await self.http.get_json(url, limiter="variational")
            self.state.upsert_markets("variational", parse_variational(payload))
            await self._sleep("markets_variational", 5)

    async def _lighter(self) -> None:
        cfg = self._cfg("lighter")
        while not self.stop.is_set():
            books = await self.http.get_json(cfg["order_books"], limiter="lighter")
            funding = await self.http.get_json(cfg["funding"], limiter="lighter")
            rows = parse_lighter_books(books)
            rates = lighter_funding_map(funding)
            for row in rows:
                row.funding = rates.get(("lighter", row.base))
            self.state.upsert_markets("lighter", rows)
            for (exchange, symbol), rate in rates.items():
                if exchange == "lighter":
                    continue
                self.state.funding_ref.setdefault(exchange, {})[symbol] = rate
            await self._sleep("markets_lighter", 20)

    async def _aster(self) -> None:
        cfg = self._cfg("aster")
        while not self.stop.is_set():
            if not self._aster_symbols:
                info = await self.http.get_json(cfg["exchange_info"], limiter="aster", weight=10)
                self._aster_symbols = [
                    item.get("symbol")
                    for item in (info or {}).get("symbols") or []
                    if item.get("symbol") and str(item.get("status") or "TRADING").upper() not in {"BREAK", "CLOSE", "CLOSED"}
                ]
            premium = await self.http.get_json(cfg["premium"], limiter="aster", weight=10)
            rows = {row.symbol: row for row in parse_aster_premium(premium)}
            watch = self._priority_symbols(self._aster_symbols)
            batch = self._rotate(watch, "_aster_cursor", 8)
            for symbol in batch:
                try:
                    oi = await self.http.get_json(
                        cfg["open_interest"].format(symbol=symbol), limiter="aster", weight=1
                    )
                except Exception as exc:
                    logger.debug("aster oi {}: {}", symbol, exc)
                    continue
                row = rows.get(symbol)
                if row is None:
                    continue
                coins = _f((oi or {}).get("openInterest"))
                if coins is not None and row.mark:
                    row.oi_usd = coins * row.mark
            self.state.upsert_markets("aster", list(rows.values()))
            await self._sleep("markets_aster", 15)

    async def _bingx(self) -> None:
        cfg = self._cfg("bingx")
        while not self.stop.is_set():
            premium = await self.http.get_json(cfg["premium"], limiter="bingx")
            rows = {row.symbol: row for row in parse_bingx_premium(premium)}
            if not self._bingx_symbols:
                self._bingx_symbols = list(rows)
            batch = self._rotate(self._priority_symbols(self._bingx_symbols), "_bingx_cursor", 8)
            for symbol in batch:
                try:
                    payload = await self.http.get_json(
                        cfg["open_interest"].format(symbol=symbol), limiter="bingx"
                    )
                except Exception as exc:
                    logger.debug("bingx oi {}: {}", symbol, exc)
                    continue
                data = (payload or {}).get("data") or {}
                row = rows.get(symbol)
                if row is not None:
                    # BingX swap openInterest is quote notional (USDT).
                    row.oi_usd = _f(data.get("openInterest"))
            self.state.upsert_markets("bingx", list(rows.values()))
            await self._sleep("markets_bingx", 15)

    async def _bybit(self) -> None:
        cfg = self._cfg("bybit")
        urls = [cfg.get("tickers")] + list(cfg.get("tickers_failover") or [])
        urls = [url for url in urls if url]
        while not self.stop.is_set():
            payload = await self.http.get_json(urls, limiter="bybit")
            if isinstance(payload, dict) and payload.get("retCode") not in (0, "0", None):
                raise RuntimeError(payload.get("retMsg") or payload)
            self.state.upsert_markets("bybit", parse_bybit_tickers(payload))
            await self._sleep("markets_bybit", 20)

    async def _okx(self) -> None:
        cfg = self._cfg("okx")
        while not self.stop.is_set():
            marks = parse_okx_mark(await self.http.get_json(cfg["mark"], limiter="okx"))
            oi = parse_okx_oi(await self.http.get_json(cfg["open_interest"], limiter="okx"))
            by_symbol = {row.symbol: row for row in marks}
            for symbol, usd in oi.items():
                row = by_symbol.get(symbol)
                if row is not None:
                    row.oi_usd = usd
            for symbol in self._priority_symbols(list(by_symbol))[:12]:
                try:
                    payload = await self.http.get_json(
                        cfg["funding"].format(symbol=symbol), limiter="okx"
                    )
                except Exception as exc:
                    logger.debug("okx funding {}: {}", symbol, exc)
                    continue
                data = ((payload or {}).get("data") or [{}])[0]
                rate = _f(data.get("fundingRate"))
                if symbol in by_symbol and rate is not None:
                    by_symbol[symbol].funding = rate
            self.state.upsert_markets("okx", list(by_symbol.values()))
            await self._sleep("markets_okx", 20)

    async def _binance(self) -> None:
        cfg = self._cfg("binance")
        while not self.stop.is_set():
            payload = await self.http.get_json(cfg["premium_urls"], limiter="binance", weight=10)
            rows = {row.symbol: row for row in parse_binance_premium(payload)}
            for symbol in self._priority_symbols(list(rows))[:12]:
                try:
                    oi = await self.http.get_json(
                        [url.format(symbol=symbol) for url in cfg["open_interest_urls"]],
                        limiter="binance",
                        weight=1,
                    )
                except Exception as exc:
                    logger.debug("binance oi {}: {}", symbol, exc)
                    continue
                coins = _f((oi or {}).get("openInterest"))
                row = rows.get(symbol)
                if row and coins is not None and row.mark:
                    row.oi_usd = coins * row.mark
            self.state.upsert_markets("binance", list(rows.values()))
            await self._sleep("markets_binance", 20)

    async def _mexc(self) -> None:
        cfg = self._cfg("mexc")
        while not self.stop.is_set():
            if not self._mexc_sizes:
                try:
                    detail = await self.http.get_json(cfg["detail"], limiter="mexc")
                    for item in (detail or {}).get("data") or []:
                        symbol = item.get("symbol")
                        size = _f(item.get("contractSize"))
                        if symbol and size:
                            linear = item.get("settleCoin") == item.get("quoteCoin")
                            self._mexc_sizes[symbol] = {"size": size, "linear": linear}
                except Exception as exc:
                    logger.debug("mexc contract sizes: {}", exc)
            payload = await self.http.get_json(cfg["ticker"], limiter="mexc")
            self.state.upsert_markets("mexc", parse_mexc(payload, self._mexc_sizes))
            await self._sleep("markets_mexc", 30)

    def _priority_symbols(self, symbols: list[str]) -> list[str]:
        wanted = self.registry.known_tickers() or set()
        preferred = [symbol for symbol in symbols if base_symbol(symbol) in wanted]
        rest = [symbol for symbol in symbols if symbol not in preferred]
        return preferred + rest

    def _rotate(self, symbols: list[str], cursor_name: str, count: int) -> list[str]:
        if not symbols:
            return []
        cursor = getattr(self, cursor_name, 0)
        count = min(count, len(symbols))
        batch = [symbols[(cursor + offset) % len(symbols)] for offset in range(count)]
        setattr(self, cursor_name, (cursor + count) % len(symbols))
        return batch
