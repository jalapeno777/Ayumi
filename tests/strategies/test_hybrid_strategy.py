import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from backtest.engine import Bar, TradeDirection
from backtest.hybrid_strategy import (
    HybridConfig,
    HybridStrategy,
    QuantFilterName,
    RejectionMetrics,
)
from backtest.ict_smc.models import ConfluenceSignal, ICTMarketState, SignalStrength


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005):
    base = datetime(2024, 1, 1, 10, 0)
    return Bar(time=base + timedelta(hours=i), open=o, high=h, low=low, close=c)


def _h4_bar(i, o=1.0, h=1.01, low=0.99, c=1.005):
    base = datetime(2024, 1, 1)
    return Bar(time=base + timedelta(hours=i * 4), open=o, high=h, low=low, close=c)


def _make_ict_state(n=50, price_step=0.0001):
    bars = []
    for i in range(n):
        p = 1.0 + i * price_step
        bars.append(_bar(i, o=p, h=p + 0.0005, low=p - 0.0005, c=p + 0.0002))
    state = ICTMarketState(bars)
    state.atr = 0.001
    return state


def _make_confluence_signal(
    direction=TradeDirection.LONG,
    confidence=0.7,
) -> ConfluenceSignal:
    base = datetime(2024, 1, 1, 10, 0)
    return ConfluenceSignal(
        direction=direction,
        strength=SignalStrength.STRONG,
        confidence_score=confidence,
        entry_price=1.0010,
        stop_loss=0.9980,
        take_profit_1=1.0040,
        take_profit_2=1.0070,
        take_profit_3=1.0100,
        signal_time=base,
        rationale="Test signal",
        confluence_count=3,
        risk_reward_ratio=2.0,
    )


def _make_h4_bars(n=50):
    bars = []
    for i in range(n):
        p = 1.0 + i * 0.0001
        bars.append(_h4_bar(i, o=p, h=p + 0.001, low=p - 0.001, c=p + 0.0005))
    return bars


class TestHybridConfig(unittest.TestCase):
    def test_defaults(self):
        config = HybridConfig()
        self.assertEqual(config.min_confidence, 0.5)
        self.assertEqual(config.volatility_threshold_percentile, 30.0)
        self.assertEqual(config.trend_threshold_adx, 20.0)
        self.assertEqual(len(config.enabled_filters), 3)

    def test_custom_filters(self):
        config = HybridConfig(enabled_filters=(QuantFilterName.VOLATILITY,))
        self.assertEqual(len(config.enabled_filters), 1)
        self.assertIn(QuantFilterName.VOLATILITY, config.enabled_filters)


class TestRejectionMetrics(unittest.TestCase):
    def test_initial_state(self):
        metrics = RejectionMetrics()
        self.assertEqual(metrics.total_evaluated, 0)
        self.assertEqual(metrics.passed, 0)
        self.assertEqual(metrics.rejection_rate, 0.0)

    def test_rejection_rate(self):
        metrics = RejectionMetrics(total_evaluated=10, passed=7)
        self.assertAlmostEqual(metrics.rejection_rate, 0.3)

    def test_rejection_rate_zero_evaluated(self):
        metrics = RejectionMetrics()
        self.assertEqual(metrics.rejection_rate, 0.0)

    def test_to_dict(self):
        metrics = RejectionMetrics(
            total_evaluated=5,
            rejected_by_confidence=1,
            rejected_by_volatility=1,
            passed=3,
        )
        d = metrics.to_dict()
        self.assertEqual(d["total_evaluated"], 5)
        self.assertEqual(d["passed"], 3)


class TestHybridStrategy(unittest.TestCase):
    def _make_strategy(self, config=None, ict_engine=None):
        return HybridStrategy(config=config, ict_engine=ict_engine)

    def test_name(self):
        strategy = self._make_strategy()
        self.assertEqual(strategy.name, "Hybrid ICT/SMC + Quantitative Filter")

    def test_signal_passes_when_both_layers_agree(self):
        signal = _make_confluence_signal(confidence=0.7)
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = signal

        mock_h4 = MagicMock()
        mock_h4.analyze.return_value = MagicMock(bullish_score=0.8, bearish_score=0.1)

        strategy = self._make_strategy(ict_engine=mock_engine)
        strategy._h4_module = mock_h4
        ict_state = _make_ict_state()
        h4_bars = _make_h4_bars()
        atr_series = [0.001 + i * 0.00001 for i in range(60)]

        result = strategy.evaluate(
            ict_state,
            h4_bars=h4_bars,
            atr_series=atr_series,
            high_series=[b.high for b in ict_state.bars],
            low_series=[b.low for b in ict_state.bars],
            close_series=[b.close for b in ict_state.bars],
            bar_time=ict_state.latest_bar.time,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.direction, TradeDirection.LONG)
        self.assertAlmostEqual(result.confidence, 0.7)
        self.assertEqual(strategy.metrics.passed, 1)

    def test_signal_rejected_when_ict_confidence_too_low(self):
        signal = _make_confluence_signal(confidence=0.3)
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = signal

        config = HybridConfig(min_confidence=0.5)
        strategy = self._make_strategy(config=config, ict_engine=mock_engine)
        ict_state = _make_ict_state()

        result = strategy.evaluate(ict_state)

        self.assertIsNone(result)
        self.assertEqual(strategy.metrics.rejected_by_confidence, 1)
        self.assertEqual(strategy.metrics.passed, 0)

    def test_signal_rejected_when_volatility_too_low(self):
        signal = _make_confluence_signal(confidence=0.7)
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = signal

        config = HybridConfig(
            enabled_filters=(QuantFilterName.VOLATILITY,),
            volatility_threshold_percentile=50.0,
        )
        strategy = self._make_strategy(config=config, ict_engine=mock_engine)
        ict_state = _make_ict_state()

        low_atr = [0.001] * 50 + [0.0005]
        result = strategy.evaluate(ict_state, atr_series=low_atr)

        self.assertIsNone(result)
        self.assertEqual(strategy.metrics.rejected_by_volatility, 1)

    def test_signal_rejected_when_trend_too_low(self):
        signal = _make_confluence_signal(confidence=0.7)
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = signal

        config = HybridConfig(
            enabled_filters=(QuantFilterName.TREND,),
            trend_threshold_adx=25.0,
        )
        strategy = self._make_strategy(config=config, ict_engine=mock_engine)
        ict_state = _make_ict_state(n=50)

        flat_close = [1.0] * 50
        flat_high = [1.0001] * 50
        flat_low = [0.9999] * 50

        result = strategy.evaluate(
            ict_state,
            high_series=flat_high,
            low_series=flat_low,
            close_series=flat_close,
        )

        self.assertIsNone(result)
        self.assertEqual(strategy.metrics.rejected_by_trend, 1)

    def test_signal_rejected_when_h4_misaligned(self):
        signal = _make_confluence_signal(direction=TradeDirection.LONG, confidence=0.7)
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = signal

        mock_h4 = MagicMock()
        mock_h4.analyze.return_value = MagicMock(bullish_score=0.1, bearish_score=0.8)

        config = HybridConfig(
            enabled_filters=(QuantFilterName.H4_ALIGNMENT,),
        )
        strategy = self._make_strategy(config=config, ict_engine=mock_engine)
        strategy._h4_module = mock_h4

        ict_state = _make_ict_state()
        h4_bars = _make_h4_bars()

        result = strategy.evaluate(
            ict_state,
            h4_bars=h4_bars,
        )

        self.assertIsNone(result)
        self.assertEqual(strategy.metrics.rejected_by_h4_alignment, 1)

    def test_no_ict_signal_returns_none(self):
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = None

        strategy = self._make_strategy(ict_engine=mock_engine)
        ict_state = _make_ict_state()

        result = strategy.evaluate(ict_state)

        self.assertIsNone(result)
        self.assertEqual(strategy.metrics.total_evaluated, 1)
        self.assertEqual(strategy.metrics.passed, 0)

    def test_disable_all_quant_filters_signal_passes(self):
        signal = _make_confluence_signal(confidence=0.6)
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = signal

        config = HybridConfig(enabled_filters=())
        strategy = self._make_strategy(config=config, ict_engine=mock_engine)
        ict_state = _make_ict_state()

        result = strategy.evaluate(ict_state)

        self.assertIsNotNone(result)
        self.assertEqual(strategy.metrics.passed, 1)

    def test_selective_filter_disable(self):
        signal = _make_confluence_signal(confidence=0.7)
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = signal

        config = HybridConfig(
            enabled_filters=(QuantFilterName.VOLATILITY,),
        )
        strategy = self._make_strategy(config=config, ict_engine=mock_engine)
        ict_state = _make_ict_state()

        atr_series = [0.001 + i * 0.00001 for i in range(60)]
        result = strategy.evaluate(
            ict_state,
            atr_series=atr_series,
        )

        self.assertIsNotNone(result)
        self.assertEqual(strategy.metrics.passed, 1)

    def test_metrics_tracked_across_multiple_evaluations(self):
        mock_engine = MagicMock()

        high_signal = _make_confluence_signal(
            direction=TradeDirection.LONG, confidence=0.7
        )
        low_conf_signal = _make_confluence_signal(confidence=0.3)
        mock_engine.evaluate.side_effect = [
            high_signal,
            low_conf_signal,
            high_signal,
        ]

        mock_h4 = MagicMock()
        mock_h4.analyze.return_value = MagicMock(bullish_score=0.8, bearish_score=0.1)

        config = HybridConfig(min_confidence=0.5)
        strategy = self._make_strategy(config=config, ict_engine=mock_engine)
        strategy._h4_module = mock_h4
        ict_state = _make_ict_state()
        h4_bars = _make_h4_bars()
        atr_series = [0.001 + i * 0.00001 for i in range(60)]

        strategy.evaluate(
            ict_state,
            h4_bars=h4_bars,
            atr_series=atr_series,
            high_series=[b.high for b in ict_state.bars],
            low_series=[b.low for b in ict_state.bars],
            close_series=[b.close for b in ict_state.bars],
            bar_time=ict_state.latest_bar.time,
        )
        strategy.evaluate(ict_state)
        strategy.evaluate(
            ict_state,
            h4_bars=h4_bars,
            atr_series=atr_series,
            high_series=[b.high for b in ict_state.bars],
            low_series=[b.low for b in ict_state.bars],
            close_series=[b.close for b in ict_state.bars],
            bar_time=ict_state.latest_bar.time,
        )

        self.assertEqual(strategy.metrics.total_evaluated, 3)
        self.assertEqual(strategy.metrics.passed, 2)
        self.assertEqual(strategy.metrics.rejected_by_confidence, 1)
        self.assertAlmostEqual(strategy.metrics.rejection_rate, 1 / 3)

    def test_reset_metrics(self):
        strategy = self._make_strategy()
        strategy.metrics.total_evaluated = 10
        strategy.metrics.passed = 5

        strategy.reset_metrics()

        self.assertEqual(strategy.metrics.total_evaluated, 0)
        self.assertEqual(strategy.metrics.passed, 0)

    def test_convert_signal_preserves_fields(self):
        ict_signal = _make_confluence_signal(confidence=0.75)
        result = HybridStrategy._convert_signal(ict_signal)

        self.assertEqual(result.direction, ict_signal.direction)
        self.assertAlmostEqual(result.confidence, ict_signal.confidence_score)
        self.assertEqual(result.entry_price, ict_signal.entry_price)
        self.assertEqual(result.stop_loss, ict_signal.stop_loss)
        self.assertEqual(result.take_profit_1, ict_signal.take_profit_1)
        self.assertEqual(result.take_profit_2, ict_signal.take_profit_2)
        self.assertEqual(result.take_profit_3, ict_signal.take_profit_3)
        self.assertEqual(result.rationale, ict_signal.rationale)

    def test_missing_quant_data_passes_filter(self):
        signal = _make_confluence_signal(confidence=0.7)
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = signal

        strategy = self._make_strategy(ict_engine=mock_engine)
        ict_state = _make_ict_state()

        result = strategy.evaluate(ict_state)

        self.assertIsNotNone(result)
        self.assertEqual(strategy.metrics.passed, 1)

    def test_short_signal_with_h4_alignment(self):
        signal = _make_confluence_signal(direction=TradeDirection.SHORT, confidence=0.7)
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = signal

        mock_h4 = MagicMock()
        mock_h4.analyze.return_value = MagicMock(bullish_score=0.1, bearish_score=0.8)

        config = HybridConfig(
            enabled_filters=(QuantFilterName.H4_ALIGNMENT,),
        )
        strategy = self._make_strategy(config=config, ict_engine=mock_engine)
        strategy._h4_module = mock_h4

        ict_state = _make_ict_state()
        result = strategy.evaluate(ict_state, h4_bars=_make_h4_bars())

        self.assertIsNotNone(result)
        self.assertEqual(result.direction, TradeDirection.SHORT)


if __name__ == "__main__":
    unittest.main()
