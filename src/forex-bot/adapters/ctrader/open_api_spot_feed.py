"""Compatibility shim: re-exports OpenApiSpotFeed from archived legacy module.

The old launcher (launch_blend_forward_test.py) and its tests import OpenApiSpotFeed from here.
The new infrastructure uses `market_data_feed.py` instead.

Concurrent session note (BQ-1329):
------------------------------------
This module re-exports the live spot feed / order execution class from the
archive.  It authenticates with the primary OpenAPI app credentials
(``CTRADER_OPENAPI_CLIENT_ID`` / ``CTRADER_OPENAPI_CLIENT_SECRET``).
To avoid cTrader's single-session rule, the historical-data client
(``CTraderOpenApiClient`` in ``open_api_client.py``) can authenticate with a
*second* OpenAPI app via ``CTRADER_TRADE_APP_ID`` / ``CTRADER_TRADE_SECRET``.
A fully shared TCP socket was deferred because it requires invasive changes
to the archived feed implementation; the second-app approach is the
Phase-5 pragmatic fallback.

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

# BQ-1327: Explicitly re-export auth payload type constants so consumers
# of the live shim can validate auth responses without importing from
# the archive directly.
_APP_AUTH_RES_PAYLOAD_TYPE = _archive_mod._APP_AUTH_RES_PAYLOAD_TYPE
_ACCT_AUTH_RES_PAYLOAD_TYPE = _archive_mod._ACCT_AUTH_RES_PAYLOAD_TYPE

from archive.legacy_ctrader._pkg.open_api_spot_feed import *  # noqa: F401,F403,E402

__all__ = [n for n in dir(_archive_mod) if not n.startswith("__") or n in {
    "_HEARTBEAT_DEGRADED_SEC", "_HEARTBEAT_RECONNECT_SEC",
    "_STALE_TICK_WARN_SEC", "_STALE_TICK_FREEZE_SEC",
    "_normalize_symbol_name", "_lots_to_units",
    "_APP_AUTH_RES_PAYLOAD_TYPE", "_ACCT_AUTH_RES_PAYLOAD_TYPE",
}]
