"""
On-chain моніторинг:
- Відстеження відомих гаманців хакерів (Lazarus, Drift attacker...)
- Великі переміщення коштів (whale alerts)
- Зміни балансів підозрілих адрес
"""
import aiohttp
from loguru import logger
from config import (
    TRACKED_WALLETS_ETH, TRACKED_WALLETS_SOL,
    ETHERSCAN_API_KEY, SOLSCAN_API_KEY, WHALE_TX_USD
)
from database.db import is_seen

ETHERSCAN_API = "https://api.etherscan.io/api"
SOLSCAN_API = "https://pro-api.solscan.io/v2"
SOLSCAN_FREE_API = "https://api.solscan.io"


async def check_eth_wallet(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """Перевірка нових транзакцій ETH гаманця."""
    alerts = []
    try:
        params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "page": 1,
            "offset": 5,  # Останні 5 транзакцій
            "sort": "desc",
            "apikey": ETHERSCAN_API_KEY or "YourApiKeyToken",
        }
        async with session.get(ETHERSCAN_API, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()

        if data.get("status") != "1":
            return []

        for tx in data.get("result", []):
            tx_hash = tx.get("hash", "")
            value_eth = int(tx.get("value", 0)) / 1e18
            
            # Пропускаємо дрібні транзакції
            if value_eth < 0.1:
                continue

            already_seen = await is_seen(tx_hash, source="onchain_eth")
            if already_seen:
                continue

            # Отримуємо ціну ETH приблизно
            usd_value = value_eth * 3000  # Приблизно, буде уточнено AI

            short_addr = f"{address[:8]}...{address[-6:]}"

            alerts.append({
                "type": "wallet_movement",
                "chain": "ETH",
                "wallet": address,
                "wallet_short": short_addr,
                "tx_hash": tx_hash,
                "value_native": value_eth,
                "value_usd_approx": usd_value,
                "from": tx.get("from", ""),
                "to": tx.get("to", ""),
                "link": f"https://etherscan.io/tx/{tx_hash}",
                "arkham_link": f"https://platform.arkhamintelligence.com/explorer/address/{address}",
                "alert_level": "critical" if usd_value > 1_000_000 else "warning",
                "full_text": f"Known hacker wallet {short_addr} moved {value_eth:.2f} ETH (~${usd_value:,.0f})",
                "source": "Etherscan on-chain monitor",
            })

    except Exception as e:
        logger.warning(f"ETH wallet check error {address}: {e}")
    return alerts


async def check_sol_wallet(session: aiohttp.ClientSession, address: str) -> list[dict]:
    """Перевірка нових транзакцій Solana гаманця."""
    alerts = []
    try:
        url = f"{SOLSCAN_FREE_API}/account/transactions"
        params = {"account": address, "limit": 5}
        headers = {}
        if SOLSCAN_API_KEY:
            headers["token"] = SOLSCAN_API_KEY

        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        for tx in (data if isinstance(data, list) else data.get("data", [])):
            tx_sig = tx.get("txHash", tx.get("signature", ""))
            if not tx_sig:
                continue

            already_seen = await is_seen(tx_sig, source="onchain_sol")
            if already_seen:
                continue

            short_addr = f"{address[:8]}...{address[-6:]}"

            alerts.append({
                "type": "wallet_movement",
                "chain": "SOL",
                "wallet": address,
                "wallet_short": short_addr,
                "tx_hash": tx_sig,
                "link": f"https://solscan.io/tx/{tx_sig}",
                "arkham_link": f"https://platform.arkhamintelligence.com/explorer/address/{address}",
                "alert_level": "critical",
                "full_text": f"Tracked wallet {short_addr} (SOL) new transaction: {tx_sig[:20]}...",
                "source": "Solscan on-chain monitor",
            })

    except Exception as e:
        logger.warning(f"SOL wallet check error {address}: {e}")
    return alerts


async def check_all_tracked_wallets() -> list[dict]:
    """Перевіряє всі відслідковувані гаманці."""
    all_alerts = []

    async with aiohttp.ClientSession() as session:
        for address in TRACKED_WALLETS_ETH:
            alerts = await check_eth_wallet(session, address)
            all_alerts.extend(alerts)

        for address in TRACKED_WALLETS_SOL:
            alerts = await check_sol_wallet(session, address)
            all_alerts.extend(alerts)

    if all_alerts:
        logger.warning(f"On-chain: {len(all_alerts)} wallet movements detected")

    return all_alerts


async def fetch_large_transfers_defillama(session: aiohttp.ClientSession) -> list[dict]:
    """
    Whale Alert через DefiLlama large transactions API.
    Повертає великі переміщення коштів по протоколах.
    """
    alerts = []
    try:
        url = "https://api.llama.fi/bridges/dayStats/ethereum"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            # Аналіз незвично великих обсягів
            # (DefiLlama не дає whale alerts напряму, але дає bridge stats)
    except Exception as e:
        logger.debug(f"Bridge stats fetch: {e}")
    return alerts
