"""Ticker normalisation shared by venues and the registry."""

from __future__ import annotations

import re

_SUFFIXES = (
    "-USDT-SWAP",
    "-USD-SWAP",
    "-USDC-SWAP",
    "-PERP",
    "USDT",
    "-USDT",
    "_USDT",
    "-USDC",
    "_USDC",
    "-USD",
    "_USD",
)


def base_symbol(raw: str) -> str:
    text = (raw or "").strip().upper()
    if not text:
        return ""
    if ":" in text:
        text = text.split(":")[-1]
    for suffix in _SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text.replace("-", "").replace("_", "")


def find_tickers(text: str, known: set[str]) -> list[str]:
    if not text or not known:
        return []
    upper = text.upper()
    found: list[str] = []
    for ticker in sorted(known, key=len, reverse=True):
        if len(ticker) < 2:
            continue
        if re.search(rf"(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])", upper):
            found.append(ticker)
    return found


def short_addr(address: str | None, keep: int = 4) -> str:
    if not address:
        return ""
    addr = address.strip()
    if len(addr) <= keep * 2 + 2:
        return addr
    return f"{addr[: 2 + keep]}…{addr[-keep:]}"
