"""Tests for HistoricalSignalProvider."""

import pytest
from ml.blend_optimizer import BlendConfig
from ml.signal_provider import HistoricalSignalProvider
from strategies.registry import StrategyConfig, StrategyRegistry


@pytest.fixture
def registry():
    reg = StrategyRegistry()
    reg.register(
        StrategyConfig(
            strategy_id="momentum_v1",
            name="Momentum V1",
            strategy_type="momentum",
            symbols=["EURUSD", "GBPUSD"],
            timeframes=["H1"],
            typical_confidence_range=(0.55, 0.85),
        )
    )
    reg.register(
        StrategyConfig(
            strategy_id="mean_rev_v1",
            name="Mean Reversion V1",
            strategy_type="mean_reversion",
            symbols=["USDJPY"],
            timeframes=["H4"],
            typical_confidence_range=(0.50, 0.75),
        )
    )
    return reg


@pytest.fixture
def provider(registry, tmp_path):
    return HistoricalSignalProvider(registry, data_dir=str(tmp_path / "signals"))


@pytest.fixture
def cached_signals(provider, tmp_path):
    """Pre-generate and cache signals for testing."""
    provider.generate_signals("EURUSD", "2025-01-01", "2025-03-31")
    return provider


def test_load_from_cache(cached_signals):
    signals = cached_signals.load_signals("momentum_v1", "EURUSD")
    assert len(signals) > 0
    assert signals[0]["strategy_id"] == "momentum_v1"
    assert signals[0]["symbol"] == "EURUSD"
    assert "confidence" in signals[0]
    assert "outcome_pnl" in signals[0]


def test_deterministic_generation(registry, tmp_path):
    """Same strategy + same data = same signals."""
    p1 = HistoricalSignalProvider(registry, data_dir=str(tmp_path / "sig1"))
    p1.generate_signals("EURUSD", "2025-01-01", "2025-03-31")
    s1 = p1.load_signals("momentum_v1", "EURUSD")

    p2 = HistoricalSignalProvider(registry, data_dir=str(tmp_path / "sig2"))
    p2.generate_signals("EURUSD", "2025-01-01", "2025-03-31")
    s2 = p2.load_signals("momentum_v1", "EURUSD")

    assert len(s1) == len(s2)
    for a, b in zip(s1, s2):  # noqa: B905
        assert a == b


def test_get_signals_for_blend(cached_signals):
    config = BlendConfig(
        active_strategies={"momentum_v1": True, "mean_rev_v1": False},
        strategy_weights={"momentum_v1": 0.7},
        allowed_symbols={"momentum_v1": ["EURUSD"]},
        sniper_threshold=0.7,
        swarm_threshold=0.4,
    )
    signals = cached_signals.get_signals_for_blend(config)
    assert len(signals) > 0
    assert all(s["strategy_id"] == "momentum_v1" for s in signals)
    assert all(s["symbol"] == "EURUSD" for s in signals)


def test_has_cache(cached_signals):
    assert cached_signals.has_cache("momentum_v1", "EURUSD") is True
    assert cached_signals.has_cache("mean_rev_v1", "GBPUSD") is False


def test_empty_cache_handling(provider):
    signals = provider.load_signals("nonexistent", "EURUSD")
    assert signals == []


def test_signal_filtering_by_symbol(cached_signals):
    # Generate signals for a second symbol
    cached_signals.generate_signals("GBPUSD", "2025-01-01", "2025-03-31")
    all_signals = cached_signals.load_signals("momentum_v1")
    eurusd_signals = cached_signals.load_signals("momentum_v1", "EURUSD")
    gbpusd_signals = cached_signals.load_signals("momentum_v1", "GBPUSD")

    assert len(all_signals) == len(eurusd_signals) + len(gbpusd_signals)
    assert all(s["symbol"] == "EURUSD" for s in eurusd_signals)
    assert all(s["symbol"] == "GBPUSD" for s in gbpusd_signals)
