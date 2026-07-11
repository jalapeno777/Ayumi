# Dukascopy .bi5 Tick Data Harvest — Runbook

**Created:** 2026-07-11
**Status:** Ready to execute (waiting for Monday market open)
**Blocked by:** Dukascopy datafeed returns 503s on weekends when markets are closed

---

## Context (What We Built Last)

### Session History (Jul 10-11, 2026)
1. **Jul 10 evening** — Set up JForex SDK 3.6.51 harvester in Docker at `/home/TacoPants/projects/Ayumi/tools/dukascopy-harvester/`
   - Demo creds: `DEMO2JNDma` / `JNDma` (in `.env`)
   - Cloudflare 404 fixed with `-Dhttp.agent=Java Web Start/17.0` JVM flag
   - Rate bumped to 4 req/s per Craig's call
   - GBPUSD harvest ran successfully: 1,183 files covering Jan 2020 → Sep 3, 2025
   - DuckDB pipeline live: `ayumi_market.duckdb` (10.9 GB) with ticks + bar generation

2. **Jul 10 overnight** — JNLP URL (`jforex.jnlp`) started returning 404, blocking the SDK approach
   - Fresh sessions sometimes fix this (observed before)
   - JNLP URL confirmed still 404 as of Jul 11

3. **Jul 11** — Pivoted to `.bi5` datafeed approach
   - Research subagent found **tick-vault** library (PyPI, MIT, Oct 2025)
   - Security audit: ✅ SAFE (full report at `docs/research/tick-vault-security-audit-2026-07-11.md`)
   - Installed successfully in Ayumi venv
   - Smoke test confirmed: library constructs correct URLs, retry logic fires properly
   - **Blocker:** Dukascopy datafeed returns 503 on weekends — even single-worker requests time out
   - Earlier `curl` HEAD requests returned 200 with 0 bytes (empty responses), but actual GET requests for data content are rejected

### Why .bi5 Instead of JForex SDK?
- JForex SDK requires a working JNLP URL that keeps breaking
- The `.bi5` datafeed (`datafeed.dukascopy.com`) is a free, no-auth CDN
- tick-vault handles retries, rate limiting, resume, and concurrency nively
- The JForex SDK harvester already proved the data pipeline (DuckDB import, bar generation) works

---

## Current Data State

| Symbol   | CSV Files | Coverage                         | DuckDB Imported? |
|----------|-----------|----------------------------------|------------------|
| GBPUSD   | 1,183     | Jan 2020 → Sep 3, 2025 (gaps)    | Partial (1.3M ticks from Jun 2024 test) |
| EURUSD   | 7         | Jun 3-9, 2024 (test batch only)  | Partial (test)   |
| USDJPY   | 7         | Jun 3-9, 2024 (test batch only)  | Partial (test)   |
| XAUUSD   | 0         | Nothing yet                      | No               |

**DuckDB:** `/home/TacoPants/projects/Ayumi/data/ayumi_market.duckdb` — 10.9 GB

---

## Harvest Plan (Monday Jul 14, 2026)

### Symbols & Ranges
| Priority | Symbol   | Range                              | Est. Hours | Notes |
|----------|----------|------------------------------------|------------|-------|
| 1        | GBPUSD   | Sep 4, 2025 → Jul 11, 2026 (gap)   | ~1-2h      | Fill gap from existing harvest |
| 2        | EURUSD   | Jan 2020 → Jul 2026               | ~3-4h      | Full historical pull |
| 3        | XAUUSD   | Jan 2020 → Jul 2026               | ~3-4h      | Full historical pull |
| 4 (opt)  | USDJPY   | Jan 2020 → Jul 2026               | ~3-4h      | If we want it |

### Configuration
```
tick-vault settings:
  worker_per_proxy: 4        (4 req/s, under the 5 req/s per-IP limit)
  fetch_max_retry_attempts: 5
  fetch_base_retry_delay: 2.0
  fetch_timeout: 30.0
  base_directory: /home/TacoPants/projects/Ayumi/data/tick-vault
```

### Execution Steps

1. **Verify datafeed is live** (Monday morning):
   ```bash
   curl -s -o /tmp/test_bi5 "https://datafeed.dukascopy.com/datafeed/GBPUSD/2024/05/03/12h_ticks.bi5"
   ls -la /tmp/test_bi5  # Should be ~18KB, not 0
   ```

2. **Run harvest** (one symbol at a time):
   ```python
   source /home/TacoPants/projects/Ayumi/.venv/bin/activate
   python3 << 'EOF'
   import asyncio
   from datetime import datetime, UTC
   from tick_vault import download_range, reload_config

   reload_config(
       base_directory="/home/TacoPants/projects/Ayumi/data/tick-vault",
       worker_per_proxy=4,
       fetch_max_retry_attempts=5,
       fetch_base_retry_delay=2.0,
       fetch_timeout=30.0,
   )

   # GBPUSD gap fill first
   asyncio.run(download_range(
       symbol="GBPUSD",
       start=datetime(2025, 9, 4, tzinfo=UTC),
       end=datetime(2026, 7, 14, tzinfo=UTC),
   ))

   # Then EURUSD full
   asyncio.run(download_range(
       symbol="EURUSD",
       start=datetime(2020, 1, 1, tzinfo=UTC),
       end=datetime(2026, 7, 14, tzinfo=UTC),
   ))

   # Then XAUUSD full
   asyncio.run(download_range(
       symbol="XAUUSD",
       start=datetime(2020, 1, 1, tzinfo=UTC),
       end=datetime(2026, 7, 14, tzinfo=UTC),
   ))
   EOF
   ```

3. **Import to DuckDB** — After harvest completes, import the `.bi5` data into the DuckDB database. The existing JForex CSV import pipeline can be adapted, OR tick-vault's `read_tick_data()` can be used to stream into DuckDB.

4. **Verify data** — Check row counts, date ranges, price sanity checks per symbol.

### Resume Capability
tick-vault uses SQLite-backed metadata. If the harvest is interrupted, re-running `download_range()` with the same parameters will skip already-downloaded hours automatically. No manual resume logic needed.

---

## Key Files & Paths

| What | Path |
|------|------|
| tick-vault install | Ayumi venv (`/home/TacoPants/projects/Ayumi/.venv`) |
| JForex SDK harvester (old) | `/home/TacoPants/projects/Ayumi/tools/dukascopy-harvester/` |
| DuckDB database | `/home/TacoPants/projects/Ayumi/data/ayumi_market.duckdb` |
| Existing CSV output (SDK) | `/home/TacoPants/projects/Ayumi/tools/dukascopy-harvester/output/` |
| tick-vault output (new) | `/home/TacoPants/projects/Ayumi/data/tick-vault/` (to be created) |
| Research: bi5 approaches | `docs/research/bi5-datafeed-research-2026-07-11.md` |
| Research: API investigation | `docs/research/dukascopy-api-investigation-2026-07-08.md` |
| Security audit | `docs/research/tick-vault-security-audit-2026-07-11.md` |
| Python download script (old) | `data/forex/historical/download_dukascopy_m5.py` |

---

## .bi5 Format Reference

**URL pattern:** `https://datafeed.dukascopy.com/datafeed/{PAIR}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5`
- **MM is 0-indexed** (January = 00, December = 11)
- DD is 1-indexed, HH is 0-indexed (UTC)

**Binary format:** LZMA-compressed, big-endian 20-byte records:
```
4 bytes: milliseconds within hour (0-3,599,999)
4 bytes: ask price (uint, divide by price_scale)
4 bytes: bid price (uint, divide by price_scale)
4 bytes: ask volume (float32, in millions)
4 bytes: bid volume (float32, in millions)
```

**Price scales:**
| Pair    | Scale   |
|---------|---------|
| EURUSD  | 100,000 |
| GBPUSD  | 100,000 |
| USDJPY  | 1,000   |
| XAUUSD  | 1,000   |

**Empty files (0 bytes):** Markets closed (weekends, holidays). Normal — skip and advance.

---

## Gotchas

1. **Weekend throttle** — Datafeed returns 503s when markets are closed (Sat/Sun). Don't waste retries; wait for Monday.
2. **TLS 1.3 required** — Some CDN nodes hang on TLS 1.2. Python's default SSL context handles this.
3. **Connection: close** — CDN drops idle keep-alive connections after ~4-5 requests. tick-vault's httpx handles this.
4. **Rate limit persistence** — If you trigger 429/503 throttling, it persists for several minutes. Stay under 5 req/s.
5. **JNLP URL fragility** — The JForex SDK JNLP URL breaks periodically. The `.bi5` approach doesn't depend on it.
6. **Partial records** — Always truncate decompressed data to `len(raw) - (len(raw) % 20)` before iterating.
7. **Volume units** — Float32 volumes are in millions. Multiply by 1e6 for raw units.

---

## Alternative: Fix Existing Script

If tick-vault doesn't work out, the existing `download_dukascopy_m5.py` can be hardened using the 120-line code snippet in `docs/research/bi5-datafeed-research-2026-07-11.md` (§5). Key changes needed:
- Replace `requests` with `httpx` (async, HTTP/2)
- Add 3-tier exception taxonomy (RateLimitError, ForbiddenError, RetryableError)
- Token-bucket pacing for rate limiting
- TLS 1.3 minimum
- Connection: close header
