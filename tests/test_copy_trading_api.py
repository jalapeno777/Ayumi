from __future__ import annotations

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from crypto.bot.api import create_app
from crypto.services.repository import TradeRepository


class TestAPI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.repo = TradeRepository(self.db_path)
        self.repo.upsert_provider("p1", "Alpha Trader", "ICT OB", 10)
        self.repo.upsert_provider("p2", "Beta Scalper", "SMC FVG", 5)
        self.client = TestClient(create_app(self.repo))

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_leaderboard(self):
        r = self.client.get("/api/leaderboard")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["provider_name"], "Alpha Trader")

    def test_leaderboard_with_limit(self):
        r = self.client.get("/api/leaderboard?limit=1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)

    def test_signals_empty(self):
        r = self.client.get("/api/signals")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_provider_stats(self):
        r = self.client.get("/api/providers/p1/stats")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["provider_name"], "Alpha Trader")

    def test_provider_stats_not_found(self):
        r = self.client.get("/api/providers/nonexistent/stats")
        self.assertEqual(r.status_code, 404)

    def test_webhook_signal_missing_fields(self):
        r = self.client.post("/api/webhook/signal", json={"symbol": "EURUSD"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Missing fields", r.json()["error"])

    def test_webhook_signal_unknown_provider(self):
        r = self.client.post("/api/webhook/signal", json={
            "provider_id": "unknown",
            "symbol": "EURUSD",
            "direction": "long",
            "entry_price": 1.1000,
            "stop_loss": 1.0950,
            "take_profit": 1.1150,
        })
        self.assertEqual(r.status_code, 403)

    def test_webhook_signal_success(self):
        r = self.client.post("/api/webhook/signal", json={
            "provider_id": "p1",
            "symbol": "EURUSD",
            "direction": "long",
            "entry_price": 1.1000,
            "stop_loss": 1.0950,
            "take_profit": 1.1150,
            "lot_size": 0.1,
            "strategy_name": "ICT OB",
            "confluence_count": 3,
            "strength": "strong",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
        self.assertGreater(r.json()["signal_id"], 0)

        signals = self.client.get("/api/signals").json()
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["symbol"], "EURUSD")

    def test_leaderboard_page(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Ayumi Copy Trading Leaderboard", r.text)

    def test_404(self):
        r = self.client.get("/nonexistent")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
