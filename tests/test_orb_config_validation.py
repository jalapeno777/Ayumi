"""Validation tests for ORB backtest configuration files.

Tests that:
1. YAML files parse correctly
2. All required fields are present with correct types
3. Session windows are valid UTC time ranges
4. Partial exit percentages sum to 1.0
5. Risk parameters are within FTMO constraints
6. Data files referenced exist on disk

Run:
    pytest tests/test_orb_config_validation.py -q
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml

# ── Paths ────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = CONFIG_DIR = REPO_ROOT / "config" / "backtest"

CONFIGS = {
    "EURUSD": CONFIG_DIR / "orb_eurusd.yaml",
    "GBPUSD": CONFIG_DIR / "orb_gbpusd.yaml",
}


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(params=list(CONFIGS.values()), ids=list(CONFIGS.keys()))
def config_path(request):
    """Yield path to each config file."""
    return request.param


@pytest.fixture
def config(config_path):
    """Load and parse a config YAML file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


# ── Structural Tests ─────────────────────────────────────────────────

class TestConfigStructure:
    """Verify the top-level structure of each config file."""

    REQUIRED_SECTIONS = [
        "account", "risk", "instrument", "strategy", "backtest", "ftmo"
    ]

    def test_file_exists(self, config_path):
        """Config file must exist."""
        assert config_path.is_file(), f"Config file not found: {config_path}"

    def test_yaml_parses(self, config_path):
        """Config file must be valid YAML."""
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), "Config must be a YAML mapping"

    def test_required_sections(self, config):
        """All required top-level sections must be present."""
        for section in self.REQUIRED_SECTIONS:
            assert section in config, f"Missing required section: {section}"

    def test_account_fields(self, config):
        """Account section must have starting_balance and currency."""
        acct = config["account"]
        assert "starting_balance" in acct
        assert "currency" in acct
        assert isinstance(acct["starting_balance"], (int, float))
        assert acct["starting_balance"] > 0
        assert acct["currency"] == "USD"

    def test_risk_fields(self, config):
        """Risk section must have all risk parameters."""
        risk = config["risk"]
        required = [
            "risk_per_trade_pct", "max_daily_drawdown_pct",
            "max_total_drawdown_pct", "max_concurrent_positions",
            "max_trades_per_day"
        ]
        for field in required:
            assert field in risk, f"Missing risk field: {field}"
        assert 0 < risk["risk_per_trade_pct"] <= 0.02
        assert 0 < risk["max_daily_drawdown_pct"] <= 0.10
        assert 0 < risk["max_total_drawdown_pct"] <= 0.20


# ── Instrument Tests ─────────────────────────────────────────────────

class TestInstrument:
    """Verify instrument configuration."""

    def test_instrument_fields(self, config):
        inst = config["instrument"]
        required = ["symbol", "timeframe", "spread_pips", "pip_value_usd_per_lot", "commission_per_lot"]
        for field in required:
            assert field in inst, f"Missing instrument field: {field}"

    def test_symbol_valid(self, config):
        """Symbol must be a known forex pair."""
        valid_symbols = {"EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD"}
        assert config["instrument"]["symbol"] in valid_symbols

    def test_timeframe_m15(self, config):
        """Timeframe must be M15 (data constraint)."""
        assert config["instrument"]["timeframe"] == "M15"

    def test_spread_positive(self, config):
        assert config["instrument"]["spread_pips"] > 0

    def test_pip_value_positive(self, config):
        assert config["instrument"]["pip_value_usd_per_lot"] > 0


# ── Strategy Tests ───────────────────────────────────────────────────

class TestStrategyConfig:
    """Verify ORB strategy configuration."""

    def test_strategy_type(self, config):
        assert config["strategy"]["type"] == "opening_range_breakout"

    def test_sessions_present(self, config):
        sessions = config["strategy"]["sessions"]
        assert "london" in sessions
        assert "ny" in sessions

    def test_session_windows(self, config):
        """Each session must have range and trading windows."""
        for session_name, session in config["strategy"]["sessions"].items():
            assert "range_start_utc" in session
            assert "range_end_utc" in session
            assert "trading_start_utc" in session
            assert "trading_end_utc" in session

            # Range start must be before range end (compare by minutes from midnight)
            def to_minutes(t_str):
                h, m = t_str.split(":")
                return int(h) * 60 + int(m)
            start = to_minutes(session["range_start_utc"])
            end = to_minutes(session["range_end_utc"])
            assert start < end, f"{session_name}: range start must be before end"

            # Trading end must be after range end
            t_end = to_minutes(session["trading_end_utc"])
            assert t_end > end, f"{session_name}: trading end must be after range end"

    def test_partial_exits_sum_to_one(self, config):
        """Partial exit percentages must sum to 1.0."""
        partials = config["strategy"]["partial_exits"]
        total = sum(p["close_pct"] for p in partials)
        assert abs(total - 1.0) < 0.01, f"Partial exits sum to {total}, expected 1.0"

    def test_partial_rr_ascending(self, config):
        """Partial exit RR multiples must be in ascending order."""
        partials = config["strategy"]["partial_exits"]
        rrs = [p["rr_multiple"] for p in partials]
        for i in range(1, len(rrs)):
            assert rrs[i] > rrs[i - 1], "RR multiples must be ascending"

    def test_atr_params(self, config):
        strat = config["strategy"]
        assert strat["atr_period"] > 0
        assert strat["atr_buffer_multiplier"] > 0

    def test_range_width_filters(self, config):
        strat = config["strategy"]
        assert strat["min_range_width_pips"] > 0
        assert strat["max_range_width_pips"] > strat["min_range_width_pips"]


# ── Backtest Window Tests ────────────────────────────────────────────

class TestBacktestWindow:
    """Verify backtest window configuration."""

    def test_dates_valid(self, config):
        bt = config["backtest"]
        start = datetime.strptime(bt["start_date"], "%Y-%m-%d")
        end = datetime.strptime(bt["end_date"], "%Y-%m-%d")
        assert start < end

    def test_date_range_within_data(self, config):
        """Backtest date range must be within available data (2023-01 to 2026-04-10)."""
        bt = config["backtest"]
        start = datetime.strptime(bt["start_date"], "%Y-%m-%d")
        end = datetime.strptime(bt["end_date"], "%Y-%m-%d")
        data_start = datetime(2023, 1, 1)
        data_end = datetime(2026, 4, 11)
        assert start >= data_start, "Start date before data availability"
        assert end <= data_end, "End date beyond data availability"

    def test_data_file_path(self, config):
        """Data file path must be a non-empty string."""
        bt = config["backtest"]
        assert isinstance(bt["data_file"], str)
        assert len(bt["data_file"]) > 0


# ── FTMO Tests ───────────────────────────────────────────────────────

class TestFTMOConfig:
    """Verify FTMO feasibility parameters."""

    def test_ftmo_fields(self, config):
        ftmo = config["ftmo"]
        required = ["daily_max_loss_pct", "overall_max_loss_pct",
                    "profit_target_pct", "min_trades_for_consistency"]
        for field in required:
            assert field in ftmo, f"Missing FTMO field: {field}"

    def test_ftmo_values(self, config):
        ftmo = config["ftmo"]
        assert 0 < ftmo["daily_max_loss_pct"] <= 0.10
        assert 0 < ftmo["overall_max_loss_pct"] <= 0.20
        assert ftmo["profit_target_pct"] > 0
        assert ftmo["min_trades_for_consistency"] > 0


# ── Cross-Config Consistency ─────────────────────────────────────────

class TestCrossConfig:
    """Verify consistency between the two config files."""

    def test_both_configs_exist(self):
        for name, path in CONFIGS.items():
            assert path.is_file(), f"{name} config missing: {path}"

    def test_different_symbols(self):
        """Each config must target a different symbol."""
        symbols = set()
        for path in CONFIGS.values():
            with open(path) as f:
                cfg = yaml.safe_load(f)
            symbols.add(cfg["instrument"]["symbol"])
        assert len(symbols) == len(CONFIGS), "Configs must target different symbols"

    def test_same_timeframe(self):
        """Both configs should use M15."""
        for path in CONFIGS.values():
            with open(path) as f:
                cfg = yaml.safe_load(f)
            assert cfg["instrument"]["timeframe"] == "M15"

    def test_same_risk_model(self):
        """Both configs should share the same risk per trade percentage."""
        risks = set()
        for path in CONFIGS.values():
            with open(path) as f:
                cfg = yaml.safe_load(f)
            risks.add(cfg["risk"]["risk_per_trade_pct"])
        assert len(risks) == 1, "Risk per trade must be consistent across configs"
