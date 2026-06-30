#!/usr/bin/env bash
set -euo pipefail

export PATH="/root/.nvm/versions/node/v22.22.3/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export WORK_ROOT="${WORK_ROOT:-/home/admin/ai}"

ACCOUNT="account-b"
EXPECTED="桃枝醒醒"
PORT="9224"
BOOK_ID="7654806443446504510"
BOOK_NAME="快穿：她一出现，全世界都偏心了"
AI_USE="yes"

CACHE_SCRIPT="$WORK_ROOT/codex/skills/fanqie-write-upload/scripts/fanqie-account-cache.sh"
UPLOAD_SCRIPT="$WORK_ROOT/codex/skills/fanqie-upload/scripts/fanqie-upload.js"
LOG_DIR="$WORK_ROOT/output/fanqie-upload/pianxin-daily"
LOCK_FILE="$WORK_ROOT/output/fanqie-upload/pianxin-daily.lock"
ACCOUNT_LOCK_FILE="$WORK_ROOT/output/fanqie-upload/account-b-daily.lock"

mkdir -p "$LOG_DIR" "$WORK_ROOT/output/fanqie-upload"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

main() {
  local stamp log_file actual status
  stamp="$(date '+%Y%m%d-%H%M%S')"
  log_file="$LOG_DIR/${stamp}-${ACCOUNT}-${BOOK_NAME//\//_}.log"

  log "Starting Fanqie daily publish: ${EXPECTED} / ${BOOK_NAME}" | tee -a "$log_file"
  "$CACHE_SCRIPT" switch-start "$ACCOUNT" "$PORT" | tee -a "$log_file"
  sleep 8

  actual="$("$CACHE_SCRIPT" identify "$PORT" | tail -n 1)"
  log "Account identified: ${actual}" | tee -a "$log_file"
  if [[ "$actual" != "$EXPECTED" ]]; then
    log "ERROR account mismatch: expected=${EXPECTED} actual=${actual}" | tee -a "$log_file"
    "$CACHE_SCRIPT" stop || true
    exit 1
  fi

  set +e
  timeout 10m node "$UPLOAD_SCRIPT" publish-cdp \
    --root "$WORK_ROOT/txt" \
    --book "$BOOK_NAME" \
    --book-id "$BOOK_ID" \
    --port "$PORT" \
    --from 1 \
    --to 999 \
    --ai-use "$AI_USE" | tee -a "$log_file"
  status=${PIPESTATUS[0]}
  set -e

  "$CACHE_SCRIPT" save "$ACCOUNT" | tee -a "$log_file" || true
  "$CACHE_SCRIPT" stop || true
  log "Finished Fanqie daily publish: status=${status} log=${log_file}" | tee -a "$log_file"
  exit "$status"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "Another Pianxin Fanqie publish job is already running; exit."
  exit 0
fi

exec 8>"$ACCOUNT_LOCK_FILE"
if ! flock -n 8; then
  log "Another account-b Fanqie publish job is already running; exit."
  exit 0
fi

main
