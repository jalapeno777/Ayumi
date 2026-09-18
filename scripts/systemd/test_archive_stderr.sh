#!/usr/bin/env bash
# test_archive_stderr.sh — targeted test for scripts/systemd/archive_stderr.sh (card 68d4b7fe)
# Covers: (1) non-empty stderr is archived with content intact,
#         (2) empty/missing stderr produces no archive,
#         (3) retention cap removes oldest archives,
#         (4) >5 same-timestamp collisions never overwrite.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_SCRIPT="$SCRIPT_DIR/archive_stderr.sh"

failures=0
check() { # check <label> <condition-result>
    if [[ "$2" -eq 0 ]]; then echo "PASS: $1"; else echo "FAIL: $1"; failures=$((failures + 1)); fi
}

# --- Case 1: non-empty stderr is archived, content intact ---
T1=$(mktemp -d)
printf 'old-run stderr line A\nold-run stderr line B\n' > "$T1/forward_test-stderr.log"
STDERR_ARCHIVE_KEEP=30 bash "$ARCHIVE_SCRIPT" "$T1"
n=$(find "$T1/stderr-archive" -name 'forward_test-stderr-*.log' 2>/dev/null | wc -l)
[[ "$n" -eq 1 ]]; check "non-empty stderr archived exactly once" $?
arch=$(find "$T1/stderr-archive" -name 'forward_test-stderr-*.log' | head -1)
grep -q 'old-run stderr line A' "$arch"; check "archived content intact (line A)" $?
grep -q 'old-run stderr line B' "$arch"; check "archived content intact (line B)" $?
cmp -s "$arch" "$T1/forward_test-stderr.log"; check "source log preserved (cp, not mv)" $?

# --- Case 2: empty stderr -> no archive, exit 0 ---
T2=$(mktemp -d)
: > "$T2/forward_test-stderr.log"
bash "$ARCHIVE_SCRIPT" "$T2"; rc=$?
[[ $rc -eq 0 ]]; check "empty stderr exits 0" $?
[[ ! -d "$T2/stderr-archive" || -z $(ls -A "$T2/stderr-archive" 2>/dev/null) ]]; check "empty stderr creates no archive" $?

# --- Case 2b: missing log dir entirely -> exit 0 (best-effort) ---
T2b=$(mktemp -d)
bash "$ARCHIVE_SCRIPT" "$T2b/nope"; rc=$?
[[ $rc -eq 0 ]]; check "missing stderr file exits 0" $?

# --- Case 3: retention cap keeps newest N (deterministic mtimes via touch -d) ---
T3=$(mktemp -d)
mkdir -p "$T3/stderr-archive"
base=1000000000
for i in 1 2 3 4 5; do
    f="$T3/stderr-archive/forward_test-stderr-20260918T00000$i.log"
    printf 'archive %s\n' "$i" > "$f"
    touch -d "@$((base + i))" "$f"
done
printf 'current run stderr\n' > "$T3/forward_test-stderr.log"
STDERR_ARCHIVE_KEEP=3 bash "$ARCHIVE_SCRIPT" "$T3"
n=$(find "$T3/stderr-archive" -name 'forward_test-stderr-*.log' | wc -l)
[[ "$n" -eq 3 ]]; check "retention keeps exactly 3 archives (new + 2 newest)" $?
[[ ! -e "$T3/stderr-archive/forward_test-stderr-20260918T000001.log" ]]; check "oldest archive pruned" $?
grep -q 'archive 5' "$T3/stderr-archive/forward_test-stderr-20260918T000005.log"; check "newest fake archive retained" $?
newarch=$(grep -l 'current run stderr' "$T3"/stderr-archive/forward_test-stderr-*.log | head -1)
[[ -n "$newarch" ]]; check "current run archived into retention set" $?

# --- Case 4: >5 same-timestamp collisions never overwrite (Rin r1 MEDIUM fix) ---
T4=$(mktemp -d)
mkdir -p "$T4/stderr-archive"
ts=20260918T235959Z
# Deterministic clock: PATH-shim 'date' returns the fixed ts so collisions are guaranteed.
mkdir -p "$T4/bin"
printf '#!/usr/bin/env bash\necho "%s"\n' "$ts" > "$T4/bin/date"
chmod +x "$T4/bin/date"
for sfx in "" -1 -2 -3 -4 -5; do
    printf 'pre %s\n' "${sfx:-base}" > "$T4/stderr-archive/forward_test-stderr-$ts$sfx.log"
done
printf 'seventh run\n' > "$T4/forward_test-stderr.log"
PATH="$T4/bin:$PATH" bash "$ARCHIVE_SCRIPT" "$T4"
[[ -e "$T4/stderr-archive/forward_test-stderr-$ts-6.log" ]]; check "7th same-second collision archived as suffix -6" $?
grep -q 'seventh run' "$T4/stderr-archive/forward_test-stderr-$ts-6.log"; check "7th collision content intact" $?
all7=$(ls -1 "$T4/stderr-archive"/forward_test-stderr-*.log | wc -l)
[[ "$all7" -eq 7 ]]; check "no archive overwritten (7 files present)" $?

rm -rf "$T1" "$T2" "$T2b" "$T3" "$T4"
if [[ $failures -eq 0 ]]; then echo "ALL PASS"; exit 0; else echo "$failures FAILURES"; exit 1; fi
