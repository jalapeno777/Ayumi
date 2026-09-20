#!/usr/bin/env bash
# archive_stderr.sh — ExecStartPre helper for ayumi-forward-test.service (card 68d4b7fe)
#
# Archives the previous run's stderr into logs/stderr-archive/ before the new
# run starts, so pre-restart stderr is never lost (see
# docs/diagnoses/forward-test-restarts-2026-09-15.md).
#
# Design notes:
# - Uses cp (not mv): the systemd append: target keeps working unchanged and
#   existing logrotate rotations (.1.gz ...) are unaffected.
# - Best-effort: never fails service startup. Any error exits 0 silently.
# - Retention: keeps the newest $STDERR_ARCHIVE_KEEP archives (default 30).

set -uo pipefail

LOG_DIR="${1:-$AYUMI_ROOT/logs}"
STDERR_LOG="$LOG_DIR/forward_test-stderr.log"
ARCHIVE_DIR="$LOG_DIR/stderr-archive"
KEEP="${STDERR_ARCHIVE_KEEP:-30}"

if [[ ! -s "$STDERR_LOG" ]]; then
    exit 0
fi

mkdir -p "$ARCHIVE_DIR" || exit 0

ts=$(date -u +%Y%m%dT%H%M%SZ)
dest="$ARCHIVE_DIR/forward_test-stderr-$ts.log"
n=0
while [[ -e "$dest" ]]; do
    n=$((n + 1))
    dest="$ARCHIVE_DIR/forward_test-stderr-$ts-$n.log"
done

cp -- "$STDERR_LOG" "$dest" || exit 0

# Retention sweep: keep only the newest $KEEP archives.
ls -1t "$ARCHIVE_DIR"/forward_test-stderr-*.log 2>/dev/null \
    | tail -n +$((KEEP + 1)) \
    | xargs -r rm -f --

exit 0
