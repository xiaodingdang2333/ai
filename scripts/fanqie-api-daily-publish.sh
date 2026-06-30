#!/usr/bin/env bash
set -euo pipefail

export PATH="/root/.nvm/versions/node/v22.22.3/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export WORK_ROOT="${WORK_ROOT:-/home/admin/ai}"

LOG_DIR="$WORK_ROOT/output/fanqie-upload/api-daily"
LOCK_FILE="$WORK_ROOT/output/fanqie-upload/api-daily.lock"
PUBLISHER="$WORK_ROOT/scripts/fanqie-api-publish.js"

if [[ -z "${PUSHPLUS_TOKEN:-}" ]]; then
  for env_file in \
    "$WORK_ROOT/trade/runs/renminwang_paper_monitor/ntfy.env" \
    "$WORK_ROOT/trade/runs/ndxtmc_qdii_monitor/env" \
    "$WORK_ROOT/monitors/cmb-gold-monitor/env"
  do
    if [[ -f "$env_file" ]]; then
      # shellcheck disable=SC1090
      source "$env_file"
      [[ -n "${PUSHPLUS_TOKEN:-}" ]] && break
    fi
  done
fi
PUSHPLUS_TOKEN="${PUSHPLUS_TOKEN:-}"

mkdir -p "$LOG_DIR" "$WORK_ROOT/output/fanqie-upload"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

notify_pushplus() {
  local title="$1"
  local body="${2:-}"
  if [[ -n "${PUSHPLUS_TOKEN:-}" ]]; then
    curl -fsS \
      -X POST \
      -H 'Content-Type: application/json' \
      -d "$(node -e 'const [token,title,content]=process.argv.slice(1); console.log(JSON.stringify({token,title,content,template:"markdown"}))' "$PUSHPLUS_TOKEN" "$title" "$body")" \
      'https://www.pushplus.plus/send' >/dev/null && return 0
  fi
  log "WARN PushPlus notification not sent: missing token or request failed: $title"
  return 0
}

run_one() {
  local account="$1"
  local expected="$2"
  local book="$3"
  local book_id="$4"
  local ai_use="$5"
  local stamp log_file status

  stamp="$(date '+%Y%m%d-%H%M%S')"
  log_file="$LOG_DIR/${stamp}-${account}-${book//\//_}.log"
  log "Publish start: $expected / $book / ai_use=$ai_use"

  set +e
  node "$PUBLISHER" \
    --account "$account" \
    --expected-account "$expected" \
    --book "$book" \
    --book-id "$book_id" \
    --ai-use "$ai_use" | tee "$log_file"
  status=${PIPESTATUS[0]}
  set -e

  if (( status != 0 )); then
    log "ERROR publish failed: $book status=$status log=$log_file"
    notify_pushplus "番茄定时发布失败" "《${book}》发布失败，账号：${expected}，退出码：${status}。\n\n日志：\`${log_file}\`"
    return 0
  fi

  local summary_json remaining_words draft_total chapter_total published stop_text
  summary_json="$(grep '^SUMMARY ' "$log_file" | tail -n 1 | sed 's/^SUMMARY //')"
  if [[ -z "$summary_json" ]]; then
    log "ERROR no SUMMARY marker: $book log=$log_file"
    notify_pushplus "番茄定时发布异常" "《${book}》没有输出 SUMMARY，账号：${expected}。\n\n日志：\`${log_file}\`"
    return 0
  fi

  remaining_words="$(node -e 'const s=JSON.parse(process.argv[1]); console.log(s.remaining_platform_words)' "$summary_json")"
  draft_total="$(node -e 'const s=JSON.parse(process.argv[1]); console.log(s.final_draft_total)' "$summary_json")"
  chapter_total="$(node -e 'const s=JSON.parse(process.argv[1]); console.log(s.final_chapter_total)' "$summary_json")"
  published="$(node -e 'const s=JSON.parse(process.argv[1]); console.log((s.published||[]).join(","))' "$summary_json")"
  stop_text="$(node -e 'const s=JSON.parse(process.argv[1]); console.log(s.stop ? `${s.stop.type || ""} ${s.stop.no || ""} ${s.stop.message || ""}` : "")' "$summary_json")"

  log "Publish done: $book published=${published:-none} drafts=$draft_total chapters=$chapter_total remaining_words=$remaining_words stop=${stop_text:-none}"

  if (( draft_total == 0 )); then
    notify_pushplus "番茄草稿箱已发布完" "《${book}》草稿箱已经全部发布完。\n\n账号：${expected}\n草稿数：${draft_total}\n章节/审核列表：${chapter_total}\n本次发布：${published:-无}\n停止原因：${stop_text:-无}\n日志：\`${log_file}\`"
  fi
}

main() {
  cd "$WORK_ROOT"
  log "Fanqie API daily publish started"

  run_one "account-a" "西大水怪" "首辅绝嗣？我一胎三宝堵他满门" "7652965171274468376" "no"
  run_one "account-a" "西大水怪" "七零听声鉴宝：她靠收破烂掀翻全厂" "7652576394576137278" "no"
  run_one "account-b" "桃枝醒醒" "重生六岁，我带空间抢回军区大院" "7654615479075490878" "yes"
  run_one "account-b" "桃枝醒醒" "快穿：他们要我还债，我偏要讨债" "7652403779324611646" "yes"
  run_one "account-c" "泡芙软呼呼" "天道破产后，我在修真界开养老院" "7648515504381889560" "no"

  log "Fanqie API daily publish finished"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "Another Fanqie API daily publish job is already running; exit."
  exit 0
fi

main >> "$LOG_DIR/daily-$(date '+%Y%m%d').log" 2>&1
