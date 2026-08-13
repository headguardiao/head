#!/usr/bin/env bash
# Run on the VPS (as a sudo-capable user) after copying the repo to
# /opt/forge-heatmap. Installs Python, creates a venv, installs deps,
# and registers/starts the systemd service.
set -euo pipefail

APP_DIR="/opt/forge-heatmap"
SERVICE_USER="forge"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    sudo useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip

sudo mkdir -p "$APP_DIR"
sudo rsync -a --delete --exclude ".git" --exclude ".venv" ./ "$APP_DIR/"
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

sudo cp "$APP_DIR/deploy/forge-heatmap.service" /etc/systemd/system/forge-heatmap.service
sudo systemctl daemon-reload
sudo systemctl enable forge-heatmap
sudo systemctl restart forge-heatmap

echo "Deployed. Check status with: sudo systemctl status forge-heatmap"
echo "Tail logs with: sudo journalctl -u forge-heatmap -f"
