#!/usr/bin/env bash
set -euo pipefail

WORK_ROOT="${WORK_ROOT:-/home/admin/ai}"
SNAP_PROFILE="${SNAP_PROFILE:-/root/snap/chromium/common/chromium}"
BACKUP_DIR="${BACKUP_DIR:-$WORK_ROOT/.fanqie-profiles/snap-backups}"
LIVE_DIR="${LIVE_DIR:-/root/snap/chromium/common/fanqie-profiles/live}"
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
    account-a|account-b|account-c) printf '%s\n' "$LIVE_DIR/$1" ;;
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
  local profile
  name="$(backup_name "$account")"
  profile="$(account_dir "$account")"
  mkdir -p "$BACKUP_DIR"
  rm -rf "$BACKUP_DIR/$name"
  if [[ -d "$profile" ]]; then
    cp -a "$profile" "$BACKUP_DIR/$name"
  elif [[ -d "$SNAP_PROFILE" ]]; then
    cp -a "$SNAP_PROFILE" "$BACKUP_DIR/$name"
  else
    mkdir -p "$BACKUP_DIR/$name"
  fi
  du -sh "$BACKUP_DIR/$name" >&2 || true
}

restore_cache() {
  local account="$1"
  local name
  local profile
  name="$(backup_name "$account")"
  profile="$(account_dir "$account")"
  if [[ ! -d "$BACKUP_DIR/$name" ]]; then
    echo "Missing cache backup: $BACKUP_DIR/$name" >&2
    exit 3
  fi
  rm -rf "$profile"
  mkdir -p "$(dirname "$profile")"
  cp -a "$BACKUP_DIR/$name" "$profile"
  rm -f "$profile"/Singleton*
}

start_chrome() {
  local account="$1"
  local port="$2"
  local profile
  profile="$(account_dir "$account")"
  mkdir -p "$profile"
  rm -f "$profile"/Singleton*
  mkdir -p "$WORK_ROOT/output/fanqie-upload"
  nohup "$CHROMIUM" \
    --headless=new \
    --disable-gpu \
    --disable-dev-shm-usage \
    --disable-extensions \
    --renderer-process-limit=1 \
    --disk-cache-size=33554432 \
    --js-flags=--max-old-space-size=192 \
    --no-sandbox \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port="$port" \
    --noerrdialogs \
    --no-first-run \
    --password-store=basic \
    --user-data-dir="$profile" \
    --ozone-platform=headless \
    --ozone-override-screen-size=1000,800 \
    --use-angle=swiftshader-webgl \
    'https://fanqienovel.com/writer/zone' \
    > "$WORK_ROOT/output/fanqie-upload/chrome-$account.log" 2>&1 7>&- 8>&- 9>&- &
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
    const deadline = Date.now() + 30000;
    let identity = 'UNKNOWN';
    while (Date.now() < deadline) {
      const result = await Runtime.evaluate({returnByValue: true, expression: `document.body.innerText.slice(0, 2500)`});
      const text = result.result.value || '';
      if (text.includes('请登录')) { identity = 'LOGIN_REQUIRED'; break; }
      const greeting = text.match(/(?:早上好|中午好|下午好|晚上好|深夜好)，([^\n]+)/);
      if (greeting) { identity = greeting[1]; break; }
      const known = ['西大水怪', '桃枝醒醒', '泡芙软呼呼'].filter(name => text.includes(name));
      if (known.length === 1) { identity = known[0]; break; }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    console.log(identity);
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
