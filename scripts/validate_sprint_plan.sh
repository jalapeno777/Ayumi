#!/usr/bin/env bash
# validate_sprint_plan.sh — phase-gated sprint plan validator
#
# Usage:
#     bash scripts/validate_sprint_plan.sh <sprint-id> phase3 [--doc <path>]
#     bash scripts/validate_sprint_plan.sh <sprint-id> phase3 --doc fixtures/sprint-with-untagged-date.md
#
# Exit codes:
#     0  — plan passes the phase gate
#     1  — plan has blocking issues (untagged dates, missing required fields, etc.)
#     2  — invocation error (missing args, missing --doc, unknown phase, etc.)
#
# Phase model:
#     phase1 — scope sanity (sprint id non-empty, doc exists)
#     phase2 — required sections (Acceptance Criteria, Verification Command,
#              Rollback) present in the doc
#     phase3 — deadline-owner contract (added by card 0b910897):
#              every date in the doc carries a CRAIG-OWNED or AGENT-OWNED tag.
#              Fails if any untagged dates are detected.
#
# Phases are cumulative: phase3 implies phase1 + phase2 passed. A request for
# phaseN runs phase1..phaseN in order; any failure short-circuits.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEADLINE_CHECK="${SCRIPT_DIR}/deadline_owner_check.py"

log() { printf '[validate_sprint_plan] %s\n' "$*" >&2; }
fail() { log "FAIL: $*"; exit 1; }
usage_err() { log "usage error: $*"; exit 2; }

usage() {
    cat >&2 <<'USAGE'
Usage:
    bash scripts/validate_sprint_plan.sh <sprint-id> <phase> [--doc <path>]

    <sprint-id>    identifier for the sprint being validated (informational)
    <phase>        phase1 | phase2 | phase3
    --doc <path>   path to the sprint/plan markdown (required for phase2+)

Examples:
    bash scripts/validate_sprint_plan.sh test-sprint phase3 --doc fixtures/sprint-with-untagged-date.md
    bash scripts/validate_sprint_plan.sh test-sprint phase3 --doc fixtures/sprint-with-tags.md
USAGE
}

# --- arg parsing ----------------------------------------------------------

[[ $# -ge 2 ]] || { usage; usage_err "missing arguments"; }

SPRINT_ID="$1"; shift
PHASE="$1"; shift

[[ "${PHASE}" =~ ^phase[123]$ ]] || usage_err "phase must be phase1|phase2|phase3 (got '${PHASE}')"

DOC_PATH=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --doc)
            [[ $# -ge 2 ]] || usage_err "--doc requires a path argument"
            DOC_PATH="$2"
            shift 2
            ;;
        -h|--help)
            usage; exit 0
            ;;
        *)
            usage_err "unknown argument: $1"
        ;;
    esac
done

# --- phase1: scope sanity -------------------------------------------------

run_phase1() {
    [[ -n "${SPRINT_ID// }" ]] || fail "sprint id is empty"
    log "phase1 OK — sprint id='${SPRINT_ID}'"
}

# --- phase2: required sections --------------------------------------------

run_phase2() {
    [[ -n "${DOC_PATH}" ]] || usage_err "--doc is required for phase2"
    [[ -f "${DOC_PATH}" ]] || fail "doc not found: ${DOC_PATH}"

    local missing=()
    local required=("Acceptance Criteria" "Verification Command" "Rollback")
    local doc_text
    doc_text="$(cat "${DOC_PATH}")"

    for section in "${required[@]}"; do
        if ! grep -qF "${section}" <<<"${doc_text}"; then
            missing+=("${section}")
        fi
    done

    if (( ${#missing[@]} > 0 )); then
        fail "phase2 missing required sections: ${missing[*]}"
    fi
    log "phase2 OK — required sections present in ${DOC_PATH}"
}

# --- phase3: deadline-owner contract (the new gate) -----------------------

run_phase3() {
    [[ -n "${DOC_PATH}" ]] || usage_err "--doc is required for phase3"
    [[ -f "${DOC_PATH}" ]] || fail "doc not found: ${DOC_PATH}"
    [[ -x "${DEADLINE_CHECK}" ]] || fail "deadline_owner_check.py missing or not executable: ${DEADLINE_CHECK}"

    # Run the scanner; capture JSON report. Non-zero exit means there are
    # untagged dates — that's the failure signal we propagate for phase3.
    local report
    report="$("${DEADLINE_CHECK}" --json --quiet "${DOC_PATH}" 2>/dev/null)"
    local exit_code=$?
    if [[ ${exit_code} -ne 0 ]]; then
        # Capture a human-readable breakdown on stderr before propagating.
        "${DEADLINE_CHECK}" --quiet "${DOC_PATH}" >/dev/null 2>&1 || true
        "${DEADLINE_CHECK}" "${DOC_PATH}" >/dev/null 2>"${DOC_PATH}.deadline-stderr" || true
        log "phase3 FAIL — untagged dates found in ${DOC_PATH}; see ${DOC_PATH}.deadline-stderr"
        return ${exit_code}
    fi

    log "phase3 OK — all dates in ${DOC_PATH} carry an owner tag"
    return 0
}

# --- dispatch -------------------------------------------------------------

case "${PHASE}" in
    phase1) run_phase1 ;;
    phase2) run_phase1 && run_phase2 ;;
    phase3) run_phase1 && run_phase2 && run_phase3 ;;
esac