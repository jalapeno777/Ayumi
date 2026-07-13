# Data Pipeline Runbook — Dukascopy Tick Data

> **Canonical source of truth for downloading, importing, and aggregating tick data.**
> The old CDN script (`download_dukascopy.py`) is DEPRECATED and deleted. Do not use it.
> Created: 2026-07-13

---

## Architecture

```
Dukascopy JForex SDK (Docker) → CSV files → import_ticks.py → DuckDB (ticks table) → aggregate_ticks_to_bars.py → DuckDB (bars table)
```

- **Harvester:** `tools/dukascopy-harvester/` — Java SDK in Docker, connects to Dukascopy demo account
- **Storage:** `data/ayumi_market.duckdb` (53GB) — ticks + bars + import_log tables
- **Import:** `scripts/import_ticks.py` — bulk CSV → DuckDB with dedup
- **Aggregation:** `scripts/aggregate_ticks_to_bars.py` — ticks → OHLCV bars

## Prerequisites

- Docker image `duka-harvester:latest` built (see `tools/dukascopy-harvester/Dockerfile`)
- Demo credentials in `tools/dukascopy-harvester/.env` (`DUKA_USER`, `DUKA_PASS`)
- JNLP URL: `https://www.dukascopy.com/client/demo/jclient/jforex.jnlp`

## Step 1: Harvest Tick Data

### Single symbol, single day (smoke test)

```bash
cd /home/TacoPants/projects/Ayumi/tools/dukascopy-harvester

docker run --rm \
  --env-file .env \
  -e INSTRUMENTS=GBPUSD \
  -e START_DATE=2024-06-03 \
  -e END_DATE=2024-06-04 \
  -e BATCH_DAYS=1 \
  -e RATE_LIMIT_RPS=2.5 \
  -e GET_TICKS_TIMEOUT_SEC=90 \
  -e GET_TICKS_MAX_RETRIES=3 \
  -e FALLBACK_TO_BARS=true \
  -v $(pwd)/output:/data/output \
  duka-harvester
```

### Production harvest (one symbol at a time, full range)

```bash
cd /home/TacoPants/projects/Ayumi/tools/dukascopy-harvester

docker run --rm \
  --env-file .env \
  -e INSTRUMENTS=USDJPY \
  -e START_DATE=2020-01-01 \
  -e END_DATE=2026-07-13 \
  -e BATCH_DAYS=1 \
  -e RATE_LIMIT_RPS=2.5 \
  -e GET_TICKS_TIMEOUT_SEC=90 \
  -e GET_TICKS_MAX_RETRIES=3 \
  -e FALLBACK_TO_BARS=true \
  -v $(pwd)/output:/data/output \
  duka-harvester
```

### Using the runner script (with retry + circuit breaker)

```bash
cd /home/TacoPants/projects/Ayumi/tools/dukascopy-harvester
nohup bash run_harvest.sh &
```

Edit `run_harvest.sh` to set `SYMBOLS`, `START_DATE`, `END_DATE` before running.

### JNLP URL Issues

The JNLP URL (`https://www.dukascopy.com/client/demo/jclient/jforex.jnlp`) is **intermittently 404**. This is a server-side issue — the URL works sometimes and 404s other times with no pattern.

**Self-healing tactics (already built into the harvester):**
1. `-Dhttp.agent=Java Web Start/17.0` JVM flag (baked into Dockerfile ENTRYPOINT) — fixes Cloudflare 404s caused by Java's default user-agent
2. Per-call `getTicks()` timeout (90s) with 3 retries
3. M1 bar fallback if tick fetch fails permanently (`FALLBACK_TO_BARS=true`)
4. Weekend skip (markets closed = no data)
5. Feed readiness polling before harvest
6. Runner-level exponential backoff (30s→480s) + 10-failure circuit breaker

**If JNLP is persistently 404:**
- Wait 5-10 minutes and retry — it comes back on its own
- Avoid running during market close/open transitions (21:00-22:00 UTC) and Saturdays
- The `run_harvest.sh` script handles this automatically with MAX_RETRIES=5

### Output Format

CSV files per pair per day in `output/`:
```
timestamp,instrument,bid,ask,bidVol,askVol
1717372800167,GBPUSD,1.27439,1.27448,0.90,0.90
```

Fallback files (when ticks unavailable) use `_M1.csv` suffix with OHLCV columns.

## Step 2: Import CSVs to DuckDB

```bash
cd /home/TacoPants/projects/Ayumi
source .venv/bin/activate

python3 scripts/import_ticks.py \
  --staging tools/dukascopy-harvester/output \
  --db-path data/ayumi_market.duckdb \
  --generate-bars \
  --timeframes M5,M15,H1,H4,D1
```

- Dedup-safe: `import_log` table tracks imported files
- Skips already-imported files automatically
- `--generate-bars` runs aggregation after import

## Step 3: Aggregate Ticks → Bars

If you need to re-aggregate without re-importing:

```bash
source .venv/bin/activate

# Aggregate all timeframes for a symbol
python3 scripts/aggregate_ticks_to_bars.py --symbol USDJPY

# Specific timeframes
python3 scripts/aggregate_ticks_to_bars.py --symbol USDJPY --timeframes M5,M15,H1,H4,D1

# Force re-aggregation (delete + rebuild)
python3 scripts/aggregate_ticks_to_bars.py --symbol USDJPY --force

# List what's already aggregated
python3 scripts/aggregate_ticks_to_bars.py --list
```

## Step 4: Validate Data

```bash
source .venv/bin/activate
python3 scripts/health_check_tick_pipeline.py

# Per-symbol QA
python3 scripts/qa_market_data.py --pair USDJPY
```

## DuckDB Schema

```sql
-- Ticks table (source of truth)
ticks: timestamp_ms BIGINT, symbol VARCHAR, bid DOUBLE, ask DOUBLE, bid_vol DOUBLE, ask_vol DOUBLE

-- Bars table (pre-materialized OHLCV)
bars: symbol VARCHAR, timeframe VARCHAR, timestamp_utc BIGINT, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, spread_pips DOUBLE

-- Import audit trail
import_log: filename VARCHAR (PK), symbol VARCHAR, row_count BIGINT, imported_at VARCHAR
```

## Background Harvest Plan

For long-running harvests (e.g., USDJPY 2020-2026 = ~79 months):

1. Use `run_harvest.sh` with `nohup` — it has retry logic, circuit breaker, and progress tracking
2. Run ONE symbol at a time to avoid rate limiting
3. Set `RATE_LIMIT_RPS=2.5` (under the 3 req/s ceiling)
4. Monitor progress: `tail -f tools/dukascopy-harvester/harvest_log.txt`
5. After harvest completes, run import_ticks.py to load into DuckDB
6. The harvester is resume-safe — re-running skips already-downloaded days

## Current Data State (2026-07-13)

| Symbol  | CSV Files | DuckDB Ticks | DuckDB Bars Coverage         |
|---------|-----------|-------------|------------------------------|
| EURUSD  | 1,080     | 112M        | M5/M15/H1 (2020-01 → 2026-07) |
| GBPUSD  | 1,374     | 117M        | M1-M30/H1/H4/D1 (2020-01 → 2026-07) |
| XAUUSD  | 801       | 199M        | M5/M15/H1 (2022-01 → 2026-07) |
| USDJPY  | 7 (test)  | 0           | ❌ NOT HARVESTED              |

## Price Scales

| Pair    | Scale   | Notes                        |
|---------|---------|------------------------------|
| EURUSD  | 100,000 | 5-digit quote                |
| GBPUSD  | 100,000 | 5-digit quote                |
| USDJPY  | 1,000   | 3-digit JPY pair             |
| XAUUSD  | 1,000   | 3-digit gold                 |
