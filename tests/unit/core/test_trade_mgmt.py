"""Tests for TradeManagementMixin.

Rewritten for post-refactor API (card 99a4d28d).
- EngineCore requires BacktestConfig
- TradeManagementMixin.__init__ takes optional tm_config
"""

from __future__ import annotations


from core.config import BacktestConfig
from engine.base import EngineCore
from engine.trade_mgmt import TradeManagementMixin


class _TMHost(EngineCore, TradeManagementMixin):
    def __init__(self):
        config = BacktestConfig()
        EngineCore.__init__(self, config)
        TradeManagementMixin.__init__(self)


def test_tm_host_creates():
    host = _TMHost()
    assert hasattr(host, "config")
    assert hasattr(host, "_tm_config")


def test_tm_host_is_engine_core():
    host = _TMHost()
    assert isinstance(host, EngineCore)
    assert isinstance(host, TradeManagementMixin)


def test_check_entry_allowed_signature():
    host = _TMHost()
    # check_entry_allowed requires bar, signal, atr, spread_pips, pair
    assert callable(host.check_entry_allowed)
