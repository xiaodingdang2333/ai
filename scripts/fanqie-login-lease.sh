#!/usr/bin/env bash
set -euo pipefail

# Start a fresh QR login without ever losing the prior cache on timeout,
# cancellation, or an account mismatch.  The lease script saves the live
# profile only when the node helper exits; this wrapper restores the saved
# baseline if that helper fails.

account="${1:?usage: fanqie-login-lease.sh account-a|account-b PORT EXPECTED_ACCOUNT [OUT_FILE]}"
port="${2:?missing port}"
expected="${3:?missing expected account name}"
out="${4:-/home/admin/ai/output/qr-login/current.png}"

case "$account" in
  account-a) backup_name='account-a-snap' ;;
  account-b) backup_name='account-b-snap' ;;
  account-c) backup_name='account-c-snap' ;;
  *) echo "Unknown account: $account" >&2; exit 2 ;;
esac

work_root='/home/admin/ai'
backup_dir="$work_root/.fanqie-profiles/snap-backups"
backup="$backup_dir/$backup_name"
lease="$work_root/scripts/fanqie-browser-lease.sh"
helper="$work_root/scripts/fanqie-qr-login.js"

[[ -d "$backup" ]] || { echo "Missing saved profile: $backup" >&2; exit 3; }
snapshot="$(mktemp -d "$backup_dir/.${account}.pre-login.XXXXXX")"
cp -a "$backup" "$snapshot/original"

success=0
cleanup() {
  local rc=$?
  if [[ "$success" -ne 1 ]]; then
    rm -rf "$backup"
    cp -a "$snapshot/original" "$backup"
    echo "LOGIN_CACHE_ROLLED_BACK $account" >&2
  fi
  rm -rf "$snapshot"
  exit "$rc"
}
trap cleanup EXIT INT TERM

if "$lease" run "$account" "$port" node "$helper" \
  --port "$port" --expected "$expected" --out "$out" --wait-ms 1200000 --fresh yes; then
  success=1
fi

[[ "$success" -eq 1 ]]
