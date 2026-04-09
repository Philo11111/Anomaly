"""
AI аналізатор подій.
Підтримує Anthropic напряму або через OpenRouter (для VPS без постійного підключення).
"""
import aiohttp
import json
from loguru import logger
from config import (
    ANTHROPIC_API_KEY, OPENROUTER_API_KEY,
    USE_OPENROUTER, OPENROUTER_MODEL, MIN_AI_SCORE
)

_anthropic_client = None
if not USE_OPENROUTER and ANTHROPIC_API_KEY:
    import anthropic
    _anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Ти — провідний аналітик крипто-безпеки та трейдингу. Аналізуєш новини, on-chain дані та ринкові аномалії.

ВІДПОВІДЬ ТІЛЬКИ JSON, БЕЗ MARKDOWN, БЕЗ КОМЕНТАРІВ:

{
  "score": <1-10, де 10=критично>,
  "event_type": "<hack|exploit|rug|manipulation|whale|liquidation|bridge|news|other>",
  "severity": "<critical|high|medium|low>",
  "affected_asset": "<тікер або unknown>",
  "affected_protocol": "<назва або unknown>",
  "estimated_loss": "<сума або unknown>",
  "attacker_wallet": "<адреса або unknown>",
  "stolen_assets": ["<актив 1>", "<актив 2>"],
  "summary": "<2-3 речення>",
  "market_impact": "<прогноз впливу на ціну>",
  "tokens_to_short": ["<тікер1>", "<тікер2>"],
  "actions": ["<дія 1>", "<дія 2>", "<дія 3>"],
  "confidence": "<high|medium|low>",
  "time_sensitivity": "<immediate|hours|days>"
}

СКОРИНГ: 9-10=злом >$10M; 7-8=exploit <$10M або whale; 5-6=підозрілий рух; 1-4=загальне.
ACTIONS: конкретні і actionable, вказуй які токени шортити."""

async def _call_openrouter(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://anomalityparcer.bot",
        "X-Title": "AnomalityParcer",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 700,
        "temperature": 0.1,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

async def _call_anthropic(prompt: str) -> str:
    message = await _anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=700,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text

def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip().rstrip("`").strip())

async def analyze_event(text: str, source: str = "", event_type: str = "news") -> dict | None:
    if not (ANTHROPIC_API_KEY or OPENROUTER_API_KEY):
        logger.warning("No AI API key configured")
        return None
    prompt = f"ДЖЕРЕЛО: {source}\nТИП: {event_type}\n\nТЕКСТ:\n{text[:2500]}"
    try:
        raw = await _call_openrouter(prompt) if USE_OPENROUTER else await _call_anthropic(prompt)
        result = _parse_json(raw)
        score = result.get("score", 0)
        logger.info(f"AI [{score}/10] {result.get('event_type')} | {source[:40]}")
        return result if score >= MIN_AI_SCORE else None
    except Exception as e:
        logger.error(f"AI error ({source}): {e}")
        return None

async def analyze_price_anomaly(symbol, current_price, old_price, change_pct, timeframe="5m"):
    text = f"Різка зміна ціни {symbol}: {change_pct:+.2f}% за {timeframe}. ${old_price:.4f} -> ${current_price:.4f}."
    return await analyze_event(text, source="Binance WebSocket", event_type="price_anomaly")

async def analyze_tvl_drop(protocol, current_tvl, old_tvl, drop_pct):
    text = f"TVL {protocol} впав {drop_pct:.1f}% за 1 год. ${old_tvl/1e6:.2f}M -> ${current_tvl/1e6:.2f}M."
    return await analyze_event(text, source="DefiLlama", event_type="tvl_anomaly")

async def analyze_wallet_movement(alert: dict):
    text = (
        f"Відомий гаманець {alert.get('wallet_short')} ({alert.get('chain')}) нова транзакція. "
        f"~${alert.get('value_usd_approx', 0):,.0f}. TX: {str(alert.get('tx_hash',''))[:30]}"
    )
    return await analyze_event(text, source=alert.get("source", "On-chain"), event_type="wallet_movement")
