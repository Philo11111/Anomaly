"""Ukrainian alert text. Times are Europe/Kyiv."""

from __future__ import annotations

from anomaly.models import Alert
from anomaly.symbols import short_addr
from anomaly.timeutil import format_kyiv

_LEVEL = {"red": "🔴", "yellow": "🟡", "info": "⚪"}
_HEAD = {
    "mint": "EXPLOIT",
    "drain": "EXPLOIT",
    "signer": "EXPLOIT",
    "dex_gap": "GAP",
    "notice": "NOTICE",
    "news": "NEWS",
    "crash": "CRASH",
    "listing": "LISTING",
}
_CHAIN = {
    "ethereum": "Ethereum",
    "eth": "Ethereum",
    "bsc": "BSC",
    "bnb": "BSC",
    "base": "Base",
    "arbitrum": "Arbitrum",
    "solana": "Solana",
    "hyperliquid": "Hyperliquid",
}


def chain_label(chain: str | None) -> str:
    if not chain:
        return "—"
    return _CHAIN.get(chain.lower(), chain)


def compact_tokens(amount: float) -> str:
    sign = "-" if amount < 0 else ""
    value = abs(amount)
    for scale, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= scale:
            return f"{sign}{value / scale:.2f}{suffix}".replace(".00", "")
    return f"{sign}{value:.2f}"


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    value = abs(value)
    for scale, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= scale:
            return f"{sign}${value / scale:.2f}{suffix}"
    return f"{sign}${value:.0f}"


def _funding(rate: float | None, hours: float | None) -> str:
    if rate is None:
        return "—"
    period = f"{hours:g}h" if hours else ""
    return f"{rate * 100:.4f}%{('/' + period) if period else ''}"


def type_line(alert: Alert) -> str:
    kinds = {signal.kind for signal in alert.signals}
    if alert.type == "mint":
        if "fresh_signer" in kinds:
            return "незабезпечений мінт через bridge-minter"
        return "незабезпечений мінт"
    if alert.type == "drain":
        return "відтік з мосту / резерву лендінгу"
    if alert.type == "signer":
        return "переказ з deployer/minter на свіжий гаманець"
    if alert.type == "dex_gap":
        return "розрив ціни DEX і перпа"
    if alert.type == "notice":
        if "korean_halt" in kinds:
            return "корейська біржа зупинила депозити"
        return "нотис біржі (security / reduce-only / rollback)"
    if alert.type == "news":
        return "підтвердження з джерела"
    if alert.type == "crash":
        return "різке падіння марк-ціни"
    if alert.type == "listing":
        return "новий або делістинг ринок"
    return alert.type


def format_alert(alert: Alert) -> str:
    emoji = _LEVEL.get(alert.level, "⚪")
    head = _HEAD.get(alert.type, "ALERT")
    ticker = alert.ticker or "—"
    name = f" ({alert.name})" if alert.name else ""
    when = format_kyiv(alert.updated_at)
    payload = alert.payload or {}
    lines = [
        f"{emoji} {head} {alert.score}/100 | {ticker}{name} | {chain_label(alert.chain)} | {when} Kyiv",
        f"Тип: {type_line(alert)}",
    ]
    amount = payload.get("amount_tokens")
    pct = payload.get("supply_pct")
    if amount is not None or pct is not None:
        minted = f"+{compact_tokens(float(amount))} {ticker}" if amount is not None else ticker
        supply = f" (supply ↑ {float(pct):.1f}%)" if pct is not None else ""
        window = payload.get("window_seconds")
        span = f" за {int(window) // 60} хв" if window and int(window) >= 60 else ""
        minter = payload.get("minter")
        who = f" · мінтер {short_addr(minter)}" if minter else ""
        lines.append(f"On-chain: {minted}{span}{supply}{who}")
    gap = payload.get("gap_pct")
    if gap is not None:
        lines.append(f"DEX vs perp: {float(gap):+.1f}%")
    elif alert.type in {"mint", "drain", "dex_gap"}:
        lines.append("DEX vs perp: —")
    venues = payload.get("venues") or []
    if venues:
        bits = []
        for row in venues:
            bits.append(
                f"{row.get('venue')}: OI {_money(row.get('oi_usd'))} / "
                f"funding {_funding(row.get('funding'), row.get('funding_hours'))} / "
                f"mark {row.get('mark') if row.get('mark') is not None else '—'}"
            )
        lines.append("Перпи (OI / funding / mark): " + "; ".join(bits))
    else:
        lines.append("Перпи (OI / funding / mark): зріз ще не зібраний")
    risks = payload.get("risks")
    if risks:
        lines.append(f"Ризики: {risks}")
    lines.append("Підтвердження: " + _confirmations(alert))
    link_bits = []
    for label, url in (alert.links or {}).items():
        if url:
            link_bits.append(f"[{label}] {url}")
    if link_bits:
        lines.append(" · ".join(link_bits))
    if alert.summary:
        lines.append(alert.summary)
    return "\n".join(lines)


def _confirmations(alert: Alert) -> str:
    sources = " ".join(alert.sources).lower()
    onchain = any(token in sources for token in ("evm", "solana", "hyperliquid", "dex"))
    news = "news" in sources or "rss" in sources or "defillama" in sources
    notice = "notice" in sources
    telegram = "telegram" in sources

    def mark(flag: bool) -> str:
        return "✅" if flag else "⏳"

    return (
        f"{mark(onchain)} on-chain  {mark(telegram)} TG-алерти  {mark(news or notice)} нотиси/новини"
    )
