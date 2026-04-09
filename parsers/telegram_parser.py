"""
Telethon парсер Telegram каналів.

Як це працює:
- Telethon логіниться як звичайний Telegram юзер (не бот)
- При першому запуску питає SMS код — більше ніколи
- Сесія зберігається в рядок (STRING SESSION) і кладеться в Railway Variables
- Телефон після цього не потрібен взагалі

Як отримати STRING SESSION (один раз, локально):
  pip install telethon
  python tools/create_session.py
  Скопіюй рядок що видасть → вставив в TELEGRAM_SESSION в Railway Variables
"""
import asyncio
from loguru import logger
from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH,
    TELEGRAM_SESSION, TELEGRAM_CHANNELS
)
from analyzers.keyword_filter import check_keywords
from database.db import is_seen

_client = None

async def get_client():
    global _client
    if _client is not None and _client.is_connected():
        return _client
    if not TELEGRAM_API_ID or not TELEGRAM_SESSION:
        return None
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        _client = TelegramClient(
            StringSession(TELEGRAM_SESSION),
            TELEGRAM_API_ID,
            TELEGRAM_API_HASH
        )
        await _client.start()
        me = await _client.get_me()
        logger.info(f"Telethon connected as: {me.first_name} (@{me.username})")
        return _client
    except Exception as e:
        logger.error(f"Telethon init error: {e}")
        return None

async def scan_telegram_channels(limit: int = 15) -> list[dict]:
    alerts = []
    if not TELEGRAM_API_ID or not TELEGRAM_SESSION:
        logger.debug("Telethon not configured, skipping")
        return []
    try:
        client = await get_client()
        if not client:
            return []
        for channel in TELEGRAM_CHANNELS:
            try:
                entity = await client.get_entity(channel)
                messages = await client.get_messages(entity, limit=limit)
                for msg in messages:
                    if not msg.text:
                        continue
                    level, keywords = check_keywords(msg.text)
                    if level == "none":
                        continue
                    msg_id = f"{channel}_{msg.id}"
                    if await is_seen(msg_id, source="telegram"):
                        continue
                    alerts.append({
                        "title": msg.text[:100],
                        "full_text": msg.text,
                        "link": f"https://t.me/{channel.lstrip('@')}/{msg.id}",
                        "source": f"Telegram {channel}",
                        "published": str(msg.date),
                        "alert_level": level,
                        "keywords": keywords,
                    })
                    logger.info(f"[TG:{level.upper()}] {channel}: {msg.text[:60]}")
            except Exception as e:
                logger.warning(f"Error reading {channel}: {e}")
    except Exception as e:
        logger.error(f"Telegram scan error: {e}")
    return alerts

async def start_realtime_listener(callback):
    """Realtime слухач — реагує миттєво на нові повідомлення."""
    if not TELEGRAM_API_ID or not TELEGRAM_SESSION:
        return
    try:
        from telethon import events
        client = await get_client()
        if not client:
            return
        channel_entities = []
        for channel in TELEGRAM_CHANNELS:
            try:
                entity = await client.get_entity(channel)
                channel_entities.append(entity)
            except Exception as e:
                logger.warning(f"Can't resolve {channel}: {e}")

        @client.on(events.NewMessage(chats=channel_entities))
        async def handler(event):
            msg = event.message
            if not msg.text:
                return
            level, keywords = check_keywords(msg.text)
            if level == "none":
                return
            channel_name = getattr(event.chat, 'username', 'unknown')
            alert = {
                "title": msg.text[:100],
                "full_text": msg.text,
                "link": f"https://t.me/{channel_name}/{msg.id}",
                "source": f"Telegram @{channel_name}",
                "published": str(msg.date),
                "alert_level": level,
                "keywords": keywords,
            }
            logger.warning(f"[REALTIME:{level.upper()}] @{channel_name}: {msg.text[:80]}")
            await callback(alert)

        logger.info(f"Realtime listener active on {len(channel_entities)} channels")
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"Realtime listener error: {e}")
