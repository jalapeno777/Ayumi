"""Tests for DailyAnalytics."""

import json

import pytest
from analytics.daily_report import DailyAnalytics


@pytest.fixture
def trade_log(tmp_path):
    log_path = tmp_path / "trades.jsonl"
    trades = [
        {
            "timestamp": "2025-04-20T09:00:00",
            "strategy_id": "mom_v1",
            "symbol": "EURUSD",
            "direction": "LONG",
            "profile": "sniper",
            "confidence": 0.75,
            "lots": 0.5,
            "risk_amount": 50.0,
            "pnl": 25.0,
            "gate_passes": ["spread", "session"],
            "gate_rejections": [],
            "sl_distance_pips": 15.0,
        },
        {
            "timestamp": "2025-04-20T10:00:00",
            "strategy_id": "mr_v1",
            "symbol": "GBPUSD",
            "direction": "SHORT",
            "profile": "swarm",
            "confidence": 0.55,
            "lots": 0.3,
            "risk_amount": 30.0,
            "pnl": -15.0,
            "gate_passes": ["spread"],
            "gate_rejections": ["volatility"],
            "sl_distance_pips": 20.0,
        },
        {
            "timestamp": "2025-04-20T14:00:00",
            "strategy_id": "mom_v1",
            "symbol": "EURUSD",
            "direction": "LONG",
            "profile": "sniper",
            "confidence": 0.82,
            "lots": 0.5,
            "risk_amount": 50.0,
            "pnl": 40.0,
            "gate_passes": ["spread", "session"],
            "gate_rejections": [],
            "sl_distance_pips": 12.0,
        },
        {
            "timestamp": "2025-04-21T09:00:00",
            "strategy_id": "mom_v1",
            "symbol": "EURUSD",
            "direction": "SHORT",
            "profile": "sniper",
            "confidence": 0.45,
            "lots": 0.3,
            "risk_amount": 30.0,
            "pnl": -10.0,
            "gate_passes": ["spread"],
            "gate_rejections": ["session"],
            "sl_distance_pips": 18.0,
        },
    ]
    with open(log_path, "w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")
    return str(log_path)


def test_generate_report_from_trade_log(trade_log):
    analytics = DailyAnalytics(trade_log)
    report = analytics.generate_report("2025-04-20")
    assert report.date == "2025-04-20"
    assert report.total_trades == 3
    assert report.winning_trades == 2
    assert report.losing_trades == 1
    assert report.total_pnl == 50.0


def test_empty_trade_log_returns_zeros(tmp_path):
    log_path = tmp_path / "empty.jsonl"
    log_path.write_text("")
    analytics = DailyAnalytics(str(log_path))
    report = analytics.generate_report("2025-04-20")
    assert report.total_trades == 0
    assert report.win_rate == 0.0
    assert report.total_pnl == 0.0


def test_win_rate_calculation(trade_log):
    analytics = DailyAnalytics(trade_log)
    report = analytics.generate_report("2025-04-20")
    # 3 trades: 25, -15, 40 -> 2 wins, 1 loss
    assert report.win_rate == pytest.approx(2 / 3)


def test_per_strategy_breakdown(trade_log):
    analytics = DailyAnalytics(trade_log)
    report = analytics.generate_report("2025-04-20")
    assert "mom_v1" in report.per_strategy
    assert report.per_strategy["mom_v1"]["trades"] == 2
    assert report.per_strategy["mom_v1"]["pnl"] == 65.0
    assert "mr_v1" in report.per_strategy
    assert report.per_strategy["mr_v1"]["pnl"] == -15.0


def test_confidence_distribution_bucketing(trade_log):
    analytics = DailyAnalytics(trade_log)
    report = analytics.generate_report("2025-04-20")
    # confidences: 0.75 (med), 0.55 (low), 0.82 (high)
    assert report.confidence_distribution["low"] == 1
    assert report.confidence_distribution["med"] == 1
    assert report.confidence_distribution["high"] == 1


def test_format_report_produces_readable_text(trade_log):
    analytics = DailyAnalytics(trade_log)
    report = analytics.generate_report("2025-04-20")
    text = analytics.format_report(report)
    assert "2025-04-20" in text
    assert "Trades:" in text
    assert "Win Rate:" in text
    assert "PnL:" in text
    assert "Sniper:" in text
    assert "mom_v1" in text
    assert "mr_v1" in text
