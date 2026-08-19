"""Tests for confluence_scorer.py — all 14 spec §7.1 boosters + pattern_type bonus."""

import pytest
from signal_engine.confluence_scorer import (
    BoosterResult,
    ConfluenceScorer,
    WEIGHT_MTF_ALIGNMENT,
    WEIGHT_MULTI_SESSION,
    WEIGHT_SVC_PRESENT,
    WEIGHT_HITS_TO_LEVEL,
    WEIGHT_HITS_WITH_VOLUME,
    WEIGHT_NEAR_PERIOD_EXTREME,
    WEIGHT_HTF_NOT_CONSOLIDATING,
    WEIGHT_KILL_ZONE,
    WEIGHT_SESSION_OVERLAP,
    WEIGHT_SESSION_PHASE,
    WEIGHT_DAY_OF_WEEK,
    WEIGHT_ASIA_CONTROL,
    WEIGHT_EMA_BOUNCE,
    WEIGHT_DXY_CORRELATION,
    WEIGHT_PATTERN_TYPE,
)


@pytest.fixture
def scorer():
    return ConfluenceScorer()


def _base_candidate(**overrides):
    """Candidate with all fields populated for maximum confluence."""
    c = {
        "direction": "long",
        "level_proximity_pct": 0.002,
        "ema_distance_pct": 0.0005,
        "volume_ratio": 1.8,
        "pattern_type": "M",
        "multi_session_count": 3,
        "hits_to_level": 2,
        "hits_volume_trend": "increasing",
        "htf_consolidating": False,
        "svc_present": True,
        "asia_range_pct": 0.015,
        "asia_trending": False,
        "ema_rejection_candle": True,
    }
    c.update(overrides)
    return c


def _base_session(**overrides):
    s = {
        "phase": "opening",
        "phase_score": 0.7,
        "kill_zone_active": True,
        "session_overlap": True,
        "day_of_week": "wednesday",
    }
    s.update(overrides)
    return s


def _base_mtf(**overrides):
    m = {"tf_agreement_count": 4, "includes_htf": True}
    m.update(overrides)
    return m


def _base_dxy(**overrides):
    d = {"agrees": True, "flat": False}
    d.update(overrides)
    return d


def _base_htf(**overrides):
    h = {"alignment_score": 0.8}
    h.update(overrides)
    return h


# ──────────────────────────────────────────────────────────────
# Core structure tests
# ──────────────────────────────────────────────────────────────


def test_score_returns_tuple(scorer):
    result = scorer.score(_base_candidate())
    assert isinstance(result, tuple)
    assert isinstance(result[0], float)
    assert isinstance(result[1], list)


def test_score_range(scorer):
    """Total score should be between 0 and 1."""
    score, _ = scorer.score(
        _base_candidate(), _base_htf(), _base_session(), _base_mtf(), _base_dxy()
    )
    assert 0.0 <= score <= 1.0


def test_all_15_booster_names_present(scorer):
    """All 14 spec boosters + pattern_type bonus should be present."""
    _, boosters = scorer.score(
        _base_candidate(), _base_htf(), _base_session(), _base_mtf(), _base_dxy()
    )
    names = {b.name for b in boosters}
    expected = {
        # 14 spec §7.1 boosters
        "mtf_alignment",
        "multi_session",
        "svc_present",
        "hits_to_level",
        "hits_with_volume",
        "near_period_extreme",
        "htf_not_consolidating",
        "kill_zone",
        "session_overlap",
        "session_phase",
        "day_of_week",
        "asia_control",
        "ema_bounce",
        "dxy_correlation",
        # bonus (5% slack)
        "pattern_type",
    }
    assert names == expected, (
        f"Missing boosters: {expected - names}, Extra: {names - expected}"
    )


def test_booster_count_is_15(scorer):
    """14 spec + 1 bonus = 15 total boosters."""
    _, boosters = scorer.score(_base_candidate())
    assert len(boosters) == 15


# ──────────────────────────────────────────────────────────────
# 1. mtf_alignment booster tests
# ──────────────────────────────────────────────────────────────


def test_mtf_alignment_all_agree(scorer):
    _, res = scorer.score(
        _base_candidate(), mtf_state=_base_mtf(tf_agreement_count=4, includes_htf=True)
    )
    b = next(b for b in res if b.name == "mtf_alignment")
    assert b.score == 1.0


def test_mtf_alignment_3_of_4_with_htf(scorer):
    _, res = scorer.score(
        _base_candidate(), mtf_state=_base_mtf(tf_agreement_count=3, includes_htf=True)
    )
    b = next(b for b in res if b.name == "mtf_alignment")
    assert b.score == 0.75


def test_mtf_alignment_2_of_4_with_htf(scorer):
    _, res = scorer.score(
        _base_candidate(), mtf_state=_base_mtf(tf_agreement_count=2, includes_htf=True)
    )
    b = next(b for b in res if b.name == "mtf_alignment")
    assert b.score == 0.50


def test_mtf_alignment_2_of_4_ltf_only(scorer):
    _, res = scorer.score(
        _base_candidate(), mtf_state=_base_mtf(tf_agreement_count=2, includes_htf=False)
    )
    b = next(b for b in res if b.name == "mtf_alignment")
    assert b.score == 0.25


def test_mtf_alignment_none_agree(scorer):
    _, res = scorer.score(_base_candidate(), mtf_state=_base_mtf(tf_agreement_count=0))
    b = next(b for b in res if b.name == "mtf_alignment")
    assert b.score == 0.0


# ──────────────────────────────────────────────────────────────
# 2. multi_session booster tests
# ──────────────────────────────────────────────────────────────


def test_multi_session_3_plus(scorer):
    _, res = scorer.score(_base_candidate(multi_session_count=3))
    b = next(b for b in res if b.name == "multi_session")
    assert b.score == 1.0


def test_multi_session_2(scorer):
    _, res = scorer.score(_base_candidate(multi_session_count=2))
    b = next(b for b in res if b.name == "multi_session")
    assert b.score == 0.7


def test_multi_session_1(scorer):
    _, res = scorer.score(_base_candidate(multi_session_count=1))
    b = next(b for b in res if b.name == "multi_session")
    assert b.score == 0.2


# ──────────────────────────────────────────────────────────────
# 3. svc_present booster tests
# ──────────────────────────────────────────────────────────────


def test_svc_present_explicit_true(scorer):
    _, res = scorer.score(_base_candidate(svc_present=True, volume_ratio=0.5))
    b = next(b for b in res if b.name == "svc_present")
    assert b.score == 1.0


def test_svc_present_explicit_false(scorer):
    _, res = scorer.score(_base_candidate(svc_present=False, volume_ratio=0.5))
    b = next(b for b in res if b.name == "svc_present")
    assert b.score == 0.0


def test_svc_present_via_volume_proxy(scorer):
    """If svc_present not set but volume_ratio >= 1.5, treat as SVC."""
    _, res = scorer.score(_base_candidate(svc_present=False, volume_ratio=1.6))
    b = next(b for b in res if b.name == "svc_present")
    assert b.score == 1.0


# ──────────────────────────────────────────────────────────────
# 4. hits_to_level booster tests
# ──────────────────────────────────────────────────────────────


def test_hits_to_level_3_plus(scorer):
    _, res = scorer.score(_base_candidate(hits_to_level=3))
    b = next(b for b in res if b.name == "hits_to_level")
    assert b.score == 1.0


def test_hits_to_level_2(scorer):
    _, res = scorer.score(_base_candidate(hits_to_level=2))
    b = next(b for b in res if b.name == "hits_to_level")
    assert b.score == 0.7


def test_hits_to_level_1(scorer):
    _, res = scorer.score(_base_candidate(hits_to_level=1))
    b = next(b for b in res if b.name == "hits_to_level")
    assert b.score == 0.4


def test_hits_to_level_0(scorer):
    _, res = scorer.score(_base_candidate(hits_to_level=0))
    b = next(b for b in res if b.name == "hits_to_level")
    assert b.score == 0.0


# ──────────────────────────────────────────────────────────────
# 5. hits_with_volume booster tests
# ──────────────────────────────────────────────────────────────


def test_hits_volume_increasing(scorer):
    _, res = scorer.score(_base_candidate(hits_volume_trend="increasing"))
    b = next(b for b in res if b.name == "hits_with_volume")
    assert b.score == 1.0


def test_hits_volume_flat(scorer):
    _, res = scorer.score(_base_candidate(hits_volume_trend="flat"))
    b = next(b for b in res if b.name == "hits_with_volume")
    assert b.score == 0.3


def test_hits_volume_decreasing(scorer):
    _, res = scorer.score(_base_candidate(hits_volume_trend="decreasing"))
    b = next(b for b in res if b.name == "hits_with_volume")
    assert b.score == 0.1


# ──────────────────────────────────────────────────────────────
# 6. near_period_extreme booster tests (formerly level_proximity)
# ──────────────────────────────────────────────────────────────


def test_near_period_extreme_t1(scorer):
    """Closer than T1 = score 1.0."""
    from signal_engine.thresholds import PERIOD_EXTREME_T1

    _, res = scorer.score(_base_candidate(level_proximity_pct=PERIOD_EXTREME_T1))
    b = next(b for b in res if b.name == "near_period_extreme")
    assert b.score == 1.0


def test_near_period_extreme_t2(scorer):
    from signal_engine.thresholds import PERIOD_EXTREME_T1, PERIOD_EXTREME_T2

    _, res = scorer.score(
        _base_candidate(level_proximity_pct=(PERIOD_EXTREME_T1 + PERIOD_EXTREME_T2) / 2)
    )
    b = next(b for b in res if b.name == "near_period_extreme")
    assert b.score == 0.7


def test_near_period_extreme_t3(scorer):
    from signal_engine.thresholds import PERIOD_EXTREME_T2, PERIOD_EXTREME_T3

    _, res = scorer.score(
        _base_candidate(level_proximity_pct=(PERIOD_EXTREME_T2 + PERIOD_EXTREME_T3) / 2)
    )
    b = next(b for b in res if b.name == "near_period_extreme")
    assert b.score == 0.3


def test_near_period_extreme_far(scorer):
    from signal_engine.thresholds import PERIOD_EXTREME_T3

    _, res = scorer.score(_base_candidate(level_proximity_pct=PERIOD_EXTREME_T3 + 0.01))
    b = next(b for b in res if b.name == "near_period_extreme")
    assert b.score == 0.0


# ──────────────────────────────────────────────────────────────
# 7. htf_not_consolidating booster tests (formerly boardroom)
# ──────────────────────────────────────────────────────────────


def test_htf_not_consolidating_clear(scorer):
    _, res = scorer.score(_base_candidate(htf_consolidating=False))
    b = next(b for b in res if b.name == "htf_not_consolidating")
    assert b.score == 1.0


def test_htf_consolidating_explicit(scorer):
    _, res = scorer.score(_base_candidate(htf_consolidating=True))
    b = next(b for b in res if b.name == "htf_not_consolidating")
    assert b.score == 0.0


def test_htf_consolidating_boardroom_fallback(scorer):
    """When htf_consolidating not set, use boardroom as proxy."""
    _, res = scorer.score(
        _base_candidate(
            htf_consolidating=None,
            in_boardroom=True,
            boardroom_bars=25,
        )
    )
    b = next(b for b in res if b.name == "htf_not_consolidating")
    assert b.score == 0.0


def test_htf_not_consolidating_boardroom_fallback(scorer):
    _, res = scorer.score(
        _base_candidate(
            htf_consolidating=None,
            in_boardroom=False,
            boardroom_bars=0,
        )
    )
    b = next(b for b in res if b.name == "htf_not_consolidating")
    assert b.score == 1.0


# ──────────────────────────────────────────────────────────────
# 8. kill_zone booster tests
# ──────────────────────────────────────────────────────────────


def test_kill_zone_active(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(kill_zone_active=True)
    )
    b = next(b for b in res if b.name == "kill_zone")
    assert b.score == 1.0


def test_kill_zone_inactive(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(kill_zone_active=False)
    )
    b = next(b for b in res if b.name == "kill_zone")
    assert b.score == 0.0


# ──────────────────────────────────────────────────────────────
# 9. session_overlap booster tests
# ──────────────────────────────────────────────────────────────


def test_session_overlap_active(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(session_overlap=True)
    )
    b = next(b for b in res if b.name == "session_overlap")
    assert b.score == 1.0


def test_session_overlap_inactive(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(session_overlap=False)
    )
    b = next(b for b in res if b.name == "session_overlap")
    assert b.score == 0.0


# ──────────────────────────────────────────────────────────────
# 10. session_phase booster tests
# ──────────────────────────────────────────────────────────────


def test_session_phase_opening(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(phase="opening")
    )
    b = next(b for b in res if b.name == "session_phase")
    assert b.score == 1.0


def test_session_phase_mid(scorer):
    _, res = scorer.score(_base_candidate(), session_state=_base_session(phase="mid"))
    b = next(b for b in res if b.name == "session_phase")
    assert b.score == 0.5


def test_session_phase_closing(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(phase="closing")
    )
    b = next(b for b in res if b.name == "session_phase")
    assert b.score == 0.2


def test_session_phase_fallback(scorer):
    """When phase string not set, use phase_score + kill_zone bonus."""
    _, res = scorer.score(
        _base_candidate(),
        session_state=_base_session(
            phase="",
            phase_score=0.5,
            kill_zone_active=False,
        ),
    )
    b = next(b for b in res if b.name == "session_phase")
    assert b.score == 0.5


# ──────────────────────────────────────────────────────────────
# 11. day_of_week booster tests
# ──────────────────────────────────────────────────────────────


def test_day_of_week_wednesday_best(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(day_of_week="wednesday")
    )
    b = next(b for b in res if b.name == "day_of_week")
    assert b.score == 0.9


def test_day_of_week_tuesday(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(day_of_week="tuesday")
    )
    b = next(b for b in res if b.name == "day_of_week")
    assert b.score == 0.7


def test_day_of_week_monday_low(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(day_of_week="monday")
    )
    b = next(b for b in res if b.name == "day_of_week")
    assert b.score == 0.2


def test_day_of_week_friday_worst(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(day_of_week="friday")
    )
    b = next(b for b in res if b.name == "day_of_week")
    assert b.score == 0.1


def test_day_of_week_unknown(scorer):
    _, res = scorer.score(
        _base_candidate(), session_state=_base_session(day_of_week="")
    )
    b = next(b for b in res if b.name == "day_of_week")
    assert b.score == 0.3


# ──────────────────────────────────────────────────────────────
# 12. asia_control booster tests
# ──────────────────────────────────────────────────────────────


def test_asia_control_tight_consolidating(scorer):
    _, res = scorer.score(_base_candidate(asia_range_pct=0.015, asia_trending=False))
    b = next(b for b in res if b.name == "asia_control")
    assert b.score == 1.0


def test_asia_control_trending(scorer):
    _, res = scorer.score(_base_candidate(asia_range_pct=0.025, asia_trending=True))
    b = next(b for b in res if b.name == "asia_control")
    assert b.score == 0.0


def test_asia_control_neutral(scorer):
    # Range >= 0.02 and not trending = neutral (not tight, not trending)
    _, res = scorer.score(_base_candidate(asia_range_pct=0.025, asia_trending=False))
    b = next(b for b in res if b.name == "asia_control")
    assert b.score == 0.5


def test_asia_control_unknown(scorer):
    _, res = scorer.score(_base_candidate(asia_range_pct=None, asia_trending=None))
    b = next(b for b in res if b.name == "asia_control")
    assert b.score == 0.5


# ──────────────────────────────────────────────────────────────
# 13. ema_bounce booster tests (formerly ema_proximity)
# ──────────────────────────────────────────────────────────────


def test_ema_bounce_with_rejection_candle(scorer):
    _, res = scorer.score(_base_candidate(ema_rejection_candle=True))
    b = next(b for b in res if b.name == "ema_bounce")
    assert b.score == 1.0


def test_ema_bounce_no_rejection_candle(scorer):
    _, res = scorer.score(_base_candidate(ema_rejection_candle=False))
    b = next(b for b in res if b.name == "ema_bounce")
    assert b.score == 0.0


def test_ema_bounce_at_ema_fallback(scorer):
    """Without explicit flag, use distance as proxy."""
    from signal_engine.thresholds import EMA_TOUCH_THRESHOLD

    _, res = scorer.score(
        _base_candidate(ema_rejection_candle=None, ema_distance_pct=EMA_TOUCH_THRESHOLD)
    )
    b = next(b for b in res if b.name == "ema_bounce")
    assert b.score == 1.0


def test_ema_bounce_near_ema_fallback(scorer):
    from signal_engine.thresholds import EMA_TOUCH_THRESHOLD

    _, res = scorer.score(
        _base_candidate(
            ema_rejection_candle=None, ema_distance_pct=EMA_TOUCH_THRESHOLD * 2
        )
    )
    b = next(b for b in res if b.name == "ema_bounce")
    assert b.score == 0.5


def test_ema_bounce_far_from_ema_fallback(scorer):
    _, res = scorer.score(
        _base_candidate(ema_rejection_candle=None, ema_distance_pct=0.01)
    )
    b = next(b for b in res if b.name == "ema_bounce")
    assert b.score == 0.0


# ──────────────────────────────────────────────────────────────
# 14. dxy_correlation booster tests
# ──────────────────────────────────────────────────────────────


def test_dxy_correlation_agrees(scorer):
    _, res = scorer.score(
        _base_candidate(), dxy_state=_base_dxy(agrees=True, flat=False)
    )
    b = next(b for b in res if b.name == "dxy_correlation")
    assert b.score == 1.0


def test_dxy_correlation_opposes(scorer):
    _, res = scorer.score(
        _base_candidate(), dxy_state={"agrees": False, "flat": False, "opposes": True}
    )
    b = next(b for b in res if b.name == "dxy_correlation")
    assert b.score == 0.0


def test_dxy_correlation_flat(scorer):
    _, res = scorer.score(_base_candidate(), dxy_state={"agrees": False, "flat": True})
    b = next(b for b in res if b.name == "dxy_correlation")
    assert b.score == 0.5


def test_dxy_correlation_unknown(scorer):
    _, res = scorer.score(_base_candidate(), dxy_state={})
    b = next(b for b in res if b.name == "dxy_correlation")
    assert b.score == 0.5


# ──────────────────────────────────────────────────────────────
# 15. pattern_type booster tests (bonus)
# ──────────────────────────────────────────────────────────────


def test_pattern_type_m(scorer):
    _, res = scorer.score(_base_candidate(pattern_type="M"))
    b = next(b for b in res if b.name == "pattern_type")
    assert b.score == 0.9


def test_pattern_type_w(scorer):
    _, res = scorer.score(_base_candidate(pattern_type="W"))
    b = next(b for b in res if b.name == "pattern_type")
    assert b.score == 0.9


def test_pattern_type_svc(scorer):
    _, res = scorer.score(_base_candidate(pattern_type="SVC"))
    b = next(b for b in res if b.name == "pattern_type")
    assert b.score == 0.7


def test_pattern_type_unknown(scorer):
    _, res = scorer.score(_base_candidate(pattern_type="UNKNOWN"))
    b = next(b for b in res if b.name == "pattern_type")
    assert b.score == 0.3


# ──────────────────────────────────────────────────────────────
# Weight verification tests
# ──────────────────────────────────────────────────────────────


def test_spec_weights_sum_to_0_95(scorer):
    """Spec §7.1 weight total should be 0.95 (5% slack)."""
    spec_weights = [
        WEIGHT_MTF_ALIGNMENT,
        WEIGHT_MULTI_SESSION,
        WEIGHT_SVC_PRESENT,
        WEIGHT_HITS_TO_LEVEL,
        WEIGHT_HITS_WITH_VOLUME,
        WEIGHT_NEAR_PERIOD_EXTREME,
        WEIGHT_HTF_NOT_CONSOLIDATING,
        WEIGHT_KILL_ZONE,
        WEIGHT_SESSION_OVERLAP,
        WEIGHT_SESSION_PHASE,
        WEIGHT_DAY_OF_WEEK,
        WEIGHT_ASIA_CONTROL,
        WEIGHT_EMA_BOUNCE,
        WEIGHT_DXY_CORRELATION,
    ]
    assert abs(sum(spec_weights) - 0.95) < 0.001, (
        f"Spec weights sum to {sum(spec_weights)}, expected 0.95"
    )


def test_total_weights_sum_to_1_0(scorer):
    """Spec weights + pattern_type bonus = 1.00."""
    all_weights = [
        WEIGHT_MTF_ALIGNMENT,
        WEIGHT_MULTI_SESSION,
        WEIGHT_SVC_PRESENT,
        WEIGHT_HITS_TO_LEVEL,
        WEIGHT_HITS_WITH_VOLUME,
        WEIGHT_NEAR_PERIOD_EXTREME,
        WEIGHT_HTF_NOT_CONSOLIDATING,
        WEIGHT_KILL_ZONE,
        WEIGHT_SESSION_OVERLAP,
        WEIGHT_SESSION_PHASE,
        WEIGHT_DAY_OF_WEEK,
        WEIGHT_ASIA_CONTROL,
        WEIGHT_EMA_BOUNCE,
        WEIGHT_DXY_CORRELATION,
        WEIGHT_PATTERN_TYPE,
    ]
    assert abs(sum(all_weights) - 1.00) < 0.001, (
        f"All weights sum to {sum(all_weights)}, expected 1.00"
    )


# ──────────────────────────────────────────────────────────────
# Edge case + integration tests
# ──────────────────────────────────────────────────────────────


def test_zero_confluence_low_score(scorer):
    """A candidate with all-zero factors should produce a low score."""
    candidate = _base_candidate(
        level_proximity_pct=0.05,
        ema_distance_pct=0.01,
        volume_ratio=0.5,
        pattern_type="",
        multi_session_count=1,
        hits_to_level=0,
        hits_volume_trend="decreasing",
        htf_consolidating=True,
        svc_present=False,
        asia_range_pct=0.03,
        asia_trending=True,
        ema_rejection_candle=False,
    )
    session = _base_session(
        kill_zone_active=False,
        session_overlap=False,
        phase="closing",
        day_of_week="friday",
    )
    mtf = _base_mtf(tf_agreement_count=1, includes_htf=False)
    dxy = _base_dxy(agrees=False, flat=False, opposes=True)

    score, boosters = scorer.score(
        candidate, session_state=session, mtf_state=mtf, dxy_state=dxy
    )
    assert score < 0.15, f"Expected low score with all-zero factors, got {score}"


def test_max_confluence_high_score(scorer):
    """A candidate with all-max factors should produce a high score."""
    score, boosters = scorer.score(
        _base_candidate(),
        session_state=_base_session(),
        mtf_state=_base_mtf(),
        dxy_state=_base_dxy(),
    )
    assert score > 0.85, f"Expected high score with all-max factors, got {score}"


def test_backward_compat_minimal_candidate(scorer):
    """Score should work with minimal candidate data (all defaults)."""
    score, boosters = scorer.score({})
    assert isinstance(score, float)
    assert len(boosters) == 15


def test_backward_compat_htf_state(scorer):
    """Score should work with legacy htf_state parameter."""
    score, boosters = scorer.score(
        _base_candidate(),
        htf_state={"alignment_score": 0.8},
        session_state=_base_session(),
    )
    assert isinstance(score, float)
    assert len(boosters) == 15


# ──────────────────────────────────────────────────────────────
# BoosterResult dataclass tests
# ──────────────────────────────────────────────────────────────


def test_booster_result_dataclass():
    br = BoosterResult(name="test", score=0.5, weight=0.1, raw_detail="info")
    assert br.name == "test"
    assert br.score == 0.5
    assert br.weight == 0.1
    assert br.raw_detail == "info"


def test_booster_result_default_detail():
    br = BoosterResult(name="test", score=1.0, weight=0.2)
    assert br.raw_detail == ""
