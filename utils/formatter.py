from datetime import datetime, timezone

SEVERITY_EMOJI = {
    "critical": "🚨", "high": "🔴", "medium": "🟡", "low": "🟢", "warning": "⚠️",
}
EVENT_EMOJI = {
    "hack": "💀", "exploit": "⚡", "rug": "🪤", "manipulation": "🎭",
    "liquidation": "💸", "whale": "🐋", "price_anomaly": "📊",
    "tvl_anomaly": "📉", "wallet_movement": "👾", "bridge": "🌉",
    "news": "📰", "other": "🔔",
}

def format_news_alert(article: dict, ai_result: dict) -> str:
    severity = ai_result.get("severity", "medium")
    event_type = ai_result.get("event_type", "other")
    score = ai_result.get("score", 0)
    sev_emoji = SEVERITY_EMOJI.get(severity, "⚠️")
    evt_emoji = EVENT_EMOJI.get(event_type, "🔔")
    actions = ai_result.get("actions", [])
    actions_text = "\n".join([f"  • {a}" for a in actions]) if actions else "  • Моніторь ситуацію"
    conf_map = {"high": "Висока ✅", "medium": "Середня ⚠️", "low": "Низька ❓"}
    conf_text = conf_map.get(ai_result.get("confidence", "medium"), "Середня")
    asset = ai_result.get("affected_asset", "unknown")
    protocol = ai_result.get("affected_protocol", "unknown")
    loss = ai_result.get("estimated_loss", "unknown")
    wallet = ai_result.get("attacker_wallet", "unknown")
    stolen = ai_result.get("stolen_assets", [])
    to_short = ai_result.get("tokens_to_short", [])
    time_sens = ai_result.get("time_sensitivity", "hours")
    time_map = {"immediate": "🔴 НЕГАЙНО", "hours": "🟡 Є кілька годин", "days": "🟢 Слідкуй"}
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    text = f"""{sev_emoji} *{severity.upper()}* | Score: {score}/10 {evt_emoji}

📋 *Подія:* {ai_result.get("summary", "—")}

🏦 *Протокол:* `{protocol}`
🎯 *Актив:* `{asset}`
💰 *Збитки:* `{loss}`"""

    if stolen and stolen != ["unknown"] and stolen:
        stolen_str = ", ".join([f"`{s}`" for s in stolen[:6]])
        text += f"\n🪙 *Вкрадено:* {stolen_str}"

    if wallet and wallet != "unknown":
        short_w = f"{wallet[:10]}...{wallet[-6:]}" if len(wallet) > 20 else wallet
        text += f"\n👾 *Гаманець:* `{short_w}`"
        if wallet.startswith("0x"):
            text += f" [Etherscan](https://etherscan.io/address/{wallet}) | [Arkham](https://platform.arkhamintelligence.com/explorer/address/{wallet})"
        else:
            text += f" [Solscan](https://solscan.io/account/{wallet})"

    text += f"\n📊 *Вплив:* {ai_result.get('market_impact', '—')}"

    if to_short and to_short != ["unknown"] and to_short:
        short_str = " ".join([f"`{t}`" for t in to_short[:4]])
        text += f"\n📉 *Шортити:* {short_str}"

    text += f"""

⚡ *Рекомендації ({time_map.get(time_sens, '⚠️')}):*
{actions_text}

🔗 [{article.get("source", "Джерело")}]({article.get("link", "")})
🕐 {now} | {conf_text}
#{event_type} #{severity} #AnomalityParcer"""
    return text


def format_price_alert(anomaly: dict, ai_result: dict | None = None) -> str:
    symbol = anomaly["symbol"]
    change = anomaly["change_pct"]
    current = anomaly["current_price"]
    old = anomaly["old_price"]
    direction = anomaly["direction"]
    emoji = "🚀" if change > 0 else "💥"
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    text = f"""{emoji} *PRICE ANOMALY* | `{symbol}`

📊 *Зміна за 5 хв:* `{change:+.2f}%`
💲 *Поточна:* `${current:,.4f}`
📌 *5хв тому:* `${old:,.4f}`
{direction}

"""
    if ai_result:
        to_short = ai_result.get("tokens_to_short", [])
        actions = ai_result.get("actions", [])
        if to_short:
            text += "📉 *Шортити:* " + " ".join([f"`{t}`" for t in to_short[:3]]) + "\n"
        if actions:
            text += "⚡ *Дії:*\n" + "\n".join([f"  • {a}" for a in actions]) + "\n\n"
        text += f"🤖 {ai_result.get('summary', '—')}\n"
    text += f"\n🕐 {now}\n#price_anomaly #{symbol} #AnomalityParcer"
    return text


def format_tvl_alert(anomaly: dict, ai_result: dict | None = None) -> str:
    protocol = anomaly["protocol"]
    drop = anomaly["drop_pct"]
    current = anomaly["current_tvl"]
    old = anomaly["old_tvl"]
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    text = f"""📉 *TVL ANOMALY* | `{protocol}`

🔻 *Падіння за 1 год:* `{drop:.1f}%`
💰 *Поточний TVL:* `${current/1e6:.2f}M`
📌 *Годину тому:* `${old/1e6:.2f}M`

"""
    if ai_result:
        to_short = ai_result.get("tokens_to_short", [])
        actions = ai_result.get("actions", [])
        if to_short:
            text += "📉 *Шортити:* " + " ".join([f"`{t}`" for t in to_short[:3]]) + "\n"
        if actions:
            text += "⚡ *Рекомендації:*\n" + "\n".join([f"  • {a}" for a in actions]) + "\n\n"
        text += f"🤖 {ai_result.get('summary', '—')}\n\n"
    text += f"🔗 [DefiLlama](https://defillama.com/protocol/{protocol})\n🕐 {now}\n#tvl_anomaly #{protocol} #AnomalityParcer"
    return text


def format_wallet_alert(alert: dict, ai_result: dict | None = None) -> str:
    chain = alert.get("chain", "?")
    wallet = alert.get("wallet", "")
    short_w = f"{wallet[:10]}...{wallet[-6:]}" if len(wallet) > 20 else wallet
    tx = alert.get("tx_hash", "")
    short_tx = f"{tx[:12]}...{tx[-8:]}" if len(tx) > 20 else tx
    link = alert.get("link", "")
    arkham = alert.get("arkham_link", "")
    usd = alert.get("value_usd_approx", 0)
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    text = f"""👾 *TRACKED WALLET MOVE* | {chain}

🔑 *Гаманець:* `{short_w}`
💸 *Сума:* ~`${usd:,.0f}`
🔗 TX: [{short_tx}]({link})"""

    if arkham:
        text += f" | [Arkham]({arkham})"

    if ai_result:
        actions = ai_result.get("actions", [])
        to_short = ai_result.get("tokens_to_short", [])
        if to_short:
            text += "\n📉 *Шортити:* " + " ".join([f"`{t}`" for t in to_short[:3]])
        if actions:
            text += "\n⚡ *Дії:*\n" + "\n".join([f"  • {a}" for a in actions])
        text += f"\n🤖 {ai_result.get('summary', '—')}"

    text += f"\n\n🕐 {now}\n#wallet_movement #{chain} #AnomalityParcer"
    return text


def format_status(is_running: bool, stats: dict) -> str:
    status = "🟢 Активний" if is_running else "🔴 Зупинений"
    return f"""📊 *AnomalityParcer Status*

{status}

📡 *Моніторинг:*
  • RSS джерел: {stats.get("rss_feeds", 0)}
  • Telegram каналів: {stats.get("tg_channels", 0)}
  • Активів: {stats.get("assets", 0)}
  • Протоколів: {stats.get("protocols", 0)}
  • Відстежуваних гаманців: {stats.get("wallets", 0)}

📈 *За останні 24 год:*
  • Всього алертів: {stats.get("alerts_24h", 0)}
  • Критичних: {stats.get("critical_24h", 0)}

🕐 {datetime.now(timezone.utc).strftime("%H:%M UTC")}"""
