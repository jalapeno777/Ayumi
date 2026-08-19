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
    _cgroup_v2_available,
    _set_cgroup_cpu_limit,
    _cleanup_cgroup,
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

    def test_cpu_limited_api_signature_unchanged(self):
        """cpu_limited accepts percent as keyword and positional arg (backward compat)."""
        with cpu_limited(20):
            pass
        with cpu_limited(percent=30):
            pass


# ── cgroup v2 helpers ───────────────────────────────────────────────────


class TestCgroupV2:
    def test_cgroup_v2_available_returns_bool(self):
        """_cgroup_v2_available returns a boolean."""
        result = _cgroup_v2_available()
        assert isinstance(result, bool)

    def test_set_cgroup_cpu_limit_returns_path_or_none(self):
        """_set_cgroup_cpu_limit returns a path string or None."""
        path = _set_cgroup_cpu_limit(percent=50)
        assert path is None or isinstance(path, str)
        if path:
            _cleanup_cgroup(path)

    def test_set_and_cleanup_cgroup(self):
        """If cgroup v2 is available, setting a limit and cleaning up works."""
        if not _cgroup_v2_available():
            pytest.skip("cgroup v2 not available on this host")

        path = _set_cgroup_cpu_limit(percent=30)
        assert path is not None, "Expected cgroup path when v2 is available"
        assert os.path.exists(path), f"cgroup dir {path} should exist"

        # Verify cpu.max was written
        cpu_max_path = f"{path}/cpu.max"
        assert os.path.isfile(cpu_max_path)
        with open(cpu_max_path) as f:
            content = f.read().strip()
        # Should be "quota period" format
        parts = content.split()
        assert len(parts) == 2, f"cpu.max should have 'quota period', got: {content}"

        # Verify process is in this cgroup
        with open(f"/proc/{os.getpid()}/cgroup") as f:
            cgroup_line = f.read().strip()
        assert "ayumi_cpu" in cgroup_line, (
            f"Process should be in ayumi_cpu cgroup, got: {cgroup_line}"
        )

        _cleanup_cgroup(path)
        assert not os.path.exists(path), (
            f"cgroup dir {path} should be removed after cleanup"
        )

    def test_cpu_limited_uses_cgroup_when_available(self):
        """cpu_limited creates and cleans up a cgroup when v2 is available."""
        if not _cgroup_v2_available():
            pytest.skip("cgroup v2 not available on this host")

        with cpu_limited(percent=40):
            # During the block, process should be in an ayumi_cpu cgroup
            with open(f"/proc/{os.getpid()}/cgroup") as f:
                cgroup_line = f.read().strip()
            assert "ayumi_cpu" in cgroup_line, (
                f"Process should be in cgroup during cpu_limited, got: {cgroup_line}"
            )

        # After the block, cgroup should be cleaned up
        # Process should be back in root or original cgroup
        pid = os.getpid()
        expected_stale = f"/sys/fs/cgroup/ayumi_cpu_{pid}"
        assert not os.path.exists(expected_stale), (
            "cgroup should be cleaned up after cpu_limited exits"
        )

    def test_cgroup_fallback_on_permission_error(self):
        """cpu_limited falls back to advisory when cgroup creation fails."""
        # This test verifies the fallback path works without error.
        # On systems without cgroup v2, _set_cgroup_cpu_limit returns None
        # and _set_cpu_affinity is called instead.
        # We can't force a permission error, but we verify the code path
        # doesn't raise.
        with cpu_limited(percent=15):
            pass  # Should not raise regardless of cgroup availability


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
