"""Token → contracts → venues. Seeded from YAML, refreshed from CoinGecko."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from loguru import logger

from anomaly.httpclient import HttpClient
from anomaly.settings import Settings, interval
from anomaly.state import State
from anomaly.symbols import base_symbol

_PLATFORM = {
    "ethereum": "ethereum",
    "binance-smart-chain": "bsc",
    "base": "base",
    "arbitrum-one": "arbitrum",
    "polygon-pos": "polygon",
    "solana": "solana",
}


@dataclass
class Contract:
    chain: str
    address: str
    decimals: int = 18
    ticker: str = ""
    name: str = ""


@dataclass
class WatchAddress:
    chain: str
    address: str
    ticker: str
    role: str
    label: str = ""
    token: str = ""


@dataclass
class Registry:
    settings: Settings
    http: HttpClient
    state: State
    contracts: list[Contract] = field(default_factory=list)
    addresses: list[WatchAddress] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    version: int = 0
    _by_chain: dict[str, dict[str, Contract]] = field(default_factory=dict)

    def load_seed(self) -> None:
        self.contracts.clear()
        self.addresses.clear()
        self.names.clear()
        for token in self.settings.watchlist.get("tokens") or []:
            ticker = str(token.get("ticker") or "").upper()
            if not ticker:
                continue
            self.names[ticker] = token.get("name") or ticker
            for item in token.get("contracts") or []:
                self.add_contract(
                    Contract(
                        chain=str(item["chain"]),
                        address=str(item["address"]).lower(),
                        decimals=int(item.get("decimals") or 18),
                        ticker=ticker,
                        name=self.names[ticker],
                    )
                )
            for item in token.get("bridges") or []:
                self.addresses.append(
                    WatchAddress(
                        chain=str(item["chain"]),
                        address=str(item["address"]).lower(),
                        ticker=ticker,
                        role="bridge",
                        label=item.get("label") or "bridge",
                        token=str(item.get("token") or "").lower(),
                    )
                )
            for item in token.get("signers") or []:
                self.addresses.append(
                    WatchAddress(
                        chain=str(item.get("chain") or ""),
                        address=str(item["address"]).lower(),
                        ticker=ticker,
                        role=str(item.get("role") or "minter"),
                        label=item.get("label") or "",
                    )
                )
        self.version += 1
        self.state.set_module("registry", "running", f"{len(self.contracts)} contracts")

    def add_contract(self, contract: Contract) -> None:
        book = self._by_chain.setdefault(contract.chain, {})
        key = contract.address.lower()
        contract.address = key
        if key in book:
            return
        book[key] = contract
        self.contracts.append(contract)
        if contract.ticker and contract.name:
            self.names.setdefault(contract.ticker, contract.name)

    def add_signer(self, item: WatchAddress) -> None:
        item.address = item.address.lower()
        for current in self.addresses:
            if current.chain == item.chain and current.address == item.address and current.role == item.role:
                return
        self.addresses.append(item)
        self.version += 1

    def known_tickers(self) -> set[str]:
        return set(self.names) | {contract.ticker for contract in self.contracts if contract.ticker}

    def contract(self, chain: str, address: str) -> Contract | None:
        return self._by_chain.get(chain, {}).get(address.lower())

    def contracts_on(self, chain: str) -> list[Contract]:
        return list(self._by_chain.get(chain, {}).values())

    def vaults_on(self, chain: str) -> list[WatchAddress]:
        return [item for item in self.addresses if item.chain == chain and item.role == "bridge"]

    def signers_on(self, chain: str) -> list[WatchAddress]:
        return [item for item in self.addresses if item.chain == chain and item.role in {"minter", "deployer"}]

    def signer(self, chain: str, address: str) -> WatchAddress | None:
        target = address.lower()
        for item in self.signers_on(chain):
            if item.address == target:
                return item
        return None

    def solana_mints(self) -> list[Contract]:
        return self.contracts_on("solana")

    def name_of(self, ticker: str | None) -> str | None:
        if not ticker:
            return None
        return self.names.get(ticker.upper())

    async def refresh_coingecko(self) -> None:
        tokens = [
            token for token in (self.settings.watchlist.get("tokens") or []) if token.get("coingecko_id")
        ]
        added = 0
        for token in tokens:
            ticker = str(token.get("ticker") or "").upper()
            coin_id = token["coingecko_id"]
            url = (
                "https://api.coingecko.com/api/v3/coins/"
                f"{coin_id}?localization=false&tickers=false&market_data=false"
                "&community_data=false&developer_data=false&sparkline=false"
            )
            await asyncio.sleep(12)
            try:
                payload = await self.http.get_json(url, limiter="coingecko")
            except Exception as exc:
                logger.warning("coingecko {} failed: {}", coin_id, exc)
                self.state.set_module("registry", "degraded", f"coingecko {coin_id}: {exc}")
                continue
            platforms = (payload or {}).get("platforms") or {}
            for platform, address in platforms.items():
                chain = _PLATFORM.get(platform)
                if not chain or not address:
                    continue
                if chain == "solana":
                    normalized = str(address)
                else:
                    normalized = str(address).lower()
                before = len(self.contracts)
                self.add_contract(
                    Contract(
                        chain=chain,
                        address=normalized,
                        decimals=int(token.get("decimals") or (9 if chain == "solana" else 18)),
                        ticker=ticker,
                        name=token.get("name") or ticker,
                    )
                )
                if len(self.contracts) != before:
                    added += 1
        self.version += 1
        self.state.set_module(
            "registry",
            "running",
            f"{len(self.contracts)} contracts, +{added} from CoinGecko",
        )

    async def run(self, stop: asyncio.Event) -> None:
        self.load_seed()
        while not stop.is_set():
            try:
                await self.refresh_coingecko()
            except Exception as exc:
                logger.warning("registry refresh failed: {}", exc)
                self.state.set_module("registry", "degraded", str(exc))
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval(self.settings, "registry", 6 * 3600))
            except asyncio.TimeoutError:
                continue

    def listed_bases(self) -> set[str]:
        found = set()
        for book in self.state.markets.values():
            for row in book.values():
                if row.base:
                    found.add(row.base)
        return found

    def match_symbol(self, raw: str) -> str:
        base = base_symbol(raw)
        if base in self.known_tickers():
            return base
        return base
