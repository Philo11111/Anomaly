"""Rule score, 0–100. No model call, no minimum that drops the event."""

from __future__ import annotations

from datetime import datetime

from anomaly.models import Component, Score, Signal
from anomaly.timeutil import is_night

# Higher rank becomes the thread's headline type.
TYPE_RANK = {
    "mint": 60,
    "drain": 50,
    "signer": 40,
    "dex_gap": 30,
    "notice": 20,
    "news": 10,
    "crash": 5,
    "listing": 1,
}


def score_signals(
    signals: list[Signal],
    *,
    when: datetime,
    settings,
    ticker: str | None = None,
    venue_oi_usd: float | None = None,
) -> Score:
    rules = settings.score
    best: dict[str, Component] = {}

    def add(code: str, points: int, detail: str) -> None:
        current = best.get(code)
        if current is None or points > current.points:
            best[code] = Component(code, points, detail)

    for signal in signals:
        detail = signal.detail or signal.kind
        if signal.kind == "mint" and signal.pct + 1e-9 >= rules.mint_supply_pct:
            add("mint", rules.mint_points, detail or f"supply +{signal.pct:.1f}%")
        elif signal.kind == "drain" and signal.pct + 1e-9 >= rules.drain_pct:
            add("drain", rules.drain_points, detail or f"outflow {signal.pct:.1f}%")
        elif signal.kind == "fresh_signer":
            add("fresh_signer", rules.fresh_signer_points, detail)
        elif signal.kind == "dex_gap" and signal.pct + 1e-9 >= rules.dex_gap_pct:
            add("dex_gap", rules.dex_gap_points, detail or f"gap {signal.pct:.1f}%")
        elif signal.kind == "korean_halt":
            add("korean_halt", rules.korean_halt_points, detail)
        elif signal.kind == "trusted_source":
            add("trusted_source", rules.trusted_source_points, detail)
        elif signal.kind == "notice":
            add("notice", rules.notice_points, detail)

    if (
        ticker
        and venue_oi_usd is not None
        and venue_oi_usd + 1e-6 >= rules.venue_oi_usd
    ):
        add("venue_oi", rules.venue_oi_points, f"OI ${venue_oi_usd:,.0f} on a user venue")

    components = list(best.values())
    total = min(100, sum(item.points for item in components))
    night = is_night(when, rules.night_start_hour, rules.night_end_hour)
    red_at = rules.red_night if night else rules.red_day
    if total >= red_at:
        level = "red"
    elif total >= rules.yellow:
        level = "yellow"
    else:
        level = "info"
    return Score(total=total, level=level, components=components, night=night)


def stronger_type(current: str, incoming: str) -> str:
    if TYPE_RANK.get(incoming, 0) > TYPE_RANK.get(current, 0):
        return incoming
    return current
