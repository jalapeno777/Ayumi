"""Tests for the credential health probe and SDK callback-name linter.

Covers:
    - scripts/probe_ctrader_credentials.py  (credential probe)
    - .github/linters/check_sdk_callback_names.py  (AST linter)
"""

from __future__ import annotations

import importlib.util
import pathlib
import textwrap
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Load check_sdk_callback_names from its actual location (.github/linters/)
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location(
    "check_sdk_callback_names",
    pathlib.Path(__file__).resolve().parents[2]
    / ".github"
    / "linters"
    / "check_sdk_callback_names.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
find_callback_typos = _mod.find_callback_typos
lint_directory = _mod.lint_directory


# ===========================================================================
# Credential Probe Tests
# ===========================================================================


class TestGetCredentials:
    """Tests for probe_ctrader_credentials.get_credentials."""

    def test_reads_all_env_vars(self, monkeypatch):
        from probe_ctrader_credentials import get_credentials

        monkeypatch.setenv("CTRADER_OPENAPI_CLIENT_ID", "test_id")
        monkeypatch.setenv("CTRADER_OPENAPI_CLIENT_SECRET", "test_secret")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCESS_TOKEN", "test_token")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCOUNT_ID", "12345")

        creds = get_credentials()
        assert creds["CTRADER_OPENAPI_CLIENT_ID"] == "test_id"
        assert creds["CTRADER_OPENAPI_CLIENT_SECRET"] == "test_secret"
        assert creds["CTRADER_OPENAPI_ACCESS_TOKEN"] == "test_token"
        assert creds["CTRADER_OPENAPI_ACCOUNT_ID"] == "12345"

    def test_missing_env_returns_empty_string(self, monkeypatch):
        from probe_ctrader_credentials import get_credentials

        monkeypatch.delenv("CTRADER_OPENAPI_CLIENT_ID", raising=False)
        monkeypatch.setenv("CTRADER_OPENAPI_CLIENT_SECRET", "s")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCESS_TOKEN", "t")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCOUNT_ID", "1")

        creds = get_credentials()
        assert creds["CTRADER_OPENAPI_CLIENT_ID"] == ""

    def test_strips_whitespace(self, monkeypatch):
        from probe_ctrader_credentials import get_credentials

        monkeypatch.setenv("CTRADER_OPENAPI_CLIENT_ID", "  spaced_id  ")
        monkeypatch.setenv("CTRADER_OPENAPI_CLIENT_SECRET", "s")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCESS_TOKEN", "t")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCOUNT_ID", "1")

        creds = get_credentials()
        assert creds["CTRADER_OPENAPI_CLIENT_ID"] == "spaced_id"


class TestValidateCredentials:
    """Tests for probe_ctrader_credentials.validate_credentials."""

    def test_detects_missing_values(self):
        from probe_ctrader_credentials import validate_credentials

        creds = {
            "CTRADER_OPENAPI_CLIENT_ID": "abc",
            "CTRADER_OPENAPI_CLIENT_SECRET": "",
            "CTRADER_OPENAPI_ACCESS_TOKEN": "xyz",
            "CTRADER_OPENAPI_ACCOUNT_ID": "",
        }
        missing = validate_credentials(creds)
        assert "CTRADER_OPENAPI_CLIENT_SECRET" in missing
        assert "CTRADER_OPENAPI_ACCOUNT_ID" in missing
        assert "CTRADER_OPENAPI_CLIENT_ID" not in missing

    def test_all_present_returns_empty(self):
        from probe_ctrader_credentials import validate_credentials

        creds = {
            k: "value"
            for k in [
                "CTRADER_OPENAPI_CLIENT_ID",
                "CTRADER_OPENAPI_CLIENT_SECRET",
                "CTRADER_OPENAPI_ACCESS_TOKEN",
                "CTRADER_OPENAPI_ACCOUNT_ID",
            ]
        }
        assert validate_credentials(creds) == []


class TestRunProbe:
    """Tests for probe_ctrader_credentials.run_probe."""

    def test_reports_missing_creds(self, monkeypatch):
        from probe_ctrader_credentials import run_probe

        for key in [
            "CTRADER_OPENAPI_CLIENT_ID",
            "CTRADER_OPENAPI_CLIENT_SECRET",
            "CTRADER_OPENAPI_ACCESS_TOKEN",
            "CTRADER_OPENAPI_ACCOUNT_ID",
        ]:
            monkeypatch.delenv(key, raising=False)

        result = run_probe()
        assert result.success is False
        assert result.stage == "validation"
        assert "Missing" in result.message

    @patch("probe_ctrader_credentials.check_auth")
    def test_calls_check_auth_when_creds_present(self, mock_check, monkeypatch):
        from probe_ctrader_credentials import run_probe, ProbeResult

        monkeypatch.setenv("CTRADER_OPENAPI_CLIENT_ID", "id")
        monkeypatch.setenv("CTRADER_OPENAPI_CLIENT_SECRET", "secret")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCESS_TOKEN", "token")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCOUNT_ID", "42")

        mock_check.return_value = ProbeResult(
            success=True,
            stage="auth",
            message="OK",
            details={},
        )

        result = run_probe()
        assert result.success is True
        assert result.stage == "auth"
        mock_check.assert_called_once()

    @patch("probe_ctrader_credentials.check_auth")
    def test_propagates_auth_failure(self, mock_check, monkeypatch):
        from probe_ctrader_credentials import run_probe, ProbeResult

        monkeypatch.setenv("CTRADER_OPENAPI_CLIENT_ID", "id")
        monkeypatch.setenv("CTRADER_OPENAPI_CLIENT_SECRET", "secret")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCESS_TOKEN", "token")
        monkeypatch.setenv("CTRADER_OPENAPI_ACCOUNT_ID", "42")

        mock_check.return_value = ProbeResult(
            success=False,
            stage="auth",
            message="Bad creds",
            details={},
        )

        result = run_probe()
        assert result.success is False
        assert "Bad creds" in result.message


class TestProbeResult:
    """ProbeResult is a NamedTuple — verify structure."""

    def test_namedtuple_fields(self):
        from probe_ctrader_credentials import ProbeResult

        r = ProbeResult(success=True, stage="auth", message="ok", details={"a": 1})
        assert r.success is True
        assert r.stage == "auth"
        assert r.message == "ok"
        assert r.details == {"a": 1}


# ===========================================================================
# Callback Name Linter Tests
# ===========================================================================


class TestFindCallbackTypos:
    """Tests for check_sdk_callback_names.find_callback_typos."""

    def test_detects_setConnectCallback(self):

        source = "client.setConnectCallback(lambda x: None)\n"
        v = find_callback_typos(source, "test.py")
        assert len(v) == 1
        assert v[0]["typo"] == "setConnectCallback"
        assert v[0]["suggestion"] == "setConnectedCallback"

    def test_detects_setDisconnectCallback(self):

        source = "obj.setDisconnectCallback(handler)\n"
        v = find_callback_typos(source, "test.py")
        assert len(v) == 1
        assert v[0]["typo"] == "setDisconnectCallback"
        assert v[0]["suggestion"] == "setDisconnectedCallback"

    def test_correct_names_not_flagged(self):

        source = textwrap.dedent("""\
            client.setConnectedCallback(handler)
            client.setDisconnectedCallback(handler)
        """)
        assert find_callback_typos(source, "ok.py") == []

    def test_unrelated_code_not_flagged(self):

        source = textwrap.dedent("""\
            obj.set_callback(fn)
            obj.connect(host, port)
            result = setConnectCallback_variable
        """)
        assert find_callback_typos(source, "misc.py") == []

    def test_multiple_violations(self):

        source = textwrap.dedent("""\
            a.setConnectCallback(f1)
            b.setDisconnectCallback(f2)
            c.setConnectedCallback(f3)
            d.setDisconnectedCallback(f4)
        """)
        v = find_callback_typos(source, "multi.py")
        assert len(v) == 2
        typos = {x["typo"] for x in v}
        assert typos == {"setConnectCallback", "setDisconnectCallback"}

    def test_syntax_error_returns_empty(self):

        v = find_callback_typos("def broken(:\n", "bad.py")
        assert v == []

    def test_line_and_col_reported(self):

        source = "x = 1\nobj.setConnectCallback(fn)\n"
        v = find_callback_typos(source, "lined.py")
        assert len(v) == 1
        assert v[0]["line"] == 2
        assert v[0]["col"] == 0  # col_offset of the Call node starting at 'obj'


class TestLintDirectory:
    """Tests for check_sdk_callback_names.lint_directory."""

    def test_finds_violations_in_tree(self, tmp_path):

        (tmp_path / "bad.py").write_text("obj.setConnectCallback(fn)\n")
        (tmp_path / "good.py").write_text("obj.setConnectedCallback(fn)\n")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "nested.py").write_text("x.setDisconnectCallback(f)\n")

        v = lint_directory(tmp_path)
        assert len(v) == 2

    def test_empty_dir_returns_empty(self, tmp_path):

        assert lint_directory(tmp_path) == []

    def test_non_python_files_ignored(self, tmp_path):

        (tmp_path / "readme.txt").write_text("setConnectCallback\n")
        (tmp_path / "data.json").write_text('{"call": "setConnectCallback"}\n')
        assert lint_directory(tmp_path) == []
