#!/usr/bin/env bash
set -euo pipefail

WORK_ROOT="${WORK_ROOT:-/home/admin/ai}"
SNAP_PROFILE="${SNAP_PROFILE:-/root/snap/chromium/common/chromium}"
BACKUP_DIR="${BACKUP_DIR:-$WORK_ROOT/.fanqie-profiles/snap-backups}"
CHROMIUM="${CHROMIUM:-/snap/bin/chromium}"

usage() {
  cat <<'EOF'
Usage:
  fanqie-account-cache.sh stop
  fanqie-account-cache.sh save account-a|account-b|account-c
  fanqie-account-cache.sh restore account-a|account-b|account-c
  fanqie-account-cache.sh start account-a|account-b|account-c PORT
  fanqie-account-cache.sh switch-start account-a|account-b|account-c PORT
  fanqie-account-cache.sh identify PORT

Account map:
  account-a = 西大水怪
  account-b = 桃枝醒醒
  account-c = 泡芙软呼呼
EOF
}

backup_name() {
  case "${1:-}" in
    account-a) printf '%s\n' "account-a-snap" ;;
    account-b) printf '%s\n' "account-b-snap" ;;
    account-c) printf '%s\n' "account-c-snap" ;;
    *) echo "Unknown account: ${1:-}" >&2; exit 2 ;;
  esac
}

account_dir() {
  case "${1:-}" in
    account-a|account-b|account-c) printf '%s\n' "$SNAP_PROFILE" ;;
    *) echo "Unknown account: ${1:-}" >&2; exit 2 ;;
  esac
}

stop_chrome() {
  local pids
  pids="$(ps -ef | awk '/chromium|chromium-browser|chrome/ && !/awk/ {print $2}')"
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

save_cache() {
  local account="$1"
  local name
  name="$(backup_name "$account")"
  mkdir -p "$BACKUP_DIR"
  rm -rf "$BACKUP_DIR/$name"
  if [[ -d "$SNAP_PROFILE" ]]; then
    cp -a "$SNAP_PROFILE" "$BACKUP_DIR/$name"
  else
    mkdir -p "$BACKUP_DIR/$name"
  fi
  du -sh "$BACKUP_DIR/$name" >&2 || true
}

restore_cache() {
  local account="$1"
  local name
  name="$(backup_name "$account")"
  if [[ ! -d "$BACKUP_DIR/$name" ]]; then
    echo "Missing cache backup: $BACKUP_DIR/$name" >&2
    exit 3
  fi
  rm -rf "$SNAP_PROFILE"
  mkdir -p "$(dirname "$SNAP_PROFILE")"
  cp -a "$BACKUP_DIR/$name" "$SNAP_PROFILE"
}

start_chrome() {
  local account="$1"
  local port="$2"
  mkdir -p "$WORK_ROOT/output/fanqie-upload"
  nohup "$CHROMIUM" \
    --headless=new \
    --disable-gpu \
    --no-sandbox \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port="$port" \
    --noerrdialogs \
    --no-first-run \
    --password-store=basic \
    --ozone-platform=headless \
    --ozone-override-screen-size=1000,800 \
    --use-angle=swiftshader-webgl \
    'https://fanqienovel.com/writer/zone' \
    > "$WORK_ROOT/output/fanqie-upload/chrome-$account.log" 2>&1 &
  echo "$!"
}

identify() {
  local port="$1"
  cd "$WORK_ROOT"
  node - "$port" <<'NODE'
const CDP = require('chrome-remote-interface');
const port = Number(process.argv[2]);
(async () => {
  let c;
  try {
    c = await CDP({port});
    const {Page, Runtime} = c;
    await Page.enable();
    await Page.navigate({url: 'https://fanqienovel.com/writer/zone'});
    await new Promise(r => setTimeout(r, 5000));
    const r = await Runtime.evaluate({returnByValue: true, expression: `document.body.innerText.slice(0, 1500)`});
    const text = r.result.value || '';
    const m = text.match(/(?:早上好|中午好|下午好|晚上好|深夜好)，([^\n]+)/) || text.match(/消息通知\d*\n([^\n]+)\n/);
    console.log(m ? m[1] : (text.includes('请登录') ? 'LOGIN_REQUIRED' : 'UNKNOWN'));
  } finally {
    if (c) await c.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
NODE
}

cmd="${1:-}"
case "$cmd" in
  stop)
    stop_chrome
    ;;
  save)
    [[ $# -eq 2 ]] || { usage; exit 2; }
    stop_chrome
    save_cache "$2"
    ;;
  restore)
    [[ $# -eq 2 ]] || { usage; exit 2; }
    stop_chrome
    restore_cache "$2"
    ;;
  start)
    [[ $# -eq 3 ]] || { usage; exit 2; }
    start_chrome "$2" "$3"
    ;;
  switch-start)
    [[ $# -eq 3 ]] || { usage; exit 2; }
    stop_chrome
    restore_cache "$2"
    start_chrome "$2" "$3"
    ;;
  identify)
    [[ $# -eq 2 ]] || { usage; exit 2; }
    identify "$2"
    ;;
  *)
    usage
    exit 2
    ;;
esac
