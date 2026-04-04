from __future__ import annotations

import os
import tempfile
import unittest

from crypto.services.repository import TradeRepository


class TestTradeRepository(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.repo = TradeRepository(self.db_path)
        self.repo.upsert_provider("p1", "Alpha Trader", "ICT OB", 10)
        self.repo.upsert_provider("p2", "Beta Scalper", "SMC FVG", 5)

    def _insert_signal(self, **overrides) -> int:
        signal = {
            "provider_id": "p1",
            "symbol": "EURUSD",
            "direction": "long",
            "entry_price": 1.1000,
            "stop_loss": 1.0950,
            "take_profit": 1.1150,
            "lot_size": 0.1,
            "signal_time": "2026-04-03T12:00:00",
            "strategy_name": "ICT OB",
            "confluence_count": 3,
            "strength": "strong",
        }
        signal.update(overrides)
        return self.repo.save_signal(signal)

    def _insert_closed_trade(self, signal_id: int, profit: float) -> int:
        trade = {
            "signal_id": signal_id,
            "follower_account_id": "f1",
            "allocation_usd": 100,
            "status": "closed",
            "opened_at": "2026-04-03T12:00:00",
        }
        tid = self.repo.save_trade(trade)
        self.repo.close_trade(tid, 1.1100, profit)
        return tid

    def test_upsert_provider(self):
        self.repo.upsert_provider("p3", "New Provider", "Strategy", 1)
        stats = self.repo.get_provider_stats("p3")
        self.assertEqual(stats["provider_name"], "New Provider")

    def test_save_signal(self):
        sid = self._insert_signal()
        self.assertGreater(sid, 0)

    def test_save_and_close_trade(self):
        sid = self._insert_signal()
        tid = self.repo.save_trade(
            {
                "signal_id": sid,
                "follower_account_id": "f1",
                "allocation_usd": 100,
            }
        )
        self.repo.close_trade(tid, 1.1120, 120.0)
        signals = self.repo.get_recent_signals()
        self.assertEqual(len(signals), 1)

    def test_get_provider_stats_empty(self):
        stats = self.repo.get_provider_stats("p1")
        self.assertEqual(stats["total_trades"], 0)
        self.assertEqual(stats["total_profit"], 0.0)

    def test_get_provider_stats_with_trades(self):
        sid = self._insert_signal()
        self._insert_closed_trade(sid, 100.0)
        stats = self.repo.get_provider_stats("p1")
        self.assertEqual(stats["total_trades"], 1)
        self.assertEqual(stats["wins"], 1)
        self.assertAlmostEqual(stats["total_profit"], 100.0)

    def test_get_leaderboard(self):
        s1 = self._insert_signal(provider_id="p1")
        s2 = self._insert_signal(provider_id="p2")
        self._insert_closed_trade(s1, 200.0)
        self._insert_closed_trade(s2, 50.0)
        lb = self.repo.get_leaderboard()
        self.assertEqual(len(lb), 2)
        self.assertEqual(lb[0]["provider_name"], "Alpha Trader")
        self.assertGreater(lb[0]["total_profit"], lb[1]["total_profit"])

    def test_get_recent_signals(self):
        self._insert_signal()
        self._insert_signal(provider_id="p2", symbol="GBPUSD")
        signals = self.repo.get_recent_signals()
        self.assertEqual(len(signals), 2)

    def test_close_trade_updates_status(self):
        sid = self._insert_signal()
        tid = self.repo.save_trade({"signal_id": sid, "follower_account_id": "f1"})
        self.repo.close_trade(tid, 1.0980, -20.0)
        stats = self.repo.get_provider_stats("p1")
        self.assertEqual(stats["losses"], 1)


class TestBroadcaster(unittest.TestCase):
    def test_format_discord_signal(self):
        from crypto.services.broadcaster import SignalBroadcaster

        b = SignalBroadcaster()
        sig = {
            "provider_id": "p1",
            "symbol": "EURUSD",
            "direction": "long",
            "entry_price": 1.1000,
            "stop_loss": 1.0950,
            "take_profit": 1.1150,
            "lot_size": 0.1,
            "signal_time": "2026-04-03T12:00:00",
            "strategy_name": "ICT OB",
            "confluence_count": 3,
            "strength": "strong",
            "risk_reward": 3.0,
        }
        result = b.format_signal(sig)
        self.assertIn("EURUSD", result["formatted"])
        self.assertIn("LONG", result["formatted"])
        self.assertIn("ICT OB", result["formatted"])

    def test_webhook_handler_valid(self):
        from crypto.services.broadcaster import WebhookHandler

        wh = WebhookHandler(providers={"p1"})
        payload = {
            "provider_id": "p1",
            "symbol": "EURUSD",
            "direction": "long",
            "entry_price": 1.1000,
            "stop_loss": 1.0950,
            "take_profit": 1.1150,
        }
        result = wh.handle_incoming(payload)
        self.assertIsNotNone(result)
        self.assertEqual(result["symbol"], "EURUSD")

    def test_webhook_handler_invalid(self):
        from crypto.services.broadcaster import WebhookHandler

        wh = WebhookHandler()
        result = wh.handle_incoming({"symbol": "EURUSD"})
        self.assertIsNone(result)

    def test_webhook_handler_unknown_provider(self):
        from crypto.services.broadcaster import WebhookHandler

        wh = WebhookHandler(providers={"p1"})
        payload = {
            "provider_id": "unknown",
            "symbol": "EURUSD",
            "direction": "long",
            "entry_price": 1.1000,
            "stop_loss": 1.0950,
            "take_profit": 1.1150,
        }
        result = wh.handle_incoming(payload)
        self.assertIsNone(result)


class TestCopyTradingBot(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self.tmpdir, "test.db")
        from crypto.bot.copy_trading_bot import CopyTradingBot

        self.bot = CopyTradingBot(repo=TradeRepository(db_path))

    def test_register_provider(self):
        self.bot.register_provider("p1", "Alpha", "ICT", 10)
        stats = self.bot.get_provider_stats("p1")
        self.assertEqual(stats["provider_name"], "Alpha")

    def test_receive_signal(self):
        self.bot.register_provider("p1", "Alpha")
        signal = self.bot.receive_signal(
            {
                "provider_id": "p1",
                "symbol": "EURUSD",
                "direction": "long",
                "entry_price": 1.1000,
                "stop_loss": 1.0950,
                "take_profit": 1.1150,
            }
        )
        self.assertIsNotNone(signal)
        self.assertIn("signal_db_id", signal)

    def test_receive_signal_unknown_provider(self):
        signal = self.bot.receive_signal(
            {
                "provider_id": "unknown",
                "symbol": "EURUSD",
                "direction": "long",
                "entry_price": 1.1000,
                "stop_loss": 1.0950,
                "take_profit": 1.1150,
            }
        )
        self.assertIsNone(signal)

    def test_broadcast_signal(self):
        from crypto.models.trade import TradeSignal, TradeDirection

        sig = TradeSignal(
            provider_id="p1",
            symbol="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1150,
        )
        result = self.bot.broadcast_signal(sig)
        self.assertIn("formatted", result)
        self.assertIn("EURUSD", result["formatted"])

    def test_leaderboard_empty(self):
        lb = self.bot.get_leaderboard()
        self.assertEqual(lb, [])


if __name__ == "__main__":
    unittest.main()
