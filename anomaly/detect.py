"""Pure mint / supply detector used live and by the historical backtest."""

from __future__ import annotations

from dataclasses import dataclass, field

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


@dataclass
class MintHit:
    fired: bool
    amount_raw: int
    supply_before: int
    pct: float
    tx_hashes: list[str] = field(default_factory=list)
    recipients: list[str] = field(default_factory=list)
    senders: list[str] = field(default_factory=list)
    block: int | None = None


def topic_address(topic: str) -> str:
    raw = topic.lower().removeprefix("0x")
    return "0x" + raw[-40:]


def is_zero_topic(topic: str) -> bool:
    try:
        return int(topic, 16) == 0
    except (TypeError, ValueError):
        return False


def decode_uint(data: str | None) -> int:
    if not data or data in {"0x", "0x0"}:
        return 0
    return int(data, 16)


def pct_of(amount: int, supply_before: int) -> float:
    if amount <= 0:
        return 0.0
    if supply_before <= 0:
        return 100.0
    return (amount * 100.0) / supply_before


def human_amount(amount_raw: int, decimals: int) -> float:
    return amount_raw / float(10 ** decimals)


def evaluate_mint_logs(
    logs: list[dict],
    *,
    contract: str,
    supply_before: int,
    threshold_pct: float,
    block: int | None = None,
) -> MintHit:
    """Sum Transfer events from the zero address for one contract.

    A hit fires when the summed mint is at least `threshold_pct` of the
    supply observed before those logs. Callers pass one block or a short
    window; the live source uses the same function.
    """
    target = contract.lower()
    amount = 0
    txs: list[str] = []
    recipients: list[str] = []
    senders: list[str] = []
    seen_tx: set[str] = set()
    hit_block = block
    for log in logs:
        topics = [str(t) for t in (log.get("topics") or [])]
        if len(topics) < 3:
            continue
        if topics[0].lower() != TRANSFER_TOPIC:
            continue
        if str(log.get("address", "")).lower() != target:
            continue
        if not is_zero_topic(topics[1]):
            continue
        value = decode_uint(log.get("data"))
        if value <= 0:
            continue
        amount += value
        tx = str(log.get("transactionHash") or log.get("transaction_hash") or "")
        if tx and tx not in seen_tx:
            seen_tx.add(tx)
            txs.append(tx)
        recipients.append(topic_address(topics[2]))
        sender = log.get("tx_from") or log.get("from")
        if sender:
            senders.append(str(sender).lower())
        if hit_block is None and log.get("blockNumber") is not None:
            raw_block = log["blockNumber"]
            hit_block = int(raw_block, 16) if isinstance(raw_block, str) else int(raw_block)
    pct = pct_of(amount, supply_before)
    return MintHit(
        fired=pct + 1e-12 >= threshold_pct and amount > 0,
        amount_raw=amount,
        supply_before=supply_before,
        pct=pct,
        tx_hashes=txs,
        recipients=recipients,
        senders=senders,
        block=hit_block,
    )
