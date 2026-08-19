"""Test suite for pair selection policy and correlation matrix dual-window.

Covers SRB-AYUMI-001 acceptance criteria:
- Over-clustered portfolio detection (6 USD-strong pairs flagged)
- Valid 4-cluster portfolio passes
- Correlation matrix dual-window computation (30d + 90d)
- Edge cases: empty portfolio, unknown pairs, multi-cluster membership
"""

from __future__ import annotations

import pytest

from risk.correlation_matrix import CorrelationMatrix
from risk.pair_selection import (
    PairSelectionPolicy,
)


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #
@pytest.fixture
def policy() -> PairSelectionPolicy:
    return PairSelectionPolicy()


@pytest.fixture
def valid_portfolio() -> list[str]:
    """A balanced portfolio with ≤2 pairs per cluster."""
    return ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "GBPJPY"]


@pytest.fixture
def over_clustered_portfolio() -> list[str]:
    """A portfolio with too many USD-strong pairs (6 from one cluster).

    Note: this is an artificial worst-case for stress-testing the policy.
    The real USD-strong cluster has 3 members (USDJPY, USDCHF, USDCAD),
    so we add extra pairs that also fall into this cluster via the
    broader USD-positive correlation structure.
    """
    # We simulate 6 USD-strong by extending the cluster definition
    custom_clusters = {
        "usd_weak_majors": {"EURUSD", "GBPUSD"},
        "usd_strong": {
            "USDJPY",
            "USDCHF",
            "USDCAD",
            "USDMXN",
            "USDSGD",
            "USDHKD",
        },
        "commodity_linked": {"AUDUSD", "XAUUSD", "USDCAD"},
        "jpy_crosses": {"GBPJPY", "EURJPY", "EURGBP"},
    }
    return custom_clusters


# ------------------------------------------------------------------ #
# PairSelectionPolicy — cluster usage
# ------------------------------------------------------------------ #
class TestClusterUsage:
    def test_valid_portfolio_cluster_usage(self, policy, valid_portfolio):
        usage = policy.get_cluster_usage(valid_portfolio)
        # Each cluster should have ≤2 pairs
        for cluster, pairs in usage.items():
            assert len(pairs) <= 2, f"{cluster} has {len(pairs)} pairs"

    def test_usd_weak_majors_detected(self, policy):
        usage = policy.get_cluster_usage(["EURUSD", "GBPUSD"])
        assert "usd_weak_majors" in usage
        assert set(usage["usd_weak_majors"]) == {"EURUSD", "GBPUSD"}

    def test_usd_strong_detected(self, policy):
        usage = policy.get_cluster_usage(["USDJPY", "USDCHF", "USDCAD"])
        assert "usd_strong" in usage
        assert len(usage["usd_strong"]) == 3

    def test_empty_portfolio(self, policy):
        usage = policy.get_cluster_usage([])
        assert usage == {}

    def test_unknown_pair_not_in_any_cluster(self, policy):
        usage = policy.get_cluster_usage(["NZDUSD"])
        assert usage == {}


# ------------------------------------------------------------------ #
# PairSelectionPolicy — validation
# ------------------------------------------------------------------ #
class TestPortfolioValidation:
    def test_valid_portfolio_passes(self, policy, valid_portfolio):
        result = policy.validate_portfolio(valid_portfolio)
        assert result.is_valid
        assert len(result.violations) == 0
        assert result.total_pairs == len(set(valid_portfolio))

    def test_over_clustered_usd_strong_flagged(self, over_clustered_portfolio):
        """Acceptance criterion: 6 USD-strong pairs flagged as over-clustered."""
        custom_clusters = over_clustered_portfolio
        policy = PairSelectionPolicy(clusters=custom_clusters)
        result = policy.validate_portfolio(
            ["USDJPY", "USDCHF", "USDCAD", "USDMXN", "USDSGD", "USDHKD"]
        )
        assert not result.is_valid
        assert len(result.violations) == 1
        assert result.violations[0].cluster_name == "usd_strong"
        assert len(result.violations[0].pairs) == 6
        assert result.violations[0].excess == 4

    def test_valid_4_cluster_portfolio_passes(self, policy):
        """Acceptance criterion: valid 4-cluster portfolio (2 per cluster) passes."""
        # Pick exactly 2 from each cluster
        portfolio = [
            "EURUSD",
            "GBPUSD",  # usd_weak_majors
            "USDJPY",
            "USDCHF",  # usd_strong
            "AUDUSD",
            "XAUUSD",  # commodity_linked
            "GBPJPY",
            "EURJPY",  # jpy_crosses
        ]
        result = policy.validate_portfolio(portfolio)
        assert result.is_valid
        assert result.total_pairs == 8
        assert len(result.cluster_usage) == 4

    def test_usd_strong_at_limit_passes(self, policy):
        """3 USD-strong pairs = violation (max 2)."""
        result = policy.validate_portfolio(["USDJPY", "USDCHF", "USDCAD"])
        assert not result.is_valid
        assert any(v.cluster_name == "usd_strong" for v in result.violations)

    def test_usd_strong_at_max_passes(self, policy):
        """Exactly 2 USD-strong pairs = OK."""
        result = policy.validate_portfolio(["USDJPY", "USDCHF"])
        assert result.is_valid

    def test_summary_valid(self, policy, valid_portfolio):
        result = policy.validate_portfolio(valid_portfolio)
        assert "valid" in result.summary.lower()

    def test_summary_invalid(self, policy):
        result = policy.validate_portfolio(["USDJPY", "USDCHF", "USDCAD"])
        assert "invalid" in result.summary.lower()
        assert "usd_strong" in result.summary.lower()


# ------------------------------------------------------------------ #
# PairSelectionPolicy — multi-cluster membership
# ------------------------------------------------------------------ #
class TestMultiClusterMembership:
    def test_usdcad_in_two_clusters(self, policy):
        clusters = policy.find_cluster("USDCAD")
        assert "usd_strong" in clusters
        assert "commodity_linked" in clusters

    def test_find_cluster_case_insensitive(self, policy):
        clusters = policy.find_cluster("eurusd")
        assert "usd_weak_majors" in clusters

    def test_unknown_pair_no_cluster(self, policy):
        clusters = policy.find_cluster("NZDUSD")
        assert clusters == []


# ------------------------------------------------------------------ #
# PairSelectionPolicy — unassigned pairs
# ------------------------------------------------------------------ #
class TestUnassignedPairs:
    def test_unassigned_detected(self, policy):
        unassigned = policy.get_unassigned_pairs(["EURUSD", "NZDUSD", "USDMXN"])
        assert "NZDUSD" in unassigned
        assert "USDMXN" in unassigned
        assert "EURUSD" not in unassigned

    def test_all_assigned(self, policy):
        unassigned = policy.get_unassigned_pairs(["EURUSD", "GBPUSD"])
        assert unassigned == []


# ------------------------------------------------------------------ #
# PairSelectionPolicy — flag_over_clustered
# ------------------------------------------------------------------ #
class TestFlagOverClustered:
    def test_flag_returns_cluster_names(self, policy):
        flagged = policy.flag_over_clustered(["USDJPY", "USDCHF", "USDCAD"])
        assert "usd_strong" in flagged

    def test_flag_empty_when_valid(self, policy, valid_portfolio):
        flagged = policy.flag_over_clustered(valid_portfolio)
        assert flagged == []


# ------------------------------------------------------------------ #
# CorrelationMatrix — dual-window computation
# ------------------------------------------------------------------ #
class TestCorrelationMatrixDualWindow:
    """Acceptance criterion: correlation_matrix.py computes 30d + 90d rolling matrix."""

    def test_compute_multi_window_returns_both_windows(self):
        cm = CorrelationMatrix(window=30)
        # Generate synthetic return data (100 days)
        import random

        random.seed(42)
        for sym in ["EURUSD", "GBPUSD", "USDJPY"]:
            returns = [random.gauss(0, 0.001) for _ in range(100)]
            cm.add_returns(sym, returns)

        results = cm.compute_multi_window([30, 90])
        assert 30 in results
        assert 90 in results
        # Each window should have a full matrix
        for w in [30, 90]:
            matrix = results[w]
            assert "EURUSD" in matrix
            assert "GBPUSD" in matrix["EURUSD"]
            assert -1.0 <= matrix["EURUSD"]["GBPUSD"] <= 1.0
            assert matrix["EURUSD"]["EURUSD"] == 1.0

    def test_compute_multi_window_default_windows(self):
        cm = CorrelationMatrix()
        import random

        random.seed(42)
        for sym in ["EURUSD", "GBPUSD"]:
            returns = [random.gauss(0, 0.001) for _ in range(100)]
            cm.add_returns(sym, returns)

        results = cm.compute_multi_window()
        assert set(results.keys()) == {30, 90}

    def test_compute_multi_window_restores_window(self):
        cm = CorrelationMatrix(window=30)
        import random

        random.seed(42)
        for sym in ["EURUSD", "GBPUSD"]:
            returns = [random.gauss(0, 0.001) for _ in range(100)]
            cm.add_returns(sym, returns)

        cm.compute_multi_window([30, 90])
        assert cm.window == 30  # restored

    def test_correlation_values_differ_between_windows(self):
        """30d and 90d windows should produce different correlation values
        when the return series has regime changes."""
        cm = CorrelationMatrix(window=30)
        # First 50 days: EURUSD and GBPUSD perfectly correlated
        # Next 50 days: anti-correlated
        returns_eur = [0.001] * 50 + [-0.001] * 50
        returns_gbp = [0.001] * 50 + [0.001] * 50  # diverges in second half

        cm.add_returns("EURUSD", returns_eur)
        cm.add_returns("GBPUSD", returns_gbp)

        results = cm.compute_multi_window([30, 90])
        corr_30 = results[30]["EURUSD"]["GBPUSD"]
        corr_90 = results[90]["EURUSD"]["GBPUSD"]
        # The 30d window (recent anti-correlation) should differ from 90d
        assert corr_30 != corr_90

    def test_backward_compat_compute_still_works(self):
        """Existing compute() method should still work unchanged."""
        cm = CorrelationMatrix(window=30)
        import random

        random.seed(42)
        for sym in ["EURUSD", "GBPUSD"]:
            returns = [random.gauss(0, 0.001) for _ in range(50)]
            cm.add_returns(sym, returns)

        matrix = cm.compute()
        assert "EURUSD" in matrix
        assert "GBPUSD" in matrix["EURUSD"]
        assert matrix["EURUSD"]["EURUSD"] == 1.0


# ------------------------------------------------------------------ #
# Integration: CorrelationMatrix + PairSelectionPolicy
# ------------------------------------------------------------------ #
class TestIntegration:
    """Verify that correlation matrix data can inform pair selection decisions."""

    def test_highly_correlated_pairs_in_same_cluster(self, policy):
        """Pairs within the same cluster should show high correlation."""
        cm = CorrelationMatrix(window=30)
        # Simulate highly correlated EURUSD and GBPUSD
        import random

        random.seed(42)
        base = [random.gauss(0, 0.001) for _ in range(60)]
        cm.add_returns("EURUSD", base)
        cm.add_returns("GBPUSD", [r + random.gauss(0, 0.0001) for r in base])

        matrix = cm.compute()
        corr = matrix["EURUSD"]["GBPUSD"]

        # They should be highly correlated
        assert corr > 0.8
        # And they are in the same cluster
        eur_clusters = policy.find_cluster("EURUSD")
        gbp_clusters = policy.find_cluster("GBPUSD")
        assert set(eur_clusters) & set(gbp_clusters)  # share at least one cluster
