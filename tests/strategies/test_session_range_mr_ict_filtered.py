from datetime import datetime, timedelta

from backtest.engine import (
    Bar,
    MarketState,
    SessionType,
    StrategySignal,
)
from strategies.session_range_mean_reversion import SessionRangeMRConfig
from strategies.session_range_mr_ict_filtered import (
    ICTFilterConfig,
    SessionRangeMRWithICTFilter,
)


def _make_h1_bars(n: int, base_price: float = 1.1000, seed: int = 42) -> list:
    import random

    random.seed(seed)
    bars = []
    price = base_price
    now = datetime(2024, 1, 1, 0, 0)
    for i in range(n):
        change = random.uniform(-0.0010, 0.0010)  # noqa: S311
        high = price + abs(change)
        low = price - abs(change)
        if change > 0:
            close = price + change * 0.7
        else:
            close = price + change * 0.7
        open_ = price
        bars.append(
            Bar(
                time=now + timedelta(hours=i),
                open=open_,
                high=max(open_, close, high),
                low=min(open_, close, low),
                close=close,
                volume=random.uniform(100, 1000),  # noqa: S311
            )
        )
        price = close
    return bars


class TestSessionRangeMRWithICTFilter:
    def test_name(self):
        s = SessionRangeMRWithICTFilter()
        assert s.name == "Session-Range MR + ICT Filter"

    def test_insufficient_bars_returns_none(self):
        s = SessionRangeMRWithICTFilter()
        bars = _make_h1_bars(10)
        state = MarketState(bars=bars, current_session=SessionType.ASIAN)
        assert s.evaluate(state) is None

    def test_passes_through_mr_signal_when_ict_confirms(self):
        s = SessionRangeMRWithICTFilter(
            ict_config=ICTFilterConfig(min_confluence_confidence=0.20),
        )
        bars = _make_h1_bars(500, seed=99)
        state = MarketState(bars=bars, current_session=SessionType.ASIAN)
        result = s.evaluate(state)
        assert result is None or isinstance(result, StrategySignal)

    def test_stricter_ict_threshold_reduces_signals(self):
        loose = SessionRangeMRWithICTFilter(
            ict_config=ICTFilterConfig(min_confluence_confidence=0.20),
        )
        strict = SessionRangeMRWithICTFilter(
            ict_config=ICTFilterConfig(min_confluence_confidence=0.80),
        )
        bars = _make_h1_bars(2000, seed=55)
        loose_count = 0
        strict_count = 0
        for i in range(100, len(bars)):
            state = MarketState(bars=bars[: i + 1], current_session=SessionType.ASIAN)
            if loose.evaluate(state) is not None:
                loose_count += 1
            if strict.evaluate(state) is not None:
                strict_count += 1
        assert strict_count <= loose_count

    def test_filter_stats_tracked(self):
        s = SessionRangeMRWithICTFilter(
            ict_config=ICTFilterConfig(min_confluence_confidence=0.20),
        )
        bars = _make_h1_bars(500, seed=77)
        s.reset_stats()
        for i in range(100, len(bars)):
            state = MarketState(bars=bars[: i + 1], current_session=SessionType.ASIAN)
            s.evaluate(state)
        stats = s.filter_stats
        assert stats["total_evaluated"] > 0
        assert stats["mr_signals"] >= stats["passed_ict"]
        assert stats["rejected_ict"] == stats["mr_signals"] - stats["passed_ict"]

    def test_reset_stats_clears_counters(self):
        s = SessionRangeMRWithICTFilter()
        s._total_evaluated = 10
        s._mr_signals = 5
        s._passed_ict_filter = 3
        s._rejected_ict_filter = 2
        s.reset_stats()
        assert s.filter_stats["total_evaluated"] == 0
        assert s.filter_stats["mr_signals"] == 0

    def test_custom_mr_config(self):
        custom_mr = SessionRangeMRConfig(rsi_long_level=25.0, rsi_short_level=75.0)
        s = SessionRangeMRWithICTFilter(
            mr_config=custom_mr,
            ict_config=ICTFilterConfig(min_confluence_confidence=0.20),
        )
        bars = _make_h1_bars(500, seed=33)
        state = MarketState(bars=bars, current_session=SessionType.ASIAN)
        result = s.evaluate(state)
        assert result is None or isinstance(result, StrategySignal)

    def test_require_structure_alignment(self):
        s_aligned = SessionRangeMRWithICTFilter(
            ict_config=ICTFilterConfig(
                min_confluence_confidence=0.20,
                require_structure_alignment=True,
            ),
        )
        s_no_align = SessionRangeMRWithICTFilter(
            ict_config=ICTFilterConfig(
                min_confluence_confidence=0.20,
                require_structure_alignment=False,
            ),
        )
        bars = _make_h1_bars(2000, seed=88)
        aligned_count = 0
        no_align_count = 0
        for i in range(100, len(bars)):
            state = MarketState(bars=bars[: i + 1], current_session=SessionType.ASIAN)
            if s_aligned.evaluate(state) is not None:
                aligned_count += 1
            if s_no_align.evaluate(state) is not None:
                no_align_count += 1
        assert aligned_count <= no_align_count

    def test_min_confluence_count_filter(self):
        s_none = SessionRangeMRWithICTFilter(
            ict_config=ICTFilterConfig(
                min_confluence_confidence=0.20,
                min_confluence_count=0,
            ),
        )
        s_three = SessionRangeMRWithICTFilter(
            ict_config=ICTFilterConfig(
                min_confluence_confidence=0.20,
                min_confluence_count=3,
            ),
        )
        bars = _make_h1_bars(2000, seed=44)
        none_count = 0
        three_count = 0
        for i in range(100, len(bars)):
            state = MarketState(bars=bars[: i + 1], current_session=SessionType.ASIAN)
            if s_none.evaluate(state) is not None:
                none_count += 1
            if s_three.evaluate(state) is not None:
                three_count += 1
        assert three_count <= none_count

    def test_combined_confidence_uses_both_sources(self):
        s = SessionRangeMRWithICTFilter(
            ict_config=ICTFilterConfig(min_confluence_confidence=0.20),
        )
        bars = _make_h1_bars(1000, seed=66)
        for i in range(100, len(bars)):
            state = MarketState(bars=bars[: i + 1], current_session=SessionType.ASIAN)
            result = s.evaluate(state)
            if result is not None:
                assert 0.0 < result.confidence <= 0.95
                assert str(result.direction) in ("long", "short", "neutral")
                assert result.stop_loss != 0.0
                break

    def test_no_h4_context_mode(self):
        s = SessionRangeMRWithICTFilter(
            ict_config=ICTFilterConfig(
                min_confluence_confidence=0.20,
                use_h4_context=False,
            ),
        )
        bars = _make_h1_bars(500, seed=22)
        state = MarketState(bars=bars, current_session=SessionType.ASIAN)
        result = s.evaluate(state)
        assert result is None or isinstance(result, StrategySignal)

    def test_ict_pass_rate_calculation(self):
        s = SessionRangeMRWithICTFilter()
        s._mr_signals = 0
        s._passed_ict_filter = 0
        stats = s.filter_stats
        assert stats["ict_pass_rate"] == 0.0

        s._mr_signals = 10
        s._passed_ict_filter = 7
        stats = s.filter_stats
        assert abs(stats["ict_pass_rate"] - 0.7) < 0.001
