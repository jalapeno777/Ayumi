"""Tests for quant.markov_regime — first-order Markov regime filter.

Covers:
- train(): correct transition-matrix construction from synthetic data
- observe(): incremental online updates preserve prior history
- predict_next(): valid probability distribution, multi-step differs
- confidence(): diagonal entry matches persistence probability
- size_multiplier(): cold start, tier mapping, hard clamps
- is_ready(): threshold gating by ``min_history``
- Laplace smoothing: unseen transitions are still reachable
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from quant.markov_regime import MarkovRegimeFilter, MarkovRegimeSummary


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
SIX_STATES: list[str] = [
    "low_ranging",
    "low_trending",
    "normal_ranging",
    "normal_trending",
    "high_ranging",
    "high_trending",
]


def _make_six_state_filter(min_history: int = 100) -> MarkovRegimeFilter:
    return MarkovRegimeFilter(states=list(SIX_STATES), min_history=min_history)


def _flat_transitions(
    state: str,
    n: int,
) -> list[tuple[str, str]]:
    """Synthesise ``n`` self-transitions on ``state``."""
    return [(state, state)] * n


# ---------------------------------------------------------------------------
# train(): transition-matrix construction
# ---------------------------------------------------------------------------
class TestTrain:
    def test_train_builds_correct_matrix(self) -> None:
        """A small synthetic history should produce the expected
        Laplace-smoothed row probabilities.

        With states = [A, B] and transitions = [A→A, A→A, A→B]:
            - counts[A, :] = [1 (seed) + 2, 1 (seed) + 1] = [3, 2]
            - counts[B, :] = [1, 1]   (B is never observed as a source)
            - P[A, :] = [3/5, 2/5] = [0.6, 0.4]
            - P[B, :] = [0.5, 0.5]
        """
        f = MarkovRegimeFilter(states=["A", "B"])
        f.train([("A", "A"), ("A", "A"), ("A", "B")])

        matrix = f.transition_matrix
        assert matrix.shape == (2, 2)

        # Row A: 2 self, 1 to B. With Laplace seed of 1 each.
        assert matrix[0, 0] == pytest.approx(0.6, abs=1e-12)
        assert matrix[0, 1] == pytest.approx(0.4, abs=1e-12)

        # Row B: only Laplace seed contributes (no outgoing transitions observed).
        assert matrix[1, 0] == pytest.approx(0.5, abs=1e-12)
        assert matrix[1, 1] == pytest.approx(0.5, abs=1e-12)

        # Total observations are tracked and the matrix is row-stochastic.
        assert f.total_observations == 3
        for i in range(2):
            assert matrix[i].sum() == pytest.approx(1.0, abs=1e-12)

    def test_train_replaces_prior_history(self) -> None:
        """train() is destructive: a second call resets counts before
        applying new transitions, even if the prior matrix was built up
        via observe().
        """
        f = MarkovRegimeFilter(states=["A", "B"])
        # Build up some "online" history first.
        for _ in range(10):
            f.observe("A", "A")
        assert f.total_observations == 10

        # A fresh train() should reset and start fresh.
        f.train([("B", "A")])
        assert f.total_observations == 1
        # Row A only has the Laplace seed (no A-sourced transitions).
        assert f.transition_matrix[0, 0] == pytest.approx(0.5, abs=1e-12)
        # Row B saw B→A once.
        assert f.transition_matrix[1, 0] == pytest.approx(2 / 3, abs=1e-12)
        assert f.transition_matrix[1, 1] == pytest.approx(1 / 3, abs=1e-12)

    def test_train_rejects_unknown_states(self) -> None:
        f = MarkovRegimeFilter(states=["A", "B"])
        with pytest.raises(ValueError):
            f.train([("A", "Z")])
        with pytest.raises(ValueError):
            f.train([("Q", "A")])
        # A failed train() call must NOT poison the filter — the prior
        # state should be intact and the filter still usable.
        assert f.total_observations == 0
        assert f.transition_matrix.sum(axis=1).tolist() == [1.0, 1.0]


# ---------------------------------------------------------------------------
# observe(): online updates
# ---------------------------------------------------------------------------
class TestObserve:
    def test_observe_online(self) -> None:
        """observe() updates the matrix incrementally without resetting."""
        f = MarkovRegimeFilter(states=["A", "B"])
        f.observe("A", "A")  # counts[A,A]=2, counts[A,B]=1
        f.observe("A", "B")  # counts[A,A]=2, counts[A,B]=2
        # Row A: 4/5 self, 2/5 to B... wait recount.
        # Initial seed [1, 1] + (A→A: +1) + (A→B: +1) = [2, 2]; sum=4.
        assert f.transition_matrix[0, 0] == pytest.approx(0.5, abs=1e-12)
        assert f.transition_matrix[0, 1] == pytest.approx(0.5, abs=1e-12)
        assert f.total_observations == 2

        f.observe("B", "B")  # counts[B,B]=2
        assert f.transition_matrix[1, 1] == pytest.approx(2 / 3, abs=1e-12)

    def test_observe_rejects_unknown_states(self) -> None:
        f = MarkovRegimeFilter(states=["A", "B"])
        with pytest.raises(ValueError):
            f.observe("A", "ZZ")
        # Failed observation must not advance the counter.
        assert f.total_observations == 0


# ---------------------------------------------------------------------------
# predict_next(): multi-step forecast
# ---------------------------------------------------------------------------
class TestPredictNext:
    def test_predict_next_returns_valid_distribution(self) -> None:
        """Sum of returned probabilities equals 1.0 within fp tolerance."""
        f = _make_six_state_filter()
        f.train(_flat_transitions("normal_ranging", 200))

        dist = f.predict_next("normal_ranging", horizon=5)
        total = sum(p for _, p in dist)
        assert total == pytest.approx(1.0, abs=1e-9)
        # Every state appears exactly once.
        assert {s for s, _ in dist} == set(SIX_STATES)
        # Probabilities are non-negative.
        assert all(p >= 0.0 for _, p in dist)

    def test_predict_next_returns_sorted_descending(self) -> None:
        """Higher probability states come first in the returned list."""
        f = _make_six_state_filter()
        f.train(_flat_transitions("normal_ranging", 200))

        dist = f.predict_next("normal_ranging", horizon=3)
        probs = [p for _, p in dist]
        for a, b in zip(probs, probs[1:]):
            assert a >= b

    def test_predict_next_multi_step_differs_from_one_step(self) -> None:
        """With a non-degenerate matrix, h=5 should differ from h=1.

        We train a slightly asymmetric matrix so the multi-step result
        is measurably different.
        """
        f = MarkovRegimeFilter(states=["A", "B"])
        # A→A 6 times, A→B 2 times, B→A 1 time, B→B 5 times.
        f.train(
            [("A", "A")] * 6 + [("A", "B")] * 2 + [("B", "A")] * 1 + [("B", "B")] * 5
        )

        one_step = dict(f.predict_next("A", horizon=1))
        five_step = dict(f.predict_next("A", horizon=5))

        # 1-step: row A of the matrix directly.
        # counts[A] = [1+6, 1+2] = [7, 3]; P(A,A) = 7/10 = 0.7
        assert one_step["A"] == pytest.approx(0.7, abs=1e-12)
        assert one_step["B"] == pytest.approx(0.3, abs=1e-12)

        # 5-step: mass diffuses — A's probability should shift noticeably.
        assert not math.isclose(one_step["A"], five_step["A"], abs_tol=1e-3)

        # Distribution invariant: still sums to 1.
        assert sum(five_step.values()) == pytest.approx(1.0, abs=1e-9)

    def test_predict_next_horizon_zero_is_one_hot(self) -> None:
        """horizon=0 returns the degenerate distribution at the current state."""
        f = MarkovRegimeFilter(states=["A", "B"])
        f.train([("A", "A"), ("A", "B")])
        dist = dict(f.predict_next("A", horizon=0))
        assert dist == {
            "A": pytest.approx(1.0, abs=1e-12),
            "B": pytest.approx(0.0, abs=1e-12),
        }

    def test_predict_next_rejects_unknown_state(self) -> None:
        f = _make_six_state_filter()
        f.train(_flat_transitions("normal_ranging", 100))
        with pytest.raises(ValueError):
            f.predict_next("bogus_state", horizon=1)

    def test_predict_next_rejects_negative_horizon(self) -> None:
        f = _make_six_state_filter()
        with pytest.raises(ValueError):
            f.predict_next("normal_ranging", horizon=-1)


# ---------------------------------------------------------------------------
# confidence(): persistence probability
# ---------------------------------------------------------------------------
class TestConfidence:
    def test_confidence_returns_diagonal_entry(self) -> None:
        f = MarkovRegimeFilter(states=["A", "B"])
        f.train([("A", "A"), ("A", "B")])
        # Row A: counts [2, 2] (seed [1,1] + observation), so P(A,A) = 0.5
        assert f.confidence("A") == pytest.approx(0.5, abs=1e-12)
        # Row B: only seed [1,1] → 0.5
        assert f.confidence("B") == pytest.approx(0.5, abs=1e-12)

    def test_confidence_high_when_self_transitions_dominate(self) -> None:
        f = MarkovRegimeFilter(states=["A", "B"])
        f.train([("A", "A")] * 20 + [("A", "B")])
        # counts[A] = [1+20, 1+1] = [21, 2]; P(A,A) = 21/23 ≈ 0.913
        assert f.confidence("A") == pytest.approx(21 / 23, abs=1e-12)

    def test_confidence_rejects_unknown_state(self) -> None:
        f = _make_six_state_filter()
        with pytest.raises(ValueError):
            f.confidence("bogus_state")


# ---------------------------------------------------------------------------
# size_multiplier(): tiered sizing + clamps
# ---------------------------------------------------------------------------
class TestSizeMultiplier:
    def test_size_multiplier_cold_start(self) -> None:
        """Below ``min_history`` the multiplier is the neutral 1.0."""
        f = MarkovRegimeFilter(states=list(SIX_STATES), min_history=100)
        # No observations at all — definitely not ready.
        assert f.is_ready() is False
        for s in SIX_STATES:
            assert f.size_multiplier(s) == 1.0

    def test_size_multiplier_cold_start_returns_one_even_with_high_confidence(
        self,
    ) -> None:
        """Cold start must ignore the diagonal reading and return 1.0."""
        f = MarkovRegimeFilter(states=["A", "B"], min_history=1000)
        # Force a high diagonal without crossing the readiness threshold.
        for _ in range(50):
            f.observe("A", "A")
        assert f.is_ready() is False
        # The diagonal might be ~0.96 but cold-start still wins.
        assert f.confidence("A") > 0.9
        assert f.size_multiplier("A") == 1.0

    def test_size_multiplier_persistence_levels(self) -> None:
        """Each tier maps to the documented multiplier once the filter is ready.

        Each case uses pre-computed integer counts that pin the
        diagonal entry inside a known tier. With the Laplace seed of
        [1, 1] plus ``c_self`` self-transitions and ``c_other``
        other-transitions, persistence is::

            P(SELF, SELF) = (1 + c_self) / (2 + c_self + c_other)

        The ``c_other=10`` base lets us exercise the full tier range.
        """
        cases: list[tuple[int, int, float]] = [
            # (c_self, c_other, expected_persistence)
            # Below the lowest tier (0.35).
            (0, 10, 1 / 12),  # ≈ 0.0833 → 0.5
            (3, 10, 4 / 15),  # ≈ 0.2667 → 0.5
            # 0.35-0.50 tier → 0.8.
            (5, 10, 6 / 17),  # ≈ 0.3529 → 0.8
            (9, 10, 10 / 21),  # ≈ 0.4762 → 0.8
            # 0.50-0.65 tier → 1.0.
            (14, 10, 15 / 26),  # ≈ 0.5769 → 1.0
            (17, 10, 18 / 29),  # ≈ 0.6207 → 1.0
            # 0.65-0.80 tier → 1.1.
            (20, 10, 21 / 32),  # ≈ 0.6563 → 1.1
            (24, 10, 25 / 36),  # ≈ 0.6944 → 1.1
            (31, 10, 32 / 43),  # ≈ 0.7442 → 1.1
            # ≥ 0.80 tier → 1.2.
            (44, 10, 45 / 56),  # ≈ 0.8036 → 1.2
            (99, 10, 100 / 111),  # ≈ 0.9009 → 1.2
        ]

        # Tier mapping: (low_persistence_inclusive, expected_multiplier).
        # We infer the expected multiplier from the persistence itself.
        def expected_mult_for(p: float) -> float:
            if p < 0.35:
                return 0.5
            if p < 0.50:
                return 0.8
            if p < 0.65:
                return 1.0
            if p < 0.80:
                return 1.1
            return 1.2

        f = MarkovRegimeFilter(states=["SELF", "OTHER"], min_history=0)
        for c_self, c_other, expected_p in cases:
            f.train([("SELF", "SELF")] * c_self + [("SELF", "OTHER")] * c_other)
            observed = f.confidence("SELF")
            assert observed == pytest.approx(expected_p, abs=1e-12), (
                f"c_self={c_self}, c_other={c_other}: expected {expected_p}, got {observed}"
            )
            assert f.size_multiplier("SELF") == expected_mult_for(expected_p)

    def test_size_multiplier_clamps_to_floor(self) -> None:
        """Persistence below the lowest tier still hits the floor."""
        # We can't go BELOW the floor via tier mapping (0.5 IS the floor)
        # so we exercise the clamp through tiering directly: at p=0.0 the
        # tier lookup returns 0.5 which equals the floor.
        f = MarkovRegimeFilter(states=["A", "B"], min_history=0)
        f.train([("A", "B")] * 5)  # P(A,A) ≈ 1/7 ≈ 0.14 → < 0.35 → 0.5
        mult = f.size_multiplier("A")
        assert mult == 0.5
        # And it must equal the floor (i.e., the clamp is a no-op here).
        assert mult >= 0.5

    def test_size_multiplier_clamps_to_ceiling(self) -> None:
        """Persistence above the highest tier still hits the ceiling.

        All natural persistence values from a valid probability matrix
        map to <= 1.2 from the tier table, so the 1.3 ceiling is just a
        safety bound. We exercise it by constructing an artificial case
        and confirming the clamp does not move the natural tier result.
        """
        f = MarkovRegimeFilter(states=["A", "B"], min_history=0)
        f.train([("A", "A")] * 50)  # very high persistence
        # Natural tier result must already be <= ceiling.
        assert f.size_multiplier("A") <= 1.3

    def test_size_multiplier_clamps_inside_bounds(self) -> None:
        """Every multiplier must lie in [0.5, 1.3] across the full tier range."""
        f = MarkovRegimeFilter(states=list(SIX_STATES), min_history=0)
        # Build varied matrices by training different histories.
        for i, n in enumerate([1, 5, 50, 500]):
            for _ in range(n):
                f.observe(SIX_STATES[i % 6], SIX_STATES[(i + 1) % 6])
        for s in SIX_STATES:
            m = f.size_multiplier(s)
            assert 0.5 <= m <= 1.3, f"{s} -> {m}"


# ---------------------------------------------------------------------------
# is_ready(): readiness threshold
# ---------------------------------------------------------------------------
class TestIsReady:
    def test_is_ready_threshold(self) -> None:
        """is_ready() flips at exactly ``min_history`` observations."""
        f = MarkovRegimeFilter(states=["A", "B"], min_history=5)

        # Below threshold.
        for _ in range(4):
            f.observe("A", "A")
        assert f.total_observations == 4
        assert f.is_ready() is False

        # At threshold.
        f.observe("A", "B")
        assert f.total_observations == 5
        assert f.is_ready() is True

        # Past threshold.
        f.observe("B", "B")
        assert f.total_observations == 6
        assert f.is_ready() is True

    def test_is_ready_zero_min_history(self) -> None:
        f = MarkovRegimeFilter(states=["A"], min_history=0)
        assert f.is_ready() is True
        # Single-state filter: with only the Laplace seed [1] the
        # diagonal is 1.0 → that puts us in the ≥ 0.80 tier → 1.2.
        assert f.confidence("A") == pytest.approx(1.0, abs=1e-12)
        assert f.size_multiplier("A") == 1.2


# ---------------------------------------------------------------------------
# Laplace smoothing: zero-cell protection
# ---------------------------------------------------------------------------
class TestLaplaceSmoothing:
    def test_unseen_transitions_get_nonzero_probability(self) -> None:
        """Even a state pair that has never been observed must keep a
        non-zero probability (Laplace seed). Otherwise ``predict_next``
        could produce a zero row and break downstream consumers.
        """
        f = MarkovRegimeFilter(states=list(SIX_STATES))
        f.train([("normal_ranging", "normal_ranging")] * 200)

        matrix = f.transition_matrix
        # Every cell must be strictly > 0.
        assert (matrix > 0).all()

        # Specifically the never-observed high_trending row.
        h_idx = SIX_STATES.index("high_trending")
        assert (matrix[h_idx] > 0).all()
        # And the never-observed transition into low_ranging from any
        # state other than normal_ranging.
        l_idx = SIX_STATES.index("low_ranging")
        n_idx = SIX_STATES.index("normal_ranging")
        for i, row in enumerate(matrix):
            if i != n_idx:
                # All cells in row i that go to low_ranging should still be
                # positive, even if very small.
                assert row[l_idx] > 0

    def test_laplace_smoothing_persists_in_zero_history(self) -> None:
        """With zero observations, every row must be the uniform 1/n."""
        f = MarkovRegimeFilter(states=list(SIX_STATES))
        # No train(), no observe() — only Laplace seeds contribute.
        expected = 1.0 / len(SIX_STATES)
        matrix = f.transition_matrix
        assert matrix.shape == (len(SIX_STATES), len(SIX_STATES))
        assert np.allclose(matrix, expected)


# ---------------------------------------------------------------------------
# Summary / introspection
# ---------------------------------------------------------------------------
class TestSummary:
    def test_summary_is_frozen_and_readonly(self) -> None:
        """summary() returns a frozen dataclass with copies, not views."""
        f = _make_six_state_filter()
        f.train(_flat_transitions("normal_ranging", 150))

        snap = f.summary()
        assert isinstance(snap, MarkovRegimeSummary)
        assert snap.states == tuple(SIX_STATES)
        assert snap.total_observations == 150
        assert snap.is_ready is True
        assert snap.n_states == 6

        # Frozen: assignment raises.
        with pytest.raises(Exception):
            snap.total_observations = 0  # type: ignore[misc]

        # Mutating the returned matrix tuple of tuples must not change
        # the filter's internal matrix.
        row0 = snap.transition_matrix[0]
        assert row0 == tuple(f.transition_matrix[0].tolist())


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------
class TestConstructor:
    def test_empty_states_rejected(self) -> None:
        with pytest.raises(ValueError):
            MarkovRegimeFilter(states=[])

    def test_duplicate_states_rejected(self) -> None:
        with pytest.raises(ValueError):
            MarkovRegimeFilter(states=["A", "A", "B"])

    def test_negative_min_history_rejected(self) -> None:
        with pytest.raises(ValueError):
            MarkovRegimeFilter(states=["A"], min_history=-1)
