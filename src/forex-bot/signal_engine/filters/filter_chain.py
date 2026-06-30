"""FilterChain — priority-ordered, short-circuit evaluation of signal filters.

Filters are sorted by priority (ascending). The first filter to reject
a signal stops the chain — no later filters run. This mirrors the
production philosophy: cheap checks first, expensive checks only if
cheap ones pass.

Usage:
    chain = FilterChain()
    chain.add(TrendFilter())
    chain.add(ATRFilter())
    chain.add(FVGFilter())

    if chain.evaluate(signal_direction="LONG", context=filter_ctx):
        # Signal passes all filters
        ...
    else:
        # Signal rejected — check chain.last_rejection
        logger.info(chain.last_rejection)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .trend_filter import TrendFilter
from .atr_filter import ATRFilter
from .fvg_filter import FVGFilter

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    """Outcome of a chain evaluation."""
    passed: bool
    filter_name: str = ""
    reason: str = ""


class FilterChain:
    """Priority-ordered filter chain with short-circuit evaluation."""

    def __init__(self, filters: Optional[list] = None) -> None:
        self._filters: list = []
        self._last_result: FilterResult = FilterResult(passed=True)

        if filters:
            for f in filters:
                self.add(f)
        else:
            # Default chain: trend → atr → fvg
            self.add(TrendFilter())
            self.add(ATRFilter())
            self.add(FVGFilter())

    def add(self, signal_filter: Any) -> None:
        """Add a filter, keeping the list sorted by priority."""
        priority = getattr(signal_filter, "priority", 50)
        insert_at = 0
        for i, existing in enumerate(self._filters):
            existing_pri = getattr(existing, "priority", 50)
            if priority < existing_pri:
                break
            insert_at = i + 1
        self._filters.insert(insert_at, signal_filter)
        logger.debug(
            "FilterChain: added %s (priority=%d) at position %d",
            getattr(signal_filter, "name", type(signal_filter).__name__),
            priority, insert_at,
        )

    @property
    def filters(self) -> list:
        """Return filters in priority order."""
        return list(self._filters)

    @property
    def last_result(self) -> FilterResult:
        return self._last_result

    def evaluate(self, **context: Any) -> bool:
        """Run all filters in priority order.

        Short-circuits on first rejection. Returns True if all filters pass.

        The context dict is unpacked and passed to each filter's evaluate().
        Each filter picks the keys it needs from kwargs.
        """
        for f in self._filters:
            name = getattr(f, "name", type(f).__name__)
            try:
                # Each filter receives the full context and picks what it needs
                # We use a signature that accepts **kwargs per filter
                passed = self._call_filter(f, **context)
                if not passed:
                    self._last_result = FilterResult(
                        passed=False,
                        filter_name=name,
                        reason=f"{name} rejected signal",
                    )
                    logger.debug("FilterChain short-circuit at %s", name)
                    return False
            except Exception as exc:
                logger.warning("FilterChain: %s raised %s — treating as pass", name, exc)
                # Don't fail the chain on a filter error — fail open
                continue

        self._last_result = FilterResult(passed=True)
        return True

    def _call_filter(self, f: Any, **context: Any) -> bool:
        """Call a filter's evaluate method with the relevant kwargs.

        Inspects the filter's evaluate signature and passes only
        the kwargs it accepts.
        """
        import inspect

        sig = inspect.signature(f.evaluate)
        applicable = {}
        for param_name, param in sig.parameters.items():
            if param_name in context:
                applicable[param_name] = context[param_name]
            elif param.default is not inspect.Parameter.empty:
                # Has a default — skip
                continue
            elif param.kind == inspect.Parameter.VAR_KEYWORD:
                # **kwargs — pass everything
                applicable = context
                break
            else:
                # Required param not in context — let the filter use its default
                # or raise naturally
                continue

        return f.evaluate(**applicable)
