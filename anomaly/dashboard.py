"""Local dashboard: live alerts, scores, and per-venue OI / funding."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web
from loguru import logger

from anomaly import __version__

_HTML = Path(__file__).resolve().parent / "static" / "index.html"


def _authorized(request: web.Request, token: str) -> bool:
    if not token or request.path == "/health":
        return True
    header = request.headers.get("Authorization", "")
    if header == f"Bearer {token}":
        return True
    return request.query.get("token") == token


def create_app(settings, state) -> web.Application:
    app = web.Application()
    token = settings.dashboard_token

    def guard(handler):
        async def wrapped(request: web.Request):
            if not _authorized(request, token):
                raise web.HTTPUnauthorized(text="dashboard token required")
            return await handler(request)

        return wrapped

    async def health(_request: web.Request):
        degraded = [name for name, item in state.modules.items() if item.get("status") == "degraded"]
        return web.json_response(
            {"ok": True, "version": __version__, "degraded": degraded, "modules": len(state.modules)}
        )

    async def index(request: web.Request):
        html = _HTML.read_text(encoding="utf-8")
        if token:
            html = html.replace("__TOKEN__", token)
        else:
            html = html.replace("__TOKEN__", "")
        return web.Response(text=html, content_type="text/html")

    async def alerts(_request: web.Request):
        limit = 150
        return web.json_response([alert.as_dict() for alert in state.recent_alerts(limit)])

    async def markets(request: web.Request):
        venue = request.query.get("venue")
        books = state.markets if not venue else {venue: state.markets.get(venue, {})}
        payload = {}
        for name, rows in books.items():
            ordered = sorted(rows.values(), key=lambda row: row.oi_usd or 0, reverse=True)
            rendered = []
            for row in ordered[:400]:
                item = row.as_dict()
                if item.get("funding") is None:
                    item["funding"] = state.funding_ref.get(name, {}).get(row.base)
                rendered.append(item)
            payload[name] = rendered
        return web.json_response({"venues": payload, "funding_ref": state.funding_ref})

    async def status(_request: web.Request):
        return web.json_response(
            {
                "modules": state.modules,
                "alerts": len(state.alerts),
                "version": __version__,
            }
        )

    async def stream(request: web.Request):
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)
        queue = state.subscribe()
        try:
            snapshot = json.dumps({"modules": state.modules})
            await response.write(f"event: hello\ndata: {snapshot}\n\n".encode())
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    await response.write(b": ping\n\n")
                    continue
                if item is None:
                    continue
                payload = json.dumps(item.get("data"), default=str)
                await response.write(f"event: {item.get('event')}\ndata: {payload}\n\n".encode())
        except (asyncio.CancelledError, ConnectionResetError, ConnectionError):
            pass
        finally:
            state.unsubscribe(queue)
        return response

    async def favicon(_request: web.Request):
        return web.Response(status=204)

    app.router.add_get("/favicon.ico", favicon)
    app.router.add_get("/health", health)
    app.router.add_get("/", guard(index))
    app.router.add_get("/api/alerts", guard(alerts))
    app.router.add_get("/api/markets", guard(markets))
    app.router.add_get("/api/status", guard(status))
    app.router.add_get("/api/stream", guard(stream))
    return app


async def start_dashboard(settings, state) -> web.AppRunner:
    app = create_app(settings, state)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.host, settings.port)
    await site.start()
    logger.info("dashboard http://{}:{}/", settings.host, settings.port)
    return runner
