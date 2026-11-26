"""In-memory service state plus SQLite so restarts do not replay old notices."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from anomaly.format import format_alert
from anomaly.models import Alert, Component, Event, MarketRow, Score, Signal
from anomaly.scoring import stronger_type
from anomaly.timeutil import utcnow


class State:
    def __init__(self, db_path: Path, dedup_hours: float = 2.0) -> None:
        self.db_path = db_path
        self.dedup_hours = dedup_hours
        self.db: aiosqlite.Connection | None = None
        self.alerts: dict[str, Alert] = {}
        self.order: list[str] = []
        self.markets: dict[str, dict[str, MarketRow]] = {}
        self.funding_ref: dict[str, dict[str, float]] = {}
        self.modules: dict[str, dict] = {}
        self.liquidations: list[dict] = []
        self._lock = asyncio.Lock()
        self._subscribers: list[asyncio.Queue] = []

    async def open(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.db_path)
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                hash TEXT PRIMARY KEY,
                source TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.db.commit()
        await self._load_alerts()

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
            self.db = None

    async def _load_alerts(self) -> None:
        assert self.db is not None
        cutoff = (utcnow() - timedelta(days=7)).isoformat()
        cursor = await self.db.execute(
            "SELECT payload FROM alerts WHERE updated_at >= ? ORDER BY updated_at",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        for (payload,) in rows:
            alert = _alert_from_json(json.loads(payload))
            self.alerts[alert.id] = alert
            self.order.append(alert.id)

    def set_module(self, name: str, status: str, detail: str = "") -> None:
        self.modules[name] = {
            "name": name,
            "status": status,
            "detail": detail[:300],
            "updated_at": utcnow().isoformat(),
        }
        self.publish({"event": "status", "data": self.modules[name]})

    def upsert_markets(self, venue: str, rows: list[MarketRow]) -> None:
        book = self.markets.setdefault(venue, {})
        for row in rows:
            book[row.symbol] = row
        self.set_module(f"m8:{venue}", "running", f"{len(book)} markets")

    def venue_oi_usd(self, ticker: str | None, venues: list[str]) -> float | None:
        if not ticker:
            return None
        best = None
        for venue in venues:
            for row in self.markets.get(venue, {}).values():
                if row.base == ticker.upper() and row.oi_usd is not None:
                    best = row.oi_usd if best is None else max(best, row.oi_usd)
        return best

    def venue_snapshot(self, ticker: str | None, venues: list[str]) -> list[dict]:
        if not ticker:
            return []
        found = []
        for venue in venues:
            for row in self.markets.get(venue, {}).values():
                if row.base == ticker.upper():
                    item = row.as_dict()
                    if item.get("funding") is None:
                        ref = self.funding_ref.get(venue, {}).get(row.base)
                        if ref is not None:
                            item["funding"] = ref
                            item["funding_via"] = "lighter"
                    found.append(item)
                    break
        return found

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def publish(self, message: dict) -> None:
        stale = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self.unsubscribe(queue)

    async def seen(self, key: str, source: str) -> bool:
        assert self.db is not None
        cursor = await self.db.execute("SELECT 1 FROM seen WHERE hash = ?", (key,))
        row = await cursor.fetchone()
        if row:
            return True
        await self.db.execute(
            "INSERT OR IGNORE INTO seen (hash, source, created_at) VALUES (?, ?, ?)",
            (key, source, utcnow().isoformat()),
        )
        await self.db.commit()
        return False

    async def mark_seen(self, key: str, source: str) -> None:
        await self.seen(key, source)

    def _open_alert(self, event: Event, now: datetime) -> Alert | None:
        window = timedelta(hours=self.dedup_hours)
        if event.ticker:
            candidates = [
                alert
                for alert in self.alerts.values()
                if alert.ticker
                and alert.ticker.upper() == event.ticker.upper()
                and now - alert.updated_at <= window
            ]
        else:
            ident = event.dedup_id()
            candidates = [
                alert
                for alert in self.alerts.values()
                if not alert.ticker
                and alert.payload.get("dedup_id") == ident
                and now - alert.updated_at <= window
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda alert: alert.updated_at)

    async def commit_event(
        self,
        event: Event,
        score_fn,
        *,
        venues: list[dict] | None = None,
    ) -> Alert:
        """`score_fn(signals) -> Score` is applied to the merged signal set.

        A later, weaker source must not replace an earlier on-chain score.
        """
        async with self._lock:
            existing = self._open_alert(event, event.timestamp)
            previous_score = existing.score if existing else None
            previous_sources = set(existing.sources) if existing else set()
            if existing is None:
                score = score_fn(event.signals)
                alert = Alert(
                    id=uuid.uuid4().hex,
                    ticker=event.ticker.upper() if event.ticker else None,
                    type=event.type,
                    score=score.total,
                    level=score.level,
                    night=score.night,
                    title=event.title,
                    text="",
                    summary=event.summary,
                    chain=event.chain,
                    name=event.name,
                    components=list(score.components),
                    signals=list(event.signals),
                    sources=[event.source],
                    links=dict(event.links),
                    payload=dict(event.payload),
                    created_at=event.timestamp,
                    updated_at=event.timestamp,
                )
                self.alerts[alert.id] = alert
                self.order.append(alert.id)
                created = True
            else:
                alert = existing
                alert.signals = _merge_signals(alert.signals, event.signals)
                score = score_fn(alert.signals)
                alert.score = score.total
                alert.level = score.level
                alert.night = score.night
                alert.components = list(score.components)
                alert.updated_at = event.timestamp
                previous_type = alert.type
                alert.type = stronger_type(previous_type, event.type)
                if alert.type == event.type:
                    alert.title = event.title
                    alert.summary = event.summary
                if event.chain and not alert.chain:
                    alert.chain = event.chain
                if event.name and not alert.name:
                    alert.name = event.name
                if event.source not in alert.sources:
                    alert.sources.append(event.source)
                alert.links.update({k: v for k, v in event.links.items() if v})
                alert.payload.update(event.payload)
                created = False
            if venues:
                alert.payload["venues"] = venues
            alert.payload["dedup_id"] = event.dedup_id()
            alert.text = format_alert(alert)
            new_source = event.source not in previous_sources
            score_up = previous_score is None or score.total > previous_score
            alert.notify = alert.level == "red" and (created or score_up or new_source)
            await self._save(alert)
            self.publish({"event": "alert", "data": alert.as_dict()})
            return alert

    async def _save(self, alert: Alert) -> None:
        if self.db is None:
            return
        await self.db.execute(
            """
            INSERT INTO alerts (id, payload, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
            """,
            (alert.id, json.dumps(alert.as_dict()), alert.updated_at.isoformat()),
        )
        await self.db.commit()

    def recent_alerts(self, limit: int = 100) -> list[Alert]:
        ids = list(reversed(self.order))[:limit]
        return [self.alerts[item] for item in ids if item in self.alerts]


def _merge_signals(old: list[Signal], new: list[Signal]) -> list[Signal]:
    by_kind = {signal.kind: signal for signal in old}
    for signal in new:
        current = by_kind.get(signal.kind)
        if current is None or signal.pct > current.pct:
            by_kind[signal.kind] = signal
        elif signal.pct == current.pct and len(signal.detail) > len(current.detail):
            by_kind[signal.kind] = signal
    return list(by_kind.values())


def _parse_dt(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _alert_from_json(raw: dict) -> Alert:
    return Alert(
        id=raw["id"],
        ticker=raw.get("ticker"),
        type=raw.get("type") or "news",
        score=int(raw.get("score") or 0),
        level=raw.get("level") or "info",
        night=bool(raw.get("night")),
        title=raw.get("title") or "",
        text=raw.get("text") or "",
        summary=raw.get("summary") or "",
        chain=raw.get("chain"),
        name=raw.get("name"),
        components=[
            Component(item["code"], int(item["points"]), item.get("detail") or "")
            for item in raw.get("components") or []
        ],
        signals=[Signal.from_dict(item) for item in raw.get("signals") or []],
        sources=list(raw.get("sources") or []),
        links=raw.get("links") or {},
        payload=raw.get("payload") or {},
        created_at=_parse_dt(raw["created_at"]),
        updated_at=_parse_dt(raw["updated_at"]),
        notify=False,
    )
