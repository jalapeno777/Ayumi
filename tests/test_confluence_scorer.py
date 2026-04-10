"""Tests for confluence_scorer.py"""

import pytest
from signal_engine.confluence_scorer import ConfluenceScorer, BoosterResult, WEIGHT_SESSION_PHASE


@pytest.fixture
def scorer():
    return ConfluenceScorer()


def _base_candidate(**overrides):
    c = {
        "direction": "long",
        "level_proximity_pct": 0.002,
        "ema_distance_pct": 0.0005,
        "in_boardroom": True,
        "boardroom_bars": 25,
        "volume_ratio": 1.8,
        "pattern_type": "M",
    }
    c.update(overrides)
    return c


def _base_session(**overrides):
    s = {"phase_score": 0.7, "kill_zone_active": True}
    s.update(overrides)
    return s


def _base_htf(**overrides):
    h = {"alignment_score": 0.8}
    h.update(overrides)
    return h


def test_score_returns_tuple(scorer):
    result = scorer.score(_base_candidate())
    assert isinstance(result, tuple)
    assert isinstance(result[0], float)
    assert isinstance(result[1], list)


def test_score_range(scorer):
    """Total score should be between 0 and 1."""
    score, _ = scorer.score(_base_candidate(), _base_htf(), _base_session())
    assert 0.0 <= score <= 1.0


def test_kill_zone_bonus(scorer):
    """Kill zone active should boost session score."""
    _, no_kz = scorer.score(_base_candidate(), _base_htf(), _base_session(kill_zone_active=False))
    _, with_kz = scorer.score(_base_candidate(), _base_htf(), _base_session(kill_zone_active=True))

    kz_no = next(b for b in no_kz if b.name == "session_phase")
    kz_yes = next(b for b in with_kz if b.name == "session_phase")
    assert kz_yes.score > kz_no.score


def test_level_proximity_tiers(scorer):
    """Closer to level = higher score."""
    from signal_engine.thresholds import PERIOD_EXTREME_T1, PERIOD_EXTREME_T3

    _, far = scorer.score(_base_candidate(level_proximity_pct=PERIOD_EXTREME_T3 + 0.01))
    _, near = scorer.score(_base_candidate(level_proximity_pct=PERIOD_EXTREME_T1))

    far_b = next(b for b in far if b.name == "level_proximity")
    near_b = next(b for b in near if b.name == "level_proximity")
    assert near_b.score > far_b.score


def test_htf_alignment_long(scorer):
    """Long signal with positive HTF alignment should score high."""
    _, res = scorer.score(_base_candidate(), _base_htf(alignment_score=0.9))
    b = next(b for b in res if b.name == "htf_alignment")
    assert b.score == 0.9


def test_htf_alignment_short(scorer):
    """Short signal with negative HTF alignment should score high."""
    _, res = scorer.score(
        _base_candidate(direction="short"),
        _base_htf(alignment_score=-0.8),
    )
    b = next(b for b in res if b.name == "htf_alignment")
    assert b.score == 0.8


def test_volume_booster_high(scorer):
    _, res = scorer.score(_base_candidate(volume_ratio=2.0))
    b = next(b for b in res if b.name == "volume")
    assert b.score == 1.0


def test_volume_booster_low(scorer):
    _, res = scorer.score(_base_candidate(volume_ratio=0.5))
    b = next(b for b in res if b.name == "volume")
    assert b.score == 0.0


def test_boardroom_qualified(scorer):
    _, res = scorer.score(_base_candidate(in_boardroom=True, boardroom_bars=22))
    b = next(b for b in res if b.name == "boardroom")
    assert b.score == 1.0


def test_boardroom_too_few_bars(scorer):
    _, res = scorer.score(_base_candidate(in_boardroom=True, boardroom_bars=10))
    b = next(b for b in res if b.name == "boardroom")
    assert b.score == 0.5


def test_all_booster_names_present(scorer):
    _, boosters = scorer.score(_base_candidate(), _base_htf(), _base_session())
    names = {b.name for b in boosters}
    expected = {"session_phase", "level_proximity", "htf_alignment",
                "ema_proximity", "boardroom", "volume", "pattern_type"}
    assert names == expected
