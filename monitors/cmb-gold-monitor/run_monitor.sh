#!/usr/bin/env bash
set -euo pipefail

cd /home/admin/ai/monitors/cmb-gold-monitor
set -a
source ./env
set +a

flock -n ./monitor.lock python3 ./monitor.py >> ./scheduler.log 2>&1
