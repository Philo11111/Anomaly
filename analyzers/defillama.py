import aiohttp
from loguru import logger
from config import TVL_DROP_THRESHOLD, TRACKED_PROTOCOLS
from database.db import save_tvl, get_tvl_hour_ago

DEFILLAMA_API = "https://api.llama.fi"

async def fetch_protocol_tvl(session: aiohttp.ClientSession, protocol: str) -> float | None:
    """Отримати поточний TVL протоколу."""
    try:
        url = f"{DEFILLAMA_API}/protocol/{protocol}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            # currentChainTvls або tvl[-1]
            tvl = data.get("currentChainTvls", {})
            if tvl:
                return sum(tvl.values())
            tvl_list = data.get("tvl", [])
            if tvl_list:
                return tvl_list[-1].get("totalLiquidityUSD", 0)
            return None
    except Exception as e:
        logger.warning(f"DefiLlama fetch error for {protocol}: {e}")
        return None

async def check_tvl_anomalies() -> list[dict]:
    """
    Перевіряє всі протоколи на аномальне падіння TVL.
    Повертає список аномалій.
    """
    anomalies = []
    
    async with aiohttp.ClientSession() as session:
        for protocol in TRACKED_PROTOCOLS:
            current_tvl = await fetch_protocol_tvl(session, protocol)
            if current_tvl is None:
                continue
            
            # Зберігаємо поточний snapshot
            await save_tvl(protocol, current_tvl)
            
            # Порівнюємо з годиною тому
            old_tvl = await get_tvl_hour_ago(protocol)
            if old_tvl is None or old_tvl == 0:
                continue
            
            drop_pct = ((old_tvl - current_tvl) / old_tvl) * 100
            
            if drop_pct >= TVL_DROP_THRESHOLD:
                logger.warning(
                    f"TVL anomaly: {protocol} dropped {drop_pct:.1f}% "
                    f"(${old_tvl/1e6:.1f}M → ${current_tvl/1e6:.1f}M)"
                )
                anomalies.append({
                    "protocol": protocol,
                    "current_tvl": current_tvl,
                    "old_tvl": old_tvl,
                    "drop_pct": drop_pct,
                })
    
    return anomalies
