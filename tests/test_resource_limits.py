"""Tests for CPU and memory resource limit context managers (BQ-1038)."""

import os
import resource
import pytest

from common.resource_limits import (
    cpu_limited,
    memory_capped,
    run_limited,
    configure_pytest_defaults,
    add_resource_args,
)


# ── cpu_limited ─────────────────────────────────────────────────────────

class TestCpuLimited:
    def test_cpu_limited_is_context_manager(self):
        """cpu_limited returns a context manager that can be entered and exited."""
        with cpu_limited(percent=50):
            pass  # Should not raise

    def test_cpu_limited_accepts_various_percentages(self):
        """cpu_limited works with different percentage values."""
        for percent in (1, 10, 25, 50, 100):
            with cpu_limited(percent=percent):
                pass

    def test_cpu_limited_default_parameter(self):
        """Default percent is 20."""
        with cpu_limited():
            pass


# ── memory_capped ───────────────────────────────────────────────────────

class TestMemoryCapped:
    def test_memory_capped_is_context_manager(self):
        """memory_capped returns a context manager."""
        with memory_capped(mb=4096):
            pass  # Should not raise

    def test_memory_capped_restores_previous_limit(self):
        """After exiting, the original RLIMIT_AS is restored."""
        old_soft, old_hard = resource.getrlimit(resource.RLIMIT_AS)
        with memory_capped(mb=4096):
            pass
        restored_soft, restored_hard = resource.getrlimit(resource.RLIMIT_AS)
        assert restored_soft == old_soft
        assert restored_hard == old_hard

    def test_memory_capped_sets_lower_limit(self):
        """Inside the block, the memory limit is lowered."""
        cap_mb = 4096
        expected_bytes = cap_mb * 1024 * 1024
        with memory_capped(mb=cap_mb):
            cur_soft, cur_hard = resource.getrlimit(resource.RLIMIT_AS)
            # On systems where the current hard limit is lower than our cap,
            # the limit won't be raised — so just check it's <= expected
            if cur_hard != resource.RLIM_INFINITY:
                assert cur_hard <= expected_bytes

    def test_memory_capped_zero_mb_is_noop(self):
        """mb=0 should be a no-op (early return)."""
        with memory_capped(mb=0):
            pass


# ── run_limited decorator ───────────────────────────────────────────────

class TestRunLimited:
    def test_run_limited_decorates_function(self):
        """run_limited wraps a function and it still returns the correct value."""
        @run_limited(cpu_percent=50, memory_mb=4096)
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_run_limited_preserves_function_name(self):
        """The decorator preserves the wrapped function's name via functools.wraps."""
        @run_limited(cpu_percent=50, memory_mb=4096)
        def my_special_function():
            """My docstring."""
            pass

        assert my_special_function.__name__ == "my_special_function"
        assert my_special_function.__doc__ == "My docstring."

    def test_run_limited_passes_args_and_kwargs(self):
        """The decorator forwards positional and keyword arguments."""
        @run_limited(cpu_percent=50, memory_mb=4096)
        def combine(a, b, c=0):
            return a + b + c

        assert combine(1, 2) == 3
        assert combine(1, 2, c=10) == 13

    def test_run_limited_default_params(self):
        """run_limited works with default parameters (cpu=20, memory=2048)."""
        @run_limited()
        def noop():
            return 42

        assert noop() == 42


# ── configure_pytest_defaults ───────────────────────────────────────────

class TestConfigurePytestDefaults:
    def test_configure_pytest_defaults_runs_without_error(self):
        """configure_pytest_defaults does not raise."""
        configure_pytest_defaults(max_memory_mb=4096)


# ── add_resource_args ───────────────────────────────────────────────────

class TestAddResourceArgs:
    def test_add_resource_args_adds_flags(self):
        """add_resource_args adds --max-cpu and --max-memory-mb to a parser."""
        import argparse
        parser = argparse.ArgumentParser()
        add_resource_args(parser)

        args = parser.parse_args(["--max-cpu", "50", "--max-memory-mb", "1024"])
        assert args.max_cpu == 50
        assert args.max_memory_mb == 1024

    def test_add_resource_args_has_defaults(self):
        """Default values are cpu=20, memory=2048."""
        import argparse
        parser = argparse.ArgumentParser()
        add_resource_args(parser)

        args = parser.parse_args([])
        assert args.max_cpu == 20
        assert args.max_memory_mb == 2048
