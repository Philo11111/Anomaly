"""YAML configuration plus environment overrides. Secrets stay in the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


def repo_root() -> Path:
    override = os.environ.get("ANOMALY_HOME")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1]


@dataclass
class ChainCfg:
    name: str
    chain_id: int | None
    ws: list[str]
    http: list[str]
    explorer_tx: str
    explorer_address: str
    llama: str


@dataclass
class ScoreCfg:
    mint_supply_pct: float = 5.0
    mint_points: int = 50
    drain_pct: float = 30.0
    drain_points: int = 40
    fresh_signer_points: int = 30
    fresh_nonce_max: int = 5
    dex_gap_pct: float = 20.0
    dex_gap_points: int = 25
    korean_halt_points: int = 30
    trusted_source_points: int = 25
    notice_points: int = 20
    venue_oi_usd: float = 500_000
    venue_oi_points: int = 15
    red_day: int = 60
    red_night: int = 75
    yellow: int = 40
    night_start_hour: int = 0
    night_end_hour: int = 8
    dedup_hours: float = 2.0
    mint_window_seconds: int = 600


@dataclass
class Settings:
    root: Path
    host: str
    port: int
    log_level: str
    data_dir: Path
    log_dir: Path
    webhook_url: str
    webhook_min_level: str
    dashboard_token: str
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_api_id: int
    telegram_api_hash: str
    telegram_session: str
    score: ScoreCfg
    keywords: dict
    korean_exchanges: list[str]
    trusted_sources: list[str]
    user_venues: list[str]
    reference_venues: list[str]
    chains: dict[str, ChainCfg]
    limits: dict[str, tuple[float, float]]
    intervals: dict[str, float]
    venues: dict
    rss_feeds: list[str]
    telegram_channels: list[str]
    watchlist: dict
    news_max_age_hours: float = 48
    crash_pct: float = 25.0
    raw: dict = field(default_factory=dict)


def _score(raw: dict) -> ScoreCfg:
    data = dict(raw or {})
    known = {item.name for item in ScoreCfg.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return ScoreCfg(**{key: value for key, value in data.items() if key in known})


def _chain(name: str, raw: dict) -> ChainCfg:
    return ChainCfg(
        name=name,
        chain_id=raw.get("chain_id"),
        ws=list(raw.get("ws") or []),
        http=list(raw.get("http") or []),
        explorer_tx=raw.get("explorer_tx") or "",
        explorer_address=raw.get("explorer_address") or "",
        llama=raw.get("llama") or name,
    )


def load_settings() -> Settings:
    root = repo_root()
    load_dotenv(root / ".env")
    config_path = Path(os.environ.get("ANOMALY_CONFIG") or (root / "config" / "settings.yaml"))
    watch_path = Path(os.environ.get("ANOMALY_WATCHLIST") or (root / "config" / "watchlist.yaml"))
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    watch = yaml.safe_load(watch_path.read_text(encoding="utf-8")) or {}
    limits = {}
    for name, item in (raw.get("limits") or {}).items():
        limits[name] = (float(item["rate"]), float(item["per_seconds"]))
    chains = {name: _chain(name, item) for name, item in (raw.get("chains") or {}).items()}
    data_dir = Path(os.environ.get("ANOMALY_DATA") or (root / "data"))
    log_dir = Path(os.environ.get("ANOMALY_LOG_DIR") or (root / "logs"))
    port = int(os.environ.get("PORT") or raw.get("port") or 8080)
    host = os.environ.get("DASHBOARD_HOST") or raw.get("host") or "0.0.0.0"
    return Settings(
        root=root,
        host=host,
        port=port,
        log_level=os.environ.get("LOG_LEVEL") or raw.get("log_level") or "INFO",
        data_dir=data_dir,
        log_dir=log_dir,
        webhook_url=os.environ.get("WEBHOOK_URL") or "",
        webhook_min_level=(raw.get("webhook_min_level") or "red").lower(),
        dashboard_token=os.environ.get("DASHBOARD_TOKEN") or "",
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or "",
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or "",
        telegram_api_id=int(os.environ.get("TELEGRAM_API_ID") or "0"),
        telegram_api_hash=os.environ.get("TELEGRAM_API_HASH") or "",
        telegram_session=os.environ.get("TELEGRAM_SESSION") or "",
        score=_score(raw.get("score") or {}),
        keywords=raw.get("keywords") or {},
        korean_exchanges=[item.lower() for item in (raw.get("korean_exchanges") or [])],
        trusted_sources=list(raw.get("trusted_sources") or []),
        user_venues=list(raw.get("user_venues") or []),
        reference_venues=list(raw.get("reference_venues") or []),
        chains=chains,
        limits=limits,
        intervals={key: float(value) for key, value in (raw.get("intervals") or {}).items()},
        venues=raw.get("venues") or {},
        rss_feeds=list(raw.get("rss_feeds") or []),
        telegram_channels=list((watch.get("telegram_channels") or raw.get("telegram_channels") or [])),
        watchlist=watch,
        news_max_age_hours=float(raw.get("news_max_age_hours") or 48),
        crash_pct=float(raw.get("crash_pct") or 25),
        raw=raw,
    )


def interval(settings: Settings, name: str, default: float) -> float:
    return float(settings.intervals.get(name, default))
