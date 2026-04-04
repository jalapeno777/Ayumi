from __future__ import annotations

import logging
import os
import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

FIX_BEGIN_STRING = "FIX.4.4"
SOH = "\x01"

_REQUIRED_ENV_VARS = [
    "CTRADER_HOST",
    "CTRADER_SSL_PORT",
    "CTRADER_ACCOUNT",
    "CTRADER_PASSWORD",
    "CTRADER_SENDER_COMP_ID",
    "CTRADER_TARGET_COMP_ID",
    "CTRADER_SENDER_SUB_ID",
]

OPTIONAL_ENV_VARS = [
    "CTRADER_PLAIN_PORT",
    "CTRADER_QUOTE_SENDER_SUB_ID",
]


class MissingCredentialError(RuntimeError):
    pass


class FIXConnectionError(RuntimeError):
    pass


def _find_dotenv() -> Path | None:
    explicit = os.environ.get("DOTENV_PATH")
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None

    project_root = Path(__file__).parents[3]
    candidates = [
        project_root / ".env",
        project_root.parent / ".env",
        Path.cwd() / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_credentials() -> dict[str, str]:
    env_path = _find_dotenv()
    if env_path is not None:
        load_dotenv(env_path)

    missing = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        raise MissingCredentialError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    creds = {v: os.environ[v] for v in _REQUIRED_ENV_VARS}
    for v in OPTIONAL_ENV_VARS:
        val = os.environ.get(v)
        if val is not None:
            creds[v] = val
    return creds


def _checksum(body: str) -> str:
    total = sum(ord(c) for c in body)
    return f"{total % 256:03d}"


def _build_fix_message(tags: dict[int, str], msg_seq_num: int) -> str:
    pairs = [f"{k}={v}" for k, v in tags.items()]
    body_str = SOH.join(pairs) + SOH

    header_fields: list[str] = []
    header_fields.append(f"8={FIX_BEGIN_STRING}{SOH}")
    header_fields.append(f"9={len(body_str)}{SOH}")
    header_fields.append(body_str)

    full_body = "".join(header_fields)
    chk = _checksum(full_body)

    return full_body + f"10={chk}{SOH}"


class CTraderConnection:
    def __init__(
        self,
        credentials: Optional[dict[str, str]] = None,
        heartbeat_interval: int = 30,
    ):
        self._creds = credentials or _load_credentials()
        self._heartbeat_interval = heartbeat_interval
        self._msg_seq_num = 1
        self._socket: Optional[ssl.SSLSocket] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _get_sending_time(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S.%f")[:-3]

    def _build_logon_message(self) -> str:
        tags = {
            35: "A",
            49: self._creds["CTRADER_SENDER_COMP_ID"],
            56: self._creds["CTRADER_TARGET_COMP_ID"],
            34: str(self._msg_seq_num),
            52: self._get_sending_time(),
            50: self._creds["CTRADER_SENDER_SUB_ID"],
            57: self._creds.get("CTRADER_QUOTE_SENDER_SUB_ID", ""),
            98: "0",
            108: str(self._heartbeat_interval),
            553: self._creds["CTRADER_ACCOUNT"],
            554: self._creds["CTRADER_PASSWORD"],
        }
        return _build_fix_message(tags, self._msg_seq_num)

    def _build_market_data_request(self, symbol: str) -> str:
        self._msg_seq_num += 1
        tags = {
            35: "V",
            49: self._creds["CTRADER_SENDER_COMP_ID"],
            56: self._creds["CTRADER_TARGET_COMP_ID"],
            34: str(self._msg_seq_num),
            52: self._get_sending_time(),
            262: f"MD-{symbol}",
            263: "1",
            264: "0",
            265: "0",
            267: 1,
            269: "1",
            146: symbol,
        }
        return _build_fix_message(tags, self._msg_seq_num)

    def _build_logout_message(self) -> str:
        self._msg_seq_num += 1
        tags = {
            35: "5",
            49: self._creds["CTRADER_SENDER_COMP_ID"],
            56: self._creds["CTRADER_TARGET_COMP_ID"],
            34: str(self._msg_seq_num),
            52: self._get_sending_time(),
        }
        return _build_fix_message(tags, self._msg_seq_num)

    def _recv_message(self) -> str:
        if self._socket is None:
            raise FIXConnectionError("Not connected")
        data = b""
        while True:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise FIXConnectionError("Connection closed by server")
            data += chunk
            text = data.decode("ascii")
            if text.endswith(SOH):
                return text

    def _parse_msg_type(self, raw: str) -> str:
        for field in raw.split(SOH):
            if field.startswith("35="):
                return field[3:]
        return ""

    def connect(self) -> None:
        host = self._creds["CTRADER_HOST"]
        port = int(self._creds["CTRADER_SSL_PORT"])

        logger.info("Connecting to cTrader FIX at %s:%s", host, port)

        raw_socket = socket.create_connection((host, port), timeout=10)
        context = ssl.create_default_context()
        self._socket = context.wrap_socket(raw_socket, server_hostname=host)
        self._connected = True

        logon_msg = self._build_logon_message()
        logger.info("Sending FIX Logon")
        self._socket.sendall(logon_msg.encode("ascii"))

        response = self._recv_message()
        msg_type = self._parse_msg_type(response)

        if msg_type != "A":
            self._connected = False
            self._socket.close()
            self._socket = None
            raise FIXConnectionError(
                f"Expected Logon response (MsgType=A), got MsgType={msg_type}"
            )

        logger.info("FIX Logon confirmed")

    def disconnect(self) -> None:
        if self._socket is not None and self._connected:
            try:
                logout_msg = self._build_logout_message()
                self._socket.sendall(logout_msg.encode("ascii"))
            except OSError:
                pass
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = None
        self._connected = False
        logger.info("Disconnected from cTrader FIX")

    def send_market_data_request(self, symbol: str) -> str:
        if not self._connected or self._socket is None:
            raise FIXConnectionError("Not connected — call connect() first")
        msg = self._build_market_data_request(symbol)
        self._socket.sendall(msg.encode("ascii"))
        logger.info("Sent Market Data Request for %s", symbol)
        return msg
