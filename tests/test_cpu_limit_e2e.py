"""E2E CPU limit validation for cpu_limited (BQ-1038).

This test is intentionally skipped in normal CI because it burns 60 seconds
of CPU time. Run it manually when validating the advisory CPU limiter.
"""

import time
import psutil
import pytest

from common.resource_limits import cpu_limited


@pytest.mark.skip(reason="60s test; run manually")
def test_cpu_limited_20_percent_measured_under_cap():
    """Run a 60s CPU-busy loop under cpu_limited(20) and measure actual CPU%.

    The limiter uses advisory enforcement (cpu_affinity + nice=19), so the
    measured average should be <= 20% of total server capacity on a quiet
    machine, but may exceed it under contention or due to nice being ignored.
    """
    duration = 60.0
    process = psutil.Process()

    # Discard any stale baseline reading
    process.cpu_percent(interval=None)

    with cpu_limited(percent=20):
        start = time.monotonic()
        # CPU-busy loop; no I/O
        while time.monotonic() - start < duration:
            _ = sum(i * i for i in range(1000))
            # Yield tiny slices so nice/affinity have a chance to throttle
            time.sleep(0.0001)

    elapsed = time.monotonic() - start
    measured = process.cpu_percent(interval=None)
    # cpu_percent() returns cumulative percent since last call over the
    # process lifetime, divided by CPU count. Give it a moment to settle.
    time.sleep(0.5)
    measured_final = process.cpu_percent(interval=None)

    print(
        f"\nCPU E2E: elapsed={elapsed:.1f}s, cpu_percent={measured:.1f}%, "
        f"final_cpu_percent={measured_final:.1f}%"
    )

    # Soft assertion — advisory enforcement may fail; result is documented.
    assert measured <= 20.0, (
        f"Measured CPU {measured:.1f}% exceeded 20% cap; "
        "advisory enforcement insufficient on this host"
    )
