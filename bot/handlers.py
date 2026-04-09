from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from loguru import logger

from bot.keyboards import main_keyboard, alert_keyboard
from config import TRACKED_ASSETS, TRACKED_PROTOCOLS, RSS_FEEDS, TELEGRAM_CHANNELS
from utils.formatter import format_status

router = Router()

WELCOME_TEXT = """🤖 *AnomalityParcer* — твій крипто-сторожовий пес

Я слідкую за:
• 📰 Новинними RSS джерелами (rekt.news, CoinTelegraph, etc.)
• 📡 Telegram каналами безпеки (@peckshieldalert, @zachxbt...)
• 📊 Цінами через Binance WebSocket
• 📉 TVL протоколів через DefiLlama

Коли знаходжу аномалію — аналізую через AI та надсилаю тобі сигнал з рекомендаціями.

*Команди:*
/status — поточний стан моніторингу
/watchlist — що відстежую
/help — допомога

*Корисні ресурси для спредів:*
• [Coinglass](https://coinglass.com) — funding rates, OI
• [Velo](https://velo.xyz) — спреди DEX/CEX  
• [Laevitas](https://laevitas.ch) — basis, options
• [DefiLlama](https://defillama.com) — TVL"""

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        WELCOME_TEXT,
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
        disable_web_page_preview=True,
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    text = """📖 *Довідка AnomalityParcer*

*Що я моніторю:*
• RSS: CoinTelegraph, Decrypt, TheBlock, Rekt News...
• Telegram: PeckShield, ZachXBT, CertiK, SlowMist...
• Ціни: Binance WebSocket (5хв аномалії ±{pct}%)
• TVL: DefiLlama (падіння >10% за годину)

*Як працює AI аналіз:*
1. Знаходжу підозрілу новину/рух
2. Відправляю Claude AI для аналізу
3. AI оцінює від 1 до 10 по важливості
4. Якщо score ≥ 6 → надсилаю тобі сигнал

*Формат алерту:*
🚨 Рівень критичності
📋 Стислий опис події
⚡ Рекомендовані дії
🎯 Впевненість AI"""
    
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("status"))
async def cmd_status(message: Message):
    stats = {
        "rss_feeds": len(RSS_FEEDS),
        "tg_channels": len(TELEGRAM_CHANNELS),
        "assets": len(TRACKED_ASSETS),
        "protocols": len(TRACKED_PROTOCOLS),
        "alerts_24h": 0,
        "critical_24h": 0,
        "high_score_24h": 0,
    }
    text = format_status(is_running=True, stats=stats)
    await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard())

@router.message(Command("watchlist"))
async def cmd_watchlist(message: Message):
    assets_text = "\n".join([f"  • `{a}`" for a in TRACKED_ASSETS])
    protocols_text = "\n".join([f"  • `{p}`" for p in TRACKED_PROTOCOLS])
    channels_text = "\n".join([f"  • {c}" for c in TELEGRAM_CHANNELS])
    
    text = f"""📋 *Watchlist*

💰 *Активи (Binance WS):*
{assets_text}

🏦 *DeFi протоколи (DefiLlama):*
{protocols_text}

📡 *Telegram канали:*
{channels_text}"""
    
    await message.answer(text, parse_mode="Markdown")

@router.callback_query(F.data == "status")
async def cb_status(callback: CallbackQuery):
    await cmd_status(callback.message)
    await callback.answer()

@router.callback_query(F.data == "watchlist")
async def cb_watchlist(callback: CallbackQuery):
    await cmd_watchlist(callback.message)
    await callback.answer()

@router.callback_query(F.data == "ack")
async def cb_ack(callback: CallbackQuery):
    await callback.answer("✅ Прийнято до уваги")

@router.callback_query(F.data == "false_alarm")
async def cb_false_alarm(callback: CallbackQuery):
    await callback.answer("❌ Позначено як хибна тривога")
    logger.info(f"False alarm marked by {callback.from_user.id}")
