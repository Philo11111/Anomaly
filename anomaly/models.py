"""Shared records. Scoring never consults a model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from anomaly.timeutil import utcnow


@dataclass
class Signal:
    kind: str
    pct: float = 0.0
    detail: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "pct": self.pct, "detail": self.detail}

    @classmethod
    def from_dict(cls, raw: dict) -> "Signal":
        return cls(kind=raw["kind"], pct=float(raw.get("pct") or 0), detail=raw.get("detail") or "")


@dataclass
class Component:
    code: str
    points: int
    detail: str

    def as_dict(self) -> dict:
        return {"code": self.code, "points": self.points, "detail": self.detail}


@dataclass
class Score:
    total: int
    level: str
    components: list[Component]
    night: bool

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "level": self.level,
            "night": self.night,
            "components": [c.as_dict() for c in self.components],
        }


@dataclass
class Event:
    type: str
    source: str
    timestamp: datetime
    title: str
    summary: str
    ticker: str | None = None
    chain: str | None = None
    name: str | None = None
    signals: list[Signal] = field(default_factory=list)
    links: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)

    def dedup_id(self) -> str:
        if self.ticker:
            return self.ticker.upper()
        return f"{self.type}:{self.payload.get('dedup') or self.title}"


@dataclass
class MarketRow:
    venue: str
    symbol: str
    base: str
    mark: float | None = None
    index: float | None = None
    funding: float | None = None
    funding_hours: float | None = None
    oi_usd: float | None = None
    volume_usd: float | None = None
    updated_at: datetime = field(default_factory=utcnow)

    def as_dict(self) -> dict:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "base": self.base,
            "mark": self.mark,
            "index": self.index,
            "funding": self.funding,
            "funding_hours": self.funding_hours,
            "oi_usd": self.oi_usd,
            "volume_usd": self.volume_usd,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class Alert:
    id: str
    ticker: str | None
    type: str
    score: int
    level: str
    night: bool
    title: str
    text: str
    summary: str
    chain: str | None
    name: str | None
    components: list[Component]
    signals: list[Signal]
    sources: list[str]
    links: dict
    payload: dict
    created_at: datetime
    updated_at: datetime
    notify: bool = False

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "type": self.type,
            "score": self.score,
            "level": self.level,
            "night": self.night,
            "title": self.title,
            "text": self.text,
            "summary": self.summary,
            "chain": self.chain,
            "name": self.name,
            "components": [c.as_dict() for c in self.components],
            "signals": [s.as_dict() for s in self.signals],
            "sources": list(self.sources),
            "links": self.links,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "notify": self.notify,
        }
