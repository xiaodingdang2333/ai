#!/usr/bin/env bash
set -euo pipefail

# Own the single browser-sized slice of this low-memory host while an account
# operation is in progress.  ChatGPT and Fanqie use incompatible profiles and
# must never run concurrently here.

WORK_ROOT="${WORK_ROOT:-/home/admin/ai}"
LIVE_DIR="${LIVE_DIR:-/root/snap/chromium/common/fanqie-profiles/live}"
BACKUP_DIR="${BACKUP_DIR:-$WORK_ROOT/.fanqie-profiles/snap-backups}"
LEASE_FILE="${FANQIE_BROWSER_LEASE_FILE:-/run/lock/fanqie-browser-account.lock}"
CHATGPT_UNIT="chatgpt-web-browser.service"
LEASE_STARTED=0
LEASE_ACCOUNT=""
LEASE_CHATGPT_WAS_ACTIVE=0

usage() {
  echo "Usage: fanqie-browser-lease.sh run account-a|account-b|account-c PORT COMMAND [ARGS...]" >&2
}

backup_name() {
  case "$1" in
    account-a) echo account-a-snap ;;
    account-b) echo account-b-snap ;;
    account-c) echo account-c-snap ;;
    *) echo "Unknown account: $1" >&2; exit 2 ;;
  esac
}

profile_pids() {
  ps -eo pid=,args= | awk '/(chromium|chromium-browser|chrome)/ && /fanqie-profiles\/live\// {print $1}'
}

stop_fanqie() {
  systemctl stop fanqie-account-lease.service 2>/dev/null || true
  local pids
  pids="$(profile_pids)"
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
    sleep 2
  fi
}

save_profile() {
  local account="$1" profile="$LIVE_DIR/$1" backup="$BACKUP_DIR/$(backup_name "$1")"
  [[ -d "$profile" ]] || return 0
  mkdir -p "$BACKUP_DIR"
  rm -rf "$backup"
  cp -a "$profile" "$backup"
}

restore_profile() {
  local account="$1" profile="$LIVE_DIR/$1" backup="$BACKUP_DIR/$(backup_name "$1")"
  [[ -d "$backup" ]] || { echo "Missing Fanqie profile backup for $account" >&2; exit 3; }
  rm -rf "$profile"
  mkdir -p "$(dirname "$profile")"
  cp -a "$backup" "$profile"
  rm -f "$profile"/SingletonLock "$profile"/SingletonCookie "$profile"/SingletonSocket
}

wait_cdp() {
  local port="$1" i
  for i in $(seq 1 40); do
    if curl -fsS --max-time 2 "http://127.0.0.1:$port/json/version" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

ensure_browser_runtime() {
  # After a reboot there may be no interactive root session yet. Snap
  # Chromium cannot create /run/user/0 from inside confinement, and no browser
  # can render until the shared Xvfb display exists.
  systemctl start user-runtime-dir@0.service 2>/dev/null || true
  install -d -m 700 -o root -g root /run/user/0 /run/user/0/snap.chromium
  systemctl start xvfb-99.service
  local i
  for i in $(seq 1 20); do
    [[ -S /tmp/.X11-unix/X99 ]] && return 0
    sleep 1
  done
  echo "Xvfb display :99 did not become ready" >&2
  return 1
}

main() {
  [[ "${1:-}" == run && $# -ge 5 ]] || { usage; exit 2; }
  local account="$2" port="$3"
  shift 3
  LEASE_ACCOUNT="$account"
  LEASE_STARTED=0
  LEASE_CHATGPT_WAS_ACTIVE=0
  mkdir -p "$(dirname "$LEASE_FILE")"
  exec 9>"$LEASE_FILE"
  flock -w 300 9

  if systemctl is-active --quiet "$CHATGPT_UNIT"; then
    LEASE_CHATGPT_WAS_ACTIVE=1
    systemctl stop "$CHATGPT_UNIT"
  fi

  cleanup() {
    local rc=$?
    if [[ "$LEASE_STARTED" -eq 1 ]]; then
      stop_fanqie
      save_profile "$LEASE_ACCOUNT" || true
    fi
    if [[ "$LEASE_CHATGPT_WAS_ACTIVE" -eq 1 ]]; then
      systemd-run --unit=chatgpt-web-browser --collect --service-type=exec \
        --property=Environment=HOME=/root --property=Environment=DISPLAY=:99 \
        /root/.cache/puppeteer/chrome/linux-131.0.6778.204/chrome-linux64/chrome \
        --no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run --password-store=basic \
        --remote-debugging-address=127.0.0.1 --remote-debugging-port=9224 --remote-allow-origins='*' \
        --user-data-dir=/home/admin/ai/.chatgpt-web-profile about:blank >/dev/null 2>&1 || true
    fi
    exit "$rc"
  }
  trap cleanup EXIT INT TERM

  stop_fanqie
  ensure_browser_runtime
  restore_profile "$account"
  systemd-run --unit=fanqie-account-lease --collect --service-type=exec \
    --property=Environment=HOME=/root --property=Environment=DISPLAY=:99 \
    /snap/bin/chromium --no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run \
    --disable-background-networking --disable-component-update --renderer-process-limit=1 \
    --password-store=basic --remote-debugging-address=127.0.0.1 --remote-debugging-port="$port" \
    --remote-allow-origins='*' --user-data-dir="$LIVE_DIR/$account" \
    https://fanqienovel.com/writer/zone >/dev/null
  LEASE_STARTED=1
  wait_cdp "$port" || { echo "Fanqie CDP did not become ready" >&2; exit 1; }
  # The uploader itself performs the authoritative expected-account API check.
  # Waiting for the writer-zone renderer here is redundant and unstable on
  # this low-memory host.
  "$@"
}

main "$@"
