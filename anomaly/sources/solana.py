"""M3 Solana mint-account supply. Idle until the registry has SPL mints."""

from __future__ import annotations

import asyncio

from loguru import logger

from anomaly.models import Event, Signal
from anomaly.settings import interval
from anomaly.timeutil import utcnow
from anomaly.wsclient import run_websocket


def supply_from_account(value: dict) -> int | None:
    data = (value or {}).get("data")
    if isinstance(data, dict):
        info = ((data.get("parsed") or {}).get("info")) or {}
        raw = info.get("supply")
        if raw is None:
            return None
        return int(raw)
    if isinstance(data, list) and data:
        try:
            import base64

            blob = base64.b64decode(data[0])
        except Exception:
            return None
        if len(blob) < 44:
            return None
        return int.from_bytes(blob[36:44], "little")
    return None


class SolanaSource:
    def __init__(self, settings, http, state, registry, pipeline, stop: asyncio.Event) -> None:
        self.settings = settings
        self.http = http
        self.state = state
        self.registry = registry
        self.pipeline = pipeline
        self.stop = stop
        self.supply: dict[str, int] = {}

    async def run(self) -> None:
        chain = self.settings.chains.get("solana")
        if chain is None or not chain.ws:
            self.state.set_module("m3:solana", "disabled", "no solana endpoints")
            return
        while not self.stop.is_set():
            mints = self.registry.solana_mints()[:20]
            if not mints:
                self.state.set_module("m3:solana", "idle", "no SPL mints in the watchlist yet")
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=interval(self.settings, "solana_idle", 30))
                    return
                except asyncio.TimeoutError:
                    continue
            version = self.registry.version
            id_to_mint = {}
            subs = []
            for index, mint in enumerate(mints, start=1):
                id_to_mint[index] = mint
                subs.append(
                    {
                        "jsonrpc": "2.0",
                        "id": index,
                        "method": "accountSubscribe",
                        "params": [mint.address, {"encoding": "jsonParsed", "commitment": "confirmed"}],
                    }
                )
            sub_to_mint: dict[int, object] = {}

            async def on_message(message: dict) -> None:
                if self.registry.version != version:
                    from anomaly.wsclient import Resubscribe

                    raise Resubscribe()
                if message.get("method") is None and "id" in message and "result" in message:
                    mint = id_to_mint.get(message.get("id"))
                    result = message.get("result")
                    if mint is not None and isinstance(result, int):
                        sub_to_mint[result] = mint
                    return
                if message.get("method") != "accountNotification":
                    return
                params = message.get("params") or {}
                mint = sub_to_mint.get(params.get("subscription"))
                value = ((params.get("result") or {}).get("value")) or {}
                supply = supply_from_account(value)
                if supply is None or mint is None:
                    return
                await self._changed(mint, mint.address, supply)

            self.state.set_module("m3:solana", "running", f"{len(mints)} mint accounts")
            try:
                await run_websocket(chain.ws, on_message, name="m3:solana", subscribe=subs, stop=self.stop)
            except Exception as exc:
                self.state.set_module("m3:solana", "degraded", str(exc))
                logger.warning("solana: {}", exc)
                await asyncio.sleep(5)

    async def _changed(self, contract, address: str, supply: int) -> None:
        previous = self.supply.get(address)
        self.supply[address] = supply
        if previous is None or previous <= 0:
            return
        if supply <= previous:
            return
        pct = (supply - previous) * 100 / previous
        if pct < self.settings.score.mint_supply_pct:
            return
        ticker = contract.ticker if contract else None
        minted = (supply - previous) / float(10 ** (contract.decimals if contract else 9))
        await self.pipeline.handle(
            Event(
                type="mint",
                source="solana",
                timestamp=utcnow(),
                ticker=ticker,
                name=contract.name if contract else None,
                chain="solana",
                title=f"Solana mint {ticker or address}",
                summary=f"supply +{pct:.1f}%",
                signals=[Signal("mint", pct=pct, detail=f"supply +{pct:.1f}%")],
                links={"Tx": f"https://solscan.io/account/{address}"},
                payload={"amount_tokens": minted, "supply_pct": round(pct, 4), "minter": address},
            )
        )
