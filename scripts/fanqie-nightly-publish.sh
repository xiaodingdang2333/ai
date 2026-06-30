#!/usr/bin/env bash
set -euo pipefail

export PATH="/root/.nvm/versions/node/v22.22.3/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export WORK_ROOT="${WORK_ROOT:-/home/admin/ai}"
export CODEX_HOME="${CODEX_HOME:-/root/.codex}"

LOCK_FILE="$WORK_ROOT/output/fanqie-upload/nightly.lock"
LOG_DIR="$WORK_ROOT/output/fanqie-upload/nightly"
STATE_SCRIPT="$WORK_ROOT/scripts/fanqie-nightly-state.js"
NEXT_ALLOWED_FILE="$WORK_ROOT/output/fanqie-upload/nightly/next-allowed-epoch"
ACCOUNT_SCRIPT="$WORK_ROOT/codex/skills/fanqie-write-upload/scripts/fanqie-account-cache.sh"
UPLOAD_SCRIPT="$WORK_ROOT/codex/skills/fanqie-upload/scripts/fanqie-upload.js"
PUBLISH_THRESHOLD_CHARS="${PUBLISH_THRESHOLD_CHARS:-100000}"
SERVER_CHAN_SENDKEY="${SERVER_CHAN_SENDKEY:-}"

mkdir -p "$LOG_DIR" "$WORK_ROOT/output/fanqie-upload"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" >&2
}

notify() {
  local title="$1"
  local body="${2:-}"
  if [[ -z "${SERVER_CHAN_SENDKEY:-}" ]]; then
    log "WARN: SERVER_CHAN_SENDKEY is empty; skip notification: $title"
    return 0
  fi
  curl -fsS \
    -X POST \
    -d "title=$title" \
    --data-urlencode "desp=$body" \
    "https://sctapi.ftqq.com/${SERVER_CHAN_SENDKEY}.send" >/dev/null || true
}

on_error() {
  local line="$1"
  notify "番茄定时任务异常" "脚本在第 ${line} 行异常退出。请查看日志：$LOG_DIR/nightly-$(date '+%Y%m%d').log"
}

trap 'on_error $LINENO' ERR

check_next_allowed() {
  if [[ ! -f "$NEXT_ALLOWED_FILE" ]]; then
    return 0
  fi
  local next now
  next="$(cat "$NEXT_ALLOWED_FILE" 2>/dev/null || true)"
  now="$(date +%s)"
  if [[ "$next" =~ ^[0-9]+$ ]] && (( now < next )); then
    log "Next allowed run is $(date -d "@$next" '+%F %T'); skip."
    exit 0
  fi
  rm -f "$NEXT_ALLOWED_FILE"
}

delay_until_epoch() {
  local epoch="$1"
  local reason="$2"
  local at_time
  printf '%s\n' "$epoch" > "$NEXT_ALLOWED_FILE"
  at_time="$(date -d "@$epoch" '+%Y%m%d%H%M')"
  if command -v at >/dev/null 2>&1; then
    printf 'cd %q && %q\n' "$WORK_ROOT" "$WORK_ROOT/scripts/fanqie-nightly-publish.sh" | at -t "$at_time" >/dev/null 2>&1 || true
  fi
  notify "番茄定时任务已延后" "${reason}\n\n下次允许执行时间：$(date -d "@$epoch" '+%F %T')\n已尝试用 at 安排一次性补跑。"
}

handle_codex_quota_failure() {
  local log_file="$1"
  local book="$2"
  if rg -qi 'weekly|week|周额度|weekly limit|usage limit.*week' "$log_file"; then
    local reset_text reset_epoch
    reset_text="$(rg -io '([A-Z][a-z]{2,8}day|[A-Z][a-z]{2})[, ]+([A-Z][a-z]{2,8}|[0-9]{1,2})[ ,]+[0-9]{1,2}([, ][0-9]{4})?|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}' "$log_file" | head -n 1 || true)"
    if [[ -n "$reset_text" ]] && reset_epoch="$(date -d "$reset_text 01:00" +%s 2>/dev/null)"; then
      delay_until_epoch "$reset_epoch" "Codex 周额度不足，写《${book}》时停止。已按提示刷新日期调整到刷新日凌晨一点。"
    else
      reset_epoch="$(date -d 'next monday 01:00' +%s)"
      delay_until_epoch "$reset_epoch" "Codex 周额度不足，写《${book}》时停止；未能从提示中解析刷新日期，暂按下周一凌晨一点恢复。"
    fi
    return 0
  fi
  if rg -qi '5.?hour|five.?hour|五小时|rate limit|usage limit|quota|额度' "$log_file"; then
    delay_until_epoch "$(date -d '+5 hours' +%s)" "Codex 五小时额度不足，写《${book}》时停止。已延后 5 小时后再执行。"
    return 0
  fi
  notify "番茄定时任务需要处理" "写《${book}》时 Codex 执行失败，未能识别为五小时额度或周额度问题。请查看：${log_file}"
  return 1
}

book_id() {
  local book="$1"
  sed -n 's/^番茄作品ID：//p' "$WORK_ROOT/txt/$book/作品信息_番茄上传.md" | head -n 1
}

latest_no() {
  local book="$1"
  find "$WORK_ROOT/txt/$book/正文" -maxdepth 1 -type f -name '第*章_*.md' -printf '%f\n' \
    | sed -n 's/^第0*\([0-9][0-9]*\)章_.*/\1/p' \
    | sort -n | tail -n 1
}

run_publish() {
  local book="$1"
  local id="$2"
  local port="$3"
  local log_file="$4"
  local ai_use="$5"
  local limit="$6"
  local limit_args=()
  if [[ "$limit" =~ ^[0-9]+$ ]] && (( limit > 0 )); then
    limit_args=(--limit "$limit")
  fi
  node "$UPLOAD_SCRIPT" publish \
    --root "$WORK_ROOT/txt" \
    --book "$book" \
    --book-id "$id" \
    --port "$port" \
    --from 1 \
    --to 999 \
    --ai-use "$ai_use" \
    "${limit_args[@]}" | tee "$log_file"
}

published_total_chars() {
  local book="$1"
  node "$STATE_SCRIPT" get --work-root "$WORK_ROOT" --threshold "$PUBLISH_THRESHOLD_CHARS" --book "$book" \
    | node -pe 'JSON.parse(require("fs").readFileSync(0,"utf8")).totalPublishedChars || 0'
}

record_published_chapters() {
  local book="$1"
  local log_file="$2"
  local line no result crossed total
  while IFS= read -r line; do
    no="$(sed -n 's/^PUBLISH 第0*\([0-9][0-9]*\)章.*/\1/p' <<<"$line")"
    [[ -n "$no" ]] || continue
    result="$(node "$STATE_SCRIPT" record --work-root "$WORK_ROOT" --threshold "$PUBLISH_THRESHOLD_CHARS" --book "$book" --chapter "$no")"
    crossed="$(node -e 'const x=JSON.parse(process.argv[1]); console.log(x.crossed100k ? "yes" : "no")' "$result")"
    total="$(node -e 'const x=JSON.parse(process.argv[1]); console.log(x.totalPublishedChars || 0)' "$result")"
    if [[ "$crossed" == "yes" ]]; then
      notify "番茄小说已到 10 万字" "《${book}》已发布累计约 ${total} 字，达到番茄推荐门槛。后续定时任务将每天只发布 1 章。"
    fi
  done < <(rg '^PUBLISH ' "$log_file" || true)
}

process_book() {
  local account="$1"
  local account_name="$2"
  local port="$3"
  local book="$4"
  local expected="$5"
  local ai_use="$6"
  local id
  local stamp
  stamp="$(date '+%Y%m%d-%H%M%S')"
  id="$(book_id "$book")"
  if [[ -z "$id" ]]; then
    log "Missing 番茄作品ID for $book"
    notify "番茄定时任务缺少作品ID" "《${book}》缺少 番茄作品ID，无法自动发布。"
    return 1
  fi

  log "Switch to $account_name for $book; publish ai_use=$ai_use"
  "$ACCOUNT_SCRIPT" switch-start "$account" "$port" >/dev/null
  sleep 3
  local actual
  actual="$("$ACCOUNT_SCRIPT" identify "$port" | tail -n 1)"
  log "Identified account on $port: $actual"
  if [[ "$actual" != "$expected" ]]; then
    log "Account mismatch for $book: expected $expected, got $actual"
    notify "番茄账号不匹配" "《${book}》要求账号 ${expected}，但浏览器识别为 ${actual}。本书已停止发布。"
    "$ACCOUNT_SCRIPT" save "$account" >/dev/null || true
    return 1
  fi

  while true; do
    local publish_log="$LOG_DIR/${stamp}-${account}-${book//\//_}-publish.log"
    local total_chars publish_limit
    total_chars="$(published_total_chars "$book")"
    publish_limit=0
    if (( total_chars >= PUBLISH_THRESHOLD_CHARS )); then
      publish_limit=1
      log "$book has reached threshold ($total_chars chars); publish one chapter only."
    fi
    : > "$publish_log"
    run_publish "$book" "$id" "$port" "$publish_log" "$ai_use" "$publish_limit" || {
      log "Publish command failed for $book. See $publish_log"
      notify "番茄发布命令失败" "《${book}》发布命令失败。请查看：${publish_log}"
      break
    }
    record_published_chapters "$book" "$publish_log"

    if rg -q 'DAILY_LIMIT' "$publish_log"; then
      log "Daily publish limit reached for $book"
      break
    fi
    if rg -q 'PUBLISH ' "$publish_log"; then
      log "Published one or more drafts for $book; checking for more."
      continue
    fi
    if rg -q 'No matching drafts found' "$publish_log"; then
      log "No matching drafts found for $book; stop without auto-writing."
      notify "番茄草稿箱无可发布章节" "《${book}》没有匹配的草稿，定时任务已停止处理本书；不会自动续写或自动上传新章。"
      break
    fi
    log "No recognizable publish result for $book; stop this book."
    break
  done

  "$ACCOUNT_SCRIPT" save "$account" >/dev/null || true
}

main() {
  cd "$WORK_ROOT"
  check_next_allowed
  log "Nightly Fanqie publish started"
  process_book "account-a" "西大水怪" "9223" "坏运气寄存处" "西大水怪" "no"
  process_book "account-b" "桃枝醒醒" "9224" "她替死人开口后，满京城都慌了" "桃枝醒醒" "yes"
  "$ACCOUNT_SCRIPT" stop >/dev/null || true
  log "Nightly Fanqie publish finished"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "Another nightly Fanqie job is already running; exit."
  exit 0
fi

main >> "$LOG_DIR/nightly-$(date '+%Y%m%d').log" 2>&1
