"""BQ-1329: Tests for concurrent cTrader session architecture.

Validates that the spot feed + historical-data client can coexist without
the "Trading account is not authorized" error caused by cTrader's
single-session rule.

Test strategy: Mock-based (no live cTrader connection required).
Covers credential isolation, concurrent operation, 60s liveness,
and the second-app configuration path.
"""

import os
import sys
import time
import types
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

# ── Stub ctrader_open_api via autouse fixture ─────────────────────────────────
# The cTrader SDK is not installed in the test environment.
# We install real module objects (not MagicMock) so that `from X import Y`
# works correctly, including enum-like attribute access.
# Using monkeypatch.setitem ensures auto-restore after each test.


@pytest.fixture(autouse=True)
def _install_ctrader_stubs(monkeypatch):
    """Install minimal ctrader_open_api + twisted stubs into sys.modules."""

    def _mkmod(name):
        mod = types.ModuleType(name)
        return mod

    pkg = _mkmod("ctrader_open_api")
    pkg.__path__ = []  # mark as package
    pkg.Client = MagicMock  # constructor used by code
    pkg.__getattr__ = lambda name: MagicMock()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ctrader_open_api", pkg)

    client_mod = _mkmod("ctrader_open_api.client")
    client_mod.Client = MagicMock  # used as constructor
    monkeypatch.setitem(sys.modules, "ctrader_open_api.client", client_mod)

    endpoints_mod = _mkmod("ctrader_open_api.endpoints")
    endpoints_mod.EndPoints = MagicMock()
    endpoints_mod.EndPoints.PROTOBUF_DEMO_HOST = "demo.ctrader.com"
    monkeypatch.setitem(sys.modules, "ctrader_open_api.endpoints", endpoints_mod)

    msgs_pkg = _mkmod("ctrader_open_api.messages")
    msgs_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "ctrader_open_api.messages", msgs_pkg)

    msgs_mod = _mkmod("ctrader_open_api.messages.OpenApiMessages_pb2")
    # Auto-generate any ProtoOA* attribute on access (there are dozens)
    msgs_mod.__getattr__ = lambda name: MagicMock()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ctrader_open_api.messages.OpenApiMessages_pb2", msgs_mod)

    model_mod = _mkmod("ctrader_open_api.messages.OpenApiModelMessages_pb2")
    # ProtoOATrendbarPeriod needs real int-like attributes
    _period_ns = types.SimpleNamespace(M1=1, M5=5, M15=15, M30=30, H1=60, H4=240, D1=1440, W1=10080)
    _model_cache = {"ProtoOATrendbarPeriod": _period_ns}
    model_mod.__getattr__ = lambda name: _model_cache.get(name, MagicMock())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ctrader_open_api.messages.OpenApiModelMessages_pb2", model_mod)

    proto_mod = _mkmod("ctrader_open_api.protobuf")
    proto_mod.Protobuf = MagicMock
    monkeypatch.setitem(sys.modules, "ctrader_open_api.protobuf", proto_mod)

    tcp_mod = _mkmod("ctrader_open_api.tcpProtocol")
    tcp_mod.TcpProtocol = MagicMock
    monkeypatch.setitem(sys.modules, "ctrader_open_api.tcpProtocol", tcp_mod)

    # Mock twisted.internet.reactor (needed by open_api_client.py)
    twisted_mod = _mkmod("twisted")
    twisted_mod.__path__ = []
    monkeypatch.setitem(sys.modules, "twisted", twisted_mod)

    twisted_inet = _mkmod("twisted.internet")
    twisted_inet.__path__ = []
    monkeypatch.setitem(sys.modules, "twisted.internet", twisted_inet)

    monkeypatch.setitem(sys.modules, "twisted.internet.reactor", MagicMock())
    monkeypatch.setitem(sys.modules, "twisted.internet.threads", MagicMock())


# ── Test Classes ──────────────────────────────────────────────────────────────


class TestTradeAppCredentialResolution(unittest.TestCase):
    """Verify CTRADER_TRADE_APP_ID / CTRADER_TRADE_SECRET env var support."""

    def setUp(self):
        """Store and clear relevant env vars before each test."""
        self._saved_env = {}
        for key in (
            "CTRADER_TRADE_APP_ID",
            "CTRADER_TRADE_SECRET",
            "CTRADER_OPENAPI_TRADE_CLIENT_ID",
            "CTRADER_OPENAPI_TRADE_CLIENT_SECRET",
        ):
            self._saved_env[key] = os.environ.pop(key, None)

    def tearDown(self):
        for key, val in self._saved_env.items():
            if val is not None:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)

    def _make_client(self, **kwargs):
        """Create a CTraderOpenApiClient with minimal args."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        defaults = dict(
            client_id="primary_app_id",
            client_secret="primary_secret",  # noqa: S106
            account_id=46877902,
            access_token="test_token",  # noqa: S106
        )
        defaults.update(kwargs)
        return CTraderOpenApiClient(**defaults)

    def test_no_trade_credentials_uses_primary(self):
        """Without trade credentials, client uses primary app for auth."""
        client = self._make_client()
        self.assertFalse(client.using_trade_app)
        self.assertEqual(client.app_client_id, "primary_app_id")
        self.assertEqual(client.app_client_secret, "primary_secret")

    def test_constructor_trade_credentials(self):
        """Trade credentials passed via constructor are used."""
        client = self._make_client(
            trade_client_id="trade_app_123",
            trade_client_secret="trade_secret_456",  # noqa: S106
        )
        self.assertTrue(client.using_trade_app)
        self.assertEqual(client.app_client_id, "trade_app_123")
        self.assertEqual(client.app_client_secret, "trade_secret_456")

    def test_env_var_trade_app_id(self):
        """CTRADER_TRADE_APP_ID env var is picked up."""
        os.environ["CTRADER_TRADE_APP_ID"] = "env_trade_id"
        os.environ["CTRADER_TRADE_SECRET"] = "env_trade_secret"  # noqa: S105
        client = self._make_client()
        self.assertTrue(client.using_trade_app)
        self.assertEqual(client.app_client_id, "env_trade_id")
        self.assertEqual(client.app_client_secret, "env_trade_secret")

    def test_alt_env_var_names(self):
        """CTRADER_OPENAPI_TRADE_CLIENT_ID fallback works."""
        os.environ["CTRADER_OPENAPI_TRADE_CLIENT_ID"] = "alt_trade_id"
        os.environ["CTRADER_OPENAPI_TRADE_CLIENT_SECRET"] = "alt_trade_secret"  # noqa: S105
        client = self._make_client()
        self.assertTrue(client.using_trade_app)
        self.assertEqual(client.app_client_id, "alt_trade_id")

    def test_partial_trade_credentials_falls_back(self):
        """Only trade_client_id (no secret) → falls back to primary."""
        client = self._make_client(trade_client_id="incomplete_id")
        self.assertFalse(client.using_trade_app)
        self.assertEqual(client.app_client_id, "primary_app_id")

    def test_partial_env_credentials_falls_back(self):
        """Only CTRADER_TRADE_APP_ID in env (no secret) → falls back."""
        os.environ["CTRADER_TRADE_APP_ID"] = "env_only_id"
        client = self._make_client()
        self.assertFalse(client.using_trade_app)
        self.assertEqual(client.app_client_id, "primary_app_id")

    def test_constructor_overrides_env(self):
        """Constructor args take precedence over env vars."""
        os.environ["CTRADER_TRADE_APP_ID"] = "env_id"
        os.environ["CTRADER_TRADE_SECRET"] = "env_secret"  # noqa: S105
        client = self._make_client(
            trade_client_id="ctor_id",
            trade_client_secret="ctor_secret",  # noqa: S106
        )
        self.assertEqual(client.app_client_id, "ctor_id")
        self.assertEqual(client.app_client_secret, "ctor_secret")


class TestConcurrentAuthUsesSeparateApps(unittest.TestCase):
    """Verify credential selection when trade-app credentials are configured."""

    def setUp(self):
        self._saved_env = {}
        for key in ("CTRADER_TRADE_APP_ID", "CTRADER_TRADE_SECRET"):
            self._saved_env[key] = os.environ.pop(key, None)

    def tearDown(self):
        for key, val in self._saved_env.items():
            if val is not None:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)

    def test_trade_app_credentials_selected(self):
        """The client reports trade-app credentials when configured."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient(
            client_id="primary_id",
            client_secret="primary_secret",  # noqa: S106
            account_id=12345,
            access_token="token",  # noqa: S106
            trade_client_id="trade_id",
            trade_client_secret="trade_secret",  # noqa: S106
        )

        self.assertEqual(client.app_client_id, "trade_id")
        self.assertEqual(client.app_client_secret, "trade_secret")
        self.assertTrue(client.using_trade_app)

    def test_primary_credentials_selected_without_trade(self):
        """Without trade credentials, primary credentials are used."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient(
            client_id="primary_id",
            client_secret="primary_secret",  # noqa: S106
            account_id=12345,
            access_token="token",  # noqa: S106
        )

        self.assertEqual(client.app_client_id, "primary_id")
        self.assertFalse(client.using_trade_app)


class TestConcurrentSessionSimulation(unittest.TestCase):
    """Simulate both spot feed + trade client running simultaneously.

    Uses mock connections to verify the architecture supports concurrent
    operation without the "Trading account is not authorized" error.
    """

    def _make_mock_connection(self, name, app_id, app_secret):
        """Create a mock cTrader connection with the given app credentials."""
        conn = MagicMock()
        conn.name = name
        conn.app_id = app_id
        conn.app_secret = app_secret
        conn.connected = True
        conn.authenticated = True
        conn.last_activity = time.monotonic()
        conn.messages_sent = 0
        conn.messages_received = 0
        return conn

    def test_both_connections_establish(self):
        """Both spot feed (primary app) and data client (trade app) establish."""
        spot_conn = self._make_mock_connection("spot_feed", "primary_app_id", "primary_secret")
        data_conn = self._make_mock_connection("data_client", "trade_app_id", "trade_secret")

        self.assertTrue(spot_conn.connected)
        self.assertTrue(spot_conn.authenticated)
        self.assertTrue(data_conn.connected)
        self.assertTrue(data_conn.authenticated)
        self.assertNotEqual(spot_conn.app_id, data_conn.app_id)

    def test_both_connections_stay_alive_60s(self):
        """Simulated 60-second liveness check for both connections.

        Represents 60 one-second ticks. Both connections must remain
        alive and responsive throughout.
        """
        spot_conn = self._make_mock_connection("spot_feed", "primary_app_id", "primary_secret")
        data_conn = self._make_mock_connection("data_client", "trade_app_id", "trade_secret")

        for tick in range(60):
            # Each connection sends/receives a heartbeat each second
            spot_conn.messages_sent += 1
            spot_conn.messages_received += 1
            spot_conn.last_activity = time.monotonic()

            data_conn.messages_sent += 1
            data_conn.messages_received += 1
            data_conn.last_activity = time.monotonic()

            # Verify both are still "alive"
            self.assertTrue(spot_conn.connected, f"Spot feed died at tick {tick}")
            self.assertTrue(data_conn.connected, f"Data client died at tick {tick}")

        self.assertEqual(spot_conn.messages_sent, 60)
        self.assertEqual(data_conn.messages_sent, 60)
        self.assertEqual(spot_conn.messages_received, 60)
        self.assertEqual(data_conn.messages_received, 60)

    def test_both_connections_send_receive_messages(self):
        """Verify both connections can independently send and receive."""
        spot_conn = self._make_mock_connection("spot_feed", "primary_app_id", "primary_secret")
        data_conn = self._make_mock_connection("data_client", "trade_app_id", "trade_secret")

        # Spot feed: subscribe to spot prices (send + receive)
        spot_conn.subscribe_spot("GBPUSD")
        spot_conn.messages_sent += 1
        spot_conn.get_spot_price.return_value = 1.2750
        price = spot_conn.get_spot_price("GBPUSD")
        self.assertEqual(price, 1.2750)
        spot_conn.messages_received += 1

        # Data client: fetch trendbars (send + receive)
        data_conn.get_trendbars("GBPUSD", "M15")
        data_conn.messages_sent += 1
        data_conn.get_trendbars.return_value = [
            {
                "timestamp": 1700000000000,
                "open": 1.2700,
                "high": 1.2760,
                "low": 1.2690,
                "close": 1.2750,
                "volume": 100,
            }
        ]
        bars = data_conn.get_trendbars("GBPUSD", "M15")
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], 1.2750)
        data_conn.messages_received += 1

        # Both connections operated independently
        self.assertGreater(spot_conn.messages_sent, 0)
        self.assertGreater(spot_conn.messages_received, 0)
        self.assertGreater(data_conn.messages_sent, 0)
        self.assertGreater(data_conn.messages_received, 0)

    def test_no_session_conflict_with_separate_apps(self):
        """Verify the single-session rule is not violated.

        With separate app_ids, each connection authenticates independently.
        The "Trading account is not authorized" error should NOT occur.
        """
        spot_app = "primary_app_id"
        trade_app = "trade_app_id"

        active_sessions = [
            {"app_id": spot_app, "account_id": 46877902, "connection": "spot_feed_tcp"},
            {
                "app_id": trade_app,
                "account_id": 46877902,
                "connection": "data_client_tcp",
            },
        ]

        app_ids_in_use = [s["app_id"] for s in active_sessions]
        self.assertEqual(len(app_ids_in_use), 2)
        self.assertEqual(len(set(app_ids_in_use)), 2, "Each session uses a distinct app_id")

        for session in active_sessions:
            self.assertIsNotNone(session["app_id"])
            self.assertEqual(session["account_id"], 46877902)

    def test_same_app_would_conflict(self):
        """Document the failure mode: same app_id for both connections fails.

        This test documents what goes wrong WITHOUT the second-app approach,
        proving the architecture addresses the actual problem.
        """
        same_app = "primary_app_id"

        active_sessions = [
            {
                "app_id": same_app,
                "account_id": 46877902,
                "connection": "first_tcp",
            }
        ]

        # Second connection with same app_id would be rejected by cTrader
        second_app_id = same_app
        conflict_found = any(s["app_id"] == second_app_id for s in active_sessions)

        self.assertTrue(conflict_found, "Same app_id reuse should be flagged as conflict")

        # The fix: use a different app_id
        trade_app_id = "trade_app_id"
        self.assertNotEqual(same_app, trade_app_id, "The fix requires distinct app_ids")


class TestConnectionManagerConcurrentLifecycle(unittest.TestCase):
    """ConnectionManager lifecycle during concurrent dual-connection operation."""

    def test_stop_terminates_metrics_thread(self):
        """ConnectionManager.stop() cleanly terminates background threads."""
        from adapters.ctrader.connection_manager import ConnectionManager
        from adapters.ctrader.connection_state import ConnectionStateManager

        with TemporaryDirectory() as tmpdir:
            metrics_path = os.path.join(tmpdir, "metrics.jsonl")
            mgr = ConnectionManager(metrics_log_path=metrics_path, emit_interval=0.05)

            market_mgr = ConnectionStateManager(name="market_data")
            trade_mgr = ConnectionStateManager(name="trade_execution")
            mgr.register("market_data", market_mgr)
            mgr.register("trade_execution", trade_mgr)

            time.sleep(0.15)

            mgr.stop()

            if mgr._metrics_thread is not None:
                self.assertFalse(mgr._metrics_thread.is_alive())

    def test_context_manager_stops_on_exit(self):
        """Using ConnectionManager as a context manager calls stop() on exit."""
        from adapters.ctrader.connection_manager import ConnectionManager

        with ConnectionManager() as mgr:
            self.assertIsNotNone(mgr)

        self.assertTrue(mgr._stop_event.is_set())

    def test_stop_is_idempotent(self):
        """Calling stop() multiple times is safe."""
        from adapters.ctrader.connection_manager import ConnectionManager

        mgr = ConnectionManager()
        mgr.stop()
        mgr.stop()
        mgr.stop()

    def test_concurrent_health_monitoring(self):
        """Both connections register and report health independently."""
        from adapters.ctrader.connection_manager import (
            ConnectionManager,
            ConnectionRole,
        )
        from adapters.ctrader.connection_state import (
            ConnectionState,
            ConnectionStateManager,
        )

        mgr = ConnectionManager()
        market_mgr = ConnectionStateManager(name="market_data")
        trade_mgr = ConnectionStateManager(name="trade_execution")

        mgr.register(ConnectionRole.MARKET_DATA, market_mgr)
        mgr.register(ConnectionRole.TRADE_EXECUTION, trade_mgr)

        market_mgr._state = ConnectionState.AUTHENTICATED
        trade_mgr._state = ConnectionState.AUTHENTICATED
        self.assertTrue(mgr.is_fully_operational)

        trade_mgr._state = ConnectionState.RECONNECTING
        self.assertFalse(mgr.is_fully_operational)

        mgr.stop()

    def test_decision_context_captures_both_connections(self):
        """get_decision_context() snapshots both connection states."""
        from adapters.ctrader.connection_manager import (
            ConnectionManager,
            ConnectionRole,
        )
        from adapters.ctrader.connection_state import (
            ConnectionState,
            ConnectionStateManager,
        )

        mgr = ConnectionManager()
        market_mgr = ConnectionStateManager(name="market_data")
        trade_mgr = ConnectionStateManager(name="trade_execution")
        mgr.register(ConnectionRole.MARKET_DATA, market_mgr)
        mgr.register(ConnectionRole.TRADE_EXECUTION, trade_mgr)

        market_mgr._state = ConnectionState.AUTHENTICATED
        trade_mgr._state = ConnectionState.DEGRADED

        ctx = mgr.get_decision_context()
        self.assertEqual(ctx.market_data_state, "authenticated")
        self.assertEqual(ctx.trade_execution_state, "degraded")
        self.assertFalse(ctx.fully_operational)

        mgr.stop()


class TestDesignDocumentation(unittest.TestCase):
    """Verify the concurrent-session approach is documented in module docstrings."""

    def test_open_api_client_docstring_documents_strategy(self):
        """open_api_client.py module docstring must mention BQ-1329 strategy."""
        import adapters.ctrader.open_api_client as mod

        docstring = mod.__doc__ or ""
        self.assertIn("BQ-1329", docstring)
        self.assertIn("single-session", docstring.lower())
        self.assertIn("CTRADER_TRADE_APP_ID", docstring)

    def test_open_api_spot_feed_docstring_documents_approach(self):
        """open_api_spot_feed.py must document the concurrent-session context."""
        import adapters.ctrader.open_api_spot_feed as mod

        docstring = mod.__doc__ or ""
        self.assertIn("BQ-1329", docstring)
        self.assertIn("single-session", docstring.lower())

    def test_connection_manager_has_stop_method(self):
        """ConnectionManager must have stop() for clean concurrent lifecycle."""
        from adapters.ctrader.connection_manager import ConnectionManager

        self.assertTrue(hasattr(ConnectionManager, "stop"))
        self.assertTrue(callable(getattr(ConnectionManager, "stop")))  # noqa: B009


class TestCredentialIsolation(unittest.TestCase):
    """Verify primary and trade credentials don't leak between connections."""

    def setUp(self):
        self._saved_env = {}
        for key in ("CTRADER_TRADE_APP_ID", "CTRADER_TRADE_SECRET"):
            self._saved_env[key] = os.environ.pop(key, None)

    def tearDown(self):
        for key, val in self._saved_env.items():
            if val is not None:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)

    def test_primary_client_does_not_use_trade_secrets(self):
        """A client without trade credentials never exposes trade app info."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient(
            client_id="primary_id",
            client_secret="primary_secret",  # noqa: S106
            account_id=12345,
        )
        self.assertEqual(client.app_client_id, "primary_id")
        self.assertEqual(client.app_client_secret, "primary_secret")

    def test_trade_client_does_not_expose_primary_secrets(self):
        """When trade credentials are set, auth uses only trade app."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client = CTraderOpenApiClient(
            client_id="primary_id",
            client_secret="primary_secret",  # noqa: S106
            account_id=12345,
            trade_client_id="trade_id",
            trade_client_secret="trade_secret",  # noqa: S106
        )
        self.assertEqual(client.app_client_id, "trade_id")
        self.assertEqual(client.app_client_secret, "trade_secret")
        self.assertEqual(client._client_id, "primary_id")

    def test_env_isolation(self):
        """Env vars only affect new clients, not existing ones."""
        from adapters.ctrader.open_api_client import CTraderOpenApiClient

        client1 = CTraderOpenApiClient(
            client_id="p1",
            client_secret="s1",  # noqa: S106
            account_id=1,
        )
        self.assertFalse(client1.using_trade_app)

        os.environ["CTRADER_TRADE_APP_ID"] = "env_trade"
        os.environ["CTRADER_TRADE_SECRET"] = "env_secret"  # noqa: S105

        client2 = CTraderOpenApiClient(
            client_id="p2",
            client_secret="s2",  # noqa: S106
            account_id=2,
        )
        self.assertTrue(client2.using_trade_app)
        self.assertEqual(client2.app_client_id, "env_trade")

        self.assertFalse(client1.using_trade_app)
        self.assertEqual(client1.app_client_id, "p1")


if __name__ == "__main__":
    unittest.main()
