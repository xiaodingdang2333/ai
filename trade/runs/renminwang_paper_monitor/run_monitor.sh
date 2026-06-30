#!/usr/bin/env bash
set -euo pipefail

cd /home/admin/ai/trade/runs/renminwang_paper_monitor
set -a
source ./ntfy.env
set +a

python3 ./monitor.py >> ./scheduler.log 2>&1
