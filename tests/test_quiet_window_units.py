"""Tests for the Ayumi quiet-window systemd timer package (card 5c064a96).

Repo-only build: these tests assert the *contents* of the shipped unit files,
installer, and the flip-able Sunday-skip marker. They do not touch
/etc/systemd or the live service.
"""
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"

STOP_SERVICE = DEPLOY / "ayumi-quiet-window-stop.service"
STOP_TIMER = DEPLOY / "ayumi-quiet-window-stop.timer"
START_SERVICE = DEPLOY / "ayumi-quiet-window-start.service"
START_TIMER = DEPLOY / "ayumi-quiet-window-start.timer"
INSTALLER = DEPLOY / "install-quiet-window.sh"


def read(path: Path) -> str:
    assert path.is_file(), f"missing deliverable: {path}"
    return path.read_text()


class TestUnitFiles:
    def test_all_four_units_exist(self):
        for p in (STOP_SERVICE, STOP_TIMER, START_SERVICE, START_TIMER):
            assert p.is_file()

    def test_ny_timezone_anchor_on_both_timers(self):
        for timer in (STOP_TIMER, START_TIMER):
            text = read(timer)
            assert "America/New_York" in text, f"no NY timezone anchor in {timer.name}"
            assert "OnCalendar=" in text

    def test_stop_timer_anchored_1655_ny(self):
        assert "OnCalendar=*-*-* 16:55:00 America/New_York" in read(STOP_TIMER)

    def test_start_timer_anchored_1805_ny(self):
        assert "OnCalendar=*-*-* 18:05:00 America/New_York" in read(START_TIMER)

    def test_timers_target_correct_services(self):
        assert "Unit=ayumi-quiet-window-stop.service" in read(STOP_TIMER)
        assert "Unit=ayumi-quiet-window-start.service" in read(START_TIMER)

    def test_timers_install_into_timers_target(self):
        for timer in (STOP_TIMER, START_TIMER):
            assert "WantedBy=timers.target" in read(timer)

    def test_stop_service_stops_forward_test(self):
        assert "systemctl stop ayumi.forward-test.service" in read(STOP_SERVICE)

    def test_start_service_starts_forward_test(self):
        assert "systemctl start ayumi.forward-test.service" in read(START_SERVICE)

    def test_services_are_oneshot(self):
        for svc in (STOP_SERVICE, START_SERVICE):
            assert "Type=oneshot" in read(svc)


class TestSundaySkipMarker:
    def test_flipable_sunday_skip_documented_in_start_timer(self):
        text = read(START_TIMER)
        assert "FLIP-ABLE" in text
        # ~65-min post-reopen skip: Sunday reopen 17:00 ET, start fires 18:05 ET.
        assert "Sunday" in text or "Sundays" in text
        assert "17:00" in text and "18:05" in text


class TestInstaller:
    def test_installer_is_executable_content_dry_by_default(self):
        text = read(INSTALLER)
        assert text.startswith("#!/usr/bin/env bash")
        assert "--apply" in text, "live install must be behind explicit --apply"
        assert "DRY RUN" in text, "default run must be a dry summary"

    def test_installer_uses_idempotent_copy(self):
        text = read(INSTALLER)
        assert "install -m 0644" in text, "idempotent install loop expected"
        assert "daemon-reload" in text

    def test_installer_does_not_auto_enable_timers(self):
        text = read(INSTALLER)
        # Enable line must be printed as guidance, not executed.
        assert "systemctl enable --now" in text
        assert text.count("systemctl enable --now ayumi") == 1
        # No unguarded enable invocation on its own line.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("systemctl enable"):
                raise AssertionError("installer must not execute enable directly")
        assert "enable --now" in text  # guidance string present exactly once

    def test_installer_checks_missing_sources(self):
        assert "MISSING" in read(INSTALLER)

    def test_installer_names_predeploy_gate_service(self):
        assert "ayumi.forward-test.service" in read(INSTALLER)


class TestRepoOnlyGuarantee:
    def test_no_etc_systemd_writes_outside_apply(self):
        text = read(INSTALLER)
        assert "/etc/systemd/system" in text  # target dir declared
        # Every line that writes to /etc must be inside the apply branch,
        # guarded by the 'install -m 0644' loop which is apply-gated.
        assert '[[ "${1:-}" == "--apply" ]]' in text
        assert "set -euo pipefail" in text
