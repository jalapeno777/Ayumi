#!/usr/bin/env bash
###############################################################################
# run_harvest.sh — Standalone Dukascopy tick data harvester
#
# Iterates through symbols (EURUSD, XAUUSD), runs the duka-harvester Docker
# container for each, then imports CSVs into DuckDB via import_ticks.py.
#
# Usage:
#   nohup bash run_harvest.sh &
#   screen -d -m bash run_harvest.sh &
#
# GBPUSD is excluded — it has a separate dedicated harvest running.
###############################################################################
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="/home/TacoPants/projects/Ayumi"
VENV_DIR="${PROJECT_DIR}/.venv"
OUTPUT_DIR="${SCRIPT_DIR}/output"
ENV_FILE="${SCRIPT_DIR}/.env"
LOG_FILE="${SCRIPT_DIR}/harvest_log.txt"
PROGRESS_FILE="${SCRIPT_DIR}/harvest_progress.json"
COMPLETE_FLAG="${SCRIPT_DIR}/harvest_complete.flag"

SYMBOLS=("USDJPY")
START_DATE="2020-01-01"
END_DATE="2026-07-13"
RATE_LIMIT_RPS="2.5"
BATCH_DAYS="1"
MAX_RETRIES=5          # Max retries per symbol (with exponential backoff)
CIRCUIT_BREAKER=10    # Consecutive failures across ALL symbols before full stop

DOCKER_IMAGE="duka-harvester:latest"

# ── Helpers ──────────────────────────────────────────────────────────────────
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

json_escape() {
    # Minimal JSON string escaping
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    echo "$s"
}

write_progress() {
    # write_progress <symbol> <status> <file_count> <disk_usage> <start_time> <end_time>
    local symbol="$1" status="$2" file_count="$3" disk_usage="$4"
    local start_time="$5" end_time="$6"

    # Read existing progress entries
    local existing="[]"
    if [[ -f "$PROGRESS_FILE" ]]; then
        existing="$(cat "$PROGRESS_FILE")"
    fi

    # Check if entry for this symbol already exists; replace if so
    existing="$(python3 -c "
import json, sys
try:
    data = json.loads('''$existing''')
except:
    data = []
# Remove existing entry for this symbol
data = [e for e in data if e.get('symbol') != '$symbol']
data.append({
    'symbol': '$symbol',
    'status': '$status',
    'file_count': $file_count,
    'disk_usage': '$(json_escape "$disk_usage")',
    'start_time': '$start_time',
    'end_time': '$end_time'
})
print(json.dumps(data, indent=2))
")"

    echo "$existing" > "$PROGRESS_FILE"
}

run_harvest_for_symbol() {
    local symbol="$1"
    local attempt=1
    local start_time end_time

    start_time="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    log "=== Harvesting $symbol (start: $start_time) ==="

    write_progress "$symbol" "running" 0 "0" "$start_time" ""

    while [[ $attempt -le $MAX_RETRIES ]]; do
        log "  Attempt $attempt/$MAX_RETRIES for $symbol"

        # Clean output dir before harvest to avoid mixing symbols' fresh files
        # (import_ticks dedup via import_log handles any stragglers)
        mkdir -p "$OUTPUT_DIR"

        # Run the Docker container
        set +e
        docker run --rm \
            --network host \
            --env-file "$ENV_FILE" \
            -e "INSTRUMENTS=${symbol}" \
            -e "START_DATE=${START_DATE}" \
            -e "END_DATE=${END_DATE}" \
            -e "RATE_LIMIT_RPS=${RATE_LIMIT_RPS}" \
            -e "BATCH_DAYS=${BATCH_DAYS}" \
            -v "${OUTPUT_DIR}:/data/output" \
            "$DOCKER_IMAGE" 2>&1 | tee -a "$LOG_FILE"
        local rc=${PIPESTATUS[0]}
        set -e

        if [[ $rc -eq 0 ]]; then
            log "  ✅ $symbol harvest container exited successfully"
            CONSECUTIVE_FAILURES=0
            break
        else
            log "  ⚠️  $symbol harvest container exited with code $rc (attempt $attempt/$MAX_RETRIES)"
            CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))

            # Circuit breaker — too many consecutive failures, stop everything
            if [[ $CONSECUTIVE_FAILURES -ge $CIRCUIT_BREAKER ]]; then
                log "🛑 CIRCUIT BREAKER: $CONSECUTIVE_FAILURES consecutive failures across symbols."
                log "🛑 Stopping harvest to avoid hammering the server. Check harvest_log.txt in the morning."
                end_time="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
                write_progress "$symbol" "circuit_breaker" 0 "0" "$start_time" "$end_time"
                return 99
            fi

            if [[ $attempt -lt $MAX_RETRIES ]]; then
                # Exponential backoff: 30s, 60s, 120s, 240s, 480s
                local delay=$((30 * (1 << (attempt - 1))))
                log "  Backing off ${delay}s before retry (consecutive failures: $CONSECUTIVE_FAILURES)..."
                sleep "$delay"
                attempt=$((attempt + 1))
            else
                end_time="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
                local file_count du_out
                file_count="$(find "$OUTPUT_DIR" -name "${symbol}_*.csv" ! -name "${symbol}_*_M1.csv" 2>/dev/null | wc -l)"
                du_out="$(du -sh "$OUTPUT_DIR" 2>/dev/null | cut -f1)"
                write_progress "$symbol" "failed" "$file_count" "$du_out" "$start_time" "$end_time"
                log "  ❌ $symbol FAILED after $MAX_RETRIES attempts, moving on"
                return 1
            fi
        fi
    done

    end_time="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    # Count output files and disk usage for progress
    local file_count du_out
    file_count="$(find "$OUTPUT_DIR" -name "${symbol}_*.csv" ! -name "${symbol}_*_M1.csv" 2>/dev/null | wc -l)"
    du_out="$(du -sh "$OUTPUT_DIR" 2>/dev/null | cut -f1)"
    write_progress "$symbol" "completed" "$file_count" "$du_out" "$start_time" "$end_time"
    log "  $symbol: $file_count CSV files, disk usage: $du_out"

    # ── Import into DuckDB ───────────────────────────────────────────────────
    log "  Importing $symbol CSVs into DuckDB..."
    set +e
    (
        cd "$PROJECT_DIR"
        source "${VENV_DIR}/bin/activate"
        python3 scripts/import_ticks.py \
            --staging "tools/dukascopy-harvester/output/" \
            --db-path "data/ayumi_market.duckdb" \
            --keep-csvs
    ) 2>&1 | tee -a "$LOG_FILE"
    local import_rc=${PIPESTATUS[0]}
    set -e

    if [[ $import_rc -ne 0 ]]; then
        log "  ⚠️  DuckDB import for $symbol exited with code $import_rc (non-fatal, continuing)"
    else
        log "  ✅ DuckDB import for $symbol completed"
    fi

    return 0
}

# ── Main ─────────────────────────────────────────────────────────────────────
main() {
    log "============================================================"
    log "Dukascopy Multi-Symbol Harvester — START"
    log "Symbols: ${SYMBOLS[*]}"
    log "Date range: ${START_DATE} → ${END_DATE}"
    log "Rate limit: ${RATE_LIMIT_RPS} req/s, batch: ${BATCH_DAYS} day(s)"
    log "============================================================"

    # Clear previous completion flag
    rm -f "$COMPLETE_FLAG"

    # Verify prerequisites
    if [[ ! -f "$ENV_FILE" ]]; then
        log "❌ FATAL: Env file not found at $ENV_FILE"
        exit 1
    fi
    if ! docker image inspect "$DOCKER_IMAGE" >/dev/null 2>&1; then
        log "❌ FATAL: Docker image $DOCKER_IMAGE not found"
        exit 1
    fi

    local total=${#SYMBOLS[@]}
    local success=0 failed=0
    CONSECUTIVE_FAILURES=0

    for i in "${!SYMBOLS[@]}"; do
        local symbol="${SYMBOLS[$i]}"
        local idx=$((i + 1))
        log ""
        log ">>> Symbol $idx/$total: $symbol"

        if run_harvest_for_symbol "$symbol"; then
            success=$((success + 1))
        else
            failed=$((failed + 1))
            # Circuit breaker tripped — stop the whole run
            if [[ $? -eq 99 ]]; then
                log "🛑 Halting entire harvest due to circuit breaker."
                break
            fi
        fi
    done

    # ── Completion ───────────────────────────────────────────────────────────
    local finish_time
    finish_time="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    log ""
    log "============================================================"
    log "Harvest complete — $success/$total symbols succeeded, $failed failed"
    log "Finish time: $finish_time"
    log "============================================================"

    # Write completion flag
    cat > "$COMPLETE_FLAG" <<EOF
{
    "completed_at": "$finish_time",
    "total_symbols": $total,
    "succeeded": $success,
    "failed": $failed,
    "symbols": $(cat "$PROGRESS_FILE" 2>/dev/null || echo "[]")
}
EOF

    log "Completion flag written to $COMPLETE_FLAG"
}

main "$@"
