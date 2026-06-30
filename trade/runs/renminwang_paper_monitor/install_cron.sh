#!/usr/bin/env bash
set -euo pipefail

CRON_LINE="* 9-15 * * 1-5 /home/admin/ai/trade/runs/renminwang_paper_monitor/run_monitor.sh"
MARKER="# renminwang ntfy monitor"
TMP_FILE="$(mktemp)"

crontab -l 2>/dev/null | grep -vF "$MARKER" | grep -vF "/home/admin/ai/trade/runs/renminwang_paper_monitor/run_monitor.sh" > "$TMP_FILE" || true
{
  cat "$TMP_FILE"
  echo "$MARKER"
  echo "$CRON_LINE $MARKER"
} | crontab -
rm -f "$TMP_FILE"

echo "Installed cron:"
crontab -l | grep -F "/home/admin/ai/trade/runs/renminwang_paper_monitor/run_monitor.sh"
