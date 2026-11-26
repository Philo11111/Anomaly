"""Replay the ACE and SAND unbacked mints through the live detector.

Historical state is read from free RPCs that still serve those blocks.
PublicNode's free tier refuses archive calls, so the backtest failsover.
If every endpoint fails, the captured chain logs in tests/fixtures are replayed
through the same function.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from anomaly.detect import TRANSFER_TOPIC, evaluate_mint_logs
from anomaly.models import Signal
from anomaly.scoring import score_signals
from anomaly.settings import load_settings

ZERO_TOPIC = "0x" + "0" * 64
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
_UA = "Mozilla/5.0 (compatible; AnomalyMonitor/1.0)"


CASES = [
    {
        "name": "ACE BSC 2026-11-22",
        "chain": "bsc",
        "ticker": "ACE",
        "contract": "0xc27a719105a987b4c34116223cae8bd8f4b5def4",
        "block": 135122723,
        "timestamp": 1795370140,
        "tx": "0x4dfe4bc1bf011cd02e1119ae04341c605c4880c9c807a3f044c5917cbd3964ec",
        "tx_from": "0x3f1045210a80a375d6c7cbad57800d5e8f30f34e",
        "watched_minters": ["0x3f1045210a80a375d6c7cbad57800d5e8f30f34e"],
        "log_urls": [
            "https://bsc.drpc.org",
            "https://bsc-dataseed.binance.org",
            "https://bsc.api.pocket.network",
            "https://bsc-mainnet.public.blastapi.io",
        ],
        "supply_urls": [
            "https://bsc.api.pocket.network",
            "https://bsc-mainnet.public.blastapi.io",
        ],
        "fixture": "ace_bsc.json",
        "expect_level": "red",
    },
    {
        "name": "SAND Base 2026-08-22",
        "chain": "base",
        "ticker": "SAND",
        "contract": "0xac531eb26ca1d21b85126de8fb87e80e09002dcf",
        "block": 50283189,
        "timestamp": 1787355725,
        "tx": "0xbddb102a5dbc9324a84390aaa5a9767b89c2bac8955d486fe1cf697e2e9a8fa9",
        "tx_from": None,
        "watched_minters": [],
        "log_urls": [
            "https://base.drpc.org",
            "https://mainnet.base.org",
        ],
        "supply_urls": [
            "https://mainnet.base.org",
            "https://base.drpc.org",
        ],
        "fixture": "sand_base.json",
        "expect_level": "yellow",
    },
    {
        "name": "SAND BSC 2026-08-22",
        "chain": "bsc",
        "ticker": "SAND",
        "contract": "0xac531eb26ca1d21b85126de8fb87e80e09002dcf",
        "block": 117322026,
        "timestamp": 1787355765,
        "tx": "0x6f5f8307209b512dbbb46515c54c87cb006f076bf6d8019fe7b99ee921febf61",
        "tx_from": None,
        "watched_minters": [],
        "log_urls": [
            "https://bsc.api.pocket.network",
            "https://bsc-mainnet.public.blastapi.io",
            "https://bsc.drpc.org",
        ],
        "supply_urls": [
            "https://bsc-mainnet.public.blastapi.io",
            "https://bsc.api.pocket.network",
        ],
        "fixture": "sand_bsc.json",
        "expect_level": "yellow",
    },
]


@dataclass
class Replay:
    name: str
    source: str
    fired: bool
    pct: float
    score: int
    level: str
    tx_hashes: list[str]
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.fired and self.score >= 40


def _rpc(url: str, method: str, params: list, timeout: float = 25):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": _UA, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        snippet = exc.read()[:180].decode("utf-8", "replace")
        raise RuntimeError(f"{exc.code} {url} {snippet}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"{url} {payload['error']}")
    return payload.get("result") if isinstance(payload, dict) else None


def _mint_logs(logs: list[dict], contract: str) -> list[dict]:
    target = contract.lower()
    found = []
    for log in logs or []:
        topics = [str(topic) for topic in (log.get("topics") or [])]
        if len(topics) < 3:
            continue
        if topics[0].lower() != TRANSFER_TOPIC:
            continue
        if str(log.get("address", "")).lower() != target:
            continue
        if int(topics[1], 16) != 0:
            continue
        found.append(log)
    return found


def _fetch_logs(case: dict) -> tuple[list[dict], str]:
    errors = []
    query = [{
        "fromBlock": hex(case["block"]),
        "toBlock": hex(case["block"]),
        "address": case["contract"],
        "topics": [TRANSFER_TOPIC, ZERO_TOPIC],
    }]
    expected = case["tx"].lower()
    for url in case["log_urls"]:
        try:
            result = _rpc(url, "eth_getLogs", query)
            logs = _mint_logs(result or [], case["contract"])
            txs = {str(log.get("transactionHash", "")).lower() for log in logs}
            if expected in txs:
                return logs, f"live getLogs {url}"
            errors.append(f"{url} logs={len(logs)} missing {expected[:10]}")
        except Exception as exc:
            errors.append(str(exc)[:180])
    for url in case["log_urls"]:
        try:
            receipt = _rpc(url, "eth_getTransactionReceipt", [case["tx"]])
        except Exception as exc:
            errors.append(f"receipt {exc}"[:180])
            continue
        if not isinstance(receipt, dict):
            continue
        logs = _mint_logs(receipt.get("logs") or [], case["contract"])
        if not logs:
            errors.append(f"{url} receipt without mint")
            continue
        sender = receipt.get("from")
        for log in logs:
            log["tx_from"] = sender
        return logs, f"live receipt {url}"
    raise RuntimeError("; ".join(errors[:4]) or "no logs")


def _fetch_supply(case: dict) -> tuple[int, str]:
    errors = []
    call = [{"to": case["contract"], "data": "0x18160ddd"}, hex(case["block"] - 1)]
    for url in case["supply_urls"]:
        try:
            result = _rpc(url, "eth_call", call)
        except Exception as exc:
            errors.append(str(exc)[:160])
            continue
        if isinstance(result, str) and result not in {"0x", "0x0"}:
            return int(result, 16), url
        errors.append(f"{url} empty supply")
    raise RuntimeError("; ".join(errors[:3]) or "no supply")


def _load_fixture(case: dict) -> tuple[list[dict], int]:
    payload = json.loads((FIXTURES / case["fixture"]).read_text(encoding="utf-8"))
    return payload["logs"], int(payload["supply_before"])


def _attach_sender(case: dict, logs: list[dict]) -> None:
    if any(log.get("tx_from") for log in logs):
        return
    for url in case["log_urls"]:
        try:
            tx = _rpc(url, "eth_getTransactionByHash", [case["tx"]])
        except Exception:
            continue
        sender = tx.get("from") if isinstance(tx, dict) else None
        if not sender:
            continue
        target = case["tx"].lower()
        for log in logs:
            if str(log.get("transactionHash", "")).lower() == target:
                log["tx_from"] = sender
        return


def _score(case: dict, hit, settings) -> tuple[int, str]:
    signals = [Signal("mint", pct=hit.pct, detail=f"supply +{hit.pct:.1f}%")]
    senders = {item.lower() for item in hit.senders}
    watched = {item.lower() for item in case.get("watched_minters") or []}
    if senders & watched:
        signals.append(Signal("fresh_signer", detail="watched bridge minter"))
    when = datetime.fromtimestamp(case["timestamp"], timezone.utc)
    score = score_signals(signals, when=when, settings=settings, ticker=case["ticker"])
    return score.total, score.level


def replay_case(case: dict, *, live: bool = True, settings=None) -> Replay:
    settings = settings or load_settings()
    source = "fixture"
    detail = ""
    if live:
        try:
            logs, log_source = _fetch_logs(case)
            _attach_sender(case, logs)
            supply, supply_source = _fetch_supply(case)
            source = f"{log_source}; supply {supply_source}"
        except Exception as exc:
            logs, supply = _load_fixture(case)
            source = "fixture"
            detail = str(exc)
    else:
        logs, supply = _load_fixture(case)
    hit = evaluate_mint_logs(
        logs,
        contract=case["contract"],
        supply_before=supply,
        threshold_pct=settings.score.mint_supply_pct,
        block=case["block"],
    )
    total, level = _score(case, hit, settings)
    return Replay(
        name=case["name"],
        source=source,
        fired=hit.fired,
        pct=hit.pct,
        score=total,
        level=level,
        tx_hashes=hit.tx_hashes,
        detail=detail,
    )


def run_backtest(*, live: bool = True) -> list[Replay]:
    settings = load_settings()
    return [replay_case(case, live=live, settings=settings) for case in CASES]


def main() -> int:
    live = "--fixture" not in __import__("sys").argv
    results = run_backtest(live=live)
    failed = 0
    for result in results:
        status = "FIRE" if result.ok else "MISS"
        expected = next(case["expect_level"] for case in CASES if case["name"] == result.name)
        level_ok = result.level == expected
        if not result.ok or not level_ok:
            failed += 1
        print(
            f"{status} {result.name} score={result.score} level={result.level} "
            f"pct={result.pct:.2f}% via {result.source}"
        )
        if result.tx_hashes:
            print("  tx", ", ".join(result.tx_hashes))
        if result.detail:
            print("  note", result.detail[:300])
        if not level_ok:
            print(f"  expected level {expected}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
