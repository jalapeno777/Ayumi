# Dukascopy Tick Harvester

Headless tick data harvester using Dukascopy JForex SDK in Docker.

## Usage

```bash
# Build image
docker build -t duka-harvester .

# Small test: GBPUSD, 1 day
docker run --rm \
  --env-file .env \
  -v $(pwd)/output:/data/output \
  duka-harvester

# Multiple pairs, longer range
docker run --rm \
  --env-file .env \
  -e INSTRUMENTS=GBPUSD,USDJPY,EURUSD \
  -e START_DATE=2024-01-01 \
  -e END_DATE=2024-06-30 \
  -e BATCH_DAYS=1 \
  -e RATE_LIMIT_RPS=2.5 \
  -v $(pwd)/output:/data/output \
  duka-harvester
```

## Environment Variables

| Var | Default | Description |
|-----|---------|-------------|
| DUKA_USER | (required) | Dukascopy demo/live username |
| DUKA_PASS | (required) | Dukascopy demo/live password |
| DUKA_JNLP | `https://www.dukascopy.com/client/demo/jclient/jforex.jnlp` | JNLP URL |
| INSTRUMENTS | `GBPUSD,USDJPY,EURUSD` | Comma-separated forex pairs |
| START_DATE | `2024-01-01` | Harvest start (YYYY-MM-DD) |
| END_DATE | `2024-01-02` | Harvest end (exclusive) |
| RATE_LIMIT_RPS | `2.5` | Max requests per second |
| BATCH_DAYS | `1` | Days per fetch request |
| POST_CONNECT_SETTLE_MS | `5000` | Wait for data feed to prime after onConnect |
| GET_TICKS_TIMEOUT_SEC | `90` | Hard timeout per `IHistory.getTicks()` call |
| GET_TICKS_MAX_RETRIES | `3` | Retries if `getTicks()` returns null/empty |
| FEED_READY_TIMEOUT_SEC | `30` | Wait for live tick feed readiness before harvesting |
| FALLBACK_TO_BARS | `true` | If tick fetch fails permanently, write M1 bars instead |
| OUTPUT_DIR | `/data/output` | Where CSVs are written |

## Robustness

The SDK occasionally logs `DEBUG DCClientImpl - Unrecognized protocol message :
LastTickResponseMessage` while live ticks stream in. This is harmless — the data
IS being processed; the SDK just doesn't have a dedicated log path for those
live-stream messages and prints them at DEBUG. The harvester suppresses DEBUG
noise from `com.dukascopy.*` so the output stays readable.

If `IHistory.getTicks()` returns null/empty (live feed not primed yet) or hangs
(the SDK can wait indefinitely for a response the server never delivers), the
harvester:

1. Retries up to `GET_TICKS_MAX_RETRIES` times with exponential backoff.
2. Times each call out at `GET_TICKS_TIMEOUT_SEC`.
3. Falls back to `IHistory.getBars(Period.ONE_MIN)` for the same range if
   `FALLBACK_TO_BARS=true`, writing `*_M1.csv` next to the regular tick files.

## Output

CSV files per pair per day in `/data/output/`:
```
timestamp,instrument,bid,ask,bidVol,askVol
1717200000000,GBPUSD,1.27456,1.27468,1.50,1.20
```

Fallback files use a `_M1.csv` suffix and OHLCV columns:
```
timestamp,instrument,open,high,low,close,volume
1717200000000,GBPUSD,1.27456,1.27489,1.27440,1.27468,12.50
```

Exit codes: `0` = success (any ticks or bars written), `4` = no data harvested.
