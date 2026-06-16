"""Resource limits for CPU and memory throttling of test/backtest workloads.

Prevents runaway Python processes (backtests, walk-forward, Optuna, unit tests)
from consuming more than a configured share of server resources.

Usage (context manager):

    with cpu_limited(percent=20):
        run_backtest(...)

    with memory_capped(mb=2048):
        run_walk_forward(...)

Usage (decorator):

    @run_limited(cpu_percent=20, memory_mb=2048)
    def run_optuna(...):
        ...

CLI flags for scripts:

    python scripts/run_wf.py --max-cpu 20 --max-memory-mb 2048
"""

import os
import resource
import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Optional

logger = logging.getLogger("ayumi.resource_limits")

_NCPUS = os.cpu_count() or 1


def _set_cpu_affinity(percent: int = 20) -> None:
    """Pin process to a subset of cores to enforce CPU limit.

    20% on an 8-core machine = ~1.6 cores. We pin to floor(cores * percent/100)
    cores, minimum 1, and set nice to 19.
    """
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        allowed = max(1, int(_NCPUS * percent / 100))
        all_cores = list(range(_NCPUS))
        proc.cpu_affinity(all_cores[:allowed])
        logger.debug("CPU affinity set to %d/%d cores (%d%%)", allowed, _NCPUS, percent)
    except ImportError:
        logger.warning("psutil not available — cannot set CPU affinity")
    except OSError as e:
        logger.warning("CPU affinity failed: %s", e)

    try:
        os.nice(19)
        logger.debug("Nice set to 19")
    except OSError:
        pass


def _set_memory_limit(mb: int = 2048) -> None:
    """Set hard memory limit via RLIMIT_AS."""
    if mb <= 0:
        return
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        new_limit = mb * 1024 * 1024
        # Only lower the limit; never raise above current hard
        if hard == resource.RLIM_INFINITY or new_limit < hard:
            resource.setrlimit(resource.RLIMIT_AS, (new_limit, new_limit))
            logger.debug("Memory limit set to %d MB", mb)
    except (ValueError, OSError) as e:
        logger.warning("Memory limit failed: %s", e)


@contextmanager
def cpu_limited(percent: int = 20):
    """Context manager that limits CPU usage for the duration of the block.

    Args:
        percent: Maximum CPU percentage (relative to total server capacity).
                 20 = 20% of total cores. Pins to N cores and sets nice=19.
    """
    _set_cpu_affinity(percent)
    yield


@contextmanager
def memory_capped(mb: int = 2048):
    """Context manager that sets a hard memory limit for the duration.

    Args:
        mb: Memory limit in megabytes. MemoryError raised if exceeded.
    """
    old_soft, old_hard = resource.getrlimit(resource.RLIMIT_AS)
    _set_memory_limit(mb)
    try:
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_AS, (old_soft, old_hard))


def run_limited(cpu_percent: int = 20, memory_mb: int = 2048):
    """Decorator that applies CPU and memory limits to a function.

    Useful for wrapping backtest runners, walk-forward scripts, Optuna optimization.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with cpu_limited(percent=cpu_percent):
                with memory_capped(mb=memory_mb):
                    return func(*args, **kwargs)
        return wrapper
    return decorator


def configure_pytest_defaults(max_memory_mb: int = 2048) -> None:
    """Configure pytest defaults for memory-limited test runs.

    Call from conftest.py at module scope.
    """
    _set_memory_limit(max_memory_mb)


# ── CLI helper for argparse-based scripts ────────────────────────────────

def add_resource_args(parser) -> None:
    """Add --max-cpu and --max-memory-mb flags to an argparse parser.

    Usage in scripts:

        import argparse
        from common.resource_limits import add_resource_args

        parser = argparse.ArgumentParser()
        add_resource_args(parser)
        args = parser.parse_args()

        with cpu_limited(args.max_cpu):
            with memory_capped(args.max_memory_mb):
                main()
    """
    parser.add_argument(
        "--max-cpu", type=int, default=20,
        help="Max CPU percentage (default: 20%% of server)"
    )
    parser.add_argument(
        "--max-memory-mb", type=int, default=2048,
        help="Max memory in MB per process (default: 2048)"
    )
