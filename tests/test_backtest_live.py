"""Replay ACE and SAND from free archive RPCs. Same detector as the live watcher."""

from anomaly.backtest import CASES, run_backtest


def test_live_historical_replay_fires():
    results = run_backtest(live=True)
    assert len(results) == len(CASES)
    for result, case in zip(results, CASES):
        assert result.fired, (result.name, result.detail)
        assert result.pct > 5
        assert result.level == case["expect_level"], result
        assert result.source.startswith("live"), (result.source, result.detail)
        assert case["tx"].lower() in {tx.lower() for tx in result.tx_hashes}
