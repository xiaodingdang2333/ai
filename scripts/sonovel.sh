#!/usr/bin/env bash
set -euo pipefail

SERVICE=sonovel.service
CLIENT=/home/admin/ai/scripts/sonovel-client.js

start_service() {
  systemctl start "$SERVICE"
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:7765/version >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  journalctl -u "$SERVICE" -n 50 --no-pager >&2
  return 1
}

command=${1:-}
case "$command" in
  start)
    start_service
    echo 'SoNovel is ready at http://127.0.0.1:7765'
    ;;
  stop)
    systemctl stop "$SERVICE"
    ;;
  status)
    systemctl --no-pager --full status "$SERVICE"
    ;;
  search|download|packet|list)
    start_service
    shift
    if [[ "$command" == packet ]]; then
      trap 'systemctl stop "$SERVICE"' EXIT
    fi
    node "$CLIENT" "$command" "$@"
    ;;
  packet-list)
    [[ $# -eq 2 ]] || { echo 'Usage: sonovel.sh packet-list <official-ranking-books.json>' >&2; exit 2; }
    start_service
    trap 'systemctl stop "$SERVICE"' EXIT
    node /home/admin/ai/scripts/sonovel-ranking-queue.js "$2"
    ;;
  *)
    echo 'Usage: sonovel.sh start|stop|status|search <keyword>|packet <exact-title> [official-author]|packet-list <ranking.json>|download <exact-title> [author]|list' >&2
    exit 2
    ;;
esac
