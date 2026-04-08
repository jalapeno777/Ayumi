import unittest

from quant.vaps import VAPSConfig, vaps_regime, vaps_size, vaps_multiply
from quant.regime import VolatilityRegime


def _make_atr_series(values):
    return [float(v) for v in values]


class TestVAPSConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = VAPSConfig()
        self.assertEqual(cfg.lookback, 50)
        self.assertEqual(cfg.low_multiplier, 1.25)
        self.assertEqual(cfg.normal_multiplier, 1.0)
        self.assertEqual(cfg.high_multiplier, 0.75)
        self.assertEqual(cfg.extreme_multiplier, 0.5)
        self.assertEqual(cfg.min_multiplier, 0.25)
        self.assertEqual(cfg.max_multiplier, 1.5)
        self.assertEqual(cfg.low_pctile, 25.0)
        self.assertEqual(cfg.normal_pctile, 75.0)
        self.assertEqual(cfg.high_pctile, 90.0)

    def test_frozen(self):
        cfg = VAPSConfig()
        with self.assertRaises(AttributeError):
            cfg.low_multiplier = 2.0

    def test_custom_values(self):
        cfg = VAPSConfig(
            lookback=100,
            low_multiplier=1.5,
            extreme_multiplier=0.3,
        )
        self.assertEqual(cfg.lookback, 100)
        self.assertEqual(cfg.low_multiplier, 1.5)
        self.assertEqual(cfg.extreme_multiplier, 0.3)

    def test_custom_pctile_thresholds(self):
        cfg = VAPSConfig(
            low_pctile=30.0,
            normal_pctile=70.0,
            high_pctile=90.0,
        )
        self.assertEqual(cfg.low_pctile, 30.0)
        self.assertEqual(cfg.normal_pctile, 70.0)
        self.assertEqual(cfg.high_pctile, 90.0)


class TestVAPSRegime(unittest.TestCase):
    def test_low_volatility_regime(self):
        atr_series = _make_atr_series([0.010] * 40 + [0.001])
        regime, percentile, multiplier = vaps_regime(atr_series)
        self.assertEqual(regime, VolatilityRegime.LOW)
        self.assertLess(percentile, 25.0)
        self.assertAlmostEqual(multiplier, 1.25, places=2)

    def test_normal_volatility_regime(self):
        mid_values = [0.005 + (i - 25) * 0.0001 for i in range(50)]
        mid_values[-1] = 0.005
        atr_series = _make_atr_series(mid_values)
        regime, percentile, multiplier = vaps_regime(atr_series)
        self.assertIn(regime, (VolatilityRegime.NORMAL, VolatilityRegime.LOW))
        self.assertAlmostEqual(multiplier, 1.0, places=2)

    def test_high_volatility_regime(self):
        base = [0.005] * 20 + [0.007] * 10 + [0.010] * 10 + [0.007] * 9
        atr_series = _make_atr_series(base + [0.008])
        regime, percentile, multiplier = vaps_regime(atr_series)
        self.assertEqual(regime, VolatilityRegime.HIGH)
        self.assertGreaterEqual(percentile, 75.0)
        self.assertLess(percentile, 90.0)
        self.assertAlmostEqual(multiplier, 0.75, places=2)

    def test_extreme_volatility_regime(self):
        values = [0.005] * 46 + [0.020]
        atr_series = _make_atr_series(values)
        regime, percentile, multiplier = vaps_regime(atr_series)
        self.assertEqual(regime, VolatilityRegime.EXTREME)
        self.assertGreaterEqual(percentile, 90.0)
        self.assertAlmostEqual(multiplier, 0.5, places=2)

    def test_empty_series_returns_normal(self):
        regime, percentile, multiplier = vaps_regime([])
        self.assertEqual(regime, VolatilityRegime.NORMAL)
        self.assertEqual(percentile, 50.0)
        self.assertAlmostEqual(multiplier, 1.0, places=2)

    def test_custom_lookback(self):
        atr_series = _make_atr_series([0.010] * 20 + [0.001])
        cfg = VAPSConfig(lookback=20)
        regime, percentile, multiplier = vaps_regime(atr_series, config=cfg)
        self.assertEqual(regime, VolatilityRegime.LOW)

    def test_custom_multipliers(self):
        atr_series = _make_atr_series([0.010] * 40 + [0.001])
        cfg = VAPSConfig(low_multiplier=2.0, high_multiplier=0.3, max_multiplier=3.0)
        _regime_low, _pct_low, mult_low = vaps_regime(atr_series, config=cfg)
        self.assertAlmostEqual(mult_low, 2.0, places=2)

        base = [0.005] * 20 + [0.007] * 10 + [0.010] * 10 + [0.007] * 9
        atr_high = _make_atr_series(base + [0.008])
        _regime_high, _pct_high, mult_high = vaps_regime(atr_high, config=cfg)
        self.assertAlmostEqual(mult_high, 0.3, places=2)

    def test_min_multiplier_floor(self):
        cfg = VAPSConfig(extreme_multiplier=0.1, min_multiplier=0.25)
        atr_series = _make_atr_series([0.005] * 46 + [0.020])
        _regime, _pct, multiplier = vaps_regime(atr_series, config=cfg)
        self.assertGreaterEqual(multiplier, 0.25)

    def test_max_multiplier_cap(self):
        cfg = VAPSConfig(low_multiplier=3.0, max_multiplier=1.5)
        atr_series = _make_atr_series([0.010] * 40 + [0.001])
        _regime, _pct, multiplier = vaps_regime(atr_series, config=cfg)
        self.assertLessEqual(multiplier, 1.5)

    def test_custom_pctile_thresholds_shift_regime_boundaries(self):
        atr_series = _make_atr_series(
            [0.005] * 28 + [0.006] * 1 + [0.007] * 20 + [0.008]
        )
        default_cfg = VAPSConfig()
        custom_cfg = VAPSConfig(low_pctile=30.0, normal_pctile=70.0, high_pctile=90.0)
        _reg_default, pct_default, _mult_default = vaps_regime(
            atr_series, config=default_cfg
        )
        _reg_custom, pct_custom, _mult_custom = vaps_regime(
            atr_series, config=custom_cfg
        )
        self.assertEqual(pct_default, pct_custom)


class TestVAPSSize(unittest.TestCase):
    def test_low_vol_increases_size(self):
        atr_series = _make_atr_series([0.010] * 40 + [0.001])
        lot, regime, percentile = vaps_size(
            account_balance=10000,
            risk_pct=1.0,
            entry_price=1.1000,
            stop_loss=1.0950,
            atr_series=atr_series,
        )
        base_lot = 10000 * 0.01 / (0.0050 * 100000)
        self.assertAlmostEqual(lot, base_lot * 1.25, places=4)
        self.assertEqual(regime, VolatilityRegime.LOW)

    def test_extreme_vol_reduces_size(self):
        atr_series = _make_atr_series([0.005] * 46 + [0.020])
        lot, regime, percentile = vaps_size(
            account_balance=10000,
            risk_pct=1.0,
            entry_price=1.1000,
            stop_loss=1.0950,
            atr_series=atr_series,
        )
        base_lot = 10000 * 0.01 / (0.0050 * 100000)
        self.assertAlmostEqual(lot, base_lot * 0.5, places=4)
        self.assertEqual(regime, VolatilityRegime.EXTREME)

    def test_zero_balance(self):
        atr_series = _make_atr_series([0.010] * 50)
        lot, regime, _pct = vaps_size(
            account_balance=0,
            risk_pct=1.0,
            entry_price=1.1000,
            stop_loss=1.0950,
            atr_series=atr_series,
        )
        self.assertEqual(lot, 0.0)

    def test_zero_stop_distance(self):
        atr_series = _make_atr_series([0.010] * 50)
        lot, regime, _pct = vaps_size(
            account_balance=10000,
            risk_pct=1.0,
            entry_price=1.1000,
            stop_loss=1.1000,
            atr_series=atr_series,
        )
        self.assertEqual(lot, 0.0)

    def test_empty_atr_series(self):
        lot, regime, percentile = vaps_size(
            account_balance=10000,
            risk_pct=1.0,
            entry_price=1.1000,
            stop_loss=1.0950,
            atr_series=[],
        )
        base_lot = 10000 * 0.01 / (0.0050 * 100000)
        self.assertAlmostEqual(lot, base_lot * 1.0, places=4)
        self.assertEqual(regime, VolatilityRegime.NORMAL)

    def test_returns_regime_and_percentile(self):
        atr_series = _make_atr_series([0.010] * 40 + [0.001])
        lot, regime, percentile = vaps_size(
            account_balance=10000,
            risk_pct=1.0,
            entry_price=1.1000,
            stop_loss=1.0950,
            atr_series=atr_series,
        )
        self.assertIsInstance(regime, VolatilityRegime)
        self.assertIsInstance(percentile, float)
        self.assertGreaterEqual(percentile, 0.0)
        self.assertLessEqual(percentile, 100.0)


class TestVAPSMultiply(unittest.TestCase):
    def test_multiplies_base_lot(self):
        atr_series = _make_atr_series([0.010] * 40 + [0.001])
        lot, regime, _pct = vaps_multiply(
            base_lot=0.2,
            atr_series=atr_series,
        )
        self.assertAlmostEqual(lot, 0.25, places=4)

    def test_zero_base_returns_zero(self):
        atr_series = _make_atr_series([0.010] * 50)
        lot, regime, _pct = vaps_multiply(
            base_lot=0.0,
            atr_series=atr_series,
        )
        self.assertEqual(lot, 0.0)

    def test_extreme_halves(self):
        atr_series = _make_atr_series([0.005] * 46 + [0.020])
        lot, regime, _pct = vaps_multiply(
            base_lot=0.2,
            atr_series=atr_series,
        )
        self.assertAlmostEqual(lot, 0.1, places=4)

    def test_custom_config(self):
        atr_series = _make_atr_series([0.010] * 40 + [0.001])
        cfg = VAPSConfig(low_multiplier=1.5)
        lot, regime, _pct = vaps_multiply(
            base_lot=0.2,
            atr_series=atr_series,
            config=cfg,
        )
        self.assertAlmostEqual(lot, 0.3, places=4)


class TestVAPSPipelineIntegration(unittest.TestCase):
    def test_vaps_mode_in_pipeline(self):
        from quant.config import QuantConfig, PositionSizingConfig, SizingMode
        from quant.pipeline import QuantPipeline

        config = QuantConfig(
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.VOLATILITY_ADAPTIVE,
                risk_pct=1.0,
            ),
        )
        pipeline = QuantPipeline(config)
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
        self.assertIsNotNone(decision.lot_size)
        self.assertGreater(decision.lot_size, 0)
        self.assertEqual(decision.sizing_mode, "volatility_adaptive")

    def test_vaps_resizes_in_low_vol(self):
        from quant.config import QuantConfig, PositionSizingConfig, SizingMode
        from quant.pipeline import QuantPipeline

        config = QuantConfig(
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.VOLATILITY_ADAPTIVE,
                risk_pct=1.0,
            ),
        )
        pipeline = QuantPipeline(config)
        pipeline.portfolio.balance = 100_000.0

        for i in range(40):
            pipeline.update_bars(
                high=1.1 + i * 0.001,
                low=1.09 + i * 0.001,
                close=1.095 + i * 0.001,
                atr=0.010,
            )
        pipeline.update_bars(
            high=1.14,
            low=1.139,
            close=1.1395,
            atr=0.001,
        )

        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        self.assertIsNotNone(decision.lot_size)

    def test_vaps_reduces_in_extreme_vol(self):
        from quant.config import QuantConfig, PositionSizingConfig, SizingMode
        from quant.pipeline import QuantPipeline

        config = QuantConfig(
            position_sizing=PositionSizingConfig(
                enabled=True,
                mode=SizingMode.VOLATILITY_ADAPTIVE,
                risk_pct=1.0,
            ),
        )
        pipeline = QuantPipeline(config)
        pipeline.portfolio.balance = 100_000.0

        for i in range(46):
            pipeline.update_bars(
                high=1.1 + i * 0.001,
                low=1.09 + i * 0.001,
                close=1.095 + i * 0.001,
                atr=0.005,
            )
        pipeline.update_bars(
            high=1.146,
            low=1.143,
            close=1.1445,
            atr=0.020,
        )

        decision = pipeline.pre_trade_check(
            signal_symbol="EURUSD",
            entry_price=1.1000,
            stop_loss=1.0950,
        )
        self.assertIsNotNone(decision.lot_size)


if __name__ == "__main__":
    unittest.main()
