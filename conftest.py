"""Root conftest.py — applies resource limits to all test runs.

Prevents unit tests from consuming more than 20% CPU / 2GB memory on the shared server.
Individual tests or modules can override by calling resource_limits directly.
"""

import os
import sys

# Ensure src is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src", "forex-bot"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from common.resource_limits import configure_pytest_defaults

# Apply memory limit at collection time
configure_pytest_defaults(
    max_memory_mb=int(os.environ.get("MEMRAY_MAX_MEMORY", "2048"))
)


def pytest_collection_modifyitems(config, items):
    """Optional hook: log collection size for diagnostics."""
    import logging

    logging.getLogger("ayumi.resource_limits").debug(
        "Collected %d tests, memory limit active", len(items)
    )
