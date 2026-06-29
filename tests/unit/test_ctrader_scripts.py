"""Tests for ctrader_credential_probe.py and ctrader_callback_linter.py.

BQ-1330: Tests verify both scripts function correctly as standalone
health/lint tools.
"""

from __future__ import annotations

import importlib
import json
import sys
import textwrap
from pathlib import Path

import pytest

# Ensure scripts dir is importable
_scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


@pytest.fixture
def probe_module():
    """Import the credential probe module."""
    return importlib.import_module("ctrader_credential_probe")


@pytest.fixture
def linter_module():
    """Import the callback linter module."""
    return importlib.import_module("ctrader_callback_linter")


# ── Credential Probe Tests ──────────────────────────────────────────────────

class TestCredentialProbe:
    """Tests for the credential probe script functions."""

    def test_overall_status_healthy(self, probe_module):
        """All-good checks produce exit code 0."""
        from adapters.ctrader.token_manager import TokenStatus
        checks = {
            "credentials_loaded": True,
            "token_status": TokenStatus.OK,
            "token_message": "ok",
            "days_remaining": 30.0,
            "token_hash": "abc123",
            "refresh_status": "ok_but_untested",
            "api_reachable": True,
            "api_message": "reachable",
        }
        code, summary = probe_module._overall_status(checks)
        assert code == 0
        assert summary == "healthy"

    def test_overall_status_credentials_not_loaded(self, probe_module):
        """Missing credentials produce exit code 2."""
        checks = {
            "credentials_loaded": False,
            "token_status": None,
            "token_message": "",
            "days_remaining": 0.0,
            "token_hash": None,
            "refresh_status": "missing",
            "api_reachable": True,
            "api_message": "",
        }
        code, summary = probe_module._overall_status(checks)
        assert code == 2
        assert summary == "credentials_not_loaded"

    def test_overall_status_placeholder_token(self, probe_module):
        """Placeholder token produces exit code 2."""
        from adapters.ctrader.token_manager import TokenStatus
        checks = {
            "credentials_loaded": True,
            "token_status": TokenStatus.PLACEHOLDER,
            "token_message": "placeholder",
            "days_remaining": 0.0,
            "token_hash": None,
            "refresh_status": "ok_but_untested",
            "api_reachable": True,
            "api_message": "",
        }
        code, summary = probe_module._overall_status(checks)
        assert code == 2
        assert "placeholder" in summary

    def test_overall_status_warning_near_expiry(self, probe_module):
        """Warning status (near expiry) produces exit code 1."""
        from adapters.ctrader.token_manager import TokenStatus
        checks = {
            "credentials_loaded": True,
            "token_status": TokenStatus.WARNING,
            "token_message": "expiring soon",
            "days_remaining": 2.0,
            "token_hash": "abc",
            "refresh_status": "ok_but_untested",
            "api_reachable": True,
            "api_message": "reachable",
        }
        code, summary = probe_module._overall_status(checks)
        assert code == 1
        assert "near_expiry" in summary

    def test_overall_status_api_unreachable(self, probe_module):
        """Unreachable API produces exit code 2."""
        from adapters.ctrader.token_manager import TokenStatus
        checks = {
            "credentials_loaded": True,
            "token_status": TokenStatus.OK,
            "token_message": "ok",
            "days_remaining": 30.0,
            "token_hash": "abc",
            "refresh_status": "ok_but_untested",
            "api_reachable": False,
            "api_message": "timeout",
        }
        code, summary = probe_module._overall_status(checks)
        assert code == 2
        assert "api_unreachable" in summary

    def test_overall_status_refresh_missing(self, probe_module):
        """Missing refresh token produces exit code 2."""
        from adapters.ctrader.token_manager import TokenStatus
        checks = {
            "credentials_loaded": True,
            "token_status": TokenStatus.OK,
            "token_message": "ok",
            "days_remaining": 30.0,
            "token_hash": "abc",
            "refresh_status": "missing_or_placeholder",
            "api_reachable": True,
            "api_message": "reachable",
        }
        code, summary = probe_module._overall_status(checks)
        assert code == 2
        assert "refresh" in summary

    def test_write_health_record(self, probe_module, tmp_path, monkeypatch):
        """Health record is written as JSONL."""
        output_file = tmp_path / "health.jsonl"
        monkeypatch.setattr(probe_module, "OUTPUT_PATH", output_file)

        record = {"timestamp": "2026-01-01T00:00:00Z", "exit_code": 0, "status": "healthy"}
        probe_module._write_health_record(record)

        assert output_file.exists()
        line = output_file.read_text().strip()
        parsed = json.loads(line)
        assert parsed["exit_code"] == 0
        assert parsed["status"] == "healthy"

    def test_write_health_record_appends(self, probe_module, tmp_path, monkeypatch):
        """Multiple records are appended as JSONL lines."""
        output_file = tmp_path / "health.jsonl"
        monkeypatch.setattr(probe_module, "OUTPUT_PATH", output_file)

        probe_module._write_health_record({"id": 1})
        probe_module._write_health_record({"id": 2})

        lines = output_file.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["id"] == 1
        assert json.loads(lines[1])["id"] == 2

    def test_api_reachable_returns_tuple(self, probe_module):
        """_api_reachable returns (bool, str) tuple."""
        # Use a bad host to force fast failure
        ok, msg = probe_module._api_reachable(url="https://127.0.0.1:1", timeout=1.0)
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
        assert ok is False  # Nothing listening on port 1


# ── Callback Linter Tests ───────────────────────────────────────────────────

class TestCallbackLinter:
    """Tests for the callback linter script functions."""

    def test_clean_code_no_issues(self, linter_module, tmp_path):
        """Code with correct callback names produces no issues."""
        source = textwrap.dedent("""
            class Adapter:
                def _handle_connected(self, client):
                    pass
                def _handle_disconnected(self, client):
                    pass
                def setup(self):
                    self._client.setConnectedCallback(self._handle_connected)
                    self._client.setDisconnectedCallback(self._handle_disconnected)
        """)
        issues = linter_module._collect_issues(tmp_path / "ok.py", source)
        assert issues == []

    def test_typo_set_connect_callback(self, linter_module, tmp_path):
        """setConnectCallback (missing 'ed') is detected as typo."""
        source = textwrap.dedent("""
            class Adapter:
                def setup(self):
                    self._client.setConnectCallback(self._handler)
        """)
        issues = linter_module._collect_issues(tmp_path / "bad.py", source)
        assert len(issues) >= 1
        assert issues[0]["type"] == "typo"
        assert "setConnectedCallback" in issues[0]["message"]

    def test_typo_set_disconnect_callback(self, linter_module, tmp_path):
        """setDisconnectCallback (missing 'ed') is detected as typo."""
        source = textwrap.dedent("""
            class Adapter:
                def setup(self):
                    self._client.setDisconnectCallback(self._handler)
        """)
        issues = linter_module._collect_issues(tmp_path / "bad.py", source)
        assert len(issues) >= 1
        assert issues[0]["type"] == "typo"

    def test_typo_message_recieved(self, linter_module, tmp_path):
        """setMessageRecievedCallback (spelling error) is detected."""
        source = textwrap.dedent("""
            class Adapter:
                def setup(self):
                    self._client.setMessageRecievedCallback(self._handler)
        """)
        issues = linter_module._collect_issues(tmp_path / "bad.py", source)
        assert len(issues) >= 1
        assert any("Recieved" in i["message"] or "Received" in i["message"] for i in issues)

    def test_undefined_callback_method_flagged(self, linter_module, tmp_path):
        """Callback referencing undefined self.method is flagged."""
        source = textwrap.dedent("""
            class Adapter:
                def setup(self):
                    self._client.setConnectedCallback(self.nonexistent_method)
        """)
        issues = linter_module._collect_issues(tmp_path / "bad.py", source)
        assert len(issues) >= 1
        assert any("undefined" in i["type"] or "not defined" in i["message"] for i in issues)

    def test_non_method_callback_flagged(self, linter_module, tmp_path):
        """Callback registered with non-self argument is flagged."""
        source = textwrap.dedent("""
            class Adapter:
                def setup(self):
                    self._client.setConnectedCallback(some_module_level_fn)
        """)
        issues = linter_module._collect_issues(tmp_path / "bad.py", source)
        assert len(issues) >= 1
        assert any("non-self" in i["message"] or "non_method" in i["type"] for i in issues)

    def test_syntax_error_handled(self, linter_module, tmp_path):
        """Syntax errors produce a syntax_error issue, not a crash."""
        source = "def broken(:\n"
        issues = linter_module._collect_issues(tmp_path / "broken.py", source)
        assert len(issues) == 1
        assert issues[0]["type"] == "syntax_error"

    def test_canonical_callbacks(self, linter_module):
        """CANONICAL_CALLBACKS contains the expected set."""
        assert "setConnectedCallback" in linter_module.CANONICAL_CALLBACKS
        assert "setDisconnectedCallback" in linter_module.CANONICAL_CALLBACKS

    def test_common_typos_dict(self, linter_module):
        """COMMON_TYPOS maps typo → correction."""
        assert "setConnectCallback" in linter_module.COMMON_TYPOS
        assert linter_module.COMMON_TYPOS["setConnectCallback"] == "setConnectedCallback"
        assert "setDisconnectCallback" in linter_module.COMMON_TYPOS
        assert linter_module.COMMON_TYPOS["setDisconnectCallback"] == "setDisconnectedCallback"

    def test_scan_directory_yields_python(self, linter_module, tmp_path):
        """_scan_directory yields .py files, skips __pycache__ and .venv."""
        (tmp_path / "good.py").write_text("x = 1\n")
        (tmp_path / "data.txt").write_text("not python\n")
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "cached.py").write_text("x = 1\n")

        results = list(linter_module._scan_directory(tmp_path))
        names = [p.name for p in results]
        assert "good.py" in names
        assert "cached.py" not in names
        assert "data.txt" not in names

    def test_scan_directory_single_file(self, linter_module, tmp_path):
        """_scan_directory works with a single file input."""
        f = tmp_path / "single.py"
        f.write_text("x = 1\n")
        results = list(linter_module._scan_directory(f))
        assert len(results) == 1
        assert results[0] == f
