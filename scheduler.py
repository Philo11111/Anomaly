import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from config import (
    RSS_CHECK_INTERVAL, TVL_CHECK_INTERVAL,
    ONCHAIN_CHECK_INTERVAL, ADMIN_CHAT_ID,
    TRACKED_WALLETS_ETH, TRACKED_WALLETS_SOL,
)
from parsers.rss_parser import scan_rss_feeds
from parsers.onchain_monitor import check_all_tracked_wallets
from analyzers.defillama import check_tvl_anomalies
from analyzers.ai_analyzer import analyze_event, analyze_tvl_drop, analyze_wallet_movement
from utils.formatter import format_news_alert, format_tvl_alert, format_wallet_alert
from bot.keyboards import alert_keyboard
from database.db import cleanup_old_alerts

_bot = None

def set_bot(bot):
    global _bot
    _bot = bot

async def _send_alert(text: str, link: str = ""):
    if not _bot:
        return
    try:
        await _bot.send_message(
            ADMIN_CHAT_ID, text,
            parse_mode="Markdown",
            reply_markup=alert_keyboard(link),
            disable_web_page_preview=False,
        )
    except Exception as e:
        logger.error(f"Send alert error: {e}")

async def job_rss():
    logger.info("Running RSS scan...")
    try:
        alerts = await scan_rss_feeds()
        logger.info(f"RSS: {len(alerts)} alerts")
        for article in alerts:
            ai_result = await analyze_event(
                article.get("full_text", article.get("title", "")),
                source=article.get("source", "RSS"),
                event_type="news"
            )
            if not ai_result:
                continue
            text = format_news_alert(article, ai_result)
            await _send_alert(text, link=article.get("link", ""))
            await asyncio.sleep(2)
    except Exception as e:
        logger.error(f"RSS job error: {e}")

async def job_tvl():
    logger.info("Running TVL check...")
    try:
        anomalies = await check_tvl_anomalies()
        for anomaly in anomalies:
            ai_result = await analyze_tvl_drop(
                anomaly["protocol"], anomaly["current_tvl"],
                anomaly["old_tvl"], anomaly["drop_pct"],
            )
            text = format_tvl_alert(anomaly, ai_result)
            await _send_alert(text)
            await asyncio.sleep(2)
    except Exception as e:
        logger.error(f"TVL job error: {e}")

async def job_onchain():
    """Перевірка відстежуваних гаманців хакерів."""
    total_wallets = len(TRACKED_WALLETS_ETH) + len(TRACKED_WALLETS_SOL)
    if total_wallets == 0:
        return
    try:
        alerts = await check_all_tracked_wallets()
        for alert in alerts:
            ai_result = await analyze_wallet_movement(alert)
            text = format_wallet_alert(alert, ai_result)
            await _send_alert(text, link=alert.get("link", ""))
            await asyncio.sleep(2)
    except Exception as e:
        logger.error(f"On-chain job error: {e}")

async def job_cleanup():
    await cleanup_old_alerts(days=7)
    logger.info("DB cleanup done")

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(job_rss, "interval", seconds=RSS_CHECK_INTERVAL, id="rss")
    scheduler.add_job(job_tvl, "interval", seconds=TVL_CHECK_INTERVAL, id="tvl")
    scheduler.add_job(job_onchain, "interval", seconds=ONCHAIN_CHECK_INTERVAL, id="onchain")
    scheduler.add_job(job_cleanup, "cron", hour=3, minute=0, id="cleanup")
    return scheduler
