"""Tests for portfolio risk wiring — verifies that CorrelationAwareSizer
and Kelly criterion options are properly wired into the live execution path.

Covers SRB-AYUMI-012 acceptance criteria:
    AC1: CorrelationAwareSizer instantiated in HybridEngine, cli.py, paper_trader.py
    AC2: grep -rn "CorrelationAwareSizer" src/forex-bot/hybrid/ returns hits
    AC3: Kelly criterion available as opt-in via config flag (default: off)
    AC4: test_portfolio_risk_wiring.py verifies live path instantiates correlation sizer
"""

from __future__ import annotations

import pytest

from hybrid.engine import HybridEngine, HybridEngineConfig
from hybrid.cli import create_engine
from hybrid.paper_trader import HybridPaperTrader
from hybrid.risk_manager import RiskManager
from risk.correlation_matrix import CorrelationMatrix
from risk.correlation_sizer import CorrelationAwareSizer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_correlation_matrix() -> CorrelationMatrix:
    """A CorrelationMatrix with sample returns for EURUSD and GBPUSD."""
    cm = CorrelationMatrix(window=10)
    cm.add_returns("EURUSD", [0.001, -0.002, 0.003, 0.001, -0.001,
                              0.002, -0.001, 0.001, 0.003, -0.002])
    cm.add_returns("GBPUSD", [0.002, -0.001, 0.002, 0.002, -0.002,
                              0.001, -0.002, 0.002, 0.002, -0.001])
    cm.compute()
    return cm


@pytest.fixture
def sample_correlation_sizer(
    sample_correlation_matrix: CorrelationMatrix,
) -> CorrelationAwareSizer:
    """A CorrelationAwareSizer with the sample correlation matrix."""
    return CorrelationAwareSizer(
        correlation_matrix=sample_correlation_matrix,
        per_trade_risk_pct=0.005,
        aggregate_risk_pct=0.01,
    )


# ---------------------------------------------------------------------------
# AC1 + AC4: CorrelationAwareSizer wired into HybridEngine
# ---------------------------------------------------------------------------


class TestHybridEngineWiring:
    """Verify CorrelationAwareSizer is wired into HybridEngine's RiskManager."""

    def test_engine_accepts_correlation_sizer(
        self, sample_correlation_sizer: CorrelationAwareSizer
    ) -> None:
        """HybridEngine should accept and pass correlation_sizer to RiskManager."""
        engine = HybridEngine(
            correlation_sizer=sample_correlation_sizer,
            starting_balance=100_000.0,
        )
        assert engine.risk_manager._correlation_sizer is sample_correlation_sizer

    def test_engine_default_no_correlation_sizer(self) -> None:
        """Without correlation_sizer, RiskManager should have None."""
        engine = HybridEngine(starting_balance=100_000.0)
        assert engine.risk_manager._correlation_sizer is None

    def test_engine_with_explicit_risk_manager_keeps_sizer(
        self, sample_correlation_sizer: CorrelationAwareSizer
    ) -> None:
        """When passing an explicit RiskManager, its correlation_sizer is preserved."""
        rm = RiskManager(
            starting_balance=50_000.0,
            correlation_sizer=sample_correlation_sizer,
        )
        engine = HybridEngine(risk_manager=rm, starting_balance=50_000.0)
        assert engine.risk_manager._correlation_sizer is sample_correlation_sizer


# ---------------------------------------------------------------------------
# AC1 + AC4: CorrelationAwareSizer wired into cli.create_engine
# ---------------------------------------------------------------------------


class TestCliWiring:
    """Verify CorrelationAwareSizer is wired via cli.create_engine."""

    def test_create_engine_with_correlation_matrix(
        self, sample_correlation_matrix: CorrelationMatrix
    ) -> None:
        """create_engine should instantiate CorrelationAwareSizer when matrix is provided."""
        engine = create_engine(
            starting_balance=100_000.0,
            correlation_matrix=sample_correlation_matrix,
        )
        assert engine.risk_manager._correlation_sizer is not None
        assert isinstance(
            engine.risk_manager._correlation_sizer, CorrelationAwareSizer
        )

    def test_create_engine_without_correlation_matrix(self) -> None:
        """create_engine without matrix should result in no correlation_sizer."""
        engine = create_engine(starting_balance=100_000.0)
        assert engine.risk_manager._correlation_sizer is None


# ---------------------------------------------------------------------------
# AC1 + AC4: CorrelationAwareSizer wired into HybridPaperTrader
# ---------------------------------------------------------------------------


class TestPaperTraderWiring:
    """Verify CorrelationAwareSizer is wired into HybridPaperTrader."""

    def test_paper_trader_accepts_correlation_sizer(
        self, sample_correlation_sizer: CorrelationAwareSizer
    ) -> None:
        """HybridPaperTrader should pass correlation_sizer through to its HybridEngine."""
        trader = HybridPaperTrader(
            starting_balance=100_000.0,
            correlation_sizer=sample_correlation_sizer,
        )
        assert trader._engine.risk_manager._correlation_sizer is sample_correlation_sizer

    def test_paper_trader_default_no_correlation_sizer(self) -> None:
        """HybridPaperTrader without correlation_sizer should have None in its RiskManager."""
        trader = HybridPaperTrader(starting_balance=100_000.0)
        assert trader._engine.risk_manager._correlation_sizer is None


# ---------------------------------------------------------------------------
# AC3: Kelly criterion opt-in via config flag (default off)
# ---------------------------------------------------------------------------


class TestKellyConfigFlag:
    """Verify Kelly criterion is opt-in via config, default off."""

    def test_kelly_defaults_off(self) -> None:
        """HybridEngineConfig should default use_kelly_sizing to False."""
        config = HybridEngineConfig()
        assert config.use_kelly_sizing is False

    def test_kelly_can_be_enabled(self) -> None:
        """HybridEngineConfig should allow use_kelly_sizing=True."""
        config = HybridEngineConfig(use_kelly_sizing=True)
        assert config.use_kelly_sizing is True

    def test_engine_reflects_kelly_config(self) -> None:
        """HybridEngine should reflect the Kelly config flag."""
        config = HybridEngineConfig(use_kelly_sizing=True)
        engine = HybridEngine(config=config, starting_balance=100_000.0)
        assert engine._config.use_kelly_sizing is True

    def test_paper_trader_accepts_kelly_flag(
        self, sample_correlation_sizer: CorrelationAwareSizer
    ) -> None:
        """HybridPaperTrader should accept and pass use_kelly_sizing to config."""
        trader = HybridPaperTrader(
            starting_balance=100_000.0,
            correlation_sizer=sample_correlation_sizer,
            use_kelly_sizing=True,
        )
        assert trader._engine._config.use_kelly_sizing is True

    def test_create_engine_accepts_kelly_flag(
        self, sample_correlation_matrix: CorrelationMatrix
    ) -> None:
        """create_engine should accept and pass use_kelly_sizing."""
        engine = create_engine(
            starting_balance=100_000.0,
            correlation_matrix=sample_correlation_matrix,
            use_kelly_sizing=True,
        )
        assert engine._config.use_kelly_sizing is True
