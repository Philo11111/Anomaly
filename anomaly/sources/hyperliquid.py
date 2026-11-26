"""M4 Hyperliquid: new and delisted markets, mark crashes, spot deployers."""

from __future__ import annotations

import asyncio

from loguru import logger

from anomaly.models import Event
from anomaly.registry import WatchAddress
from anomaly.settings import interval
from anomaly.sources.markets import hyperliquid_names
from anomaly.timeutil import utcnow


class HyperliquidSource:
    def __init__(self, settings, http, state, registry, pipeline, stop: asyncio.Event) -> None:
        self.settings = settings
        self.http = http
        self.state = state
        self.registry = registry
        self.pipeline = pipeline
        self.stop = stop
        self._perps: dict[str, bool] | None = None
        self._spots: set[str] | None = None
        self._marks: dict[str, float] = {}

    async def run(self) -> None:
        url = (self.settings.venues.get("hyperliquid") or {}).get("info") or "https://api.hyperliquid.xyz/info"
        ws = (self.settings.venues.get("hyperliquid") or {}).get("ws")
        await asyncio.gather(self._rest(url), self._ws(ws))

    async def _rest(self, url: str) -> None:
        while not self.stop.is_set():
            try:
                payload = await self.http.post_json(
                    url, {"type": "metaAndAssetCtxs"}, limiter="hyperliquid", weight=20
                )
                await self._perps_diff(payload)
                spot = await self.http.post_json(
                    url, {"type": "spotMetaAndAssetCtxs"}, limiter="hyperliquid", weight=20
                )
                await self._spot_diff(url, spot)
                self.state.set_module("m4:hyperliquid", "running", "meta polled")
            except Exception as exc:
                self.state.set_module("m4:hyperliquid", "degraded", str(exc))
                logger.warning("hyperliquid meta: {}", exc)
            try:
                await asyncio.wait_for(
                    self.stop.wait(), timeout=interval(self.settings, "hl_meta", 20)
                )
                return
            except asyncio.TimeoutError:
                continue

    async def _perps_diff(self, payload) -> None:
        names = hyperliquid_names(payload)
        contexts = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        universe = (payload[0] or {}).get("universe") or []
        baseline = self._perps is None
        if baseline:
            self._perps = names
        else:
            for name, delisted in names.items():
                if name not in self._perps:
                    await self._listing(name, "new perp")
                elif delisted and not self._perps.get(name):
                    await self._listing(name, "delisted")
            self._perps = names
        for asset, ctx in zip(universe, contexts):
            name = asset.get("name")
            if not name or asset.get("isDelisted"):
                continue
            try:
                mark = float(ctx.get("markPx") or 0)
                prev = float(ctx.get("prevDayPx") or 0)
            except (TypeError, ValueError):
                continue
            if not baseline and prev > 0 and mark > 0:
                drop = (prev - mark) / prev * 100
                armed = self._marks.get(f"crash:{name}", 0)
                if drop >= self.settings.crash_pct and not armed:
                    self._marks[f"crash:{name}"] = 1
                    await self.pipeline.handle(
                        Event(
                            type="crash",
                            source="hyperliquid",
                            timestamp=utcnow(),
                            ticker=name.upper(),
                            chain="hyperliquid",
                            title=f"{name} mark {drop:.1f}% below prev day",
                            summary=f"mark {mark} vs prev day {prev}",
                            signals=[],
                            payload={"gap_pct": -drop, "risks": "різке падіння марк-ціни на Hyperliquid"},
                        )
                    )
                elif drop < self.settings.crash_pct:
                    self._marks[f"crash:{name}"] = 0
            self._marks[name] = mark

    async def _listing(self, name: str, kind: str) -> None:
        await self.pipeline.handle(
            Event(
                type="listing",
                source="hyperliquid",
                timestamp=utcnow(),
                ticker=name.split(":")[-1].upper(),
                chain="hyperliquid",
                title=f"Hyperliquid {kind}: {name}",
                summary=kind,
                signals=[],
                links={"HL": f"https://app.hyperliquid.xyz/trade/{name}"},
            )
        )

    async def _spot_diff(self, url: str, payload) -> None:
        if not isinstance(payload, list) or not payload:
            return
        tokens = (payload[0] or {}).get("tokens") or []
        current = {token.get("tokenId") for token in tokens if token.get("tokenId")}
        if self._spots is None:
            self._spots = current
            return
        fresh = [token for token in tokens if token.get("tokenId") not in self._spots]
        self._spots = current
        for token in fresh[:3]:
            try:
                details = await self.http.post_json(
                    url,
                    {"type": "tokenDetails", "tokenId": token["tokenId"]},
                    limiter="hyperliquid",
                    weight=20,
                )
            except Exception as exc:
                logger.debug("tokenDetails {}: {}", token.get("name"), exc)
                continue
            deployer = (details or {}).get("deployer")
            name = token.get("name") or ""
            if deployer:
                self.registry.add_signer(
                    WatchAddress(
                        chain="ethereum",
                        address=str(deployer).lower(),
                        ticker=name.upper(),
                        role="deployer",
                        label=f"HL spot deployer {name}",
                    )
                )
            await self._listing(name, "new spot")

    async def _ws(self, url: str | None) -> None:
        if not url:
            return
        from anomaly.wsclient import run_websocket

        async def on_message(message: dict) -> None:
            # allMids keeps the socket warm and confirms the public feed.
            if message.get("channel") == "allMids":
                self.state.set_module("m4:ws", "running", "allMids")

        while not self.stop.is_set():
            try:
                await run_websocket(
                    [url],
                    on_message,
                    name="m4:ws",
                    subscribe=[{"method": "subscribe", "subscription": {"type": "allMids"}}],
                    stop=self.stop,
                )
            except Exception as exc:
                self.state.set_module("m4:ws", "degraded", str(exc))
                logger.warning("hyperliquid ws: {}", exc)
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=5)
                return
            except asyncio.TimeoutError:
                continue
