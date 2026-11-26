"""Live check of the free endpoints the service depends on."""

from __future__ import annotations

import asyncio
import json

import aiohttp

from anomaly.wsclient import connect_websocket

_UA = {"User-Agent": "Mozilla/5.0 AnomalyMonitor/1.0", "Accept": "application/json"}


CHECKS = [
    ("GET", "defillama hacks", "https://api.llama.fi/hacks"),
    ("GET", "coingecko", "https://api.coingecko.com/api/v3/ping"),
    ("GET", "aster premium", "https://fapi.asterdex.com/fapi/v1/premiumIndex"),
    ("GET", "lighter books", "https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails"),
    ("GET", "lighter funding", "https://mainnet.zklighter.elliot.ai/api/v1/funding-rates"),
    ("GET", "variational", "https://omni-client-api.prod.ap-northeast-1.variational.io/metadata/v2/stats"),
    ("GET", "bingx premium", "https://open-api.bingx.com/openApi/swap/v2/quote/premiumIndex"),
    ("GET", "bybit tickers", "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"),
    ("GET", "bytick tickers", "https://api.bytick.com/v5/market/tickers?category=linear&symbol=BTCUSDT"),
    ("GET", "okx oi", "https://www.okx.com/api/v5/public/open-interest?instType=SWAP"),
    ("GET", "okx notices", "https://www.okx.com/api/v5/support/announcements"),
    ("GET", "binance premium", "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"),
    ("GET", "binance vision", "https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT"),
    ("GET", "upbit notices", "https://api-manager.upbit.com/api/v1/announcements?os=web&page=1&per_page=1"),
    ("GET", "bitget notices", "https://api.bitget.com/api/v2/public/annoucements?language=en_US"),
    ("GET", "bithumb notices", "https://api.bithumb.com/v1/notices?count=1"),
    ("GET", "gate currencies", "https://api.gateio.ws/api/v4/spot/currencies"),
    ("GET", "bingx notices", "https://bingx.com/api/customer/v1/announcement/list?pageId=0&pageSize=1"),
    ("GET", "mexc ticker", "https://contract.mexc.com/api/v1/contract/ticker?symbol=BTC_USDT"),
    ("GET", "rss cointelegraph", "https://cointelegraph.com/rss"),
    ("GET", "rss rekt", "https://rekt.news/feed/"),
]


async def _get(session, name, url) -> tuple[str, str, str]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
            body = await response.read()
            return name, str(response.status), body[:80].decode("utf-8", "replace").replace("\n", " ")
    except Exception as exc:
        return name, "ERR", str(exc)[:120]


async def _post_hl(session) -> tuple[str, str, str]:
    try:
        async with session.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "metaAndAssetCtxs"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            body = await response.read()
            return "hyperliquid info", str(response.status), body[:60].decode("utf-8", "replace")
    except Exception as exc:
        return "hyperliquid info", "ERR", str(exc)[:120]


async def _ws(url: str, payload: dict) -> tuple[str, str, str]:
    try:
        async with connect_websocket(url, open_timeout=10, close_timeout=2) as socket:
            await socket.send(json.dumps(payload))
            raw = await asyncio.wait_for(socket.recv(), timeout=10)
            return url, "OK", raw[:80].replace("\n", " ")
    except Exception as exc:
        return url, "ERR", str(exc)[:140]


async def run() -> int:
    failed = 0
    async with aiohttp.ClientSession(headers=_UA) as session:
        results = await asyncio.gather(*[_get(session, name, url) for _, name, url in CHECKS])
        results.append(await _post_hl(session))
    sockets = await asyncio.gather(
        _ws("wss://bsc-rpc.publicnode.com", {"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe", "params": ["newHeads"]}),
        _ws("wss://ethereum-rpc.publicnode.com", {"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe", "params": ["newHeads"]}),
        _ws("wss://base-rpc.publicnode.com", {"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe", "params": ["newHeads"]}),
        _ws("wss://arbitrum-one-rpc.publicnode.com", {"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe", "params": ["newHeads"]}),
        _ws("wss://api.hyperliquid.xyz/ws", {"method": "subscribe", "subscription": {"type": "allMids"}}),
        _ws("wss://api.mainnet-beta.solana.com", {"jsonrpc": "2.0", "id": 1, "method": "slotSubscribe"}),
    )
    print(f"{'status':<6} {'check'}")
    for name, status, detail in list(results) + list(sockets):
        ok = status in {"200", "OK"}
        if not ok:
            failed += 1
        print(f"{status:<6} {name}  {detail[:100]}")
    print(f"\n{failed} checks not OK")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
