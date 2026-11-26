"""M6 Telegram listener. Off until a Telethon string session is configured.

Plug-in rules, from the product spec:
- one session, one process
- events.NewMessage only (no get_messages polling loops)
- resolve usernames once at start and cache the entities
- never call get_entity in a loop (about 200 username resolves per day)
- catch_up=True so a short disconnect does not skip messages
Telegram data must not be sent to an LLM. This source only keyword-scores.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from anomaly.classify import news_is_incident
from anomaly.models import Event, Signal
from anomaly.symbols import find_tickers
from anomaly.timeutil import utcnow


class TelegramSource:
    def __init__(self, settings, http, state, registry, pipeline, stop: asyncio.Event) -> None:
        self.settings = settings
        self.state = state
        self.registry = registry
        self.pipeline = pipeline
        self.stop = stop

    def enabled(self) -> bool:
        return bool(
            self.settings.telegram_api_id
            and self.settings.telegram_api_hash
            and self.settings.telegram_session
            and self.settings.telegram_channels
        )

    async def run(self) -> None:
        if not self.enabled():
            self.state.set_module(
                "m6:telegram",
                "disabled",
                "set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION to enable",
            )
            await self.stop.wait()
            return
        try:
            from telethon import TelegramClient, events
            from telethon.sessions import StringSession
        except ImportError:
            self.state.set_module("m6:telegram", "disabled", "install telethon to enable the listener")
            await self.stop.wait()
            return
        client = TelegramClient(
            StringSession(self.settings.telegram_session),
            self.settings.telegram_api_id,
            self.settings.telegram_api_hash,
        )
        await client.connect()
        if not await client.is_user_authorized():
            self.state.set_module("m6:telegram", "degraded", "session is not authorized")
            await client.disconnect()
            await self.stop.wait()
            return
        entities = []
        for channel in self.settings.telegram_channels:
            try:
                entities.append(await client.get_entity(channel))
            except Exception as exc:
                logger.warning("telegram resolve {} once failed: {}", channel, exc)
        self.state.set_module("m6:telegram", "running", f"{len(entities)} channels")

        @client.on(events.NewMessage(chats=entities))
        async def on_message(event):
            text = event.raw_text or ""
            if not news_is_incident(text, self.settings):
                return
            username = getattr(event.chat, "username", None) or "channel"
            link = f"https://t.me/{username}/{event.id}" if username else ""
            key = f"tg:{username}:{event.id}"
            if await self.state.seen(key, "telegram"):
                return
            trusted = username.lower() in {item.lower().lstrip("@") for item in self.settings.trusted_sources}
            signals = [Signal("trusted_source", detail=f"@{username}")] if trusted else []
            tickers = find_tickers(text, self.registry.known_tickers()) or [None]
            for ticker in tickers[:3]:
                await self.pipeline.handle(
                    Event(
                        type="news",
                        source="telegram",
                        timestamp=utcnow(),
                        ticker=ticker,
                        name=self.registry.name_of(ticker) if ticker else None,
                        title=text[:120],
                        summary=text[:400],
                        signals=signals,
                        links={"Telegram": link} if link else {},
                        payload={"dedup": key},
                    )
                )

        if hasattr(client, "catch_up"):
            try:
                await client.catch_up()
            except Exception as exc:
                logger.warning("telegram catch_up: {}", exc)
        task = asyncio.create_task(client.run_until_disconnected())
        await self.stop.wait()
        await client.disconnect()
        task.cancel()
