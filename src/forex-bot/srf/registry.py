"""SRF Strategy Registry — decorator-based registration with search spaces."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class StrategyRegistration:
    name: str
    version: str
    module_path: str
    status: str  # "draft", "production", "retired"
    strategy_class: type
    search_space: dict[str, tuple] = field(default_factory=dict)
    default_params: dict[str, Any] = field(default_factory=dict)


# ── Global registry ──────────────────────────────────────────────────────

_REGISTRY: dict[str, StrategyRegistration] = {}


def register_strategy(
    name: str,
    *,
    version: str = "1.0",
    status: str = "production",
    default_params: dict | None = None,
):
    """Decorator that registers a strategy class in the SRF registry.

    Usage:
        @register_strategy("srmr_plus", version="1.0", status="production")
        class SRMRPlusStrategy:
            @staticmethod
            def search_space():
                return {"rsi_long_level": (15.0, 48.0), ...}
    """

    def decorator(cls: type) -> type:
        space = {}
        if hasattr(cls, "search_space"):
            space = cls.search_space()

        _REGISTRY[name] = StrategyRegistration(
            name=name,
            version=version,
            status=status,
            module_path=f"{cls.__module__}.{cls.__name__}",
            strategy_class=cls,
            search_space=space,
            default_params=default_params or {},
        )
        logger.info("Registered strategy: %s v%s [%s]", name, version, status)
        return cls

    return decorator


def get_strategy(name: str) -> StrategyRegistration | None:
    """Retrieve a registered strategy by name."""
    return _REGISTRY.get(name)


def list_strategies(
    *, status: str | None = None
) -> list[StrategyRegistration]:
    """List all registered strategies, optionally filtered by status."""
    strategies = list(_REGISTRY.values())
    if status:
        strategies = [s for s in strategies if s.status == status]
    return strategies


def discover_strategies(package: str = "strategies") -> None:
    """Auto-discover and register strategies from a package directory.

    Imports all modules in the package so decorators fire.
    """
    try:
        pkg = importlib.import_module(package)
    except ImportError:
        logger.warning("Strategy package '%s' not found", package)
        return

    if not hasattr(pkg, "__path__"):
        # Single module, not a package
        return

    for importer, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
        full_name = f"{package}.{modname}"
        try:
            importlib.import_module(full_name)
        except Exception as exc:
            logger.debug("Skipping %s: %s", full_name, exc)

    logger.info(
        "Discovery complete: %d strategies registered", len(_REGISTRY)
    )
