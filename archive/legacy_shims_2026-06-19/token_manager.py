"""Compatibility shim: re-exports TokenManager from archived legacy module.

Deprecated (BQ-681): use `token_lifecycle.TokenLifecycle` instead.
This shim remains only because the old launcher (launch_blend_forward_test.py)
still imports `TokenManager` from here. It will be removed when that launcher
is retired.

Archived: 2026-06-16 (BQ-1043 Phase 5)
"""
import warnings

warnings.warn(
    "token_manager is deprecated, use token_lifecycle instead",
    DeprecationWarning,
    stacklevel=2,
)

import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PROJECT_ROOT = _os.path.abspath(_os.path.join(_HERE, "..", "..", "..", ".."))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

from archive.legacy_ctrader._pkg import token_manager as _archive_mod  # noqa: E402
from archive.legacy_ctrader._pkg.token_manager import *  # noqa: F401,F403,E402
__all__ = getattr(_archive_mod, "__all__", None) or [n for n in dir(_archive_mod) if not n.startswith("__")]
