from datetime import datetime, timedelta, timezone  # noqa: I001
from backtest.engine import TradeDirection
from engine.strategy_executor import StrategyExecutor
from engine.strategy_registry import StrategySlot
from engine.protocol import CanonicalSignal


class _AlwaysSignalStrategy:
    """Test strategy that always returns a LONG signal."""

    @property
    def name(self) -> str:
        return "always_long"

    def evaluate(self, state):
        return type(
            "R",
            (),
            {
                "direction": TradeDirection.LONG,
                "confidence": 0.8,
                "entry_price": state.latest_bar.close,
                "stop_loss": state.latest_bar.close - 0.005,
                "take_profit_1": state.latest_bar.close + 0.01,
                "take_profit_2": 0.0,
                "take_profit_3": 0.0,
                "rationale": "test",
                "is_volatile": False,
            },
        )()


class TestStrategyExecutor:
    def _make_slot(self, symbol="EURUSD", timeframe="H1"):
        return StrategySlot(
            id="test_eurusd_h1",
            strategy_type="test",
            symbol=symbol,
            timeframe=timeframe,
            params={},
            min_confidence=0.40,
        )

    def test_creation(self):
        slot = self._make_slot()
        strategy = _AlwaysSignalStrategy()
        executor = StrategyExecutor(slot=slot, strategy=strategy, min_bars=3)
        assert executor.slot_id == "test_eurusd_h1"
        assert executor.symbol == "EURUSD"
        assert executor.bar_count == 0
        assert not executor.ready

    def test_on_tick_builds_bars(self):
        slot = self._make_slot()
        executor = StrategyExecutor(slot=slot, strategy=_AlwaysSignalStrategy(), min_bars=2)
        base = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)

        for i in range(5):
            ts = base + timedelta(hours=i)
            executor.on_tick(1.1000 + i * 0.001, 1.0999, 1.1001, ts)

        assert executor.bar_count >= 1

    def test_try_evaluate_returns_none_before_ready(self):
        slot = self._make_slot()
        executor = StrategyExecutor(slot=slot, strategy=_AlwaysSignalStrategy(), min_bars=100)
        base = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)
        executor.on_tick(1.1, 1.0999, 1.1001, base)
        assert executor.try_evaluate() is None

    def test_try_evaluate_returns_signal_when_ready(self):
        slot = self._make_slot()
        executor = StrategyExecutor(slot=slot, strategy=_AlwaysSignalStrategy(), min_bars=2)
        base = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)

        for i in range(5):
            ts = base + timedelta(hours=i)
            executor.on_tick(1.1000 + i * 0.001, 1.0999, 1.1001, ts)

        signal = executor.try_evaluate()
        assert signal is not None
        assert isinstance(signal, CanonicalSignal)
        assert signal.strategy_id == "test_eurusd_h1"
        assert signal.symbol == "EURUSD"
        assert signal.direction == TradeDirection.LONG

    def test_bar_trimming(self):
        slot = self._make_slot()
        executor = StrategyExecutor(slot=slot, strategy=_AlwaysSignalStrategy(), min_bars=2, max_bars=3)
        base = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)

        for i in range(10):
            ts = base + timedelta(hours=i)
            executor.on_tick(1.1000 + i * 0.001, 1.0999, 1.1001, ts)

        assert executor.bar_count <= 3

    def test_different_timeframes(self):
        slot = self._make_slot(timeframe="M15")
        executor = StrategyExecutor(slot=slot, strategy=_AlwaysSignalStrategy(), min_bars=2)
        base = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)

        for i in range(10):
            ts = base + timedelta(minutes=15 * i)
            executor.on_tick(1.1, 1.0999, 1.1001, ts)

        assert executor.bar_count >= 2
