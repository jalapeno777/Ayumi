"""Tests for SRF parameter stability module."""

import numpy as np
import pytest

from srf.param_stability import (
    coefficient_of_variation,
    plateau_detection,
    neighbor_robustness,
    cross_window_rank_correlation,
    generate_heatmap,
    assess_stability,
)


class TestCoefficientOfVariation:
    def test_zero_variance(self):
        assert coefficient_of_variation([1.0, 1.0, 1.0]) == pytest.approx(0.0)

    def test_uniform_spread(self):
        cv = coefficient_of_variation([1.0, 2.0, 3.0, 4.0])
        # mean=2.5, std~1.29 → CV ~ 0.516
        assert 0.3 < cv < 0.7

    def test_negative_mean(self):
        cv = coefficient_of_variation([-1.0, -2.0, -3.0])
        # mean=-2, std~1 → CV = 0.5
        assert cv == pytest.approx(0.5, rel=0.1)

    def test_single_element(self):
        assert coefficient_of_variation([5.0]) == 0.0

    def test_zero_mean(self):
        cv = coefficient_of_variation([0.0, 0.01, -0.01])
        assert cv > 0  # should not be zero


class TestPlateauDetection:
    def test_broad_plateau(self):
        # All similar performance
        perf = np.array([0.95, 0.96, 0.97, 0.98, 0.99, 1.0])
        params = np.arange(6).reshape(-1, 1).astype(float)
        score = plateau_detection(params, perf, threshold=0.95)
        assert score > 0.8  # most are on plateau

    def test_sharp_spike(self):
        # One clear winner
        perf = np.array([0.1, 0.1, 0.1, 0.1, 0.1, 1.0])
        params = np.arange(6).reshape(-1, 1).astype(float)
        score = plateau_detection(params, perf, threshold=0.95)
        assert score < 0.3  # only 1 on plateau

    def test_empty(self):
        assert plateau_detection(np.array([]), np.array([])) == 0.0


class TestNeighborRobustness:
    def test_consistent_neighbors(self):
        # Params close together have similar performance — neighbor robustness
        # returns negative correlation of distance vs perf-diff, so close
        # neighbors with similar perf → negative input corr → positive output
        rng = np.random.default_rng(42)
        N = 50
        params = rng.uniform(0, 1, size=(N, 2))
        perf = params[:, 0] + params[:, 1]  # smooth function
        corr = neighbor_robustness(params, perf)
        # Smooth landscape: close neighbors have similar perf → corr near 0 or positive
        assert corr > -0.5  # not strongly negative

    def test_noisy_landscape(self):
        rng = np.random.default_rng(42)
        N = 50
        params = rng.uniform(0, 1, size=(N, 2))
        perf = rng.normal(0, 1, size=N)  # pure noise
        corr = neighbor_robustness(params, perf)
        assert abs(corr) < 0.5  # weak correlation

    def test_too_few_points(self):
        params = np.array([[1.0], [2.0]])
        perf = np.array([1.0, 2.0])
        assert neighbor_robustness(params, perf, k=5) == 0.0


class TestCrossWindowRankCorrelation:
    def test_consistent_windows(self):
        windows = [
            {"params": {"a": 1.0, "b": 2.0}, "performance": 1.0},
            {"params": {"a": 1.1, "b": 2.1}, "performance": 1.1},
            {"params": {"a": 0.9, "b": 1.9}, "performance": 0.9},
        ]
        corr = cross_window_rank_correlation(windows)
        assert corr > 0.5  # consistent ranking

    def test_inconsistent_windows(self):
        windows = [
            {"params": {"a": 1.0, "b": 2.0}, "performance": 1.0},
            {"params": {"a": 5.0, "b": 0.1}, "performance": 0.5},
            {"params": {"a": 0.1, "b": 5.0}, "performance": 0.2},
        ]
        corr = cross_window_rank_correlation(windows)
        assert corr < 0.8  # less consistent

    def test_single_window(self):
        windows = [{"params": {"a": 1.0}, "performance": 1.0}]
        assert cross_window_rank_correlation(windows) == 1.0


class TestGenerateHeatmap:
    def test_simple_evaluation(self):
        best = {"x": 10.0, "y": 5.0}

        def eval_fn(params):
            return -((params["x"] - 10) ** 2) - (params["y"] - 5) ** 2

        hm = generate_heatmap(eval_fn, best)
        assert hm.shape == (5, 2)  # 5 perturbations × 2 params
        # Center perturbation (0.0) should be best
        assert hm[2, 0] >= hm[0, 0]  # center >= -20% for x
        assert hm[2, 1] >= hm[0, 1]  # center >= -20% for y

    def test_failed_evaluation(self):
        best = {"x": 1.0}

        def eval_fn(params):
            if params["x"] > 1.0:
                raise ValueError("bad")
            return params["x"]

        hm = generate_heatmap(eval_fn, best)
        assert hm.shape == (5, 1)
        # Some entries should be NaN
        assert np.any(np.isnan(hm))


class TestAssessStability:
    def test_stable_strategy(self):
        window_perf = [1.0, 1.05, 0.95, 1.02, 0.98]
        rng = np.random.default_rng(42)
        params = rng.uniform(0, 1, size=(30, 3))
        perf = rng.normal(loc=1.0, scale=0.1, size=30)
        result = assess_stability(window_perf, params, perf)
        assert result.cv < 0.1
        assert result.is_stable

    def test_unstable_strategy(self):
        window_perf = [1.0, 0.2, 3.0, 0.1, 2.5]
        rng = np.random.default_rng(42)
        params = rng.uniform(0, 1, size=(30, 3))
        perf = rng.normal(loc=1.0, scale=1.0, size=30)
        result = assess_stability(window_perf, params, perf)
        assert result.cv > 0.3
        assert not result.is_stable

    def test_summary(self):
        window_perf = [1.0, 1.1, 0.9]
        params = np.array([[1.0, 2.0], [1.1, 2.1], [0.9, 1.9]])
        perf = np.array([1.0, 1.1, 0.9])
        result = assess_stability(window_perf, params, perf)
        s = result.summary()
        assert "cv" in s
        assert "is_stable" in s
        assert "plateau_score" in s
