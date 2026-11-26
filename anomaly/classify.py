"""Keyword classification for news and exchange notices. Config lists the words."""

from __future__ import annotations

from anomaly.models import Signal


def _has_any(text: str, words: list[str]) -> bool:
    return any(word.lower() in text for word in words if word)


def notice_signals(title: str, exchange: str, settings) -> list[Signal]:
    text = (title or "").lower()
    words = settings.keywords
    deposit = _has_any(text, words.get("deposit_words", []))
    halt = _has_any(text, words.get("halt_words", []))
    korean = exchange.lower() in set(settings.korean_exchanges)
    signals: list[Signal] = []
    if korean and deposit and halt:
        signals.append(Signal("korean_halt", detail=title.strip()))
    notice_hit = (
        _has_any(text, words.get("reduce_only", []))
        or _has_any(text, words.get("rollback", []))
        or _has_any(text, words.get("security", []))
    )
    if notice_hit:
        signals.append(Signal("notice", detail=title.strip()))
    return signals


def news_is_incident(text: str, settings) -> bool:
    return _has_any((text or "").lower(), settings.keywords.get("incident", []))
