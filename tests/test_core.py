"""Rule scoring, mint replay, dedup and the guarantee that nothing is dropped."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anomaly.backtest import CASES, replay_case, run_backtest
from anomaly.classify import news_is_incident, notice_signals
from anomaly.detect import evaluate_mint_logs
from anomaly.format import format_alert
from anomaly.models import Event, Signal
from anomaly.notifiers import JsonNotifier
from anomaly.pipeline import Pipeline
from anomaly.ratelimit import TokenBucket, next_backoff
from anomaly.registry import Registry
from anomaly.scoring import score_signals
from anomaly.settings import load_settings
from anomaly.state import State
from anomaly.symbols import base_symbol, find_tickers
from anomaly.timeutil import KYIV, is_night, to_kyiv

ROOT = Path(__file__).resolve().parents[1]


def _settings():
    return load_settings()


def test_symbols():
    assert base_symbol("ACE-PERP") == "ACE"
    assert base_symbol("BTCUSDT") == "BTC"
    assert base_symbol("BTC-USDT-SWAP") == "BTC"
    assert base_symbol("ETH-USD-SWAP") == "ETH"
    assert base_symbol("xyz:AAPL") == "AAPL"
    assert find_tickers("Gate will suspend ACE deposits", {"ACE", "BTC"}) == ["ACE"]


def test_night_window_matches_kyiv():
    winter_morning = datetime(2026, 11, 22, 4, 30, tzinfo=KYIV)
    winter_evening = datetime(2026, 11, 22, 19, 55, tzinfo=KYIV)
    assert is_night(winter_morning)
    assert not is_night(winter_evening)
    assert to_kyiv(datetime(2026, 11, 22, 17, 55, 40, tzinfo=timezone.utc)).hour == 19


def test_score_thresholds_day_and_night():
    settings = _settings()
    day = datetime(2026, 11, 22, 19, 55, tzinfo=KYIV)
    night = datetime(2026, 8, 22, 2, 42, tzinfo=KYIV)
    mint = [Signal("mint", pct=6.4, detail="supply +6.4%")]
    both = mint + [Signal("fresh_signer", detail="minter")]
    day_mint = score_signals(mint, when=day, settings=settings, ticker="ACE")
    assert day_mint.total == 50
    assert day_mint.level == "yellow"
    day_both = score_signals(both, when=day, settings=settings, ticker="ACE")
    assert day_both.total == 80
    assert day_both.level == "red"
    night_mint = score_signals(mint, when=night, settings=settings, ticker="SAND")
    assert night_mint.level == "yellow"
    assert night_mint.night
    night_both = score_signals(both, when=night, settings=settings, ticker="SAND")
    assert night_both.total == 80
    assert night_both.level == "red"
    quiet = score_signals([], when=day, settings=settings)
    assert quiet.level == "info"
    assert quiet.total == 0


def test_venue_oi_bonus_and_cap():
    settings = _settings()
    when = datetime(2026, 11, 22, 12, 0, tzinfo=KYIV)
    signals = [
        Signal("mint", pct=10),
        Signal("drain", pct=40),
        Signal("fresh_signer"),
        Signal("dex_gap", pct=30),
        Signal("korean_halt"),
        Signal("trusted_source"),
        Signal("notice"),
    ]
    scored = score_signals(signals, when=when, settings=settings, ticker="ACE", venue_oi_usd=2_000_000)
    assert scored.total == 100
    assert any(item.code == "venue_oi" for item in scored.components)


def test_small_mint_does_not_score():
    settings = _settings()
    scored = score_signals(
        [Signal("mint", pct=1.2)],
        when=datetime(2026, 11, 22, 12, tzinfo=KYIV),
        settings=settings,
    )
    assert scored.total == 0


def test_notice_classes():
    settings = _settings()
    korean = notice_signals("Upbit will suspend ACE deposits", "upbit", settings)
    assert {item.kind for item in korean} == {"korean_halt"}
    reduce_only = notice_signals("BTCUSDT switched to reduce-only", "binance", settings)
    assert [item.kind for item in reduce_only] == ["notice"]
    assert notice_signals("New listing: ABC", "okx", settings) == []
    assert news_is_incident("protocol exploited and drained", settings)
    assert not news_is_incident("weekly market recap", settings)


def test_fixture_replays_fire():
    settings = _settings()
    for case in CASES:
        result = replay_case(case, live=False, settings=settings)
        assert result.fired, result
        assert result.pct > 5
        assert result.score >= 40
        assert result.level == case["expect_level"]
        assert result.ok


def test_ace_block_is_above_five_percent():
    result = replay_case(CASES[0], live=False, settings=_settings())
    assert result.score >= 80
    assert "0x4dfe4bc1" in result.tx_hashes[0]


def test_historical_supply_math_uses_raw_logs():
    from anomaly.backtest import _load_fixture

    logs, supply = _load_fixture(CASES[0])
    hit = evaluate_mint_logs(
        logs,
        contract=CASES[0]["contract"],
        supply_before=supply,
        threshold_pct=5,
    )
    assert hit.fired
    assert hit.amount_raw > 0
    assert hit.pct > 5


def test_dedup_updates_same_ticker_thread():
    async def inner(tmp):
        settings = _settings()
        state = State(Path(tmp) / "t.db", dedup_hours=2)
        await state.open()
        registry = Registry(settings, http=None, state=state)
        registry.load_seed()
        seen = []

        class Record:
            name = "record"

            def accepts(self, alert):
                return alert.level == "red" and alert.notify

            async def send(self, alert):
                seen.append(alert.score)

        pipeline = Pipeline(settings, state, registry, [Record()])
        start = datetime(2026, 11, 22, 17, 55, tzinfo=timezone.utc)
        first = Event(
            type="mint",
            source="evm:bsc",
            timestamp=start,
            ticker="ACE",
            chain="bsc",
            title="mint",
            summary="mint",
            signals=[Signal("mint", pct=6.4), Signal("fresh_signer", detail="minter")],
        )
        alert = await pipeline.handle(first)
        assert alert.level == "red"
        assert alert.notify
        assert seen == [80]
        second = Event(
            type="news",
            source="defillama",
            timestamp=start + timedelta(minutes=20),
            ticker="ACE",
            chain="bsc",
            title="news",
            summary="confirmed",
            signals=[Signal("trusted_source", detail="defillama")],
        )
        updated = await pipeline.handle(second)
        assert updated.id == alert.id
        assert "defillama" in updated.sources
        assert updated.score == 100
        assert len(state.alerts) == 1
        quiet = Event(
            type="news",
            source="rss",
            timestamp=start,
            ticker=None,
            title="weak",
            summary="weak",
            signals=[],
            payload={"dedup": "weak-1"},
        )
        kept = await pipeline.handle(quiet)
        assert kept.level == "info"
        assert kept.id in state.alerts
        await state.close()

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(inner(tmp))


def test_notifier_failure_does_not_drop_alert(tmp_path):
    async def inner():
        settings = _settings()
        state = State(tmp_path / "t.db")
        await state.open()
        registry = Registry(settings, http=None, state=state)
        registry.load_seed()

        class Boom:
            name = "boom"

            def accepts(self, alert):
                return True

            async def send(self, alert):
                raise RuntimeError("delivery down")

        sink = JsonNotifier(tmp_path / "alerts.jsonl", min_level="info")
        pipeline = Pipeline(settings, state, registry, [Boom(), sink])
        event = Event(
            type="mint",
            source="evm:bsc",
            timestamp=datetime(2026, 11, 22, 17, 55, tzinfo=timezone.utc),
            ticker="ACE",
            chain="bsc",
            title="mint",
            summary="kept",
            signals=[Signal("mint", pct=6)],
        )
        alert = await pipeline.handle(event)
        assert alert.level == "yellow"
        assert alert.text
        assert "Kyiv" in alert.text
        assert "ACE" in format_alert(alert)
        lines = (tmp_path / "alerts.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        await state.close()

    asyncio.run(inner())


def test_package_does_not_gate_on_an_llm():
    text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "anomaly").rglob("*.py"))
    lowered = text.lower()
    assert "anthropic" not in lowered
    assert "openai" not in lowered
    assert "min_ai_score" not in lowered
    assert "analyze_event" not in lowered


def test_backoff_and_bucket():
    assert next_backoff(1) == 2
    assert next_backoff(40) == 60

    async def inner():
        bucket = TokenBucket(2, 1)
        await bucket.acquire()
        await bucket.acquire()
        await bucket.acquire()

    asyncio.run(inner())


def test_market_parsers_cover_live_shapes():
    from anomaly.sources.markets import lighter_funding_map, parse_hyperliquid, parse_variational

    rows = parse_hyperliquid(
        [
            {"universe": [{"name": "ACE", "szDecimals": 2}]},
            [{"funding": "0.001", "openInterest": "10", "markPx": "2", "oraclePx": "2.1", "dayNtlVlm": "5"}],
        ]
    )
    assert rows[0].base == "ACE"
    assert rows[0].oi_usd == 20
    assert rows[0].funding_hours == 1
    parsed = parse_variational(
        {
            "listings": [
                {
                    "ticker": "ACE-PERP",
                    "contract_type": "perpetual",
                    "mark_price": "2",
                    "volume_24h": "3",
                    "open_interest": {"long_open_interest": "4", "short_open_interest": "5"},
                    "funding": {"last": {"interval_rate": "0.01"}, "interval_seconds": 3600},
                }
            ]
        }
    )
    assert parsed[0].oi_usd == 5
    assert parsed[0].funding_hours == 1
    assert lighter_funding_map(
        {"funding_rates": [{"exchange": "binance", "symbol": "ACE", "rate": 0.02}]}
    )[("binance", "ACE")] == 0.02


def test_mexc_linear_versus_inverse_open_interest():
    from anomaly.sources.markets import parse_mexc

    rows = parse_mexc(
        {
            "data": [
                {"symbol": "BTC_USDT", "fairPrice": "100", "holdVol": "10", "indexPrice": "100", "fundingRate": "0.001", "amount24": "5"},
                {"symbol": "BTC_USD", "fairPrice": "100", "holdVol": "10", "indexPrice": "100", "fundingRate": "0.001", "amount24": "5"},
            ]
        },
        {"BTC_USDT": {"size": 0.01, "linear": True}, "BTC_USD": {"size": 100, "linear": False}},
    )
    by_symbol = {row.symbol: row for row in rows}
    assert by_symbol["BTC_USDT"].oi_usd == 10
    assert by_symbol["BTC_USD"].oi_usd == 1000


def test_settings_expose_free_endpoints():
    settings = _settings()
    assert settings.chains["bsc"].ws[0].startswith("wss://bsc-rpc.publicnode.com")
    assert "hyperliquid" in settings.user_venues
    assert settings.score.red_night > settings.score.red_day
    assert (ROOT / "config" / "watchlist.yaml").exists()
