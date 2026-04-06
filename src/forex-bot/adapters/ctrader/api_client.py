import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Callable, Dict
import logging

from .models import (
    cTraderCredentials,
    AccountInfo,
    Order,
    Position,
    TradeDirection,
    OrderType,
    OrderStatus,
)


logger = logging.getLogger(__name__)

SOH = "\x01"


class FIXMessage:
    """FIX 4.4 message builder based on Spotware official samples.

    Field separator on the wire is SOH (0x01).
    Header field order: 8, 9, 35, 49, 56, 57, 50, 34, 52, then body fields.
    """

    def __init__(self, msg_type: Optional[str] = None):
        self.fields: Dict[int, str] = {}
        self._body_fields: Dict[int, str] = {}
        self._body_field_list: list = []  # ordered (tag, value) for repeating groups
        if msg_type:
            self.fields[35] = msg_type

    def set_field(self, tag: int, value: str) -> "FIXMessage":
        self.fields[tag] = str(value)
        return self

    def set_body_field(self, tag: int, value: str) -> "FIXMessage":
        val = str(value)
        self._body_fields[tag] = val
        self._body_field_list.append((tag, val))
        return self

    def get_field(self, tag: int) -> Optional[str]:
        return self.fields.get(tag) or self._body_fields.get(tag)

    def to_wire(self) -> str:
        """Serialize to FIX wire format with proper header order and SOH separators."""
        now = datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S")

        # Body string (all body fields terminated by SOH, preserving order for repeating groups)
        body_parts = []
        for tag, value in self._body_field_list:
            body_parts.append(f"{int(tag)}={value}{SOH}")
        body_str = "".join(body_parts)

        # Message portion (header fields after tag-9, through body)
        # Order per Spotware: 35, 49, 56, 57, 50, 34, 52
        message_parts = [
            f"35={self.fields.get(35, '')}{SOH}",
            f"49={self.fields.get(49, '')}{SOH}",
            f"56={self.fields.get(56, '')}{SOH}",
            f"57={self.fields.get(57, '')}{SOH}",
            f"50={self.fields.get(50, '')}{SOH}",
            f"34={self.fields.get(34, '1')}{SOH}",
            f"52={self.fields.get(52, now)}{SOH}",
            body_str,
        ]
        message_str = "".join(message_parts)

        # BodyLength = byte count of message_str
        body_length = len(message_str.encode("ascii"))

        # Header: BeginString + BodyLength
        header_str = f"8=FIX.4.4{SOH}9={body_length}{SOH}"

        # Full message without checksum
        msg_without_checksum = header_str + message_str

        # Checksum over all bytes before tag-10
        checksum = sum(msg_without_checksum.encode("ascii")) % 256

        return f"{msg_without_checksum}10={checksum:03d}{SOH}"

    @classmethod
    def from_wire(cls, data: str) -> "FIXMessage":
        """Parse a raw FIX message string (SOH-delimited).

        Stores all fields in a flat dict (last value wins for repeated tags)
        AND preserves raw field list in _raw_fields for repeating group parsing.
        """
        msg = cls()
        msg._raw_fields = []  # list of (tag, value) tuples preserving order
        for field in data.split(SOH):
            if "=" in field:
                tag_str, value = field.split("=", 1)
                try:
                    tag = int(tag_str)
                    msg.fields[tag] = value
                    msg._raw_fields.append((tag, value))
                except ValueError:
                    pass
        return msg

    @property
    def msg_type(self) -> Optional[str]:
        return self.fields.get(35)


class FIXClient:
    """FIX 4.4 client for cTrader based on Spotware protocol spec.

    Connection modes:
        QUOTE (read-only): port 5211, SSL
        TRADE (live):       port 5202, plain text
    """

    PROTOCOL_VERSION = "FIX.4.4"

    MSG_TYPE_LOGON = "A"
    MSG_TYPE_LOGOUT = "5"
    MSG_TYPE_HEARTBEAT = "0"
    MSG_TYPE_TEST_REQUEST = "1"
    MSG_TYPE_REJECT = "3"
    MSG_TYPE_EXECUTION_REPORT = "8"
    MSG_TYPE_ORDER_CANCEL_REJECT = "9"
    MSG_TYPE_NEW_ORDER_SINGLE = "D"
    MSG_TYPE_ORDER_CANCEL_REQUEST = "F"
    MSG_TYPE_POSITION_REPORT = "AP"
    MSG_TYPE_ACCOUNT_INFO = "W"

    TAG_MSG_TYPE = 35
    TAG_SENDER_COMP_ID = 49
    TAG_TARGET_COMP_ID = 56
    TAG_SENDER_SUB_ID = 50
    TAG_TARGET_SUB_ID = 57
    TAG_USERNAME = 553
    TAG_PASSWORD = 554
    TAG_CLORD_ID = 11
    TAG_ORDER_ID = 37
    TAG_SYMBOL = 55
    TAG_SIDE = 54
    TAG_ORD_TYPE = 40
    TAG_ORD_QTY = 38
    TAG_PRICE = 44
    TAG_STOP_PX = 99
    TAG_EXEC_TYPE = 150
    TAG_ORD_STATUS = 39
    TAG_EXEC_ID = 17
    TAG_LAST_PX = 31
    TAG_LAST_QTY = 32
    TAG_AVG_PX = 6
    TAG_TEXT = 58
    TAG_BALANCE = 60
    TAG_EQUITY = 5523
    TAG_MARGIN_USED = 5524
    TAG_MARGIN_AVAILABLE = 5525
    TAG_PNL_UNREALIZED = 5526
    TAG_PNL_DAILY = 5527
    TAG_BID = 188
    TAG_ASK = 190
    TAG_LAST = 799
    TAG_TIMESTAMP = 52

    def __init__(self, credentials: cTraderCredentials):
        self.credentials = credentials
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._recv_thread: Optional[threading.Thread] = None
        self._next_outgoing_seq = 1
        self._heartbeat_interval = 30
        self._last_heartbeat_sent = 0.0
        self._last_heartbeat_received = 0.0
        self._callbacks: Dict[str, Callable] = {}
        self._pending_orders: Dict[str, Order] = {}
        self._positions: Dict[str, Position] = {}
        self._lock = threading.Lock()
        self._logged_in = False

    def connect(self) -> bool:
        try:
            host = self.credentials.host
            port = self.credentials.port

            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(10)

            if self.credentials.use_ssl:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                self._socket = ctx.wrap_socket(self._socket, server_hostname=host)

            self._socket.connect((host, port))
            self._socket.settimeout(None)  # blocking for recv loop

            self._running = True
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()

            if self._send_logon():
                logger.info(f"Connected to cTrader at {host}:{port}")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to connect to cTrader: {e}")
            return False

    def disconnect(self):
        self._running = False
        if self._logged_in:
            self._send_logout()
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
        logger.info("Disconnected from cTrader")

    def _recv_loop(self):
        buffer = b""
        sock = self._socket
        assert sock is not None
        sock.settimeout(3)
        while self._running:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                buffer += data
                buffer = self._process_buffer(buffer)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Receive error: {e}")
                break
        self._logged_in = False

    def _process_buffer(self, buffer: bytes) -> bytes:
        """Parse complete FIX messages from the receive buffer.

        Messages are terminated by tag 10 (checksum) followed by SOH.
        """
        text = buffer.decode("latin-1", errors="replace")
        while True:
            # Find end of message: 10=XXX\x01
            idx = text.find("10=")
            if idx == -1:
                break
            # Find the SOH after checksum
            end = text.find(SOH, idx + 4)
            if end == -1:
                break
            msg_str = text[: end + 1]
            text = text[end + 1 :]

            try:
                msg = FIXMessage.from_wire(msg_str)
                self._handle_message(msg)
            except Exception as e:
                logger.error(f"Error parsing message: {e}")
        return text.encode("latin-1")

    def _handle_message(self, msg: FIXMessage):
        msg_type = msg.msg_type

        with self._lock:
            if msg_type == self.MSG_TYPE_LOGON:
                self._logged_in = True
                logger.info("Logon successful")
                self._trigger_callback("on_logon", msg)

            elif msg_type == self.MSG_TYPE_LOGOUT:
                self._logged_in = False
                reason = msg.get_field(self.TAG_TEXT) or ""
                logger.info(f"Logged out: {reason}")
                self._trigger_callback("on_logout", msg)

            elif msg_type == self.MSG_TYPE_HEARTBEAT:
                self._last_heartbeat_received = time.time()
                self._trigger_callback("on_heartbeat", msg)

            elif msg_type == self.MSG_TYPE_TEST_REQUEST:
                self._send_heartbeat()

            elif msg_type == self.MSG_TYPE_EXECUTION_REPORT:
                self._handle_execution_report(msg)

            elif msg_type == self.MSG_TYPE_REJECT:
                self._handle_reject(msg)

            elif msg_type == self.MSG_TYPE_POSITION_REPORT:
                self._handle_position_report(msg)

            elif msg_type == self.MSG_TYPE_ACCOUNT_INFO:
                self._handle_account_info(msg)

        self._check_heartbeat()

    def _handle_execution_report(self, msg: FIXMessage):
        order_id = msg.get_field(self.TAG_CLORD_ID) or msg.get_field(self.TAG_ORDER_ID)
        exec_type = msg.get_field(self.TAG_EXEC_TYPE)

        with self._lock:
            if order_id in self._pending_orders:
                order = self._pending_orders[order_id]
                if exec_type == "0":
                    order.status = OrderStatus.FILLED
                    order.filled_at = datetime.now(timezone.utc)
                    order.filled_price = float(msg.get_field(self.TAG_LAST_PX) or 0)
                    self._trigger_callback("on_order_filled", order)
                elif exec_type == "4":
                    order.status = OrderStatus.CANCELLED
                    self._trigger_callback("on_order_cancelled", order)
                elif exec_type == "8":
                    order.status = OrderStatus.REJECTED
                    order.comment = msg.get_field(self.TAG_TEXT) or "Rejected"
                    self._trigger_callback("on_order_rejected", order)

    def _handle_reject(self, msg: FIXMessage):
        clord_id = msg.get_field(self.TAG_CLORD_ID)
        text = msg.get_field(self.TAG_TEXT)
        logger.warning(f"Order rejected: {clord_id} - {text}")

        with self._lock:
            if clord_id in self._pending_orders:
                order = self._pending_orders[clord_id]
                order.status = OrderStatus.REJECTED
                order.comment = text or "Rejected"
                self._trigger_callback("on_order_rejected", order)

    def _handle_position_report(self, msg: FIXMessage):
        logger.debug(f"Position report: {msg.fields}")

    def _handle_account_info(self, msg: FIXMessage):
        account_id = self.credentials.sender_comp_id
        balance = float(msg.get_field(self.TAG_BALANCE) or 0)
        equity = float(msg.get_field(self.TAG_EQUITY) or 0)
        margin_used = float(msg.get_field(self.TAG_MARGIN_USED) or 0)
        margin_available = float(msg.get_field(self.TAG_MARGIN_AVAILABLE) or 0)
        unrealized_pnl = float(msg.get_field(self.TAG_PNL_UNREALIZED) or 0)
        daily_pnl = float(msg.get_field(self.TAG_PNL_DAILY) or 0)

        info = AccountInfo(
            account_id=account_id,
            balance=balance,
            equity=equity,
            margin_used=margin_used,
            margin_available=margin_available,
            unrealized_pnl=unrealized_pnl,
            daily_pnl=daily_pnl,
            is_demo=True,
        )
        self._trigger_callback("on_account_update", info)

    def _send_logon(self) -> bool:
        msg = FIXMessage(msg_type=self.MSG_TYPE_LOGON)
        msg.set_field(self.TAG_SENDER_COMP_ID, self.credentials.sender_comp_id)
        msg.set_field(self.TAG_TARGET_COMP_ID, self.credentials.target_comp_id)
        msg.set_field(self.TAG_SENDER_SUB_ID, self.credentials.sender_sub_id)
        msg.set_field(self.TAG_TARGET_SUB_ID, self.credentials.sender_sub_id)
        msg.set_field(34, str(self._next_outgoing_seq))
        # Body fields
        msg.set_body_field(98, "0")  # EncryptMethod = NONE
        msg.set_body_field(108, str(self._heartbeat_interval))
        msg.set_body_field(141, "Y")  # ResetSeqNumFlag
        msg.set_body_field(self.TAG_USERNAME, self.credentials.username)
        msg.set_body_field(self.TAG_PASSWORD, self.credentials.password)

        wire = msg.to_wire()
        logger.info(f"Sending logon ({len(wire)} bytes)")
        return self._send_raw(wire)

    def _send_logout(self):
        msg = FIXMessage(msg_type=self.MSG_TYPE_LOGOUT)
        msg.set_field(self.TAG_SENDER_COMP_ID, self.credentials.sender_comp_id)
        msg.set_field(self.TAG_TARGET_COMP_ID, self.credentials.target_comp_id)
        msg.set_field(self.TAG_SENDER_SUB_ID, self.credentials.sender_sub_id)
        msg.set_field(self.TAG_TARGET_SUB_ID, self.credentials.sender_sub_id)
        msg.set_field(34, str(self._next_outgoing_seq))
        self._send_raw(msg.to_wire())

    def _send_heartbeat(self):
        msg = FIXMessage(msg_type=self.MSG_TYPE_HEARTBEAT)
        msg.set_field(self.TAG_SENDER_COMP_ID, self.credentials.sender_comp_id)
        msg.set_field(self.TAG_TARGET_COMP_ID, self.credentials.target_comp_id)
        msg.set_field(self.TAG_SENDER_SUB_ID, self.credentials.sender_sub_id)
        msg.set_field(self.TAG_TARGET_SUB_ID, self.credentials.sender_sub_id)
        msg.set_field(34, str(self._next_outgoing_seq))
        self._send_raw(msg.to_wire())

    def _send_message(self, msg: FIXMessage) -> bool:
        """Send a FIX message with automatic header/footer fields."""
        msg.set_field(self.TAG_SENDER_COMP_ID, self.credentials.sender_comp_id)
        msg.set_field(self.TAG_TARGET_COMP_ID, self.credentials.target_comp_id)
        msg.set_field(self.TAG_SENDER_SUB_ID, self.credentials.sender_sub_id)
        msg.set_field(self.TAG_TARGET_SUB_ID, self.credentials.sender_sub_id)
        msg.set_field(34, str(self._next_outgoing_seq))
        self._next_outgoing_seq += 1

        wire = msg.to_wire()
        return self._send_raw(wire)

    def _send_raw(self, wire: str) -> bool:
        """Send a raw FIX wire-format string."""
        try:
            if not self._socket:
                return False
            self._socket.send(wire.encode("ascii"))
            self._last_heartbeat_sent = time.time()
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    def _check_heartbeat(self):
        now = time.time()
        if now - self._last_heartbeat_sent > self._heartbeat_interval:
            self._send_heartbeat()
        if (
            self._last_heartbeat_received > 0
            and now - self._last_heartbeat_received > self._heartbeat_interval * 3
        ):
            logger.warning("Heartbeat timeout - connection may be lost")

    def send_order(
        self,
        symbol: str,
        direction: TradeDirection,
        order_type: OrderType,
        volume: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        comment: str = "",
    ) -> Optional[Order]:
        order_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{symbol}"
        order = Order(
            order_id=order_id,
            symbol=symbol,
            direction=direction,
            order_type=order_type,
            volume=volume,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment=comment,
        )

        with self._lock:
            self._pending_orders[order_id] = order

        msg = FIXMessage(msg_type=self.MSG_TYPE_NEW_ORDER_SINGLE)
        msg.set_field(self.TAG_CLORD_ID, order_id)
        msg.set_field(self.TAG_SYMBOL, symbol)
        msg.set_field(self.TAG_SIDE, "1" if direction == TradeDirection.LONG else "2")
        msg.set_field(self.TAG_ORD_QTY, str(volume))

        if order_type == OrderType.MARKET:
            msg.set_body_field(self.TAG_ORD_TYPE, "1")
        elif order_type == OrderType.LIMIT:
            msg.set_body_field(self.TAG_ORD_TYPE, "2")
            if price:
                msg.set_body_field(self.TAG_PRICE, str(price))
        elif order_type == OrderType.STOP:
            msg.set_body_field(self.TAG_ORD_TYPE, "3")
            if price:
                msg.set_body_field(self.TAG_STOP_PX, str(price))

        if stop_loss:
            msg.set_body_field(700, str(stop_loss))
        if take_profit:
            msg.set_body_field(701, str(take_profit))

        if comment:
            msg.set_body_field(self.TAG_TEXT, comment)

        if self._send_message(msg):
            logger.info(f"Order sent: {order_id} {direction.value} {volume} {symbol}")
            return order

        with self._lock:
            order.status = OrderStatus.REJECTED
            order.comment = "Failed to send"
        return order

    def cancel_order(self, order_id: str) -> bool:
        msg = FIXMessage(msg_type=self.MSG_TYPE_ORDER_CANCEL_REQUEST)
        msg.set_field(self.TAG_CLORD_ID, f"CANCEL_{order_id}")
        msg.set_body_field(41, order_id)
        return self._send_message(msg)

    def request_account_info(self):
        msg = FIXMessage(msg_type=self.MSG_TYPE_ACCOUNT_INFO)
        self._send_message(msg)

    def request_positions(self):
        msg = FIXMessage(msg_type=self.MSG_TYPE_POSITION_REPORT)
        self._send_message(msg)

    def register_callback(self, event: str, callback: Callable):
        self._callbacks[event] = callback

    def _trigger_callback(self, event: str, *args, **kwargs):
        if event in self._callbacks:
            try:
                self._callbacks[event](*args, **kwargs)
            except Exception as e:
                logger.error(f"Callback error for {event}: {e}")

    @property
    def is_connected(self) -> bool:
        return self._logged_in


class cTraderAPIClient:
    def __init__(self, credentials: Optional[cTraderCredentials] = None):
        self._credentials = credentials
        self._client: Optional[FIXClient] = None
        self._paper_mode = True
        self._callbacks: Dict[str, Callable] = {}

    def connect(self, credentials: Optional[cTraderCredentials] = None) -> bool:
        if credentials:
            self._credentials = credentials

        if not self._credentials:
            raise ValueError("cTrader credentials not provided")

        self._client = FIXClient(self._credentials)
        return self._client.connect()

    def disconnect(self):
        if self._client:
            self._client.disconnect()

    def set_paper_mode(self, paper_mode: bool):
        self._paper_mode = paper_mode
        logger.info(f"Paper mode {'enabled' if paper_mode else 'disabled'}")

    @property
    def is_paper_mode(self) -> bool:
        return self._paper_mode

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def register_callback(self, event: str, callback: Callable):
        self._callbacks[event] = callback

    def _trigger_callback(self, event: str, *args, **kwargs):
        if event in self._callbacks:
            try:
                self._callbacks[event](*args, **kwargs)
            except Exception as e:
                logger.error(f"Callback error for {event}: {e}")

    def send_order(self, **kwargs) -> Optional[Order]:
        if self._paper_mode:
            return self._send_paper_order(**kwargs)
        return self._client.send_order(**kwargs) if self._client else None

    def _send_paper_order(self, **kwargs) -> Order:
        order_id = f"PAPER_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        order = Order(
            order_id=order_id,
            symbol=kwargs.get("symbol", ""),
            direction=kwargs.get("direction", TradeDirection.LONG),
            order_type=kwargs.get("order_type", OrderType.MARKET),
            volume=kwargs.get("volume", 0.01),
            price=kwargs.get("price"),
            stop_loss=kwargs.get("stop_loss"),
            take_profit=kwargs.get("take_profit"),
            status=OrderStatus.FILLED,
            filled_at=datetime.now(timezone.utc),
            filled_price=kwargs.get("price") or 0,
            comment=f"[PAPER MODE] {kwargs.get('comment', '')}",
        )
        logger.info(
            f"[PAPER] Order would be sent: {order.direction.value} {order.volume} {order.symbol} @ {order.filled_price}"
        )
        return order
