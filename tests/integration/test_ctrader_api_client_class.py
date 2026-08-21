"""Tests for T3 — the new ``cTraderAPIClient`` class.

The class existed as a ``TYPE_CHECKING``-only forward reference in
``PaperTrader`` / ``OrderManager`` but had no concrete implementation.
T3 creates the class so the runtime can satisfy the type annotations
and T4 can wire the live spot feed into ``PaperTrader(api_client=...)``.

The legacy test file ``tests/test_ctrader_api_client.py`` was skipped
because it imported the wrong ``api_client`` module (FIX-format types
from a previously-removed file).  We update its skip-line behavior here
and verify the new class directly.
"""

from __future__ import annotations

from adapters.ctrader.api_client import cTraderAPIClient
from adapters.ctrader.open_api_spot_feed import OpenApiSpotFeed


class TestCTraderAPIClientBasics:
    """Smoke tests for the new class."""

    def test_import_succeeds_at_runtime(self):
        """``from adapters.ctrader.api_client import cTraderAPIClient`` works."""
        # Already imported at module level; this is a guard against
        # accidentally re-importing under TYPE_CHECKING-only semantics.
        assert cTraderAPIClient is not None
        assert isinstance(cTraderAPIClient, type)

    def test_subclass_of_openapi_spot_feed(self):
        """``cTraderAPIClient`` subclasses ``OpenApiSpotFeed`` — preserves
        isinstance checks done elsewhere in the codebase."""
        assert issubclass(cTraderAPIClient, OpenApiSpotFeed)

    def test_isinstance_relation_preserved(self):
        """An ``OpenApiSpotFeed`` instance is still a valid target for
        PaperTrader.set_api_client (duck typing).  An instance of the
        subclass is also an OpenApiSpotFeed."""
        # We can't construct a real instance without patching the reactor,
        # but we can verify the subclass relationship via __bases__.
        assert OpenApiSpotFeed in cTraderAPIClient.__bases__

    def test_is_paper_mode_class_attribute_is_false(self):
        """``cTraderAPIClient.is_paper_mode`` is False (live API client).

        The parent class defines ``is_paper_mode`` as a ``@property``
        returning False; we re-affirm this as a class attribute so
        duck-typed attribute access (``getattr(client, "is_paper_mode",
        False)``) is reliable before any instance attribute lookup.
        """
        assert cTraderAPIClient.is_paper_mode is False

    def test_construct_without_connecting(self):
        """Constructing a ``cTraderAPIClient`` does not start a network
        connection.  All kwargs are forwarded to ``OpenApiSpotFeed.__init__``."""
        # We don't start a network connection: the constructor builds the
        # CTraderConnection object but does not call ``start()`` on it.
        # TokenManager writes are harmless (uses path under data/).
        client = cTraderAPIClient(
            ctid_account_id=12345,
            client_id="test_client",
            client_secret="***",  # noqa: S106
            access_token="***",  # noqa: S106
            refresh_token=None,
            host="demo.ctraderapi.com",
            port=5035,
        )
        assert client is not None
        # The instance is also an OpenApiSpotFeed (subclass relationship)
        assert isinstance(client, OpenApiSpotFeed)
        # is_paper_mode is False — satisfies OrderManager / PaperTrader
        assert client.is_paper_mode is False


class TestCTraderAPIClientInModuleExports:
    """Verify the class is part of the public API of the api_client module."""

    def test_module_exports_cTraderAPIClient(self):
        from adapters.ctrader import api_client as api_mod

        assert hasattr(api_mod, "cTraderAPIClient")
        assert api_mod.cTraderAPIClient is cTraderAPIClient

    def test_all_list_includes_class(self):
        from adapters.ctrader import api_client as api_mod

        assert "cTraderAPIClient" in api_mod.__all__

    def test_no_extra_public_symbols_leaked(self):
        """Only ``cTraderAPIClient`` is the public symbol; no helper
        functions should leak via ``from adapters.ctrader.api_client
        import *``."""
        from adapters.ctrader import api_client as api_mod

        assert set(api_mod.__all__) == {"cTraderAPIClient"}
