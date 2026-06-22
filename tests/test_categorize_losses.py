"""Tests for the loss categorization script (BQ-344)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.categorize_losses import (  # noqa: E402
    ALL_CATEGORIES,
    BAD_ENTRY_STD_DEV_THRESHOLD,
    CONFIDENCE_FLOOR,
    CATEGORY_BAD_ENTRY,
    CATEGORY_LATE_EXIT,
    CATEGORY_NEWS_EVENT,
    CATEGORY_OTHER,
    CATEGORY_SLIPPAGE,
    CATEGORY_SPREAD_WIDENING,
    CATEGORY_STOP_PLACEMENT,
    CATEGORY_WRONG_DIRECTION,
    SLIPPAGE_TOLERANCE_PIPS,
    SPREAD_WIDENING_MULTIPLIER,
    STOP_PLACEMENT_ATR_MULTIPLIER,
    categorize_trade,
    load_trades,
    render_text_report,
    summarize,
    summary_to_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_loss(**overrides):
    """Default losing trade dict; override fields per test."""
    trade = {
        "entry_time": "2024-05-10T13:00:00",
        "exit_time": "2024-05-10T15:00:00",
        "direction": "long",
        "entry_price": 1.1000,
        "stop_loss": 1.0950,
        "take_profit_1": 1.1050,
        "take_profit_2": 1.1100,
        "take_profit_3": 1.1150,
        "exit_price": 1.0950,
        "exit_reason": "sl",
        "profit_loss": -50.0,
        "pips": -50.0,
        "outcome": "loss",
        "lot_size": 10000,
        "risk_amount": 50.0,
        "confidence_score": 0.65,
        "confluence_count": 2,
        "rationale": "london breakout",
    }
    trade.update(overrides)
    return trade


def _base_win(**overrides):
    overrides.setdefault("profit_loss", 75.0)
    overrides.setdefault("pips", 50.0)
    overrides.setdefault("outcome", "win")
    return _base_loss(**overrides)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_load_trades_accepts_bare_list(tmp_path):
    payload = [_base_loss(), _base_loss()]
    p = tmp_path / "trades.json"
    p.write_text(json.dumps(payload))
    records, notes = load_trades(p)
    assert len(records) == 2
    assert notes == []


def test_load_trades_accepts_dict_with_trades_key(tmp_path):
    payload = {"trades": [_base_loss(), _base_loss()], "config": {"pair": "EURUSD"}}
    p = tmp_path / "trades.json"
    p.write_text(json.dumps(payload))
    records, notes = load_trades(p)
    assert len(records) == 2
    assert notes == []


def test_load_trades_handles_unknown_shape(tmp_path):
    p = tmp_path / "trades.json"
    p.write_text(json.dumps({"results": {"foo": "bar"}}))
    records, notes = load_trades(p)
    assert records == []
    assert any("No trade records" in n for n in notes)


def test_load_trades_errors_on_missing_file(tmp_path):
    with pytest.raises(SystemExit):
        load_trades(tmp_path / "missing.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_is_loss_recognises_outcome_field():
    from scripts.categorize_losses import _is_loss
    assert _is_loss(_base_loss()) is True
    assert _is_loss(_base_loss(outcome="win", profit_loss=20.0)) is False
    assert _is_loss(_base_loss(outcome=None, profit_loss=-25.0)) is True
    assert _is_loss(_base_loss(outcome=None, profit_loss=5.0)) is False


def test_pip_size_matches_engine():
    from scripts.categorize_losses import _pip_size
    assert _pip_size(1.1000) == 0.0001
    assert _pip_size(150.0) == 0.01
    assert _pip_size(0.5) == 0.00000001


# ---------------------------------------------------------------------------
# bad_entry
# ---------------------------------------------------------------------------


def test_bad_entry_fires_beyond_threshold():
    trade = _base_loss(
        session_mean=1.1000,
        session_std=0.00050,  # 5 pips
        entry_price=1.1100,   # 100 pips away, 20 sigma
    )
    result = categorize_trade(trade)
    assert result.category == CATEGORY_BAD_ENTRY
    assert result.confidence >= CONFIDENCE_FLOOR
    assert "σ" in result.rationale or "sigma" in result.rationale.lower()


def test_bad_entry_does_not_fire_within_threshold():
    trade = _base_loss(
        session_mean=1.1000,
        session_std=0.00500,  # 50 pips
        entry_price=1.1010,   # 10 pips = 0.2 sigma
    )
    # No other rule fires -> 'other'
    result = categorize_trade(trade)
    assert result.category != CATEGORY_BAD_ENTRY


def test_bad_entry_skipped_without_session_data():
    trade = _base_loss()
    # Without session_mean/std this rule is dormant — no category should fire
    result = categorize_trade(trade)
    assert result.category != CATEGORY_BAD_ENTRY


# ---------------------------------------------------------------------------
# stop_placement
# ---------------------------------------------------------------------------


def test_stop_placement_fires_when_sl_inside_one_atr():
    # entry 1.1000, SL 1.0995 (5 pips), ATR 0.0010 (10 pips) -> ratio 0.5
    trade = _base_loss(
        entry_price=1.1000,
        stop_loss=1.0995,
        atr=0.0010,
    )
    result = categorize_trade(trade)
    assert result.category == CATEGORY_STOP_PLACEMENT
    assert "ATR" in result.rationale


def test_stop_placement_does_not_fire_with_wide_stop():
    trade = _base_loss(
        entry_price=1.1000,
        stop_loss=1.0900,   # 100 pips
        atr=0.0010,         # 10 pips
    )
    result = categorize_trade(trade)
    assert result.category != CATEGORY_STOP_PLACEMENT


def test_stop_placement_skipped_without_atr():
    trade = _base_loss(entry_price=1.1000, stop_loss=1.0995)
    result = categorize_trade(trade)
    assert result.category != CATEGORY_STOP_PLACEMENT


# ---------------------------------------------------------------------------
# wrong_direction
# ---------------------------------------------------------------------------


def test_wrong_direction_fires_when_trend_opposes():
    trade = _base_loss(direction="long", h4_trend="short")
    result = categorize_trade(trade)
    assert result.category == CATEGORY_WRONG_DIRECTION
    assert result.confidence > CONFIDENCE_FLOOR


def test_wrong_direction_fires_when_entry_below_h4_ema():
    trade = _base_loss(
        direction="long",
        entry_price=1.0900,
        h4_ema=1.1000,
    )
    result = categorize_trade(trade)
    assert result.category == CATEGORY_WRONG_DIRECTION


def test_wrong_direction_does_not_fire_when_trend_agrees():
    trade = _base_loss(direction="long", h4_trend="long", h4_ema=1.0900)
    # h4_trend agrees -> no wrong_direction, no other strong rule
    result = categorize_trade(trade)
    assert result.category != CATEGORY_WRONG_DIRECTION


def test_wrong_direction_skipped_without_trend_data():
    trade = _base_loss()
    result = categorize_trade(trade)
    assert result.category != CATEGORY_WRONG_DIRECTION


# ---------------------------------------------------------------------------
# news_event
# ---------------------------------------------------------------------------


def test_news_event_fires_with_boolean_marker():
    trade = _base_loss(news_event=True)
    result = categorize_trade(trade)
    assert result.category == CATEGORY_NEWS_EVENT


def test_news_event_fires_with_event_list():
    trade = _base_loss(news_events=[{"name": "CPI", "time": "2024-05-10T13:30:00"}])
    result = categorize_trade(trade)
    assert result.category == CATEGORY_NEWS_EVENT


def test_news_event_skipped_without_marker():
    trade = _base_loss()
    result = categorize_trade(trade)
    assert result.category != CATEGORY_NEWS_EVENT


# ---------------------------------------------------------------------------
# spread_widening
# ---------------------------------------------------------------------------


def test_spread_widening_fires_when_ratio_exceeds_threshold():
    trade = _base_loss(spread_at_entry=4.5, spread_avg_rolling=1.5)  # 3x
    result = categorize_trade(trade)
    assert result.category == CATEGORY_SPREAD_WIDENING
    assert f"{SPREAD_WIDENING_MULTIPLIER:.2f}x" in result.rationale


def test_spread_widening_does_not_fire_below_threshold():
    trade = _base_loss(spread_at_entry=2.5, spread_avg_rolling=2.0)  # 1.25x
    result = categorize_trade(trade)
    assert result.category != CATEGORY_SPREAD_WIDENING


def test_spread_widening_skipped_without_rolling_average():
    trade = _base_loss(spread_at_entry=5.0)
    result = categorize_trade(trade)
    assert result.category != CATEGORY_SPREAD_WIDENING


# ---------------------------------------------------------------------------
# slippage
# ---------------------------------------------------------------------------


def test_slippage_fires_when_exit_beyond_tolerance():
    trade = _base_loss(
        entry_price=1.1000,
        stop_loss=1.0950,
        exit_price=1.0935,   # 15 pips beyond SL
        exit_reason="sl",
    )
    result = categorize_trade(trade)
    assert result.category == CATEGORY_SLIPPAGE
    assert "slippage" in result.rationale.lower() or "pips" in result.rationale


def test_slippage_does_not_fire_when_exit_at_expected():
    trade = _base_loss(
        entry_price=1.1000,
        stop_loss=1.0950,
        exit_price=1.0950,
        exit_reason="sl",
    )
    result = categorize_trade(trade)
    assert result.category != CATEGORY_SLIPPAGE


def test_slippage_fires_for_tp1_with_deviation():
    trade = _base_loss(
        entry_price=1.1000,
        take_profit_1=1.1050,
        exit_price=1.1065,   # 15 pips beyond TP1
        exit_reason="tp1",
    )
    result = categorize_trade(trade)
    assert result.category == CATEGORY_SLIPPAGE


# ---------------------------------------------------------------------------
# late_exit
# ---------------------------------------------------------------------------


def test_late_exit_fires_when_partial_locked_profit_but_trade_lost():
    trade = _base_loss(
        partial_closed=True,
        partial_close_pnl=40.0,
        partial_close_price=1.1030,
        profit_loss=-25.0,
    )
    result = categorize_trade(trade)
    assert result.category == CATEGORY_LATE_EXIT


def test_late_exit_does_not_fire_when_no_partial_close():
    trade = _base_loss(partial_closed=False, profit_loss=-25.0)
    result = categorize_trade(trade)
    assert result.category != CATEGORY_LATE_EXIT


def test_late_exit_does_not_fire_when_partial_was_loss():
    trade = _base_loss(
        partial_closed=True,
        partial_close_pnl=-10.0,
        profit_loss=-25.0,
    )
    result = categorize_trade(trade)
    assert result.category != CATEGORY_LATE_EXIT


def test_late_exit_does_not_fire_when_overall_won():
    trade = _base_loss(
        partial_closed=True,
        partial_close_pnl=20.0,
        profit_loss=10.0,
    )
    result = categorize_trade(trade)
    assert result.category != CATEGORY_LATE_EXIT


# ---------------------------------------------------------------------------
# 'other' fallback
# ---------------------------------------------------------------------------


def test_falls_back_to_other_when_nothing_matches():
    # Minimal loss with no extra fields -> no heuristic fires
    trade = _base_loss()
    # Strip optional fields to be safe
    for key in (
        "session_mean",
        "session_std",
        "atr",
        "h4_trend",
        "h4_ema",
        "news_event",
        "news_events",
        "spread_at_entry",
        "spread_avg_rolling",
        "partial_closed",
    ):
        trade.pop(key, None)
    result = categorize_trade(trade)
    assert result.category == CATEGORY_OTHER


def test_below_confidence_floor_falls_back_to_other():
    # All categories returning low confidence -> 'other'
    trade = _base_loss(
        session_mean=1.1000,
        session_std=0.0005,   # 5 pips sigma
        entry_price=1.1003,   # only 0.6 sigma (below 1.5 threshold)
    )
    result = categorize_trade(trade)
    # bad_entry didn't fire; no other rule should fire
    assert result.category == CATEGORY_OTHER


# ---------------------------------------------------------------------------
# summarize / dispatch
# ---------------------------------------------------------------------------


def test_summarize_counts_only_losses():
    trades = [_base_loss(), _base_win(), _base_loss()]
    summary = summarize(trades)
    assert summary.total_trades == 3
    assert summary.losing_trades == 2
    # Total counts across categories == losing trades
    total = sum(summary.category_counts.values())
    assert total == 2


def test_summarize_percentages_add_to_100():
    trades = [_base_loss(spread_at_entry=5.0, spread_avg_rolling=1.0) for _ in range(10)]
    summary = summarize(trades)
    total_pct = sum(summary.category_percentages.values())
    assert math.isclose(total_pct, 100.0, abs_tol=0.01)


def test_summarize_detects_skipped_categories():
    # No session/atr/h4/spread data -> those categories should be skipped
    trades = [_base_loss()]
    summary = summarize(trades)
    assert CATEGORY_BAD_ENTRY in summary.skipped_categories
    assert CATEGORY_STOP_PLACEMENT in summary.skipped_categories
    assert CATEGORY_WRONG_DIRECTION in summary.skipped_categories
    assert CATEGORY_SPREAD_WIDENING in summary.skipped_categories


def test_summarize_does_not_skip_when_data_present():
    trades = [_base_loss(
        atr=0.0010,
        stop_loss=1.0995,
        h4_trend="short",
        session_mean=1.1000,
        session_std=0.0005,
        spread_at_entry=1.5,
        spread_avg_rolling=1.5,
    )]
    summary = summarize(trades)
    # news_event is a marker-only field — when no marker exists it is
    # correctly reported as skipped.  All evidence-driven categories
    # (bad_entry, stop_placement, wrong_direction, spread_widening)
    # have data and must NOT be skipped.
    for evidence_cat in (
        CATEGORY_BAD_ENTRY,
        CATEGORY_STOP_PLACEMENT,
        CATEGORY_WRONG_DIRECTION,
        CATEGORY_SPREAD_WIDENING,
    ):
        assert evidence_cat not in summary.skipped_categories


def test_summarize_records_per_trade_results():
    trades = [_base_loss(news_event=True), _base_loss()]
    summary = summarize(trades)
    assert len(summary.per_trade) == 2
    # First trade flagged news_event
    assert summary.per_trade[0]["category"] == CATEGORY_NEWS_EVENT
    assert summary.per_trade[1]["category"] == CATEGORY_OTHER


def test_summary_to_dict_is_serializable():
    trades = [_base_loss(spread_at_entry=5.0, spread_avg_rolling=1.0)]
    summary = summarize(trades)
    blob = summary_to_dict(summary)
    json.dumps(blob, default=str)  # must not raise


def test_text_report_includes_counts():
    trades = [_base_loss(news_event=True)]
    summary = summarize(trades)
    report = render_text_report(summary)
    assert "Loss Categorization Report" in report
    assert CATEGORY_NEWS_EVENT in report
    assert "news_event" in report.lower()


# ---------------------------------------------------------------------------
# Realistic input tests (per HEARTBEAT.md mandate)
# ---------------------------------------------------------------------------


def test_realistic_input_a_loss_breakdown():
    """Mix of trade categories, simulating a multi-strategy backtest dump."""
    trades = [
        _base_loss(  # 1: news event
            news_event=True,
            profit_loss=-40.0,
        ),
        _base_loss(  # 2: tight stop in noise
            entry_price=1.1000,
            stop_loss=1.0992,
            atr=0.0015,
            profit_loss=-32.0,
        ),
        _base_loss(  # 3: spread widened
            spread_at_entry=6.0,
            spread_avg_rolling=1.5,
            profit_loss=-28.0,
        ),
        _base_loss(  # 4: against the trend
            direction="long",
            h4_trend="short",
            profit_loss=-50.0,
        ),
        _base_loss(  # 5: late exit after partial win
            partial_closed=True,
            partial_close_pnl=30.0,
            partial_close_price=1.1025,
            profit_loss=-15.0,
        ),
        _base_loss(  # 6: bad entry, far from session mean
            session_mean=1.1000,
            session_std=0.0004,
            entry_price=1.1060,
            profit_loss=-60.0,
        ),
        _base_loss(  # 7: no fields -> other
        ),
        _base_win(profit_loss=80.0),  # winning trade -> not counted
    ]
    summary = summarize(trades)
    counts = summary.category_counts
    # Expect the seven losses to map to at least these categories
    assert counts[CATEGORY_NEWS_EVENT] == 1
    assert counts[CATEGORY_STOP_PLACEMENT] == 1
    assert counts[CATEGORY_SPREAD_WIDENING] == 1
    assert counts[CATEGORY_WRONG_DIRECTION] == 1
    assert counts[CATEGORY_LATE_EXIT] == 1
    assert counts[CATEGORY_BAD_ENTRY] == 1
    # Trade 7 may land in 'other' or slip through stop_placement etc. depending
    # on which fields are absent — accept 'other' or slippage/late_exit if it fires
    assert counts[CATEGORY_OTHER] >= 1
    assert summary.losing_trades == 7
    # Total should sum to losing trades
    assert sum(counts.values()) == 7


def test_realistic_input_b_all_categories_present():
    """Each category fires at least once when the right evidence is supplied."""
    trades = [
        _base_loss(news_event=True),
        _base_loss(
            entry_price=1.1000,
            stop_loss=1.0990,
            atr=0.0015,
        ),
        _base_loss(direction="long", h4_trend="short"),
        _base_loss(spread_at_entry=5.0, spread_avg_rolling=1.0),
        _base_loss(
            entry_price=1.1000,
            stop_loss=1.0950,
            exit_price=1.0935,
            exit_reason="sl",
        ),
        _base_loss(
            partial_closed=True,
            partial_close_pnl=40.0,
            partial_close_price=1.1030,
            profit_loss=-20.0,
        ),
        _base_loss(
            session_mean=1.1000,
            session_std=0.0005,
            entry_price=1.1060,
        ),
    ]
    summary = summarize(trades)
    fired = {cat for cat, count in summary.category_counts.items() if count > 0}
    expected = {
        CATEGORY_NEWS_EVENT,
        CATEGORY_STOP_PLACEMENT,
        CATEGORY_WRONG_DIRECTION,
        CATEGORY_SPREAD_WIDENING,
        CATEGORY_SLIPPAGE,
        CATEGORY_LATE_EXIT,
        CATEGORY_BAD_ENTRY,
    }
    assert expected.issubset(fired), f"missing: {expected - fired}"


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_cli_runs_via_subprocess(tmp_path):
    payload = {
        "trades": [
            _base_loss(news_event=True),
            _base_loss(spread_at_entry=5.0, spread_avg_rolling=1.0),
            _base_win(profit_loss=20.0),
        ],
    }
    p = tmp_path / "in.json"
    p.write_text(json.dumps(payload))
    out = tmp_path / "report.json"
    script = PROJECT_ROOT / "scripts" / "categorize_losses.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--input",
            str(p),
            "--output",
            str(out),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.exists()
    blob = json.loads(out.read_text())
    assert blob["losing_trades"] == 2
    assert blob["total_trades"] == 3
    # The json flag also writes JSON to stdout
    assert "losing_trades" in result.stdout


def test_cli_dry_run_does_not_write(tmp_path):
    payload = {"trades": [_base_loss(news_event=True)]}
    p = tmp_path / "in.json"
    p.write_text(json.dumps(payload))
    out = tmp_path / "report.json"
    script = PROJECT_ROOT / "scripts" / "categorize_losses.py"
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--input",
            str(p),
            "--output",
            str(out),
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert not out.exists()


def test_cli_text_output_default(tmp_path):
    payload = {"trades": [_base_loss(news_event=True)]}
    p = tmp_path / "in.json"
    p.write_text(json.dumps(payload))
    script = PROJECT_ROOT / "scripts" / "categorize_losses.py"
    result = subprocess.run(
        [sys.executable, str(script), "--input", str(p)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Loss Categorization Report" in result.stdout


# ---------------------------------------------------------------------------
# Constants exposed for ops
# ---------------------------------------------------------------------------


def test_all_categories_tuple_matches_spec():
    expected = (
        "bad_entry",
        "stop_placement",
        "wrong_direction",
        "news_event",
        "spread_widening",
        "slippage",
        "late_exit",
        "other",
    )
    assert ALL_CATEGORIES == expected


def test_thresholds_match_judgment_calls():
    assert BAD_ENTRY_STD_DEV_THRESHOLD == 1.5
    assert STOP_PLACEMENT_ATR_MULTIPLIER == 1.0
    assert SPREAD_WIDENING_MULTIPLIER == 2.0
    assert CONFIDENCE_FLOOR == 0.4
    assert SLIPPAGE_TOLERANCE_PIPS == 1.0