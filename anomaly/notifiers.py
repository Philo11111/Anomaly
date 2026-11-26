"""Delivery sinks. Telegram is optional and never required for an alert to exist."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from anomaly.models import Alert

_RANK = {"info": 0, "yellow": 1, "red": 2}


def _at_least(level: str, minimum: str) -> bool:
    return _RANK.get(level, 0) >= _RANK.get(minimum, 0)


class ConsoleNotifier:
    name = "console"

    def accepts(self, alert: Alert) -> bool:
        return True

    async def send(self, alert: Alert) -> None:
        # Yellow is silent: it is logged, not pushed anywhere else by this sink.
        print(alert.text, flush=True)


class JsonNotifier:
    """Append-only JSONL sink. This is the durable local delivery path."""

    name = "json"

    def __init__(self, path: Path, min_level: str = "info") -> None:
        self.path = path
        self.min_level = min_level
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def accepts(self, alert: Alert) -> bool:
        return _at_least(alert.level, self.min_level)

    async def send(self, alert: Alert) -> None:
        line = json.dumps(alert.as_dict(), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class WebhookNotifier:
    name = "webhook"

    def __init__(self, http, url: str, min_level: str = "red") -> None:
        self.http = http
        self.url = url
        self.min_level = min_level

    def accepts(self, alert: Alert) -> bool:
        return bool(self.url) and alert.notify and _at_least(alert.level, self.min_level)

    async def send(self, alert: Alert) -> None:
        await self.http.post_json(self.url, alert.as_dict(), limiter="default")


class TelegramBotNotifier:
    """Bot API delivery. Disabled until TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""

    name = "telegram-bot"

    def __init__(self, http, token: str, chat_id: str) -> None:
        self.http = http
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def accepts(self, alert: Alert) -> bool:
        return self.enabled and alert.notify and alert.level == "red"

    async def send(self, alert: Alert) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": alert.text[:4000],
            "disable_web_page_preview": True,
        }
        await self.http.post_json(url, payload, limiter="default")
        logger.info("telegram bot delivered {}", alert.id)


def build_notifiers(settings, http) -> list:
    notifiers = [
        ConsoleNotifier(),
        JsonNotifier(settings.data_dir / "alerts.jsonl"),
    ]
    if settings.webhook_url:
        notifiers.append(
            WebhookNotifier(http, settings.webhook_url, settings.webhook_min_level)
        )
        logger.info("webhook sink enabled")
    else:
        logger.info("webhook sink off (set WEBHOOK_URL). JSONL is still written")
    bot = TelegramBotNotifier(http, settings.telegram_bot_token, settings.telegram_chat_id)
    if bot.enabled:
        notifiers.append(bot)
        logger.info("telegram bot notifier enabled")
    else:
        logger.info("telegram bot notifier disabled until TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set")
    return notifiers
