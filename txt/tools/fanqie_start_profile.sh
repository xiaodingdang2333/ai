#!/usr/bin/env bash
set -euo pipefail

account="${1:-account-a}"
port="${2:-9223}"

case "$account" in
  account-a|account-b) ;;
  *)
    echo "Usage: $0 account-a|account-b [port]" >&2
    exit 2
    ;;
esac

root="/home/admin/ai/.fanqie-profiles/$account"
mkdir -p "$root"

exec chromium-browser \
  --headless=new \
  --disable-gpu \
  --no-sandbox \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$port" \
  --user-data-dir="$root" \
  "https://fanqienovel.com/writer/zone"
