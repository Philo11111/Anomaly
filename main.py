"""
AnomalityParcer — Telegram бот для моніторингу крипто-аномалій.
"""
import asyncio
from loguru import logger
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, ADMIN_CHAT_ID, PRICE_CHANGE_THRESHOLD
from bot.handlers import router
from database.db import init_db
from scheduler import create_scheduler, set_bot
from parsers.price_monitor import price_stream
from parsers.telegram_parser import start_realtime_listener
from analyzers.ai_analyzer import analyze_price_anomaly, analyze_event
from utils.formatter import format_price_alert, format_news_alert
from bot.keyboards import alert_keyboard

# === Логування ===
logger.add(
    "logs/anomalityparcer.log",
    rotation="10 MB",
    retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
)
dp = Dispatcher()

async def send_alert(text: str, link: str = ""):
    """Централізована функція відправки алерту."""
    try:
        await bot.send_message(
            ADMIN_CHAT_ID,
            text,
            parse_mode="Markdown",
            reply_markup=alert_keyboard(link),
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"send_alert error: {e}")

# === Callback для price monitor ===
async def on_price_anomaly(anomaly: dict):
    symbol = anomaly["symbol"]
    change = anomaly["change_pct"]
    
    ai_result = await analyze_price_anomaly(
        symbol=symbol,
        current_price=anomaly["current_price"],
        old_price=anomaly["old_price"],
        change_pct=change,
    )
    
    text = format_price_alert(anomaly, ai_result)
    await send_alert(text)

# === Callback для Telegram realtime listener ===
async def on_telegram_message(alert: dict):
    from analyzers.ai_analyzer import analyze_event
    from utils.formatter import format_news_alert
    
    ai_result = await analyze_event(
        alert.get("full_text", ""),
        source=alert.get("source", "Telegram"),
        event_type="news"
    )
    
    if not ai_result:
        return
    
    text = format_news_alert(alert, ai_result)
    await send_alert(text, link=alert.get("link", ""))

async def on_startup():
    """Дії при старті."""
    logger.info("AnomalityParcer starting...")
    
    # Ініціалізація БД
    import os
    os.makedirs("logs", exist_ok=True)
    await init_db()
    
    # Повідомлення адміну
    await bot.send_message(
        ADMIN_CHAT_ID,
        "🟢 *AnomalityParcer запущено*\n\n"
        f"Моніторинг активний. Поріг аномалії: ±{PRICE_CHANGE_THRESHOLD}%\n"
        "Використай /status для деталей.",
    )
    logger.info("Startup complete")

async def main():
    dp.include_router(router)
    dp.startup.register(on_startup)
    
    # Планувальник
    set_bot(bot)
    scheduler = create_scheduler()
    scheduler.start()
    
    # Фонові задачі
    tasks = [
        asyncio.create_task(dp.start_polling(bot, drop_pending_updates=True)),
        asyncio.create_task(price_stream(on_price_anomaly)),
    ]
    
    # Telegram realtime (якщо Telethon налаштований)
    from config import TELEGRAM_API_ID
    if TELEGRAM_API_ID:
        tasks.append(
            asyncio.create_task(start_realtime_listener(on_telegram_message))
        )
    
    logger.info(f"Running {len(tasks)} async tasks")
    
    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.shutdown()
        await bot.send_message(ADMIN_CHAT_ID, "🔴 AnomalityParcer зупинено")
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
