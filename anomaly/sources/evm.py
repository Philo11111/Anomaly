"""M1 mints and M2 bridge / lending / deployer watches over free EVM websockets."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timezone

from loguru import logger

from anomaly.detect import (
    TRANSFER_TOPIC,
    decode_uint,
    evaluate_mint_logs,
    human_amount,
    is_zero_topic,
    pct_of,
    topic_address,
)
from anomaly.models import Event, Signal
from anomaly.sources.base import guard
from anomaly.timeutil import utcnow
from anomaly.wsclient import Resubscribe, run_websocket

ZERO_TOPIC = "0x" + "0" * 64


def _pad(address: str) -> str:
    return "0x" + address.lower().removeprefix("0x").rjust(64, "0")


def _chunks(items: list, size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


class EvmSource:
    def __init__(self, settings, http, state, registry, pipeline, stop: asyncio.Event) -> None:
        self.settings = settings
        self.http = http
        self.state = state
        self.registry = registry
        self.pipeline = pipeline
        self.stop = stop
        self.supply: dict[tuple[str, str], int] = {}
        self.vault_balance: dict[tuple[str, str], int] = {}
        self.vault_out: dict[tuple[str, str], int] = {}
        self.mint_window: dict[tuple[str, str], deque] = defaultdict(deque)
        self.mint_alerted: dict[tuple[str, str], float] = {}
        self._ids = 1

    async def run(self) -> None:
        names = [name for name in self.settings.chains if name != "solana" and self.settings.chains[name].ws]
        await asyncio.gather(
            *(
                guard(f"m1:{name}", lambda name=name: self._chain(name), self.state, self.stop)
                for name in names
            )
        )

    async def _chain(self, name: str) -> None:
        chain = self.settings.chains[name]
        while not self.stop.is_set():
            contracts = self.registry.contracts_on(name)
            signers = self.registry.signers_on(name)
            vaults = self.registry.vaults_on(name)
            version = self.registry.version
            if not contracts and not signers and not vaults:
                self.state.set_module(f"m1:{name}", "idle", "watchlist empty for this chain")
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=15)
                    return
                except asyncio.TimeoutError:
                    continue
            await self._prime(chain, contracts, vaults)
            self.state.set_module(
                f"m1:{name}",
                "running",
                f"{len(contracts)} contracts, {len(vaults)} vaults, {len(signers)} signers",
            )
            subscriptions = self._subscriptions(contracts, signers, vaults)

            async def on_message(message: dict, version=version, chain=chain) -> None:
                if self.registry.version != version:
                    raise Resubscribe()
                if message.get("method") != "eth_subscription":
                    return
                log = (message.get("params") or {}).get("result")
                if isinstance(log, dict):
                    await self._on_log(chain, log)

            await run_websocket(
                chain.ws,
                on_message,
                name=f"m1:{name}",
                subscribe=subscriptions,
                stop=self.stop,
            )

    def _next_id(self) -> int:
        self._ids += 1
        return self._ids

    def _subscriptions(self, contracts, signers, vaults) -> list[dict]:
        messages = []
        addresses = [item.address for item in contracts]
        for chunk in _chunks(addresses, 40):
            messages.append(
                {
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "eth_subscribe",
                    "params": ["logs", {"address": chunk, "topics": [TRANSFER_TOPIC, ZERO_TOPIC]}],
                }
            )
        for signer in signers:
            messages.append(
                {
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "eth_subscribe",
                    "params": ["logs", {"topics": [TRANSFER_TOPIC, _pad(signer.address)]}],
                }
            )
        for vault in vaults:
            filt: dict = {"topics": [TRANSFER_TOPIC, _pad(vault.address)]}
            if vault.token:
                filt["address"] = vault.token
            messages.append(
                {
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "eth_subscribe",
                    "params": ["logs", filt],
                }
            )
        return messages

    async def rpc(self, chain, method: str, params: list):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        payload = await self.http.post_json(chain.http, body, limiter="rpc")
        if not isinstance(payload, dict) or "result" not in payload:
            error = payload.get("error") if isinstance(payload, dict) else payload
            raise RuntimeError(f"{chain.name} {method}: {error}")
        return payload["result"]

    async def _prime(self, chain, contracts, vaults) -> None:
        for contract in contracts:
            key = (chain.name, contract.address)
            if key in self.supply:
                continue
            try:
                raw = await self.rpc(chain, "eth_call", [{"to": contract.address, "data": "0x18160ddd"}, "latest"])
                self.supply[key] = decode_uint(raw)
            except Exception as exc:
                logger.debug("supply prime {} {} failed: {}", chain.name, contract.ticker, exc)
        for vault in vaults:
            if not vault.token:
                continue
            key = (chain.name, vault.address)
            try:
                raw = await self.rpc(
                    chain,
                    "eth_call",
                    [
                        {
                            "to": vault.token,
                            "data": "0x70a08231" + vault.address.lower().removeprefix("0x").rjust(64, "0"),
                        },
                        "latest",
                    ],
                )
                self.vault_balance[key] = decode_uint(raw)
                self.vault_out.setdefault(key, 0)
            except Exception as exc:
                logger.debug("vault prime {} failed: {}", vault.label, exc)

    async def _on_log(self, chain, log: dict) -> None:
        topics = log.get("topics") or []
        if len(topics) < 3 or str(topics[0]).lower() != TRANSFER_TOPIC:
            return
        token = str(log.get("address", "")).lower()
        sender = topic_address(topics[1])
        recipient = topic_address(topics[2])
        amount = decode_uint(log.get("data"))
        if amount <= 0:
            return
        block = log.get("blockNumber")
        block_no = int(block, 16) if isinstance(block, str) else None
        tx = str(log.get("transactionHash") or "")
        moment = utcnow()
        if is_zero_topic(topics[1]):
            await self._mint(chain, token, amount, tx, recipient, block_no, moment, log)
            return
        vault = next((item for item in self.registry.vaults_on(chain.name) if item.address == sender), None)
        if vault is not None:
            await self._drain(chain, vault, token, amount, tx, moment)
            return
        signer = self.registry.signer(chain.name, sender)
        if signer is not None:
            await self._signer(chain, signer, token, amount, recipient, tx, moment)

    async def _mint(self, chain, token, amount, tx, recipient, block, moment, log) -> None:
        contract = self.registry.contract(chain.name, token)
        if contract is None:
            return
        key = (chain.name, token)
        supply = self.supply.get(key)
        if supply is None:
            try:
                raw = await self.rpc(chain, "eth_call", [{"to": token, "data": "0x18160ddd"}, "latest"])
                supply = decode_uint(raw)
            except Exception:
                supply = 0
        window = self.mint_window[key]
        horizon = self.settings.score.mint_window_seconds
        window.append((moment, amount, tx, supply))
        while window and (moment - window[0][0]).total_seconds() > horizon:
            window.popleft()
        supply_before = int(window[0][3] or 0)
        summed = sum(item[1] for item in window)
        if supply_before <= 0:
            self.supply[key] = (supply or 0) + amount
            return
        hit = evaluate_mint_logs(
            [
                {
                    "address": token,
                    "topics": [TRANSFER_TOPIC, ZERO_TOPIC, _pad(recipient)],
                    "data": hex(summed),
                    "transactionHash": tx,
                    "blockNumber": block,
                }
            ],
            contract=token,
            supply_before=supply_before or supply or 0,
            threshold_pct=self.settings.score.mint_supply_pct,
            block=block,
        )
        self.supply[key] = (supply or 0) + amount
        if not hit.fired:
            return
        previous = self.mint_alerted.get(key, 0.0)
        if previous and hit.pct < previous + 5:
            return
        self.mint_alerted[key] = hit.pct
        tx_from = await self._tx_from(chain, tx)
        signals = [Signal("mint", pct=hit.pct, detail=f"supply +{hit.pct:.1f}%")]
        minter = None
        watched = self.registry.signer(chain.name, tx_from) if tx_from else None
        if watched is not None:
            minter = tx_from
            signals.append(Signal("fresh_signer", detail=watched.label or "watched minter"))
        tokens = human_amount(hit.amount_raw, contract.decimals)
        await self.pipeline.handle(
            Event(
                type="mint",
                source=f"evm:{chain.name}",
                timestamp=moment,
                ticker=contract.ticker,
                name=contract.name,
                chain=chain.name,
                title=f"Mint {contract.ticker} on {chain.name}",
                summary=f"+{tokens:.4g} {contract.ticker}, supply +{hit.pct:.1f}%",
                signals=signals,
                links=self._links(chain, tx, minter or recipient),
                payload={
                    "amount_tokens": tokens,
                    "supply_pct": round(hit.pct, 4),
                    "window_seconds": horizon,
                    "minter": minter,
                    "tx": tx,
                    "block": block,
                    "recipient": recipient,
                    "risks": "міст може ще бути відкритий; можливі rollback / reduce-only",
                },
            )
        )

    async def _drain(self, chain, vault, token, amount, tx, moment) -> None:
        key = (chain.name, vault.address)
        balance = self.vault_balance.get(key) or 0
        if balance <= 0:
            return
        self.vault_out[key] = self.vault_out.get(key, 0) + amount
        pct = pct_of(self.vault_out[key], balance)
        if pct < self.settings.score.drain_pct:
            return
        contract = self.registry.contract(chain.name, token)
        decimals = contract.decimals if contract else 18
        await self.pipeline.handle(
            Event(
                type="drain",
                source=f"evm:{chain.name}",
                timestamp=moment,
                ticker=vault.ticker,
                name=self.registry.name_of(vault.ticker),
                chain=chain.name,
                title=f"Outflow {vault.ticker} {vault.label}",
                summary=f"{vault.label} outflow {pct:.1f}%",
                signals=[Signal("drain", pct=pct, detail=f"{vault.label} −{pct:.1f}%")],
                links=self._links(chain, tx, vault.address),
                payload={
                    "amount_tokens": human_amount(self.vault_out[key], decimals),
                    "supply_pct": round(pct, 4),
                    "risks": "резерв мосту/лендінгу швидко порожніє",
                },
            )
        )
        self.vault_out[key] = 0
        self.vault_balance[key] = max(0, balance - amount)

    async def _signer(self, chain, signer, token, amount, recipient, tx, moment) -> None:
        fresh = await self._is_fresh(chain, recipient)
        if not fresh:
            return
        contract = self.registry.contract(chain.name, token)
        ticker = contract.ticker if contract else signer.ticker
        decimals = contract.decimals if contract else 18
        await self.pipeline.handle(
            Event(
                type="signer",
                source=f"evm:{chain.name}",
                timestamp=moment,
                ticker=ticker,
                name=self.registry.name_of(ticker),
                chain=chain.name,
                title=f"{signer.role} transfer {ticker or signer.ticker}",
                summary=f"{signer.label or signer.role} → fresh wallet",
                signals=[Signal("fresh_signer", detail=signer.label or signer.role)],
                links=self._links(chain, tx, signer.address),
                payload={
                    "amount_tokens": human_amount(amount, decimals),
                    "minter": signer.address,
                    "recipient": recipient,
                    "risks": "ключ мінтера/деплоєра переказує на новий гаманець",
                },
            )
        )

    async def _tx_from(self, chain, tx: str) -> str | None:
        if not tx:
            return None
        try:
            raw = await self.rpc(chain, "eth_getTransactionByHash", [tx])
        except Exception:
            return None
        if isinstance(raw, dict) and raw.get("from"):
            return str(raw["from"]).lower()
        return None

    async def _is_fresh(self, chain, address: str) -> bool:
        try:
            raw = await self.rpc(chain, "eth_getTransactionCount", [address, "latest"])
        except Exception:
            return False
        nonce = int(raw, 16) if isinstance(raw, str) else 0
        return nonce <= self.settings.score.fresh_nonce_max

    def _links(self, chain, tx: str | None, address: str | None) -> dict:
        links = {}
        if tx and chain.explorer_tx:
            links["Tx"] = chain.explorer_tx.format(tx=tx)
        if address and chain.explorer_address:
            links["Address"] = chain.explorer_address.format(address=address)
        return links


def block_timestamp(raw_hex: str | int | None) -> datetime | None:
    if raw_hex is None:
        return None
    try:
        seconds = int(raw_hex, 16) if isinstance(raw_hex, str) else int(raw_hex)
        return datetime.fromtimestamp(seconds, timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
