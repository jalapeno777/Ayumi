#!/usr/bin/env bash
###############################################################################
# run_overnight.sh — Overnight tick data harvest with per-year session resets
#
# Each year gets its own Docker container = fresh Dukascopy session.
# The SDK connection degrades after ~5 months of continuous use, so we
# spin up a new container per year.
#
# Order:
#   1. GBPUSD gap: 2025-04-09 → 2026-07-11
#   2. EURUSD full: 2020-01-01 → 2026-07-11
#   3. XAUUSD full: 2020-01-01 → 2026-07-11
#
# No DuckDB import — morning task.
#
# Usage:
#   nohup bash run_overnight.sh &
###############################################################################
set -euo pipefail
exec >> "$(dirname "${BASH_SOURCE[0]}")/overnight_log.txt" 2>&1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/output"
ENV_FILE="${SCRIPT_DIR}/.env"
DOCKER_IMAGE="duka-harvester:latest"
RATE_LIMIT_RPS="4"
BATCH_DAYS="1"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Generate year chunks: outputs "START END" per year on separate lines
year_chunks() {
    local start="$1" end="$2"
    local start_year="${start:0:4}" end_year="${end:0:4}"
    local year="$start_year"
    while [[ "$year" -le "$end_year" ]]; do
        if [[ "$year" == "$start_year" && "$year" == "$end_year" ]]; then
            echo "$start $end"
        elif [[ "$year" == "$start_year" ]]; then
            echo "$start ${year}-12-31"
        elif [[ "$year" == "$end_year" ]]; then
            echo "${year}-01-01 $end"
        else
            echo "${year}-01-01 ${year}-12-31"
        fi
        year=$((year + 1))
    done
}

run_year_chunk() {
    local symbol="$1" chunk_start="$2" chunk_end="$3"
    log "  --- ${symbol}: ${chunk_start} → ${chunk_end} ---"

    mkdir -p "$OUTPUT_DIR"

    docker run --rm \
        --env-file "$ENV_FILE" \
        -e "INSTRUMENTS=${symbol}" \
        -e "START_DATE=${chunk_start}" \
        -e "END_DATE=${chunk_end}" \
        -e "RATE_LIMIT_RPS=${RATE_LIMIT_RPS}" \
        -e "BATCH_DAYS=${BATCH_DAYS}" \
        -e "GET_TICKS_TIMEOUT_SEC=30" \
        -e "GET_TICKS_MAX_RETRIES=2" \
        -v "${OUTPUT_DIR}:/data/output" \
        "$DOCKER_IMAGE" 2>&1

    local rc=$?
    if [[ $rc -eq 0 ]]; then
        log "  ✅ ${symbol} ${chunk_start}→${chunk_end} OK"
    else
        log "  ⚠️  ${symbol} ${chunk_start}→${chunk_end} exited rc=$rc (some days may have timed out, continuing)"
    fi
    return 0  # always continue to next chunk
}

run_symbol() {
    local symbol="$1" start_date="$2" end_date="$3"
    local chunks
    chunks=$(year_chunks "$start_date" "$end_date")
    local total_chunks
    total_chunks=$(echo "$chunks" | wc -l)

    log ""
    log "============================================"
    log "  ${symbol}: ${start_date} → ${end_date}"
    log "  ${total_chunks} year-chunks"
    log "============================================"

    local idx=0
    while IFS=' ' read -r cs ce; do
        idx=$((idx + 1))
        log ""
        log ">>> ${symbol} chunk ${idx}/${total_chunks}: ${cs} → ${ce}"
        run_year_chunk "$symbol" "$cs" "$ce"
    done <<< "$chunks"
}

# ── Main ────────────────────────────────────────────────────────────────────
log "############################################################"
log "# OVERNIGHT HARVEST START — $(date)"
log "############################################################"

# Verify prerequisites
if [[ ! -f "$ENV_FILE" ]]; then
    log "❌ FATAL: $ENV_FILE not found"
    exit 1
fi
if ! docker image inspect "$DOCKER_IMAGE" >/dev/null 2>&1; then
    log "❌ FATAL: Docker image $DOCKER_IMAGE not found"
    exit 1
fi

# 1. GBPUSD gap
run_symbol "GBPUSD" "2025-04-09" "2026-07-11"

# 2. EURUSD full
run_symbol "EURUSD" "2020-01-01" "2026-07-11"

# 3. XAUUSD full
run_symbol "XAUUSD" "2020-01-01" "2026-07-11"

# Summary
log ""
log "############################################################"
log "# OVERNIGHT HARVEST COMPLETE — $(date)"
log "############################################################"

gbpusd_n=$(find "$OUTPUT_DIR" -name "GBPUSD_*.csv" ! -name "GBPUSD_*_M1.csv" | wc -l)
eurusd_n=$(find "$OUTPUT_DIR" -name "EURUSD_*.csv" ! -name "EURUSD_*_M1.csv" | wc -l)
xauusd_n=$(find "$OUTPUT_DIR" -name "XAUUSD_*.csv" ! -name "XAUUSD_*_M1.csv" | wc -l)
log "GBPUSD: $gbpusd_n files | EURUSD: $eurusd_n files | XAUUSD: $xauusd_n files"

cat > "${SCRIPT_DIR}/overnight_complete.flag" <<EOF
{
    "completed_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
    "gbpusd_files": $gbpusd_n,
    "eurusd_files": $eurusd_n,
    "xauusd_files": $xauusd_n
}
EOF

log "Done."
