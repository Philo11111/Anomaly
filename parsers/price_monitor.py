"""
Binance WebSocket моніторинг цін.
Відстежує різкі рухи і аномальні обсяги.
"""
import asyncio
import json
import websockets
from loguru import logger
from config import TRACKED_ASSETS, PRICE_CHANGE_THRESHOLD
from database.db import save_price, get_price_minutes_ago

# Поточні ціни в пам'яті
_current_prices: dict[str, float] = {}
_current_volumes: dict[str, float] = {}

async def price_stream(callback):
    """
    Підключається до Binance WebSocket mini-ticker stream.
    callback(anomaly_dict) — викликається при виявленні аномалії.
    """
    symbols = [s.lower() for s in TRACKED_ASSETS]
    streams = "/".join([f"{s}@miniTicker" for s in symbols])
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"
    
    while True:
        try:
            logger.info("Connecting to Binance WebSocket...")
            async with websockets.connect(url, ping_interval=20) as ws:
                logger.info("Binance WebSocket connected")
                
                async for raw in ws:
                    try:
                        outer = json.loads(raw)
                        data = outer.get("data", outer)
                        
                        symbol = data.get("s", "")    # Symbol
                        price = float(data.get("c", 0))  # Close price
                        volume = float(data.get("v", 0))  # Volume
                        
                        if not symbol or price == 0:
                            continue
                        
                        # Зберігаємо в БД кожні ~30 секунд (дедупліковано)
                        old = _current_prices.get(symbol, 0)
                        if old == 0 or abs(price - old) / old > 0.001:
                            await save_price(symbol, price, volume)
                        
                        _current_prices[symbol] = price
                        _current_volumes[symbol] = volume
                        
                        # Перевіряємо аномалію
                        anomaly = await _check_price_anomaly(symbol, price, volume)
                        if anomaly:
                            await callback(anomaly)
                            
                    except Exception as e:
                        logger.warning(f"WS message parse error: {e}")
                        
        except websockets.ConnectionClosed:
            logger.warning("Binance WS disconnected, reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Binance WS error: {e}, reconnecting in 10s...")
            await asyncio.sleep(10)

async def _check_price_anomaly(symbol: str, price: float, volume: float) -> dict | None:
    """Перевірка цінової аномалії."""
    old_price = await get_price_minutes_ago(symbol, minutes=5)
    if not old_price or old_price == 0:
        return None
    
    change_pct = ((price - old_price) / old_price) * 100
    
    if abs(change_pct) >= PRICE_CHANGE_THRESHOLD:
        direction = "📈 PUMP" if change_pct > 0 else "📉 DUMP"
        logger.warning(
            f"[PRICE ANOMALY] {symbol}: {change_pct:+.2f}% in 5min "
            f"({old_price:.4f} → {price:.4f})"
        )
        return {
            "type": "price_anomaly",
            "symbol": symbol,
            "current_price": price,
            "old_price": old_price,
            "change_pct": change_pct,
            "direction": direction,
            "volume": volume,
            "alert_level": "critical" if abs(change_pct) >= 10 else "warning",
        }
    
    return None

def get_current_price(symbol: str) -> float | None:
    return _current_prices.get(symbol)
