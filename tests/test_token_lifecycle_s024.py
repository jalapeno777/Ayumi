"""Sprint 024 (card 591cbfe6) acceptance tests — token rotation, kill-switch re-arm.

These tests cover the new AC items added in sprint 024 (2026-08-21):

  1. Token rotation keeps ``token_age_s < 3600`` across a simulated
     refresh cycle (mocked clock + credential store, no network).
  2. Five consecutive auth failures (configurable) arm the global-freeze
     halt via the injected KillSwitchManager instead of unbounded retry.
  3. HTTP 400 (invalid grant) does NOT count toward the re-arm
     threshold — it's permanent and requires manual intervention.
  4. The validation gate is now ADVISORY by default (strict_validation
     defaults to False).
  5. Stale lock-file detection: a lock file with mtime older than
     ``STALE_LOCK_THRESHOLD_S`` is logged as stolen, and the refresh
     proceeds (kernel releases the dead holder's lock automatically).
  6. ``_issued_at`` and ``token_age_s`` are bumped/reset on every
     successful refresh.

Run with::

    python3 -m pytest tests/test_token_lifecycle_s024.py -q
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest
from adapters.ctrader.credential_store import Credentials
from adapters.ctrader.token_lifecycle import (
    DEFAULT_AUTH_FAILURE_THRESHOLD,
    STALE_LOCK_THRESHOLD_S,
    TOKEN_AGE_HEALTH_BUDGET_S,
    TokenLifecycle,
    TokenRefreshError,
)

# ── Clock helpers ────────────────────────────────────────────────────────────


class FakeClock:
    """Deterministic UTC clock for token-age tests.

    Advance by ``tick(seconds)`` to simulate time passing. The clock is
    injected into TokenLifecycle via the ``clock`` constructor kwarg.
    """

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self._now

    def tick(self, seconds: float) -> datetime:
        self._now = self._now + timedelta(seconds=seconds)
        return self._now

    def set(self, when: datetime) -> None:
        self._now = when


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_credentials(
    *,
    access_token: str = "initial-token",  # noqa: S107
    refresh_token: str = "initial-refresh",  # noqa: S107
    expires_at: datetime | None = None,
) -> Credentials:
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=15)
    return Credentials(
        client_id="cid",
        client_secret="csecret",  # noqa: S106
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=1,
        trader_login=2,
        expires_at=expires_at,
    )


def _mock_oauth_response(
    *,
    access_token: str = "fresh-token",  # noqa: S107
    refresh_token: str = "fresh-refresh",  # noqa: S107
    expires_in: int = 3600,
    status_code: int = 200,
    json_data: dict | None = None,
):
    if json_data is None:
        json_data = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresIn": expires_in,
        }
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def _make_mock_store(creds: Credentials | None = None) -> MagicMock:
    if creds is None:
        creds = _make_credentials()
    store = MagicMock()
    store.get.return_value = creds
    return store


# ── AC: token_age_s < 3600 across refresh cycle ─────────────────────────────


class TestTokenAgeAcrossRefreshCycle:
    """Sprint 024 AC: token rotation keeps ``token_age_s < 3600``.

    Simulates a long-lived forward test where the same TokenLifecycle
    instance survives multiple refresh cycles. After each refresh, the
    new access token's age must reset to (approximately) zero, and the
    clock is advanced well past the previous token's age to prove the
    reset actually happened.
    """

    def test_token_age_resets_after_refresh(self):
        """After _do_refresh(), token_age_s returns to ~0."""
        clock = FakeClock()
        expired = _make_credentials(
            access_token="old-token",  # noqa: S106
            expires_at=clock._now + timedelta(days=20),
        )
        # New credentials returned by store.update_tokens()
        fresh = _make_credentials(
            access_token="fresh-token",  # noqa: S106
            refresh_token="fresh-refresh",  # noqa: S106
            expires_at=clock._now + timedelta(days=30),
        )

        store = MagicMock()
        # First get() returns the expired creds, subsequent get() returns fresh
        store.get.side_effect = [expired, fresh, fresh]

        lc = TokenLifecycle(store, clock=clock)

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch(
                "adapters.ctrader.token_lifecycle.requests.get",
                return_value=Mock(status_code=200),
            ),
            patch.object(lc, "_validate_token", return_value=True),
        ):
            mock_post.return_value = _mock_oauth_response(
                access_token="fresh-token",  # noqa: S106
                refresh_token="fresh-refresh",  # noqa: S106
            )

            # Advance the clock to simulate an aging token
            clock.tick(7200)  # 2 hours of staleness before refresh
            assert lc.token_age_s >= 7199  # noqa: PLR2004

            # Force a refresh (force=True bypasses the validity re-check)
            token = lc._do_refresh(force=True)
            assert token == "fresh-token"  # noqa: S105
            # Token age must reset to ~0
            assert lc.token_age_s < 1.0, (  # noqa: PLR2004
                f"After refresh, token_age_s should be ~0, got {lc.token_age_s}"
            )

    def test_token_age_stays_under_3600_across_long_simulation(self):
        """End-to-end: simulated refresh cycle keeps token_age_s < 3600.

        Sprint 024 AC. Scenario: a forward-test process runs for 3 hours,
        triggers a refresh mid-cycle, then runs another hour. After
        each refresh, token_age_s drops to ~0. Between refreshes, it
        grows but never exceeds the 3600s budget (because the refresh
        happens within the budget window).

        Uses a non-frozen credentials holder (since ``Credentials`` is a
        frozen dataclass) — the side_effect returns a NEW credentials
        snapshot each call.
        """
        clock = FakeClock()
        # Note: previous version of this test built an initial creds
        # snapshot here, but the side_effect-only fake_get() below is
        # the actual source of creds (the snapshot wasn't referenced).

        # Each call to store.get() returns the current snapshot.
        refresh_count = {"n": 0}

        def fake_update(access, refresh, expires_in):  # noqa: ARG001
            refresh_count["n"] += 1

        def fake_get():
            # Build a fresh snapshot each call so the frozen-dataclass
            # doesn't get mutated and we don't share references.
            return _make_credentials(
                access_token=f"rotated-{refresh_count['n']}",
                refresh_token=f"refresh-{refresh_count['n']}",
                expires_at=clock._now + timedelta(seconds=3600),
            )

        store = MagicMock()
        store.get.side_effect = fake_get
        store.update_tokens.side_effect = fake_update

        lc = TokenLifecycle(store, clock=clock)
        # _do_refresh(force=True) bypasses the 5-day-buffer validity check
        # so we can exercise the rotation path directly.

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch(
                "adapters.ctrader.token_lifecycle.requests.get",
                return_value=Mock(status_code=200),
            ),
            patch.object(lc, "_validate_token", return_value=True),
        ):
            mock_post.return_value = _mock_oauth_response()

            # Cycle 1: refresh at t=1800s (30 min). Between construction
            # and the refresh, token_age_s has grown to 1800s — still
            # under the 3600s health budget. Refresh resets it.
            clock.tick(1800)
            assert 1799 < lc.token_age_s < 1801  # noqa: PLR2004
            assert lc.token_age_s < TOKEN_AGE_HEALTH_BUDGET_S
            lc._do_refresh(force=True)
            assert lc.token_age_s < 1.0  # noqa: PLR2004

            # Cycle 2: another 1800s passes → token_age_s ~1800s, still
            # under the budget. Refresh resets it again.
            clock.tick(1800)
            assert 1799 < lc.token_age_s < 1801  # noqa: PLR2004
            assert lc.token_age_s < TOKEN_AGE_HEALTH_BUDGET_S
            lc._do_refresh(force=True)
            assert lc.token_age_s < 1.0  # noqa: PLR2004

            # Cycle 3: advance clock PAST the budget threshold without
            # refreshing yet, to PROVE that rotation is what keeps the
            # token age under budget (rather than the token simply being
            # fresh). Then refresh and confirm the reset.
            clock.tick(4500)  # total elapsed 9900s, ~4500s since last refresh
            assert lc.token_age_s > TOKEN_AGE_HEALTH_BUDGET_S, (
                "Test setup: between refresh #2 and #3, clock must advance "
                "past 3600s so token_age_s exceeds the budget threshold, "
                "proving rotation is what keeps us under budget."
            )
            lc._do_refresh(force=True)
            assert lc.token_age_s < 1.0  # noqa: PLR2004

            # Final assertion: refresh_count must show all 3 rotations
            assert refresh_count["n"] == 3  # noqa: PLR2004

    def test_token_age_uses_injected_clock(self):
        """token_age_s is computed from the injected clock, not wall time."""
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        clock = FakeClock(start=start)

        store = _make_mock_store()
        lc = TokenLifecycle(store, clock=clock)

        # Initial age should be 0 (constructed at start)
        assert lc.token_age_s == 0.0  # noqa: PLR2004

        # Advance clock 1000s without refresh — age must track clock exactly
        clock.tick(1000)
        assert lc.token_age_s == 1000.0  # noqa: PLR2004

        clock.tick(1000)
        assert lc.token_age_s == 2000.0  # noqa: PLR2004


# ── AC: 5 consecutive auth failures arm the kill switch ────────────────────


class TestKillSwitchRearm:
    """Sprint 024 AC: 5 consecutive auth failures arm the global-freeze halt."""

    def test_default_threshold_is_five(self):
        """The default re-arm threshold matches the card AC."""
        assert DEFAULT_AUTH_FAILURE_THRESHOLD == 5  # noqa: PLR2004

    def test_kill_switch_armed_after_five_5xx_failures(self):
        """Five consecutive HTTP 5xx responses arm the injected kill switch."""
        ks = MagicMock()
        store = _make_mock_store()
        lc = TokenLifecycle(
            store,
            clock=FakeClock(),
            auth_failure_threshold=5,
            kill_switch=ks,
        )

        with patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post:
            mock_post.return_value = _mock_oauth_response(
                status_code=503,
                json_data={"error": "service_unavailable"},
            )

            # First 4 failures: no kill-switch activation yet
            for i in range(4):  # noqa: B007
                with pytest.raises(TokenRefreshError):
                    lc._do_refresh(force=True)
            assert lc.consecutive_auth_failures == 4  # noqa: PLR2004
            ks.activate_global_freeze.assert_not_called()

            # 5th failure: threshold reached → kill switch armed
            with pytest.raises(TokenRefreshError):
                lc._do_refresh(force=True)
            assert lc.consecutive_auth_failures == 5  # noqa: PLR2004
            ks.activate_global_freeze.assert_called_once()
            # Reason must mention consecutive failures + threshold
            args, kwargs = ks.activate_global_freeze.call_args
            reason = kwargs.get("reason") or args[0]
            assert "5 consecutive" in reason
            assert "threshold=5" in reason
            assert kwargs.get("triggered_by") == "token_lifecycle"

    def test_kill_switch_armed_after_five_network_errors(self):
        """Five consecutive network errors arm the kill switch."""
        import requests as req

        ks = MagicMock()
        store = _make_mock_store()
        lc = TokenLifecycle(
            store,
            clock=FakeClock(),
            auth_failure_threshold=5,
            kill_switch=ks,
        )

        with patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post:
            mock_post.side_effect = req.ConnectionError("refused")

            for _ in range(5):
                with pytest.raises(TokenRefreshError):
                    lc._do_refresh(force=True)
            assert lc.consecutive_auth_failures == 5  # noqa: PLR2004
            ks.activate_global_freeze.assert_called_once()

    def test_http_400_does_not_arm_kill_switch(self):
        """Permanent failures (HTTP 400 invalid grant) don't count toward the threshold."""
        ks = MagicMock()
        store = _make_mock_store()
        lc = TokenLifecycle(
            store,
            clock=FakeClock(),
            auth_failure_threshold=5,
            kill_switch=ks,
        )

        with patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post:
            mock_post.return_value = _mock_oauth_response(
                status_code=400,
                json_data={"error": "invalid_grant"},
            )

            for _ in range(10):
                with pytest.raises(TokenRefreshError) as exc_info:
                    lc._do_refresh(force=True)
                assert exc_info.value.retry is False

            # HTTP 400 must NOT increment the re-arm counter
            assert lc.consecutive_auth_failures == 0  # noqa: PLR2004
            ks.activate_global_freeze.assert_not_called()

    def test_successful_refresh_resets_failure_counter(self):
        """A successful refresh zeros the counter — recovery is preserved."""
        ks = MagicMock()
        creds = _make_credentials(
            access_token="old",  # noqa: S106
            expires_at=datetime.now(timezone.utc) + timedelta(days=20),
        )

        # store.get() initially returns the old creds; after a successful
        # update_tokens(), subsequent gets return the new creds.
        refreshed_creds = _make_credentials(
            access_token="recovered",  # noqa: S106
            expires_at=datetime.now(timezone.utc) + timedelta(days=20),
        )
        call_count = {"n": 0}

        def store_get():
            call_count["n"] += 1
            return refreshed_creds if call_count["n"] > 1 else creds

        store = MagicMock()
        store.get.side_effect = store_get

        lc = TokenLifecycle(
            store,
            clock=FakeClock(),
            auth_failure_threshold=5,
            kill_switch=ks,
        )

        with patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post:
            # 3 transient failures
            mock_post.return_value = _mock_oauth_response(status_code=503)
            for _ in range(3):
                with pytest.raises(TokenRefreshError):
                    lc._do_refresh(force=True)
            assert lc.consecutive_auth_failures == 3  # noqa: PLR2004

            # Now a successful refresh — return rotated creds via update_tokens
            def fake_update(access, refresh, expires_in):  # noqa: ARG001
                # Subsequent store.get() calls return refreshed creds
                call_count["n"] += 5  # bump so next get() returns refreshed

            store.update_tokens.side_effect = fake_update

            mock_post.return_value = _mock_oauth_response(
                access_token="recovered",  # noqa: S106
                refresh_token="recovered-r",  # noqa: S106
            )
            with patch.object(lc, "_validate_token", return_value=True):
                token = lc._do_refresh(force=True)
            assert token == "recovered"  # noqa: S105
            assert lc.consecutive_auth_failures == 0  # noqa: PLR2004
            ks.activate_global_freeze.assert_not_called()

            # Another 3 failures — counter restarts from 0, not 3
            mock_post.return_value = _mock_oauth_response(status_code=503)
            for _ in range(3):
                with pytest.raises(TokenRefreshError):
                    lc._do_refresh(force=True)
            assert lc.consecutive_auth_failures == 3  # noqa: PLR2004
            ks.activate_global_freeze.assert_not_called()

    def test_mixed_4xx_and_5xx_only_5xx_counts(self):
        """Mixed errors: only retryable (5xx/network) failures increment counter."""
        ks = MagicMock()
        store = _make_mock_store()
        lc = TokenLifecycle(
            store,
            clock=FakeClock(),
            auth_failure_threshold=5,
            kill_switch=ks,
        )

        with patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post:
            # 3× HTTP 400 + 4× HTTP 503 = 4 retryable failures (not 7)
            responses = [
                _mock_oauth_response(status_code=400, json_data={"error": "invalid_grant"}),
                _mock_oauth_response(status_code=400, json_data={"error": "invalid_grant"}),
                _mock_oauth_response(status_code=400, json_data={"error": "invalid_grant"}),
                _mock_oauth_response(status_code=503, json_data={"error": "server"}),
                _mock_oauth_response(status_code=503, json_data={"error": "server"}),
                _mock_oauth_response(status_code=503, json_data={"error": "server"}),
                _mock_oauth_response(status_code=503, json_data={"error": "server"}),
                # The 8th call would be the 5th 5xx — must trigger arm
                _mock_oauth_response(status_code=503, json_data={"error": "server"}),
            ]
            mock_post.side_effect = responses

            for _ in range(8):
                with pytest.raises(TokenRefreshError):
                    lc._do_refresh(force=True)

            # After 3×400 + 4×503 = 4 retryable (the 8th call would be the 5th 503)
            # BUT: after the 8th call, the 5th 503 fires — arm happens
            assert lc.consecutive_auth_failures == 5  # noqa: PLR2004
            ks.activate_global_freeze.assert_called_once()

    def test_no_kill_switch_logs_critical_does_not_raise(self):
        """Without an injected kill switch, re-arm logs and does NOT raise.

        The refresh path is already in a failure state; we must not mask
        the original TokenRefreshError with a secondary failure.
        """
        store = _make_mock_store()
        lc = TokenLifecycle(
            store,
            clock=FakeClock(),
            auth_failure_threshold=2,  # tighten for speed
            kill_switch=None,
        )

        with patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post:
            mock_post.return_value = _mock_oauth_response(status_code=503)

            # 2 failures: still raises TokenRefreshError (from the refresh)
            for _ in range(2):
                with pytest.raises(TokenRefreshError):
                    lc._do_refresh(force=True)
            assert lc.consecutive_auth_failures == 2  # noqa: PLR2004

    def test_configurable_threshold(self):
        """auth_failure_threshold is honoured — tighten to 2 for the test."""
        ks = MagicMock()
        store = _make_mock_store()
        lc = TokenLifecycle(
            store,
            clock=FakeClock(),
            auth_failure_threshold=2,
            kill_switch=ks,
        )

        with patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post:
            mock_post.return_value = _mock_oauth_response(status_code=500)

            # 2 failures with threshold=2 → arm on the 2nd
            with pytest.raises(TokenRefreshError):
                lc._do_refresh(force=True)
            assert lc.consecutive_auth_failures == 1  # noqa: PLR2004
            ks.activate_global_freeze.assert_not_called()

            with pytest.raises(TokenRefreshError):
                lc._do_refresh(force=True)
            assert lc.consecutive_auth_failures == 2  # noqa: PLR2004
            ks.activate_global_freeze.assert_called_once()


# ── AC: advisory validation by default ──────────────────────────────────────


class TestAdvisoryValidation:
    """Sprint 024: validation is advisory by default."""

    def test_default_strict_validation_is_false(self):
        """TokenLifecycle() with no strict_validation kwarg defaults to False."""
        lc = TokenLifecycle(_make_mock_store())
        assert lc._strict_validation is False

    def test_advisory_validation_persists_on_failure(self):
        """Advisory mode: failed _validate_token does NOT prevent persist."""
        lc = TokenLifecycle(_make_mock_store())
        new_creds = _make_credentials(access_token="advisory-persist")  # noqa: S106
        store_get_count = {"n": 0}

        def fake_get():
            store_get_count["n"] += 1
            return new_creds

        store = MagicMock()
        store.get.side_effect = fake_get

        lc._store = store

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch.object(lc, "_validate_token", return_value=False),
            patch.object(store, "update_tokens") as mock_update,
        ):
            mock_post.return_value = _mock_oauth_response()

            token = lc._do_refresh(force=True)
            # Token was persisted despite advisory failure
            assert token == "advisory-persist"  # noqa: S105
            mock_update.assert_called_once()
            # Failure counter NOT incremented (advisory is not "auth failure")
            assert lc.consecutive_auth_failures == 0

    def test_issued_at_bumped_on_successful_refresh(self):
        """A successful refresh bumps _issued_at to the current clock."""
        clock = FakeClock()
        lc = TokenLifecycle(_make_mock_store(), clock=clock)

        before = clock()
        clock.tick(5000)  # advance 5,000s

        new_creds = _make_credentials(
            access_token="fresh",  # noqa: S106
            expires_at=clock() + timedelta(days=15),
        )
        store = MagicMock()
        store.get.return_value = new_creds

        lc._store = store

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch.object(lc, "_validate_token", return_value=True),
        ):
            mock_post.return_value = _mock_oauth_response()
            lc._do_refresh(force=True)

        # _issued_at must reflect the current clock, not the construction time
        assert lc._issued_at > before
        assert lc.token_age_s < 1.0  # noqa: PLR2004


# ── AC: stale lock-file detection ───────────────────────────────────────────


class TestStaleLockFileSteal:
    """Sprint 024 AC: stale lock files are detected and stolen.

    POSIX ``fcntl.flock`` releases on process death, so the practical
    risk is operator confusion (stale mtime suggesting a crashed
    refresh). We log the steal and proceed.
    """

    def test_stale_lock_file_is_stolen(self, tmp_path, monkeypatch):
        """A lock file with mtime older than the threshold triggers the steal path."""
        lock_path = tmp_path / ".token_refresh.lock"
        monkeypatch.setenv("AYUMI_TOKEN_LOCK_FILE", str(lock_path))

        # Create a lock file with mtime older than STALE_LOCK_THRESHOLD_S
        lock_path.touch()
        old_mtime = time.time() - (STALE_LOCK_THRESHOLD_S + 60)
        os.utime(str(lock_path), (old_mtime, old_mtime))

        store = _make_mock_store()
        lc = TokenLifecycle(store, clock=FakeClock())

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch(
                "adapters.ctrader.token_lifecycle.requests.get",
                return_value=Mock(status_code=200),
            ),
            patch.object(lc, "_validate_token", return_value=True),
        ):
            mock_post.return_value = _mock_oauth_response(access_token="after-steal")  # noqa: S106
            new_creds = _make_credentials(access_token="after-steal")  # noqa: S106
            store.get.return_value = new_creds

            token = lc._do_refresh(force=True)
            # Despite the stale lock file, refresh completes successfully
            assert token == "after-steal"  # noqa: S105

    def test_fresh_lock_file_is_still_acquired(self, tmp_path, monkeypatch):
        """A freshly-created lock file (no concurrent holder) works normally."""
        lock_path = tmp_path / ".token_refresh.lock"
        monkeypatch.setenv("AYUMI_TOKEN_LOCK_FILE", str(lock_path))

        # Lock file doesn't even exist yet — fresh path is the standard one
        store = _make_mock_store()
        lc = TokenLifecycle(store, clock=FakeClock())

        with (
            patch("adapters.ctrader.token_lifecycle.requests.post") as mock_post,
            patch(
                "adapters.ctrader.token_lifecycle.requests.get",
                return_value=Mock(status_code=200),
            ),
            patch.object(lc, "_validate_token", return_value=True),
        ):
            mock_post.return_value = _mock_oauth_response(access_token="normal-path")  # noqa: S106
            store.get.return_value = _make_credentials(access_token="normal-path")  # noqa: S106

            token = lc._do_refresh(force=True)
            assert token == "normal-path"  # noqa: S105


# ── Property semantics ──────────────────────────────────────────────────────


class TestIssuedAtProperty:
    """The new ``issued_at`` / ``token_age_s`` properties."""

    def test_issued_at_at_construction(self):
        """At construction, _issued_at is set to the (injected) clock value."""
        fixed = datetime(2026, 8, 21, 23, 0, 0, tzinfo=timezone.utc)
        clock = FakeClock(start=fixed)
        lc = TokenLifecycle(_make_mock_store(), clock=clock)
        assert lc.issued_at == fixed

    def test_token_age_monotonic_with_clock(self):
        """token_age_s increases monotonically as the clock advances."""
        clock = FakeClock()
        lc = TokenLifecycle(_make_mock_store(), clock=clock)
        assert lc.token_age_s == 0.0  # noqa: PLR2004
        for s in (60, 300, 1800, 3600):
            clock.tick(s - lc.token_age_s)
            assert abs(lc.token_age_s - s) < 1e-6  # noqa: PLR2004

    def test_health_budget_constant(self):
        """TOKEN_AGE_HEALTH_BUDGET_S is the AC value (3600)."""
        assert TOKEN_AGE_HEALTH_BUDGET_S == 3600  # noqa: PLR2004


# ── _now() helper ────────────────────────────────────────────────────────────


class TestNowHelper:
    """The new ``_now()`` helper used everywhere instead of bare datetime.now."""

    def test_now_uses_injected_clock(self):
        """_now() returns the value from the injected clock, not wall time."""
        fixed = datetime(2030, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        clock = FakeClock(start=fixed)
        lc = TokenLifecycle(_make_mock_store(), clock=clock)
        assert lc._now() == fixed

    def test_now_default_uses_wall_clock(self):
        """Without an injected clock, _now() falls back to datetime.now(UTC)."""
        lc = TokenLifecycle(_make_mock_store())
        result = lc._now()
        assert result.tzinfo is not None
        # Should be within 5s of "now"
        assert abs((datetime.now(timezone.utc) - result).total_seconds()) < 5  # noqa: PLR2004
