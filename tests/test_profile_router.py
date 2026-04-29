"""Tests for Profile Router."""

import pytest

from risk.profile_router import ProfileRouter, Profile


class TestProfileRouter:
    def setup_method(self):
        self.router = ProfileRouter()

    # --- Threshold Boundaries ---

    def test_below_swarm_rejected(self):
        assert self.router.route(0.39) is None

    def test_at_swarm_minimum(self):
        assert self.router.route(0.40) == Profile.SWARM

    def test_below_sniper(self):
        assert self.router.route(0.69) == Profile.SWARM

    def test_at_sniper_threshold(self):
        assert self.router.route(0.70) == Profile.SNIPER

    def test_high_confidence_sniper(self):
        assert self.router.route(0.95) == Profile.SNIPER

    # --- Invalid Confidence ---

    def test_negative_confidence(self):
        with pytest.raises(ValueError):
            self.router.route(-0.1)

    def test_above_one_confidence(self):
        with pytest.raises(ValueError):
            self.router.route(1.5)

    # --- Max Concurrent Positions ---

    def test_sniper_capacity(self):
        for i in range(3):
            self.router.register_open(f"sniper-{i}", Profile.SNIPER)
        # 4th sniper should fall back to swarm
        assert self.router.route(0.80) == Profile.SWARM

    def test_sniper_and_swarm_full(self):
        for i in range(3):
            self.router.register_open(f"sniper-{i}", Profile.SNIPER)
        for i in range(5):
            self.router.register_open(f"swarm-{i}", Profile.SWARM)
        # Should reject
        assert self.router.route(0.80) is None
        assert self.router.route(0.50) is None

    def test_swarm_capacity(self):
        for i in range(5):
            self.router.register_open(f"swarm-{i}", Profile.SWARM)
        assert self.router.route(0.50) is None

    # --- Position Lifecycle ---

    def test_open_close_frees_slot(self):
        self.router.register_open("p1", Profile.SNIPER)
        self.router.register_open("p2", Profile.SNIPER)
        self.router.register_open("p3", Profile.SNIPER)
        # Full
        assert self.router.route(0.80) == Profile.SWARM
        # Close one
        self.router.close("p1")
        assert self.router.route(0.80) == Profile.SNIPER

    def test_close_unknown_raises(self):
        with pytest.raises(ValueError):
            self.router.close("nonexistent")

    def test_double_register_raises(self):
        self.router.register_open("p1", Profile.SNIPER)
        with pytest.raises(ValueError):
            self.router.register_open("p1", Profile.SNIPER)

    # --- Profile Persistence ---

    def test_multiple_signals_same_profile(self):
        """Multiple swarm signals should all route to swarm."""
        results = [self.router.route(0.55) for _ in range(3)]
        assert all(r == Profile.SWARM for r in results)

    def test_sniper_fallback_to_swarm_when_swarm_full(self):
        """When both full, sniper signal should be rejected."""
        for i in range(3):
            self.router.register_open(f"s-{i}", Profile.SNIPER)
        for i in range(5):
            self.router.register_open(f"w-{i}", Profile.SWARM)
        assert self.router.route(0.90) is None
