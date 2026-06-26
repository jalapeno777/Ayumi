from __future__ import annotations

import unittest
from datetime import datetime, timezone

from crypto.models.trade import (
    CopyTrade,
    ProviderStats,
    TradeDirection,
    TradeSignal,
    TradeStatus,
)


def _make_signal(
    *,
    provider_id: str = "provider-1",
    symbol: str = "EURUSD",
    direction: TradeDirection = TradeDirection.LONG,
    entry_price: float = 1.1000,
    stop_loss: float = 1.0950,
    take_profit: float = 1.1150,
    lot_size: float = 0.1,
    **kwargs,
) -> TradeSignal:
    return TradeSignal(
        provider_id=provider_id,
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        lot_size=lot_size,
        signal_time=kwargs.get("signal_time", datetime.now(timezone.utc)),
        strategy_name=kwargs.get("strategy_name", "ICT Order Block"),
        confluence_count=kwargs.get("confluence_count", 3),
        strength=kwargs.get("strength", "strong"),
    )


class TestTradeSignal(unittest.TestCase):
    def test_risk_reward_long(self):
        sig = _make_signal(entry_price=1.1000, stop_loss=1.0950, take_profit=1.1150)
        self.assertAlmostEqual(sig.risk_reward, 3.0, places=2)

    def test_risk_reward_short(self):
        sig = _make_signal(
            direction=TradeDirection.SHORT,
            entry_price=1.1000,
            stop_loss=1.1050,
            take_profit=1.0850,
        )
        self.assertAlmostEqual(sig.risk_reward, 3.0, places=2)

    def test_risk_reward_zero_risk(self):
        sig = _make_signal(entry_price=1.1000, stop_loss=1.1000, take_profit=1.1100)
        self.assertEqual(sig.risk_reward, 0.0)

    def test_sl_tp_ratio(self):
        sig = _make_signal(entry_price=1.1000, stop_loss=1.0950, take_profit=1.1150)
        self.assertAlmostEqual(sig.sl_tp_ratio, 1.0 / 3.0, places=2)

    def test_default_values(self):
        sig = _make_signal()
        self.assertEqual(sig.lot_size, 0.1)
        self.assertEqual(sig.confluence_count, 3)
        self.assertEqual(sig.strength, "strong")


class TestCopyTrade(unittest.TestCase):
    def test_close_long_winner(self):
        sig = _make_signal(entry_price=1.1000, stop_loss=1.0950, take_profit=1.1150)
        trade = CopyTrade(
            signal=sig, follower_account_id="follower-1", allocation_usd=100
        )
        trade.close(1.1120)
        self.assertEqual(trade.status, TradeStatus.CLOSED)
        self.assertTrue(trade.profit_loss > 0)
        self.assertIsNotNone(trade.closed_at)

    def test_close_long_loser(self):
        sig = _make_signal(entry_price=1.1000, stop_loss=1.0950, take_profit=1.1150)
        trade = CopyTrade(signal=sig, follower_account_id="follower-1")
        trade.close(1.0960)
        self.assertTrue(trade.profit_loss < 0)

    def test_close_short_winner(self):
        sig = _make_signal(
            direction=TradeDirection.SHORT,
            entry_price=1.1000,
            stop_loss=1.1050,
            take_profit=1.0850,
        )
        trade = CopyTrade(signal=sig, follower_account_id="follower-1")
        trade.close(1.0880)
        self.assertTrue(trade.profit_loss > 0)


class TestProviderStats(unittest.TestCase):
    def test_update_winner(self):
        stats = ProviderStats(provider_id="p1", provider_name="Test Provider")
        stats.update(150.0, 2.0)
        self.assertEqual(stats.total_trades, 1)
        self.assertEqual(stats.wins, 1)
        self.assertEqual(stats.losses, 0)
        self.assertAlmostEqual(stats.win_rate, 100.0)
        self.assertAlmostEqual(stats.total_profit, 150.0)

    def test_update_mixed(self):
        stats = ProviderStats(provider_id="p1", provider_name="Test Provider")
        stats.update(100.0, 2.0)
        stats.update(-50.0, 1.5)
        self.assertEqual(stats.total_trades, 2)
        self.assertEqual(stats.wins, 1)
        self.assertEqual(stats.losses, 1)
        self.assertAlmostEqual(stats.win_rate, 50.0)
        self.assertAlmostEqual(stats.total_profit, 50.0)
        self.assertAlmostEqual(stats.avg_risk_reward, 1.75, places=2)

    def test_to_dict(self):
        stats = ProviderStats(provider_id="p1", provider_name="Test")
        d = stats.to_dict()
        self.assertEqual(d["provider_id"], "p1")
        self.assertEqual(d["total_trades"], 0)
        self.assertIn("win_rate", d)


if __name__ == "__main__":
    unittest.main()
