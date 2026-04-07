import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar, SessionType, TradeDirection
from backtest.ict_smc.models import ICTMarketState
from backtest.ict_smc.inducement import InducementDetector, Inducement
from backtest.ict_smc.judas_swing import JudasSwingTimer, JudasSwing


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, volume=1000.0, hour=10):
    base = datetime(2024, 1, 1)
    return Bar(time=base + timedelta(hours=i), open=o, high=h, low=low, close=c, volume=volume)


def _bar_at_hour(o=1.0, h=1.01, low=0.99, c=1.005, volume=1000.0, hour=10):
    base = datetime(2024, 1, 1, hour, 0)
    return Bar(time=base, open=o, high=h, low=low, close=c, volume=volume)


def _make_inducement_bars(n=50, inducement_at=40):
    bars = []
    price = 1.0000
    for i in range(n):
        if i < 30:
            bars.append(_bar(i, o=price, h=price + 0.0003, low=price - 0.0003, c=price + 0.0001, volume=1000.0))
            price += 0.0001
        elif i < inducement_at:
            bars.append(_bar(i, o=price, h=price + 0.0002, low=price - 0.0002, c=price - 0.0001, volume=1000.0))
            price -= 0.0001
        elif i == inducement_at:
            bars.append(_bar(
                i, o=price, h=price + 0.0020, low=price - 0.0001,
                c=price + 0.0005, volume=3000.0
            ))
            price = price + 0.0005
        elif i == inducement_at + 1:
            bars.append(_bar(
                i, o=price, h=price + 0.0001, low=price - 0.0015,
                c=price - 0.0012, volume=2000.0
            ))
            price -= 0.0012
        else:
            bars.append(_bar(i, o=price, h=price + 0.0003, low=price - 0.0003, c=price - 0.0001, volume=1000.0))
            price -= 0.0001
    return bars


def _make_judas_swing_bars_london(n=20):
    bars = []
    price = 1.0000
    for i in range(n):
        if i == 10:
            bars.append(_bar_at_hour(
                o=price, h=price + 0.0020, low=price - 0.0001,
                c=price + 0.0003, volume=3000.0, hour=3
            ))
            price = price + 0.0003
        elif i == 11:
            bars.append(_bar_at_hour(
                o=price, h=price + 0.0001, low=price - 0.0015,
                c=price - 0.0012, volume=2000.0, hour=3
            ))
            price -= 0.0012
        else:
            bars.append(_bar(i, o=price, h=price + 0.0003, low=price - 0.0003, c=price + 0.0001, volume=1000.0))
            price += 0.0001
    return bars


def _make_judas_swing_bars_ny(n=20):
    bars = []
    price = 1.0100
    for i in range(n):
        if i == 10:
            bars.append(_bar_at_hour(
                o=price, h=price + 0.0001, low=price - 0.0020,
                c=price - 0.0003, volume=3000.0, hour=8
            ))
            price = price - 0.0003
        elif i == 11:
            bars.append(_bar_at_hour(
                o=price, h=price + 0.0015, low=price - 0.0001,
                c=price + 0.0012, volume=2000.0, hour=8
            ))
            price += 0.0012
        else:
            bars.append(_bar(i, o=price, h=price + 0.0003, low=price - 0.0003, c=price + 0.0001, volume=1000.0))
            price += 0.0001
    return bars


class TestInducementDetector(unittest.TestCase):

    def setUp(self):
        self.detector = InducementDetector()

    def test_detects_bullish_inducement(self):
        bars = _make_inducement_bars(50, inducement_at=40)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        inducements = self.detector.detect(state)

        self.assertTrue(len(inducements) > 0)

    def test_inducement_dataclass_fields(self):
        ind = Inducement(
            bar_index=40,
            direction=TradeDirection.LONG,
            break_level=0.99,
            spike_high=1.0020,
            spike_low=0.99,
            wick_ratio=0.75,
            volume_ratio=2.0,
            reversal_bars=1,
            continuation_direction=TradeDirection.SHORT,
            age=5,
        )
        self.assertEqual(ind.bar_index, 40)
        self.assertEqual(ind.continuation_direction, TradeDirection.SHORT)
        self.assertTrue(ind.wick_ratio > 0.6)

    def test_no_inducement_without_reversal(self):
        bars = []
        price = 1.0000
        for i in range(50):
            if i == 40:
                bars.append(_bar(
                    i, o=price, h=price + 0.0020, low=price - 0.0001,
                    c=price + 0.0018, volume=3000.0
                ))
                price += 0.0018
            else:
                bars.append(_bar(i, o=price, h=price + 0.0003, low=price - 0.0003, c=price + 0.0001, volume=1000.0))
                price += 0.0001
        state = ICTMarketState(bars)
        state.atr = 0.0010

        inducements = self.detector.detect(state)
        self.assertEqual(len(inducements), 0)

    def test_empty_bars_returns_empty(self):
        state = ICTMarketState([])
        state.atr = 0.0010
        inducements = self.detector.detect(state)
        self.assertEqual(len(inducements), 0)

    def test_zero_atr_returns_empty(self):
        bars = _make_inducement_bars(50)
        state = ICTMarketState(bars)
        state.atr = 0.0
        inducements = self.detector.detect(state)
        self.assertEqual(len(inducements), 0)

    def test_insufficient_bars_returns_empty(self):
        bars = _make_inducement_bars(10)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        inducements = self.detector.detect(state)
        self.assertEqual(len(inducements), 0)

    def test_min_wick_ratio_filter(self):
        detector = InducementDetector(min_wick_ratio=0.95)
        bars = _make_inducement_bars(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        inducements = detector.detect(state)
        self.assertEqual(len(inducements), 0)

    def test_volume_multiplier_filter(self):
        detector = InducementDetector(volume_multiplier=10.0)
        bars = _make_inducement_bars(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        inducements = detector.detect(state)
        self.assertEqual(len(inducements), 0)

    def test_get_recent_returns_correct_direction(self):
        bars = _make_inducement_bars(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        inducements = self.detector.detect(state)

        if inducements:
            ind = self.detector.get_recent(inducements, direction=TradeDirection.SHORT, max_age=50)
            if ind is not None:
                self.assertEqual(ind.continuation_direction, TradeDirection.SHORT)

    def test_get_recent_returns_none_when_no_match(self):
        result = self.detector.get_recent([], direction=TradeDirection.LONG)
        self.assertIsNone(result)

    def test_has_inducement_at_index(self):
        ind = Inducement(
            bar_index=5, direction=TradeDirection.LONG, break_level=0.99,
            spike_high=1.01, spike_low=0.99, wick_ratio=0.7,
            volume_ratio=2.0, reversal_bars=2,
            continuation_direction=TradeDirection.SHORT, age=3,
        )
        self.assertTrue(self.detector.has_inducement_at_index([ind], 5))
        self.assertFalse(self.detector.has_inducement_at_index([ind], 6))

    def test_max_age_filter(self):
        detector = InducementDetector(max_age=0)
        bars = _make_inducement_bars(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        inducements = detector.detect(state)
        self.assertEqual(len(inducements), 0)


class TestJudasSwingTimer(unittest.TestCase):

    def setUp(self):
        self.timer = JudasSwingTimer()

    def test_detects_london_judas_swing(self):
        bars = _make_judas_swing_bars_london(20)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        swings = self.timer.detect(state)

        self.assertTrue(len(swings) > 0)
        london_swings = [s for s in swings if s.session == SessionType.LONDON]
        self.assertTrue(len(london_swings) > 0)

    def test_detects_ny_judas_swing(self):
        bars = _make_judas_swing_bars_ny(20)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        swings = self.timer.detect(state)

        ny_swings = [s for s in swings if s.session == SessionType.NY_AM]
        self.assertTrue(len(ny_swings) > 0)

    def test_judas_swing_dataclass_fields(self):
        swing = JudasSwing(
            bar_index=10, session=SessionType.LONDON,
            spike_direction=TradeDirection.LONG,
            spike_high=1.0020, spike_low=1.0000,
            wick_ratio=0.75, reversal_confirmed=True,
            reversal_bars=2,
        )
        self.assertEqual(swing.bar_index, 10)
        self.assertEqual(swing.session, SessionType.LONDON)
        self.assertTrue(swing.reversal_confirmed)

    def test_empty_bars_returns_empty(self):
        state = ICTMarketState([])
        state.atr = 0.0010
        swings = self.timer.detect(state)
        self.assertEqual(len(swings), 0)

    def test_zero_atr_returns_empty(self):
        bars = _make_judas_swing_bars_london(20)
        state = ICTMarketState(bars)
        state.atr = 0.0
        swings = self.timer.detect(state)
        self.assertEqual(len(swings), 0)

    def test_no_swing_outside_session_hours(self):
        bars = []
        price = 1.0000
        for i in range(20):
            bars.append(_bar_at_hour(
                o=price, h=price + 0.0020, low=price - 0.0001,
                c=price + 0.0003, volume=3000.0, hour=12
            ))
            price += 0.0003
        state = ICTMarketState(bars)
        state.atr = 0.0010
        swings = self.timer.detect(state)
        self.assertEqual(len(swings), 0)

    def test_min_wick_ratio_filter(self):
        timer = JudasSwingTimer(min_wick_ratio=0.95)
        bars = _make_judas_swing_bars_london(20)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        swings = timer.detect(state)
        self.assertEqual(len(swings), 0)

    def test_spike_atr_multiplier_filter(self):
        timer = JudasSwingTimer(spike_atr_multiplier=10.0)
        bars = _make_judas_swing_bars_london(20)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        swings = timer.detect(state)
        self.assertEqual(len(swings), 0)

    def test_has_judas_swing(self):
        swing = JudasSwing(
            bar_index=10, session=SessionType.LONDON,
            spike_direction=TradeDirection.LONG,
            spike_high=1.0020, spike_low=1.0000,
            wick_ratio=0.75, reversal_confirmed=True,
            reversal_bars=2,
        )
        self.assertTrue(self.timer.has_judas_swing([swing], session=SessionType.LONDON))
        self.assertFalse(self.timer.has_judas_swing([swing], session=SessionType.NY_AM))
        self.assertTrue(self.timer.has_judas_swing([swing]))

    def test_spike_direction_suppressed(self):
        swing = JudasSwing(
            bar_index=10, session=SessionType.LONDON,
            spike_direction=TradeDirection.LONG,
            spike_high=1.0020, spike_low=1.0000,
            wick_ratio=0.75, reversal_confirmed=True,
            reversal_bars=2,
        )
        self.assertTrue(self.timer.spike_direction_suppressed([swing], TradeDirection.LONG, max_age=10, current_idx=15))
        self.assertFalse(self.timer.spike_direction_suppressed([swing], TradeDirection.SHORT, max_age=10, current_idx=15))

    def test_spike_direction_suppressed_with_age(self):
        swing = JudasSwing(
            bar_index=5, session=SessionType.LONDON,
            spike_direction=TradeDirection.LONG,
            spike_high=1.0020, spike_low=1.0000,
            wick_ratio=0.75, reversal_confirmed=True,
            reversal_bars=2,
        )
        self.assertFalse(self.timer.spike_direction_suppressed([swing], TradeDirection.LONG, max_age=3, current_idx=15))

    def test_get_recent(self):
        swing_old = JudasSwing(
            bar_index=2, session=SessionType.LONDON,
            spike_direction=TradeDirection.LONG,
            spike_high=1.0020, spike_low=1.0000,
            wick_ratio=0.7, reversal_confirmed=True,
            reversal_bars=2,
        )
        swing_new = JudasSwing(
            bar_index=12, session=SessionType.LONDON,
            spike_direction=TradeDirection.SHORT,
            spike_high=1.0030, spike_low=1.0010,
            wick_ratio=0.8, reversal_confirmed=True,
            reversal_bars=1,
        )
        recent = self.timer.get_recent([swing_old, swing_new], max_age=10, current_idx=15)
        self.assertIsNotNone(recent)
        self.assertEqual(recent.bar_index, 12)

    def test_get_recent_none_when_empty(self):
        result = self.timer.get_recent([], max_age=10, current_idx=15)
        self.assertIsNone(result)

    def test_classify_session_hour(self):
        self.assertEqual(JudasSwingTimer._classify_session_hour(3), SessionType.LONDON)
        self.assertEqual(JudasSwingTimer._classify_session_hour(4), SessionType.OUTSIDE)
        self.assertEqual(JudasSwingTimer._classify_session_hour(8), SessionType.NY_AM)
        self.assertEqual(JudasSwingTimer._classify_session_hour(9), SessionType.OUTSIDE)
        self.assertEqual(JudasSwingTimer._classify_session_hour(12), SessionType.OUTSIDE)


if __name__ == "__main__":
    unittest.main()
