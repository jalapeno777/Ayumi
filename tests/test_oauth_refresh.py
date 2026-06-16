"""Tests for OAuthRefreshManager — token refresh wrapper.

All network calls are mocked. No real HTTP requests are made.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "forex-bot"))

from adapters.ctrader.oauth_refresh import (
    OAuthRefreshManager,
    OAuthRefreshError,
    OAuthHttpError,
    NoRefreshTokenError,
    OAuthToken,
)


def _write_creds(path, *, access="access123", refresh="refresh456",
                 client_id="client_abc", client_secret="secret_xyz"):
    """Write a credentials JSON file."""
    with open(path, "w") as f:
        json.dump({
            "version": 1,
            "client_id": client_id,
            "client_secret": client_secret,
            "access_token": access,
            "refresh_token": refresh,
            "account_id": "acc_001",
        }, f)


class TestOAuthRefreshSuccess(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cred_path = os.path.join(self.tmpdir, "creds.json")
        _write_creds(self.cred_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("adapters.ctrader.oauth_refresh.requests.post")
    def test_refresh_with_valid_token(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "accessToken": "NEW_ACCESS_789",
            "refreshToken": "NEW_REFRESH_012",
            "expiresIn": 3600,
        }
        mock_post.return_value = mock_resp

        mgr = OAuthRefreshManager(self.cred_path)
        token = mgr.force_refresh()

        self.assertEqual(token.access_token, "NEW_ACCESS_789")
        self.assertEqual(token.refresh_token, "NEW_REFRESH_012")
        self.assertGreater(token.expires_at, time.time())

        # Verify credentials were written
        with open(self.cred_path) as f:
            data = json.load(f)
        self.assertEqual(data["access_token"], "NEW_ACCESS_789")
        self.assertEqual(data["refresh_token"], "NEW_REFRESH_012")
        self.assertIn("last_refreshed", data)


class TestOAuthNoRefreshToken(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cred_path = os.path.join(self.tmpdir, "creds.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_refresh_token_raises(self):
        with open(self.cred_path, "w") as f:
            json.dump({"version": 1, "access_token": "x", "refresh_token": ""}, f)

        mgr = OAuthRefreshManager(self.cred_path)
        with self.assertRaises(NoRefreshTokenError):
            mgr.force_refresh()


class TestOAuthAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cred_path = os.path.join(self.tmpdir, "creds.json")
        _write_creds(self.cred_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("adapters.ctrader.oauth_refresh.requests.post")
    def test_atomic_write_no_tmp_left_behind(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "accessToken": "new_a",
            "refreshToken": "new_r",
            "expiresIn": 3600,
        }
        mock_post.return_value = mock_resp

        mgr = OAuthRefreshManager(self.cred_path)
        mgr.force_refresh()

        # No .tmp file should remain
        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])


class TestOAuthExpiryBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cred_path = os.path.join(self.tmpdir, "creds.json")
        _write_creds(self.cred_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_expiry_buffer_triggers_early_refresh(self):
        mgr = OAuthRefreshManager(self.cred_path, expiry_buffer=300)

        # Manually set a cached token that's within the buffer
        token_near_expiry = OAuthToken(
            access_token="expiring",
            refresh_token="refresh456",
            expires_at=time.time() + 100,  # expires in 100s, buffer is 300s
        )
        mgr._cached_token = token_near_expiry

        self.assertTrue(mgr.needs_refresh())

    def test_no_refresh_when_token_fresh(self):
        mgr = OAuthRefreshManager(self.cred_path, expiry_buffer=300)

        token_fresh = OAuthToken(
            access_token="fresh",
            refresh_token="refresh456",
            expires_at=time.time() + 7200,  # 2h away
        )
        mgr._cached_token = token_fresh

        self.assertFalse(mgr.needs_refresh())


class TestOAuthErrorPaths(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cred_path = os.path.join(self.tmpdir, "creds.json")
        _write_creds(self.cred_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("adapters.ctrader.oauth_refresh.requests.post")
    def test_http_400_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "invalid_grant"
        mock_post.return_value = mock_resp

        mgr = OAuthRefreshManager(self.cred_path)
        with self.assertRaises(OAuthHttpError) as ctx:
            mgr.force_refresh()
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertFalse(ctx.exception.retry_hint)

    @patch("adapters.ctrader.oauth_refresh.requests.post")
    def test_http_500_raises_with_retry_hint(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "service unavailable"
        mock_post.return_value = mock_resp

        mgr = OAuthRefreshManager(self.cred_path)
        with self.assertRaises(OAuthHttpError) as ctx:
            mgr.force_refresh()
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertTrue(ctx.exception.retry_hint)


if __name__ == "__main__":
    unittest.main()
