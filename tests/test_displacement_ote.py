import unittest
from datetime import datetime, timedelta

from backtest.engine import Bar, TradeDirection
from backtest.ict_smc.models import ICTMarketState
from backtest.ict_smc.displacement import DisplacementDetector, DisplacementMove
from backtest.ict_smc.premium_discount import OTEZoneDetector, OTEZone


def _bar(i, o=1.0, h=1.01, low=0.99, c=1.005, volume=1000.0):
    base = datetime(2024, 1, 1, 10, 0)
    return Bar(time=base + timedelta(hours=i), open=o, high=h, low=low, close=c, volume=volume)


def _make_bars_with_displacement(n=50):
    bars = []
    price = 1.0000
    for i in range(n):
        if i == n - 3:
            bars.append(_bar(i, o=price, h=price + 0.0025, low=price - 0.0001, c=price + 0.0022, volume=3000.0))
            price += 0.0022
        elif i == n - 2:
            bars.append(_bar(i, o=price, h=price + 0.0018, low=price - 0.0001, c=price + 0.0015, volume=2500.0))
            price += 0.0015
        else:
            bars.append(_bar(i, o=price, h=price + 0.0003, low=price - 0.0003, c=price + 0.0001, volume=1000.0))
            price += 0.0001
    return bars


def _make_bars_with_bearish_displacement(n=50):
    bars = []
    price = 1.0200
    for i in range(n):
        if i == n - 3:
            bars.append(_bar(i, o=price, h=price + 0.0001, low=price - 0.0025, c=price - 0.0022, volume=3000.0))
            price -= 0.0022
        elif i == n - 2:
            bars.append(_bar(i, o=price, h=price + 0.0001, low=price - 0.0018, c=price - 0.0015, volume=2500.0))
            price -= 0.0015
        else:
            bars.append(_bar(i, o=price, h=price + 0.0003, low=price - 0.0003, c=price - 0.0001, volume=1000.0))
            price -= 0.0001
    return bars


def _make_bars_without_displacement(n=50):
    bars = []
    price = 1.0000
    for i in range(n):
        bars.append(_bar(i, o=price, h=price + 0.0005, low=price - 0.0005, c=price + 0.0001, volume=1000.0))
        price += 0.0001
    return bars


class TestDisplacementDetector(unittest.TestCase):

    def setUp(self):
        self.detector = DisplacementDetector()

    def test_detects_bullish_displacement(self):
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        moves = self.detector.detect(state)

        self.assertTrue(len(moves) > 0)
        bullish_moves = [m for m in moves if m.direction == TradeDirection.LONG]
        self.assertTrue(len(bullish_moves) > 0)
        move = bullish_moves[0]
        self.assertGreater(move.size, 0)
        self.assertGreater(move.atr_normalized, 1.5)

    def test_detects_bearish_displacement(self):
        bars = _make_bars_with_bearish_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        moves = self.detector.detect(state)

        bearish_moves = [m for m in moves if m.direction == TradeDirection.SHORT]
        self.assertTrue(len(bearish_moves) > 0)
        move = bearish_moves[0]
        self.assertGreater(move.atr_normalized, 1.5)

    def test_no_displacement_in_ranging_market(self):
        bars = _make_bars_without_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        moves = self.detector.detect(state)
        self.assertEqual(len(moves), 0)

    def test_displacement_requires_min_body_ratio(self):
        detector = DisplacementDetector(min_body_ratio=0.95)
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        moves = detector.detect(state)
        self.assertEqual(len(moves), 0)

    def test_displacement_requires_min_atr_multiplier(self):
        detector = DisplacementDetector(atr_multiplier=10.0)
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        moves = detector.detect(state)
        self.assertEqual(len(moves), 0)

    def test_displacement_age_computed(self):
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        moves = self.detector.detect(state)
        if moves:
            self.assertGreaterEqual(moves[0].age, 0)

    def test_empty_bars_returns_empty(self):
        state = ICTMarketState([])
        state.atr = 0.0010
        moves = self.detector.detect(state)
        self.assertEqual(len(moves), 0)

    def test_zero_atr_returns_empty(self):
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0
        moves = self.detector.detect(state)
        self.assertEqual(len(moves), 0)

    def test_insufficient_bars_returns_empty(self):
        bars = _make_bars_with_displacement(5)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        moves = self.detector.detect(state)
        self.assertEqual(len(moves), 0)

    def test_get_recent_returns_correct_direction(self):
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        moves = self.detector.detect(state)

        recent_bull = self.detector.get_recent(moves, TradeDirection.LONG, max_age=50)
        if moves:
            self.assertIsNotNone(recent_bull)
            self.assertEqual(recent_bull.direction, TradeDirection.LONG)

        recent_bear = self.detector.get_recent(moves, TradeDirection.SHORT, max_age=50)
        self.assertIsNone(recent_bear)

    def test_get_recent_returns_none_when_no_match(self):
        moves = []
        result = self.detector.get_recent(moves, TradeDirection.LONG)
        self.assertIsNone(result)

    def test_displacement_move_dataclass_fields(self):
        move = DisplacementMove(
            start_index=10,
            end_index=12,
            direction=TradeDirection.LONG,
            size=0.0046,
            atr_normalized=4.6,
            volume_ratio=2.5,
            body_ratio=0.85,
            age=5,
            broke_order_block=True,
            broke_fvg=False,
        )
        self.assertEqual(move.start_index, 10)
        self.assertEqual(move.end_index, 12)
        self.assertTrue(move.broke_order_block)
        self.assertFalse(move.broke_fvg)

    def test_displacement_volume_ratio(self):
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        moves = self.detector.detect(state)
        if moves:
            self.assertGreater(moves[0].volume_ratio, 0)

    def test_max_age_filter(self):
        detector = DisplacementDetector(max_age=0)
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010

        moves = detector.detect(state)
        self.assertEqual(len(moves), 0)


class TestOTEZoneDetector(unittest.TestCase):

    def setUp(self):
        self.detector = OTEZoneDetector()

    def _make_displacement_move(self, direction=TradeDirection.LONG, start=20, end=21, size=0.0046, atr_norm=4.6):
        return DisplacementMove(
            start_index=start,
            end_index=end,
            direction=direction,
            size=size,
            atr_normalized=atr_norm,
            volume_ratio=2.0,
            body_ratio=0.85,
            age=5,
        )

    def test_detects_ote_zones_from_displacement(self):
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        move = self._make_displacement_move()

        zones = self.detector.detect(state, [move])

        self.assertEqual(len(zones), 1)
        zone = zones[0]
        self.assertEqual(zone.direction, TradeDirection.LONG)
        self.assertAlmostEqual(zone.level_618, zone.impulse_high - (zone.impulse_high - zone.impulse_low) * 0.618, places=5)
        self.assertGreater(zone.level_382, zone.level_500)
        self.assertGreater(zone.level_500, zone.level_618)
        self.assertGreater(zone.level_618, zone.level_786)

    def test_empty_displacement_returns_empty(self):
        state = ICTMarketState([])
        state.atr = 0.0010
        zones = self.detector.detect(state, [])
        self.assertEqual(len(zones), 0)

    def test_zero_atr_returns_empty(self):
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0
        move = self._make_displacement_move()
        zones = self.detector.detect(state, [move])
        self.assertEqual(len(zones), 0)

    def test_fibonacci_levels_are_correct(self):
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        move = self._make_displacement_move()

        zones = self.detector.detect(state, [move])
        zone = zones[0]

        impulse_size = zone.impulse_high - zone.impulse_low
        expected_382 = zone.impulse_high - impulse_size * 0.382
        expected_500 = zone.impulse_high - impulse_size * 0.500
        expected_618 = zone.impulse_high - impulse_size * 0.618
        expected_786 = zone.impulse_high - impulse_size * 0.786

        self.assertAlmostEqual(zone.level_382, expected_382, places=5)
        self.assertAlmostEqual(zone.level_500, expected_500, places=5)
        self.assertAlmostEqual(zone.level_618, expected_618, places=5)
        self.assertAlmostEqual(zone.level_786, expected_786, places=5)

    def test_level_for_direction_long_returns_618(self):
        zone = OTEZone(
            level_382=1.0, level_500=1.001, level_618=1.002, level_786=1.003,
            direction=TradeDirection.LONG, origin_start=0, origin_end=1,
            impulse_high=1.005, impulse_low=1.0,
        )
        self.assertAlmostEqual(zone.level_for_direction(TradeDirection.LONG), 1.002, places=5)

    def test_level_for_direction_short_returns_382(self):
        zone = OTEZone(
            level_382=1.0, level_500=1.001, level_618=1.002, level_786=1.003,
            direction=TradeDirection.SHORT, origin_start=0, origin_end=1,
            impulse_high=1.005, impulse_low=1.0,
        )
        self.assertAlmostEqual(zone.level_for_direction(TradeDirection.SHORT), 1.0, places=5)

    def test_score_ote_proximity_at_level(self):
        zone = OTEZone(
            level_382=1.0000, level_500=1.0005, level_618=1.0010, level_786=1.0015,
            direction=TradeDirection.LONG, origin_start=0, origin_end=1,
            impulse_high=1.0020, impulse_low=1.0000,
        )
        score = self.detector.score_ote_proximity(
            [zone], 1.0010, TradeDirection.LONG, atr=0.0010
        )
        self.assertGreater(score, 0.5)

    def test_score_ote_proximity_far_from_level(self):
        zone = OTEZone(
            level_382=1.0000, level_500=1.0005, level_618=1.0010, level_786=1.0015,
            direction=TradeDirection.LONG, origin_start=0, origin_end=1,
            impulse_high=1.0020, impulse_low=1.0000,
        )
        score = self.detector.score_ote_proximity(
            [zone], 1.0500, TradeDirection.LONG, atr=0.0010
        )
        self.assertEqual(score, 0.0)

    def test_score_ote_proximity_with_ob_overlap(self):
        zone = OTEZone(
            level_382=1.0000, level_500=1.0005, level_618=1.0010, level_786=1.0015,
            direction=TradeDirection.LONG, origin_start=0, origin_end=1,
            impulse_high=1.0020, impulse_low=1.0000,
            in_order_block=True,
        )
        score = self.detector.score_ote_proximity(
            [zone], 1.0010, TradeDirection.LONG, atr=0.0010
        )
        self.assertGreater(score, 0.5)

    def test_get_best_zone_for_price_returns_nearest(self):
        zone_near = OTEZone(
            level_382=1.0005, level_500=1.0008, level_618=1.0010, level_786=1.0015,
            direction=TradeDirection.LONG, origin_start=0, origin_end=1,
            impulse_high=1.0020, impulse_low=1.0000,
        )
        zone_far = OTEZone(
            level_382=1.0100, level_500=1.0105, level_618=1.0110, level_786=1.0115,
            direction=TradeDirection.LONG, origin_start=2, origin_end=3,
            impulse_high=1.0120, impulse_low=1.0100,
        )
        result = self.detector.get_best_zone_for_price(
            [zone_near, zone_far], 1.0010, TradeDirection.LONG, atr=0.0010
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.level_618, 1.0010)

    def test_get_best_zone_for_price_wrong_direction(self):
        zone = OTEZone(
            level_382=1.0000, level_500=1.0005, level_618=1.0010, level_786=1.0015,
            direction=TradeDirection.LONG, origin_start=0, origin_end=1,
            impulse_high=1.0020, impulse_low=1.0000,
        )
        result = self.detector.get_best_zone_for_price(
            [zone], 1.0010, TradeDirection.SHORT, atr=0.0010
        )
        self.assertIsNone(result)

    def test_max_zones_limit(self):
        detector = OTEZoneDetector(max_zones=2)
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        moves = [
            self._make_displacement_move(start=i, end=i + 1)
            for i in range(5)
        ]
        zones = detector.detect(state, moves)
        self.assertLessEqual(len(zones), 2)

    def test_zones_sorted_by_recency(self):
        bars = _make_bars_with_displacement(50)
        state = ICTMarketState(bars)
        state.atr = 0.0010
        moves = [
            self._make_displacement_move(start=10, end=11),
            self._make_displacement_move(start=30, end=31),
            self._make_displacement_move(start=20, end=21),
        ]
        zones = self.detector.detect(state, moves)
        if len(zones) >= 2:
            self.assertGreaterEqual(zones[0].origin_end, zones[1].origin_end)

    def test_score_ote_empty_zones(self):
        score = self.detector.score_ote_proximity([], 1.0, TradeDirection.LONG, 0.001)
        self.assertEqual(score, 0.0)

    def test_get_best_zone_empty_list(self):
        result = self.detector.get_best_zone_for_price([], 1.0, TradeDirection.LONG, 0.001)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
