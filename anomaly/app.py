"""Process entry. One command starts every module; a failed module does not exit the process."""

from __future__ import annotations

import asyncio
import sys

from loguru import logger

from anomaly.dashboard import start_dashboard
from anomaly.httpclient import HttpClient
from anomaly.notifiers import build_notifiers
from anomaly.pipeline import Pipeline
from anomaly.registry import Registry
from anomaly.settings import load_settings
from anomaly.sources.base import guard
from anomaly.sources.dexgap import DexGapSource
from anomaly.sources.evm import EvmSource
from anomaly.sources.hyperliquid import HyperliquidSource
from anomaly.sources.markets import MarketSource
from anomaly.sources.news import NewsSource
from anomaly.sources.notices import NoticeSource
from anomaly.sources.solana import SolanaSource
from anomaly.sources.telegram import TelegramSource
from anomaly.state import State


def _configure_logging(settings) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(
        settings.log_dir / "anomaly.log",
        rotation="20 MB",
        retention="14 days",
        level=settings.log_level,
    )


async def serve() -> None:
    settings = load_settings()
    _configure_logging(settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    stop = asyncio.Event()
    state = State(settings.data_dir / "anomaly.db", dedup_hours=settings.score.dedup_hours)
    await state.open()
    http = HttpClient(settings.limits)
    await http.open()
    registry = Registry(settings, http, state)
    registry.load_seed()
    notifiers = build_notifiers(settings, http)
    pipeline = Pipeline(settings, state, registry, notifiers)
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(__import__("signal"), sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    sources = [
        EvmSource(settings, http, state, registry, pipeline, stop),
        SolanaSource(settings, http, state, registry, pipeline, stop),
        HyperliquidSource(settings, http, state, registry, pipeline, stop),
        MarketSource(settings, http, state, registry, pipeline, stop),
        DexGapSource(settings, http, state, registry, pipeline, stop),
        NewsSource(settings, http, state, registry, pipeline, stop),
        NoticeSource(settings, http, state, registry, pipeline, stop),
        TelegramSource(settings, http, state, registry, pipeline, stop),
    ]
    runner = await start_dashboard(settings, state)
    logger.info(
        "Anomaly started. Alerts are rule-scored and are delivered even when a source is down. "
        "Dashboard http://{}:{}/",
        settings.host,
        settings.port,
    )
    tasks = [
        asyncio.create_task(guard("registry", lambda: registry.run(stop), state, stop), name="registry"),
    ]
    for source in sources:
        name = source.__class__.__name__
        tasks.append(asyncio.create_task(guard(name, source.run, state, stop), name=name))
    await stop.wait()
    logger.info("shutting down")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await runner.cleanup()
    await http.close()
    await state.close()


def main() -> None:
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
