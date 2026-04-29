#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Ayumi Paper MVP Setup ==="
echo "Project dir: $PROJECT_DIR"

# Install systemd user service
mkdir -p ~/.config/systemd/user
cp "$PROJECT_DIR/deploy/ayumi-paper-mvp.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable ayumi-paper-mvp

# Create required directories
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/data"

# Set up logrotate
if [ -w /etc/logrotate.d ]; then
    sudo cp "$PROJECT_DIR/deploy/logrotate-ayumi" /etc/logrotate.d/ayumi
    echo "Logrotate config installed."
else
    echo "WARNING: Cannot write to /etc/logrotate.d — skip logrotate setup."
fi

echo
echo "Setup complete. Start with:"
echo "  systemctl --user start ayumi-paper-mvp"
echo
echo "Check status with:"
echo "  scripts/paper_status.sh"
echo "  systemctl --user status ayumi-paper-mvp"
