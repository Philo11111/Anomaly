"""M5 DEX price versus perp mark. DefiLlama's free coin prices, no paid RPC."""

from __future__ import annotations

import asyncio

from loguru import logger

from anomaly.models import Event, Signal
from anomaly.settings import interval
from anomaly.timeutil import utcnow


class DexGapSource:
    def __init__(self, settings, http, state, registry, pipeline, stop: asyncio.Event) -> None:
        self.settings = settings
        self.http = http
        self.state = state
        self.registry = registry
        self.pipeline = pipeline
        self.stop = stop
        self._alerted: dict[str, float] = {}

    async def run(self) -> None:
        while not self.stop.is_set():
            try:
                await self._pass()
                self.state.set_module("m5:dexgap", "running", "prices polled")
            except Exception as exc:
                self.state.set_module("m5:dexgap", "degraded", str(exc))
                logger.warning("dex gap: {}", exc)
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=interval(self.settings, "dex_gap", 30))
                return
            except asyncio.TimeoutError:
                continue

    async def _pass(self) -> None:
        grouped: dict[str, list] = {}
        for contract in self.registry.contracts:
            chain = self.settings.chains.get(contract.chain)
            if chain is None or contract.chain == "solana":
                slug = "solana" if contract.chain == "solana" else None
            else:
                slug = chain.llama
            if not slug:
                continue
            grouped.setdefault(contract.ticker, []).append((slug, contract))
        for ticker, items in grouped.items():
            coin_ids = [f"{slug}:{contract.address}" for slug, contract in items]
            url = "https://coins.llama.fi/prices/current/" + ",".join(coin_ids[:8])
            try:
                payload = await self.http.get_json(url, limiter="defillama")
            except Exception as exc:
                logger.debug("llama price {}: {}", ticker, exc)
                continue
            coins = (payload or {}).get("coins") or {}
            prices = []
            for key, row in coins.items():
                price = row.get("price")
                if price:
                    prices.append(float(price))
            if not prices:
                continue
            dex = sum(prices) / len(prices)
            await self._compare(ticker, dex)

    async def _compare(self, ticker: str, dex: float) -> None:
        threshold = self.settings.score.dex_gap_pct
        worst = None
        for venue in self.settings.user_venues:
            for row in self.state.markets.get(venue, {}).values():
                if row.base != ticker or not row.mark:
                    continue
                gap = (dex - row.mark) / row.mark * 100
                if worst is None or abs(gap) > abs(worst[0]):
                    worst = (gap, venue, row.mark)
        if worst is None:
            return
        gap, venue, mark = worst
        if abs(gap) < threshold:
            self._alerted.pop(ticker, None)
            return
        previous = self._alerted.get(ticker)
        if previous is not None and abs(gap - previous) < 5:
            return
        self._alerted[ticker] = gap
        await self.pipeline.handle(
            Event(
                type="dex_gap",
                source="dexgap",
                timestamp=utcnow(),
                ticker=ticker,
                name=self.registry.name_of(ticker),
                chain=None,
                title=f"{ticker} DEX vs {venue} {gap:+.1f}%",
                summary=f"DEX {dex:.6g} vs {venue} mark {mark:.6g}",
                signals=[Signal("dex_gap", pct=abs(gap), detail=f"{gap:+.1f}% vs {venue}")],
                payload={"gap_pct": round(gap, 2), "dex_price": dex, "mark": mark, "venue": venue},
            )
        )
