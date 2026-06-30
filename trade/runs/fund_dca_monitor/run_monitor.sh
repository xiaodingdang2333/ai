#!/usr/bin/env bash
set -euo pipefail

cd /home/admin/ai/trade/runs/fund_dca_monitor

if [[ -f /home/admin/ai/trade/runs/renminwang_paper_monitor/ntfy.env ]]; then
  set -a
  source /home/admin/ai/trade/runs/renminwang_paper_monitor/ntfy.env
  set +a
elif [[ -f /home/admin/ai/trade/runs/ndxtmc_qdii_monitor/env ]]; then
  set -a
  source /home/admin/ai/trade/runs/ndxtmc_qdii_monitor/env
  set +a
fi

python3 ./monitor.py >> ./scheduler.log 2>&1
