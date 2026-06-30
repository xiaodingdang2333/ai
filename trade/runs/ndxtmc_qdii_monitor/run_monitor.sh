#!/usr/bin/env bash
set -euo pipefail

cd /home/admin/ai/trade/runs/ndxtmc_qdii_monitor
set -a
source ./env
set +a

python3 ./monitor.py >> ./scheduler.log 2>&1
