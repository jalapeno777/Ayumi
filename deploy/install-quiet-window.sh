#!/usr/bin/env bash
# install-quiet-window.sh — installer for the Ayumi NY-anchored quiet-window
# timer package (card 5c064a96, Craig-approved Option 2, 2026-08-20).
#
# Idempotent: re-running converges (copies + daemon-reload are repeat-safe).
# SAFETY: default mode is a DRY summary. Live install to /etc/systemd/system
# requires the explicit --apply flag and root. This build ships the package
# in the repo deploy/ tree ONLY — live activation is Ava/Craig-gated.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_TARGET_DIR="/etc/systemd/system"
UNITS=(
  ayumi-quiet-window-stop.service
  ayumi-quiet-window-stop.timer
  ayumi-quiet-window-start.service
  ayumi-quiet-window-start.timer
)
TARGET_SERVICE="ayumi.forward-test.service"

apply=0
[[ "${1:-}" == "--apply" ]] && apply=1

if [[ $apply -eq 0 ]]; then
  echo "DRY RUN (no changes made). Re-run with --apply as root to install."
fi

for unit in "${UNITS[@]}"; do
  src="$DEPLOY_DIR/$unit"
  if [[ ! -f "$src" ]]; then
    echo "MISSING: $src" >&2
    exit 1
  fi
  if [[ $apply -eq 1 ]]; then
    install -m 0644 "$src" "$UNIT_TARGET_DIR/$unit"   # idempotent copy
  else
    echo "would: install -m 0644 $src $UNIT_TARGET_DIR/$unit"
  fi
done

if [[ $apply -eq 1 ]]; then
  systemctl daemon-reload                              # idempotent
  echo "Installed units. NOT enabling timers automatically:"
  echo "  systemctl enable --now ayumi-quiet-window-stop.timer ayumi-quiet-window-start.timer"
  echo "Pre-deploy gates first: confirm '$TARGET_SERVICE' exists on the host."
else
  echo "Target service (pre-deploy confirmation gate): $TARGET_SERVICE"
fi
