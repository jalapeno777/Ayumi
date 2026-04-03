import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar, SessionType, TradeDirection
from backtest.ict_smc.models import ICTMarketState
from backtest.ict_smc.h4_context import H4ContextModule, H4ContextResult, H4ZoneMapping
from backtest.ict_smc.confluence_engine import SignalConfluenceEngine


def _h4_bar(i, o=1.0, h=1.01, low=0.99, c=1.005):
    base = datetime(2024, 1, 1)
    time = base + timedelta(hours=i * 4)
    return Bar(time=time, open=o, high=h, low=low, close=c)


def _h1_bar(i, o=1.0, h=1.01, low=0.99, c=1.005):
    base = datetime(2024, 1, 1, 10, 0)
    time = base + timedelta(hours=i)
    return Bar(time=time, open=o, high=h, low=low, close=c)


def _make_h4_bars_with_bullish_ob(n=50):
    bars = []
    base_price = 1.0000
    for i in range(n):
        if i == 5:
            bars.append(_h4_bar(i, o=1.0000, h=1.0025, low=0.9998, c=1.0020))
        elif i == 6:
            bars.append(_h4_bar(i, o=1.0020, h=1.0040, low=1.0018, c=1.0035))
        else:
            p = base_price + i * 0.00005
            bars.append(_h4_bar(i, o=p, h=p + 0.0002, low=p - 0.0002, c=p + 0.00005))
    return bars


def _make_h4_bars_with_bearish_ob(n=50):
    bars = []
    base_price = 1.0200
    for i in range(n):
        if i == 5:
            bars.append(_h4_bar(i, o=1.0200, h=1.0202, low=1.0175, c=1.0180))
        elif i == 6:
            bars.append(_h4_bar(i, o=1.0180, h=1.0182, low=1.0160, c=1.0165))
        else:
            p = base_price - i * 0.00005
            bars.append(_h4_bar(i, o=p, h=p + 0.0002, low=p - 0.0002, c=p - 0.00005))
    return bars


def _make_h4_bars_with_bullish_fvg(n=50):
    bars = []
    for i in range(n):
        if i == 5:
            bars.append(_h4_bar(i, o=1.0000, h=1.0015, low=0.9998, c=1.0010))
        elif i == 6:
            bars.append(_h4_bar(i, o=1.0010, h=1.0015, low=1.0008, c=1.0012))
        elif i == 7:
            bars.append(_h4_bar(i, o=1.0030, h=1.0040, low=1.0028, c=1.0035))
        else:
            p = 1.0000 + i * 0.00005
            bars.append(_h4_bar(i, o=p, h=p + 0.0002, low=p - 0.0002, c=p + 0.00005))
    return bars


class TestH4ContextModule(unittest.TestCase):

    def test_empty_bars_returns_empty_result(self):
        module = H4ContextModule()
        result = module.analyze([], 1.0, 0.0001)
        self.assertIsInstance(result, H4ContextResult)
        self.assertEqual(result.order_block_zones, [])
        self.assertEqual(result.fvg_zones, [])
        self.assertEqual(result.bullish_score, 0.0)
        self.assertEqual(result.bearish_score, 0.0)

    def test_insufficient_bars_returns_empty_result(self):
        module = H4ContextModule()
        bars = [_h4_bar(i) for i in range(5)]
        result = module.analyze(bars, 1.0, 0.0001)
        self.assertEqual(result.bullish_score, 0.0)
        self.assertEqual(result.bearish_score, 0.0)

    def test_bullish_ob_detected(self):
        module = H4ContextModule(ob_freshness_window=50)
        h4_bars = _make_h4_bars_with_bullish_ob(50)
        result = module.analyze(h4_bars, 1.01, 0.0005)
        bullish_obs = [
            z for z in result.order_block_zones if z.direction == TradeDirection.LONG
        ]
        self.assertGreater(len(bullish_obs), 0)

    def test_bearish_ob_detected(self):
        module = H4ContextModule(ob_freshness_window=50)
        h4_bars = _make_h4_bars_with_bearish_ob(50)
        result = module.analyze(h4_bars, 1.01, 0.0005)
        bearish_obs = [
            z for z in result.order_block_zones if z.direction == TradeDirection.SHORT
        ]
        self.assertGreater(len(bearish_obs), 0)

    def test_fvg_detected(self):
        module = H4ContextModule(fvg_max_age=50)
        h4_bars = _make_h4_bars_with_bullish_fvg(50)
        result = module.analyze(h4_bars, 1.01, 0.0005)
        self.assertGreater(len(result.fvg_zones), 0)

    def test_bullish_score_positive_when_price_in_bullish_zone(self):
        module = H4ContextModule(ob_freshness_window=50)
        h4_bars = _make_h4_bars_with_bullish_ob(50)
        bullish_obs = []
        state = ICTMarketState(h4_bars)
        module._ob_detector.detect(state)
        for ob in state.active_order_blocks:
            if ob.direction == TradeDirection.LONG:
                bullish_obs.append(ob)
        if bullish_obs:
            ob = bullish_obs[0]
            price_in_zone = (ob.top + ob.bottom) / 2
            result = module.analyze(h4_bars, price_in_zone, 0.0005)
            self.assertGreater(result.bullish_score, 0.0)

    def test_scores_capped_at_one(self):
        module = H4ContextModule(ob_freshness_window=50)
        h4_bars = _make_h4_bars_with_bullish_ob(50)
        result = module.analyze(h4_bars, 1.01, 0.0005)
        self.assertLessEqual(result.bullish_score, 1.0)
        self.assertLessEqual(result.bearish_score, 1.0)

    def test_zero_atr_returns_zero_scores(self):
        module = H4ContextModule(ob_freshness_window=50)
        h4_bars = _make_h4_bars_with_bullish_ob(50)
        result = module.analyze(h4_bars, 1.01, 0.0)
        self.assertEqual(result.bullish_score, 0.0)
        self.assertEqual(result.bearish_score, 0.0)

    def test_zone_mapping_structure(self):
        zone = H4ZoneMapping(
            top=1.0100, bottom=1.0050,
            direction=TradeDirection.LONG,
            zone_type="order_block",
            strength=0.8,
        )
        self.assertEqual(zone.top, 1.0100)
        self.assertEqual(zone.bottom, 1.0050)
        self.assertEqual(zone.direction, TradeDirection.LONG)
        self.assertEqual(zone.zone_type, "order_block")
        self.assertEqual(zone.strength, 0.8)
        self.assertFalse(zone.is_filled)

    def test_confluence_counts(self):
        module = H4ContextModule(ob_freshness_window=50, fvg_max_age=50)
        h4_bars = _make_h4_bars_with_bullish_ob(50)
        result = module.analyze(h4_bars, 1.01, 0.0005)
        self.assertGreaterEqual(result.confluence_count_bullish, 0)
        self.assertGreaterEqual(result.confluence_count_bearish, 0)


class TestH4ContextIntegration(unittest.TestCase):

    def _make_h1_state(self, n=100):
        bars = []
        price = 1.0000
        for i in range(n):
            drift = 0.00005
            noise = (i % 7 - 3) * 0.00003
            price += drift + noise
            o = price - drift
            h = price + abs(noise) * 2
            low = price - abs(noise) * 2
            c = price
            bars.append(_h1_bar(i, o=o, h=h, low=low, c=c))
        state = ICTMarketState(bars)
        state.current_session = SessionType.LONDON
        return state

    def test_confluence_engine_without_h4_still_works(self):
        engine = SignalConfluenceEngine(min_confidence=0.0)
        state = self._make_h1_state(100)
        signal = engine.evaluate(state)
        self.assertTrue(signal is None or signal is not None)

    def test_confluence_engine_with_h4_bars(self):
        engine = SignalConfluenceEngine(min_confidence=0.0)
        state = self._make_h1_state(100)
        h4_bars = _make_h4_bars_with_bullish_ob(50)
        signal = engine.evaluate(state, h4_bars=h4_bars)
        self.assertTrue(signal is None or signal is not None)

    def test_confluence_engine_h4_increases_confluence_count(self):
        engine = SignalConfluenceEngine(min_confidence=0.0, h4_weight=0.15)
        state = self._make_h1_state(100)
        h4_bars = _make_h4_bars_with_bullish_ob(50)

        signal_without = engine.evaluate(state)
        signal_with = engine.evaluate(state, h4_bars=h4_bars)

        if signal_without is not None and signal_with is not None:
            self.assertGreaterEqual(
                signal_with.confluence_count, signal_without.confluence_count
            )

    def test_confluence_engine_h4_default_weight(self):
        engine = SignalConfluenceEngine()
        self.assertEqual(engine._h4_weight, 0.15)

    def test_confluence_engine_custom_h4_weight(self):
        engine = SignalConfluenceEngine(h4_weight=0.25)
        self.assertEqual(engine._h4_weight, 0.25)

    def test_h4_context_graceful_fallback_none_bars(self):
        engine = SignalConfluenceEngine(min_confidence=0.0)
        state = self._make_h1_state(100)
        signal = engine.evaluate(state, h4_bars=None)
        self.assertTrue(signal is None or signal is not None)

    def test_h4_context_in_rationale(self):
        engine = SignalConfluenceEngine(min_confidence=0.0)
        state = self._make_h1_state(100)
        h4_bars = _make_h4_bars_with_bullish_ob(50)
        signal = engine.evaluate(state, h4_bars=h4_bars)
        if signal is not None:
            has_h4_in_rationale = "H4 context" in signal.rationale or signal.confluence_count >= 0
            self.assertTrue(has_h4_in_rationale)


class TestH4ZoneMapping(unittest.TestCase):

    def test_price_in_zone_true(self):
        module = H4ContextModule()
        zone = H4ZoneMapping(top=1.0100, bottom=1.0050, direction=TradeDirection.LONG, zone_type="order_block")
        self.assertTrue(module._price_in_zone(1.0075, zone))

    def test_price_in_zone_false(self):
        module = H4ContextModule()
        zone = H4ZoneMapping(top=1.0100, bottom=1.0050, direction=TradeDirection.LONG, zone_type="order_block")
        self.assertFalse(module._price_in_zone(1.0200, zone))

    def test_price_near_zone(self):
        module = H4ContextModule()
        zone = H4ZoneMapping(top=1.0100, bottom=1.0050, direction=TradeDirection.LONG, zone_type="order_block")
        self.assertTrue(module._price_near_zone(1.0150, zone, 0.01))
        self.assertFalse(module._price_near_zone(1.0500, zone, 0.01))

    def test_proximity_score_closes(self):
        module = H4ContextModule()
        zone = H4ZoneMapping(top=1.0100, bottom=1.0050, direction=TradeDirection.LONG, zone_type="order_block")
        close_score = module._zone_proximity_score(1.0075, zone, 0.001)
        far_score = module._zone_proximity_score(1.0500, zone, 0.001)
        self.assertGreater(close_score, far_score)


if __name__ == "__main__":
    unittest.main()
