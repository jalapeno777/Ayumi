"""Compatibility shim: re-exports OpenApiSpotFeed from archived legacy module.

The old launcher (launch_blend_forward_test.py) and its tests import OpenApiSpotFeed from here.
The new infrastructure uses `market_data_feed.py` instead.

To be removed when the old launcher is retired.
Archived: 2026-06-16 (BQ-1043 Phase 5)
"""
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PROJECT_ROOT = _os.path.abspath(_os.path.join(_HERE, "..", "..", "..", ".."))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

from archive.legacy_ctrader._pkg import open_api_spot_feed as _archive_mod  # noqa: E402

# Re-export underscore-prefixed names that tests need (import * skips them).
_HEARTBEAT_DEGRADED_SEC = _archive_mod._HEARTBEAT_DEGRADED_SEC
_HEARTBEAT_RECONNECT_SEC = _archive_mod._HEARTBEAT_RECONNECT_SEC
_STALE_TICK_WARN_SEC = _archive_mod._STALE_TICK_WARN_SEC
_STALE_TICK_FREEZE_SEC = _archive_mod._STALE_TICK_FREEZE_SEC
_normalize_symbol_name = _archive_mod._normalize_symbol_name
_lots_to_units = _archive_mod._lots_to_units

from archive.legacy_ctrader._pkg.open_api_spot_feed import *  # noqa: F401,F403,E402

__all__ = [n for n in dir(_archive_mod) if not n.startswith("__") or n in {
    "_HEARTBEAT_DEGRADED_SEC", "_HEARTBEAT_RECONNECT_SEC",
    "_STALE_TICK_WARN_SEC", "_STALE_TICK_FREEZE_SEC",
    "_normalize_symbol_name", "_lots_to_units",
}]
