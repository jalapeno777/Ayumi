from __future__ import annotations

import pytest
from backtest.engine import Bar
from backtest.strategies import ISignalStrategy
from quant.config import (
    CorrelationConfig,
    MarkovConfig,
    PositionSizingConfig,
    QuantConfig,
    RegimeConfig,
    RegimeFilterMode,
    SizingMode,
    WalkForwardConfig,
)
from quant.pipeline import (
    PortfolioState,
    QuantPipeline,
    TradeAction,
    TradeDecision,
    ValidationResult,
)
from quant.position_sizing import fixed_fractional


class TestQuantConfig:
    def test_default_config_has_all_modules_enabled(self):
        config = QuantConfig()
        assert config.regime.enabled is True
        assert config.correlation.enabled is True
        assert config.position_sizing.enabled is True
        assert config.walk_forward.enabled is True

    def test_disabled_config(self):
        config = QuantConfig.disabled()
        assert config.regime.enabled is False
        assert config.correlation.enabled is False
        assert config.position_sizing.enabled is False
        assert config.walk_forward.enabled is False

    def test_paper_trading_preset(self):
        config = QuantConfig.paper_trading()
        assert config.regime.enabled is True
        assert config.regime.filter_mode == RegimeFilterMode.FILTER_HIGH_AND_EXTREME
        assert config.walk_forward.enabled is False
        assert config.position_sizing.mode == SizingMode.FIXED_FRACTIONAL
        assert config.position_sizing.risk_pct == 0.5

    def test_ftmo_preset(self):
        config = QuantConfig.ftmo()
        assert config.regime.enabled is True
        assert config.regime.filter_mode == RegimeFilterMode.FILTER_EXTREME
        assert config.position_sizing.mode == SizingMode.DYNAMIC
        assert config.walk_forward.enabled is True
        assert config.walk_forward.n_windows == 5

    def test_frozen_dataclass(self):
        config = QuantConfig()
        with pytest.raises(AttributeError):
            config.regime = RegimeConfig(enabled=False)

    def test_regime_config_defaults(self):
        cfg = RegimeConfig()
        assert cfg.filter_mode == RegimeFilterMode.FILTER_EXTREME
        assert cfg.min_confidence == 0.4
        assert cfg.atr_lookback == 50

    def test_correlation_config_defaults(self):
        cfg = CorrelationConfig()
        assert cfg.window == 50
        assert cfg.threshold == 0.7
        assert len(cfg.pairs) == 7

    def test_position_sizing_config_defaults(self):
        cfg = PositionSizingConfig()
        assert cfg.mode == SizingMode.FIXED_FRACTIONAL
        assert cfg.risk_pct == 1.0
        assert cfg.dynamic_min_multiplier == 0.5
        assert cfg.dynamic_max_multiplier == 1.5

    def test_walk_forward_config_defaults(self):
        cfg = WalkForwardConfig()
        assert cfg.n_windows == 3
        assert cfg.train_ratio == 0.7


class TestQuantPipeline:
    def _make_pipeline(self, config: QuantConfig | None = None) -> QuantPipeline:
        return QuantPipeline(config or QuantConfig())

    def test_accepts_trade_with_good_regime(self):
        pipeline = self._make_pipeline()
        for i in range(60):
            pipeline.update_bars(
                high=1.1 + i * 0.001,
                low=1.09 + i * 0.001,
                close=1.095 + i * 0.001,
                atr=0.005 + (i % 10) * 0.0001,
            )
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.action in (TradeAction.ACCEPT, TradeAction.RESIZE)
        assert decision.lot_size is not None
        assert decision.lot_size > 0

    def test_rejects_trade_when_regime_confidence_low(self):
        config = QuantConfig(
            regime=RegimeConfig(
                enabled=True,
                filter_mode=RegimeFilterMode.FILTER_EXTREME,
                min_confidence=0.99,
            ),
        )
        pipeline = self._make_pipeline(config)
        for i in range(60):
            pipeline.update_bars(
                high=1.1,
                low=1.09,
                close=1.095,
                atr=0.001,
            )
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.action == TradeAction.REJECT
        assert "Regime confidence" in decision.reject_reason

    def test_rejects_when_stop_loss_equals_entry(self):
        pipeline = self._make_pipeline()
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.1000,
        )
        assert decision.action == TradeAction.REJECT

    def test_returns_lot_size_with_fixed_fractional(self):
        pipeline = self._make_pipeline()
        pipeline.portfolio.balance = 100_000.0
        for i in range(60):
            pipeline.update_bars(
                high=1.1 + i * 0.001,
                low=1.09 + i * 0.001,
                close=1.095 + i * 0.001,
                atr=0.005,
            )
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.lot_size is not None
        assert decision.lot_size > 0

    def test_on_trade_closed_updates_streaks(self):
        pipeline = self._make_pipeline()
        pipeline.on_trade_closed(100.0)
        assert pipeline.portfolio.win_streak == 1
        assert pipeline.portfolio.loss_streak == 0
        assert pipeline.portfolio.total_wins == 1

        pipeline.on_trade_closed(-50.0)
        assert pipeline.portfolio.win_streak == 0
        assert pipeline.portfolio.loss_streak == 1
        assert pipeline.portfolio.total_losses == 1

    def test_on_trade_closed_updates_avg_win_loss(self):
        pipeline = self._make_pipeline()
        pipeline.on_trade_closed(100.0)
        assert pipeline.portfolio.avg_win == 100.0

        pipeline.on_trade_closed(200.0)
        assert pipeline.portfolio.avg_win == 150.0

        pipeline.on_trade_closed(-50.0)
        assert pipeline.portfolio.avg_loss == 50.0

    def test_validate_strategy_disabled(self):
        config = QuantConfig(walk_forward=WalkForwardConfig(enabled=False))
        pipeline = self._make_pipeline(config)

        class NoSignalsStrategy(ISignalStrategy):
            @property
            def name(self) -> str:
                return "No Signals Strategy"

            def evaluate(self, state):
                return None

        from datetime import datetime, timedelta

        strategy = NoSignalsStrategy()
        base_time = datetime(2024, 1, 1, 10, 0, 0)
        bars = [
            Bar(
                time=base_time + timedelta(hours=i),
                open=1.0 + i * 0.001,
                high=1.0 + i * 0.001 + 0.001,
                low=1.0 + i * 0.001,
                close=1.0 + i * 0.001,
                volume=1000.0,
            )
            for i in range(100)
        ]
        result = pipeline.validate_strategy(strategy=strategy, bars=bars)
        assert result.go_nogo is True
        assert result.walk_forward_passed is True
        assert len(result.per_window_metrics) == 0

    def test_portfolio_state_defaults(self):
        state = PortfolioState()
        assert state.balance == 100_000.0
        assert state.open_positions == {}
        assert state.win_streak == 0

    def test_disabled_config_accepts_all_trades(self):
        config = QuantConfig.disabled()
        pipeline = self._make_pipeline(config)
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.action == TradeAction.ACCEPT
        assert decision.lot_size is None

    def test_dynamic_sizing_applies_multiplier(self):
        config = QuantConfig(
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.DYNAMIC,
                risk_pct=1.0,
            ),
        )
        pipeline = self._make_pipeline(config)
        pipeline.portfolio.balance = 100_000.0

        for i in range(60):
            pipeline.update_bars(
                high=1.1 + i * 0.001,
                low=1.09 + i * 0.001,
                close=1.095 + i * 0.001,
                atr=0.005,
            )

        pipeline.on_trade_closed(100.0)
        pipeline.on_trade_closed(100.0)

        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.action == TradeAction.RESIZE
        assert decision.lot_size is not None
        assert decision.sizing_mode == "dynamic"


class TestTradeDecision:
    def test_frozen(self):
        decision = TradeDecision(
            action=TradeAction.ACCEPT,
            lot_size=0.1,
        )
        with pytest.raises(AttributeError):
            decision.lot_size = 0.2

    def test_reject_decision(self):
        decision = TradeDecision(
            action=TradeAction.REJECT,
            reject_reason="test reason",
        )
        assert decision.action == TradeAction.REJECT
        assert decision.reject_reason == "test reason"


class TestValidationResult:
    def test_frozen(self):
        result = ValidationResult(go_nogo=True, walk_forward_passed=True)
        with pytest.raises(AttributeError):
            result.go_nogo = False


class TestMarkovAdaptiveSizing:
    """Tests for the AYUAA-401 Phase 2 Markov-regime sizing layer.

    Contract under test:
        * ``MARKOV_ADAPTIVE`` is an additive layer on top of the base
          position-sizing mode. It multiplies the base lot by a
          persistence factor but never overrides it.
        * Cold start (``is_ready() is False``) returns the base lot
          untouched — the filter never reduces exposure before it has
          evidence.
        * The filter is fed transitions via ``update_bars()`` and
          learns from observed ``(prev_state, current_state)`` pairs.
        * The state space is the 6-state ``{vol}_{trend}`` lattice
          produced by the regime classifier with extreme→high and
          neutral→ranging merges.
    """

    def _make_markov_pipeline(
        self,
        min_history: int = 100,
        enabled: bool = True,
    ) -> QuantPipeline:
        config = QuantConfig(
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.MARKOV_ADAPTIVE,
                risk_pct=1.0,
            ),
            markov=MarkovConfig(
                enabled=enabled,
                min_history=min_history,
            ),
        )
        return QuantPipeline(config)

    def test_cold_start_returns_base_lot(self):
        """Cold start (filter not yet ready) → ``base_lot`` returned untouched.

        The Markov filter is initialised with 0 observations, so
        ``is_ready()`` is False. The MARKOV_ADAPTIVE branch must
        therefore leave the base lot alone — the filter never
        *reduces* exposure before it has evidence.
        """
        pipeline = self._make_markov_pipeline()

        # Push 50 bars of stable data. The regime classifier needs
        # 50 bars before it can produce a state, so we are still in
        # cold start with 0 observations and ``is_ready() is False``.
        for _ in range(50):
            pipeline.update_bars(
                high=1.1,
                low=1.09,
                close=1.095,
                atr=0.005,
            )

        # The filter should NOT be ready yet.
        assert pipeline._markov_filter is not None
        assert pipeline._markov_filter.is_ready() is False

        # Compute the base lot the way the pipeline does.
        base_lot = fixed_fractional(
            account_balance=pipeline.portfolio.balance,
            risk_pct=1.0,
            entry_price=1.1000,
            stop_loss=1.0950,
        )

        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.action in (TradeAction.ACCEPT, TradeAction.RESIZE)
        assert decision.lot_size is not None
        # Cold start: no modulation. lot_size must equal base_lot
        # within float precision.
        assert decision.lot_size == pytest.approx(base_lot, rel=1e-9)
        assert decision.sizing_mode == "markov_adaptive"

    def test_markov_filter_disabled_returns_base_lot(self):
        """If ``markov.enabled`` is False, the filter is not constructed
        and ``_apply_sizing_mode`` returns ``base_lot`` directly.
        """
        config = QuantConfig(
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.MARKOV_ADAPTIVE,
                risk_pct=1.0,
            ),
            markov=MarkovConfig(enabled=False),
        )
        pipeline = QuantPipeline(config)
        assert pipeline._markov_filter is None

        for _ in range(60):
            pipeline.update_bars(
                high=1.1,
                low=1.09,
                close=1.095,
                atr=0.005,
            )

        base_lot = fixed_fractional(
            account_balance=pipeline.portfolio.balance,
            risk_pct=1.0,
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision.lot_size is not None
        assert decision.lot_size == pytest.approx(base_lot, rel=1e-9)

    def test_warm_filter_applies_multiplier(self):
        """Once the filter is ready, ``lot_size`` is ``base_lot *
        multiplier`` where ``multiplier`` is determined by regime
        persistence.

        Two deterministic cases that avoid tier boundaries:

        1. **High persistence** (≥200 self-transitions → persistence
           well above 0.80) → exact ``1.2x`` multiplier.
        2. **Mid persistence** (~40 % self-transitions → persistence
           firmly inside the 0.35–0.50 tier) → exact ``0.8x``
           multiplier.

        Feeding ≥200 transitions ensures Laplace smoothing (alpha=1
        on a 6×6 matrix) has negligible influence on the tier
        boundary.
        """

        # -- shared setup ------------------------------------------------
        all_states = list(MarkovConfig().states)

        base_lot = fixed_fractional(
            account_balance=100_000.0,
            risk_pct=1.0,
            entry_price=1.1000,
            stop_loss=1.0950,
        )

        # Helper: push enough bars for the regime classifier to come
        # alive (≥ 50), then read the current state label.
        def _prime(pipeline: QuantPipeline) -> str:
            for _ in range(60):
                pipeline.update_bars(
                    high=1.100,
                    low=1.090,
                    close=1.095,
                    atr=0.0001,
                )
            state = pipeline._get_current_markov_state()
            assert state is not None, "regime classifier should be alive after 60 bars"
            return state

        # -- Case 1: high persistence → 1.2x ----------------------------
        pipeline_hi = self._make_markov_pipeline(min_history=20)
        current = _prime(pipeline_hi)
        flt = pipeline_hi._markov_filter
        assert flt is not None

        # Feed 200 self-transitions. With Laplace smoothing on a
        # 6-state matrix: P[i,i] = (1 + 200) / (6 + 200) ≈ 0.976,
        # firmly inside the >0.80 tier.
        for _ in range(200):
            flt.observe(current, current)
        assert flt.is_ready()

        decision_hi = pipeline_hi.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision_hi.lot_size is not None
        effective_mult_hi = decision_hi.lot_size / base_lot
        assert effective_mult_hi == pytest.approx(1.2, rel=1e-9), (
            f"high-persistence multiplier {effective_mult_hi:.4f} expected exactly 1.2"
        )

        # -- Case 2: mid persistence (~40 %) → 0.8x ---------------------
        pipeline_mid = self._make_markov_pipeline(min_history=20)
        current2 = _prime(pipeline_mid)
        flt2 = pipeline_mid._markov_filter
        assert flt2 is not None

        # Pick any other state as the "transition-to" target.
        other = next(s for s in all_states if s != current2)

        # Feed 80 self + 120 away = 200 total. Row sum for
        # current2 is 6 + 200 = 206; diagonal is 1 + 80 = 81.
        # P = 81/206 ≈ 0.393, firmly inside [0.35, 0.50) → 0.8x.
        for _ in range(80):
            flt2.observe(current2, current2)
        for _ in range(120):
            flt2.observe(current2, other)
        assert flt2.is_ready()

        decision_mid = pipeline_mid.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        assert decision_mid.lot_size is not None
        effective_mult_mid = decision_mid.lot_size / base_lot
        assert effective_mult_mid == pytest.approx(0.8, rel=1e-9), (
            f"mid-persistence multiplier {effective_mult_mid:.4f} expected exactly 0.8"
        )

    def test_update_bars_feeds_markov_filter(self):
        """``update_bars`` must call ``observe`` on the filter when
        both a previous and a current state are available.
        """
        pipeline = self._make_markov_pipeline(min_history=10)

        # The regime classifier needs 50 bars before it can produce
        # a state, so the first 50 ``update_bars`` calls produce no
        # observations. After bar 51 the first observation is
        # recorded, and every subsequent bar adds one more.
        for _ in range(50):
            pipeline.update_bars(
                high=1.1,
                low=1.09,
                close=1.095,
                atr=0.005,
            )
        assert pipeline._markov_filter is not None
        assert pipeline._markov_filter.total_observations == 0

        pipeline.update_bars(
            high=1.1,
            low=1.09,
            close=1.095,
            atr=0.005,
        )
        assert pipeline._markov_filter.total_observations == 1

        # Every subsequent bar adds one more observation.
        for _ in range(20):
            pipeline.update_bars(
                high=1.1,
                low=1.09,
                close=1.095,
                atr=0.005,
            )
        assert pipeline._markov_filter.total_observations == 21

    def test_get_current_markov_state_returns_valid_label(self):
        """``_get_current_markov_state`` must return a label drawn from
        the configured 6-state ``{vol}_{trend}`` lattice, or ``None``
        if there is not enough history.
        """
        pipeline = self._make_markov_pipeline()
        valid_states = set(pipeline._config.markov.states)

        # Not enough history → None.
        for _ in range(10):
            pipeline.update_bars(
                high=1.1,
                low=1.09,
                close=1.095,
                atr=0.005,
            )
        # 10 bars is below the 50-bar threshold inside the helper.
        assert pipeline._get_current_markov_state() is None

        # Push enough history for the regime classifier to be
        # meaningful. The state must then be one of the 6 valid
        # labels.
        for _ in range(80):
            pipeline.update_bars(
                high=1.100,
                low=1.090,
                close=1.095,
                atr=0.0001,
            )
        state = pipeline._get_current_markov_state()
        assert state is not None
        assert state in valid_states, (
            f"state {state!r} not in configured 6-state lattice"
        )

        # Spot-check the layout: lowercase word-word, no extra tiers.
        vol_part, trend_part = state.split("_")
        assert vol_part in {"low", "normal", "high"}
        assert trend_part in {"ranging", "trending"}

    def test_get_current_markov_state_merges_extreme_to_high(self):
        """The merge rule ``extreme → high`` means the helper must
        never return a label containing ``extreme``. With a long
        high-ATR history the classifier should produce ``high_``
        prefix, not ``extreme_``.
        """
        pipeline = self._make_markov_pipeline()

        # 100 bars of very high, expanding volatility. The current
        # ATR will sit at the top of the rolling window, which
        # pushes the volatility regime into the EXTREME bin. The
        # merge into the 6-state lattice must drop ``extreme_*`` and
        # surface ``high_*`` instead.
        for i in range(100):
            pipeline.update_bars(
                high=1.10 + (i * 0.01),
                low=1.09 + (i * 0.01),
                close=1.095 + (i * 0.01),
                atr=0.05 + (i * 0.005),
            )
        state = pipeline._get_current_markov_state()
        assert state is not None
        assert "extreme" not in state, f"state {state!r} should merge extreme → high"
        assert state.startswith("high_")
