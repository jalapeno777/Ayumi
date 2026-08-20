"""Compatibility shim: re-exports CTraderAuth from archived legacy module.

The old launcher (launch_blend_forward_test.py) imports CTraderAuth from here.
The new infrastructure uses `session.py` / `credential_store.py` instead.

To be removed when the old launcher is retired.
Archived: 2026-06-16 (BQ-1043 Phase 5)
"""

import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PROJECT_ROOT = _os.path.abspath(_os.path.join(_HERE, "..", "..", "..", ".."))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

from archive.legacy_ctrader._pkg import auth as _archive_mod  # noqa: E402, I001
from archive.legacy_ctrader._pkg.auth import *  # noqa: F401,F403,E402

__all__ = getattr(_archive_mod, "__all__", None) or [n for n in dir(_archive_mod) if not n.startswith("__")]
