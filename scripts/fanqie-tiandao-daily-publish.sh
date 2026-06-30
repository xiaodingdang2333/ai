#!/usr/bin/env bash
set -euo pipefail

export PATH="/root/.nvm/versions/node/v22.22.3/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export WORK_ROOT="${WORK_ROOT:-/home/admin/ai}"

BOOK="天道破产后，我在修真界开养老院"
BOOK_ID="7648515504381889560"
ACCOUNT="account-c"
EXPECTED_ACCOUNT="泡芙软呼呼"
PORT="${PORT:-9225}"
AI_USE="no"

ACCOUNT_SCRIPT="$WORK_ROOT/codex/skills/fanqie-write-upload/scripts/fanqie-account-cache.sh"
UPLOAD_SCRIPT="$WORK_ROOT/codex/skills/fanqie-upload/scripts/fanqie-upload.js"
DIRECT_PUBLISH_SCRIPT="$WORK_ROOT/scripts/fanqie-tiandao-publish-direct.js"
LIVE_PROFILE="/root/snap/chromium/common/fanqie-profiles/live/$ACCOUNT"
BACKUP_PROFILE="$WORK_ROOT/.fanqie-profiles/snap-backups/${ACCOUNT}-snap"
LOG_DIR="$WORK_ROOT/output/fanqie-upload/tiandao"
LOCK_FILE="$WORK_ROOT/output/fanqie-upload/tiandao.lock"
CHROME_LOG="$LOG_DIR/chrome.log"
CHROME_WRAPPER="$LOG_DIR/chrome-wrapper.log"
CHROMIUM="${CHROMIUM:-/snap/bin/chromium}"
SERVER_CHAN_SENDKEY="${SERVER_CHAN_SENDKEY:-}"
EMPTY_MARKER="$LOG_DIR/draft-empty-notified"

mkdir -p "$LOG_DIR" "$WORK_ROOT/output/fanqie-upload"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

notify() {
  local title="$1"
  local body="${2:-}"
  if [[ -z "${SERVER_CHAN_SENDKEY:-}" ]]; then
    log "WARN SERVER_CHAN_SENDKEY is empty; skip notification: $title"
    return 0
  fi
  curl -fsS \
    -X POST \
    -d "title=$title" \
    --data-urlencode "desp=$body" \
    "https://sctapi.ftqq.com/${SERVER_CHAN_SENDKEY}.send" >/dev/null || true
}

notify_empty_once() {
  if [[ -f "$EMPTY_MARKER" ]]; then
    log "Draft box is empty; empty notification was already sent."
    return 0
  fi
  notify "番茄草稿箱已空" "《${BOOK}》草稿箱已没有可发布章节。定时任务会继续每天 00:30 检查；补充草稿后会自动继续发布。"
  date '+%F %T' > "$EMPTY_MARKER"
  log "Draft box empty notification sent."
}

wait_for_port() {
  local deadline=$((SECONDS + 45))
  while (( SECONDS < deadline )); do
    if node -e "require('net').connect($PORT, '127.0.0.1').once('connect', function(){this.destroy(); process.exit(0)}).once('error', function(){process.exit(1)})" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

stop_chrome() {
  pkill -f "remote-debugging-port=$PORT" >/dev/null 2>&1 || true
  pkill -f "$LIVE_PROFILE" >/dev/null 2>&1 || true
  sleep 1
}

restore_profile() {
  if [[ ! -d "$BACKUP_PROFILE" ]]; then
    log "ERROR missing cache backup: $BACKUP_PROFILE"
    exit 3
  fi
  rm -rf "$LIVE_PROFILE"
  mkdir -p "$(dirname "$LIVE_PROFILE")"
  cp -a "$BACKUP_PROFILE" "$LIVE_PROFILE"
  rm -f "$LIVE_PROFILE"/Singleton*
}

start_chrome() {
  : > "$CHROME_LOG"
  : > "$CHROME_WRAPPER"
  /usr/bin/script -q -f -c "$CHROMIUM --headless=new --disable-gpu --no-sandbox --remote-debugging-address=127.0.0.1 --remote-debugging-port=$PORT --noerrdialogs --no-first-run --password-store=basic --user-data-dir=$LIVE_PROFILE --ozone-platform=headless --ozone-override-screen-size=1000,800 --use-angle=swiftshader-webgl https://fanqienovel.com/writer/zone > $CHROME_LOG 2>&1" "$CHROME_WRAPPER" &
  echo "$!"
}

main() {
  cd "$WORK_ROOT"
  log "Tiandao daily publish started"

  stop_chrome
  restore_profile
  start_chrome >/dev/null
  if ! wait_for_port; then
    log "ERROR Chrome CDP port $PORT did not become ready. See $CHROME_LOG and $CHROME_WRAPPER"
    exit 1
  fi

  local actual
  actual="$("$ACCOUNT_SCRIPT" identify "$PORT" | tail -n 1)"
  log "Identified account: $actual"
  if [[ "$actual" != "$EXPECTED_ACCOUNT" ]]; then
    log "ERROR account mismatch: expected $EXPECTED_ACCOUNT, got $actual"
    "$ACCOUNT_SCRIPT" save "$ACCOUNT" >/dev/null || true
    exit 1
  fi

  local publish_log="$LOG_DIR/publish-$(date '+%Y%m%d-%H%M%S').log"
  set +e
  timeout 8m node "$DIRECT_PUBLISH_SCRIPT" "$PORT" "$BOOK_ID" "$BOOK" "$AI_USE" | tee "$publish_log"
  local status=${PIPESTATUS[0]}
  set -e

  if (( status != 0 )); then
    log "ERROR publish command failed with status $status. See $publish_log"
    notify "番茄定时发布失败" "《${BOOK}》定时发布失败，退出码：${status}。请查看日志：${publish_log}"
    "$ACCOUNT_SCRIPT" save "$ACCOUNT" >/dev/null || true
    exit "$status"
  fi

  if grep -q '^DAILY_LIMIT ' "$publish_log"; then
    rm -f "$EMPTY_MARKER"
    log "Daily publish limit reached. Stopped as requested."
  elif grep -q '^PUBLISH ' "$publish_log"; then
    log "Published all currently matching drafts without hitting daily limit."
    notify_empty_once
  elif grep -q 'No matching drafts found' "$publish_log"; then
    log "No matching drafts found."
    notify_empty_once
  else
    log "Publish finished without a recognized terminal marker. See $publish_log"
  fi

  "$ACCOUNT_SCRIPT" save "$ACCOUNT" >/dev/null || true
  stop_chrome
  log "Tiandao daily publish finished"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "Another Tiandao publish job is already running; exit."
  exit 0
fi

trap 'log "ERROR interrupted at line $LINENO"; "$ACCOUNT_SCRIPT" save "$ACCOUNT" >/dev/null 2>&1 || true; stop_chrome' ERR
main >> "$LOG_DIR/daily-$(date '+%Y%m%d').log" 2>&1
