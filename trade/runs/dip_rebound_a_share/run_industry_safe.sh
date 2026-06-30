#!/usr/bin/env bash
set -euo pipefail

cd /home/admin/ai/trade/runs/dip_rebound_a_share
mkdir -p logs results/industry

exec 9>/tmp/dip_rebound_industry.lock
if ! flock -n 9; then
  echo "industry backtest is already running"
  exit 1
fi

ulimit -v 900000
export PYTHONUNBUFFERED=1

exec timeout 30m nice -n 15 ionice -c2 -n7 \
  python3 industry_backtest.py \
  > logs/industry_backtest.log 2>&1
