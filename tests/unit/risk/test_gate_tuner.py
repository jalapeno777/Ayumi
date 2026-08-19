"""Tests for GateTuner."""

import json
from confidence.gate_tuner import (
    GateTuner,
    GateTuneResult,
    DEFAULT_MAX_SPREADS,
)


def _make_trades(symbol="EURUSD", count=30, spread=1.0, atr=0.5, win_rate=0.6, hour=10):
    """Generate synthetic trade records."""
    trades = []
    for i in range(count):
        pnl = 10.0 if i / count < win_rate else -8.0
        trades.append(
            {
                "symbol": symbol,
                "spread": spread + i * 0.1,
                "atr": atr,
                "pnl": pnl,
                "timestamp": f"2025-01-{1 + i % 28:02d}T{hour:02d}:00:00",
            }
        )
    return trades


class TestTuneSpreadGates:
    def test_tune_spread_gates_from_data(self, tmp_path):
        log = tmp_path / "trades.jsonl"
        trades = _make_trades(count=30)
        with open(log, "w") as f:
            for t in trades:
                f.write(json.dumps(t) + "\n")

        tuner = GateTuner(str(log))
        result = tuner.tune_spread_gates()
        assert "EURUSD" in result
        assert result["EURUSD"] > 0

    def test_insufficient_data_returns_defaults(self, tmp_path):
        log = tmp_path / "trades.jsonl"
        trades = _make_trades(count=5)  # below MIN_TRADES
        with open(log, "w") as f:
            for t in trades:
                f.write(json.dumps(t) + "\n")

        tuner = GateTuner(str(log))
        result = tuner.tune_spread_gates()
        assert result["EURUSD"] == DEFAULT_MAX_SPREADS.get("EURUSD", 2.0)


class TestTuneSessionGates:
    def test_tune_session_gates(self, tmp_path):
        log = tmp_path / "trades.jsonl"
        trades = _make_trades(count=30, hour=10)
        with open(log, "w") as f:
            for t in trades:
                f.write(json.dumps(t) + "\n")

        tuner = GateTuner(str(log))
        result = tuner.tune_session_gates()
        assert "EURUSD" in result
        assert isinstance(result["EURUSD"], list)


class TestTuneVolatilityGates:
    def test_tune_volatility_gates(self, tmp_path):
        log = tmp_path / "trades.jsonl"
        trades = _make_trades(count=30, atr=0.8)
        with open(log, "w") as f:
            for t in trades:
                f.write(json.dumps(t) + "\n")

        tuner = GateTuner(str(log))
        result = tuner.tune_volatility_gates()
        assert "EURUSD" in result
        low, high = result["EURUSD"]
        assert low <= high


class TestGetRecommendations:
    def test_returns_all_three(self, tmp_path):
        log = tmp_path / "trades.jsonl"
        with open(log, "w") as f:
            for t in _make_trades(count=30):
                f.write(json.dumps(t) + "\n")

        tuner = GateTuner(str(log))
        result = tuner.get_recommendations()
        assert isinstance(result, GateTuneResult)
        assert isinstance(result.spread_gates, dict)
        assert isinstance(result.session_gates, dict)
        assert isinstance(result.volatility_gates, dict)


class TestEmptyTradeLog:
    def test_empty_handles_gracefully(self, tmp_path):
        log = tmp_path / "trades.jsonl"
        log.write_text("")

        tuner = GateTuner(str(log))
        result = tuner.get_recommendations()
        assert isinstance(result, GateTuneResult)
        assert "No trade data" in result.warnings[0]
