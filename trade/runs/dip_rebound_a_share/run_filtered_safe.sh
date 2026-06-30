#!/usr/bin/env bash
set -euo pipefail

cd /home/admin/ai/trade/runs/dip_rebound_a_share
mkdir -p logs results/filtered

exec 9>/tmp/dip_rebound_filtered.lock
if ! flock -n 9; then
  echo "filtered backtest is already running"
  exit 1
fi

# Keep this small VPS responsive even if the Python process misbehaves.
ulimit -v 900000
export PYTHONUNBUFFERED=1

exec timeout 30m nice -n 15 ionice -c2 -n7 \
  python3 filtered_backtest.py \
  > logs/filtered_backtest.log 2>&1
