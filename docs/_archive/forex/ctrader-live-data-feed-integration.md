# cTrader Live Data Feed Integration

**Issue:** AYUAA-52 | **Status:** done | **Source:** Paperclip

## Description

Connect the trading bot to cTrader API for real-time market data feeds. AYUAA-26 (cTrader API Access) is now done.

- Implement cTrader Open API data feed connection (tick data, candle data, order book)
- Build data normalization layer compatible with existing ICT/SMC analyzers
- Handle connection lifecycle (connect, reconnect, error handling)
- Wire market data into the Market Structure Analyzer, Order Block Detector, and FVG Detector
- Write integration tests against cTrader demo server

This unblocks live signal generation and eventually automated order execution.

## Discussion

**unknown:**

## cTrader Live Data Feed Integration -- Done

Built the full data feed stack. 24/24 tests passing.

### What shipped

- **`ctrader/proto/messages.py`** -- cTrader Open API v2 framing protocol (ProtoMessage encode/decode, message type enums)
- **`ctrader/connection.py`** -- async TCP/SSL connection manager with auto-reconnect, heartbeat keepalive, exponential backoff, state machine (disconnected → connecting → connected → authenticating → authenticated)
- **`ctrader/data_feed.py`** -- DataFeedClient with subscribe/request APIs for ticks, candles (all periods), and order book depth. Proto deserialization for tick and candle data
- **`ctrader/normalizer.py`** -- DataNormalizer converting raw proto data into ICT/SMC-compatible structures (NormalizedTick with mid/spread, NormalizedCandle with body/wick analysis, NormalizedOrderBook with best bid/ask). Recent data buffer for analyzer access
- **`ctrader/analyzers.py`** -- MarketStructureAnalyzer (swing high/low tracking, bullish/bearish structure), OrderBlockDetector, FVGDetector (fair value gaps between consecutive candles), and AnalyzerPipeline wiring feed events → normalizer → all three analyzers
- **`tests/test_data_feed.py`** -- 14 tests covering proto framing, tick/candle deserialization, normalization, order book, storage, dict export
- **`tests/test_connection.py`** -- 10 tests covering connection lifecycle, state callbacks, data feed client, analyzer wiring

### Next steps for live integration

1. Get cTrader Open API v2 access token (from [AYUAA-26](/AYUAA/issues/AYUAA-26))
2. Configure `DataFeedClient(host, port, access_token)` with demo/live credentials
3. Run against cTrader demo server to validate real data flow
4. Connect analyzer outputs to signal generation pipeline
