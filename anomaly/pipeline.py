"""Score an event, keep it, and fan it out. A failed notifier cannot drop it."""

from __future__ import annotations

from loguru import logger

from anomaly.models import Event
from anomaly.registry import Registry
from anomaly.scoring import score_signals
from anomaly.settings import Settings
from anomaly.state import State


class Pipeline:
    def __init__(self, settings: Settings, state: State, registry: Registry, notifiers) -> None:
        self.settings = settings
        self.state = state
        self.registry = registry
        self.notifiers = notifiers

    async def handle(self, event: Event):
        if event.ticker:
            event.ticker = event.ticker.upper()
            for venue in self.settings.user_venues:
                template = (self.settings.venues.get(venue) or {}).get("trade")
                if template and venue not in event.links:
                    event.links[venue] = template.format(symbol=event.ticker)
        if not event.name and event.ticker:
            event.name = self.registry.name_of(event.ticker)
        oi = self.state.venue_oi_usd(event.ticker, self.settings.user_venues)
        venues = self.state.venue_snapshot(
            event.ticker,
            self.settings.user_venues + self.settings.reference_venues,
        )

        def score_fn(signals):
            return score_signals(
                signals,
                when=event.timestamp,
                settings=self.settings,
                ticker=event.ticker,
                venue_oi_usd=oi,
            )

        alert = await self.state.commit_event(event, score_fn, venues=venues)
        logger.log(
            "WARNING" if alert.level == "red" else "INFO" if alert.level == "yellow" else "DEBUG",
            "[{}] {} {}/100 {}\n{}",
            alert.level,
            alert.ticker or "—",
            alert.score,
            alert.type,
            alert.text,
        )
        for notifier in self.notifiers:
            if not notifier.accepts(alert):
                continue
            try:
                await notifier.send(alert)
            except Exception as exc:
                logger.error("notifier {} failed (alert kept): {}", notifier.name, exc)
        return alert
