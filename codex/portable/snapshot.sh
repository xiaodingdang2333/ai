#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
portable="$repo_root/codex/portable"
codex_home="${CODEX_HOME:-$HOME/.codex}"
archive="$portable/private-state.tar.zst.enc"

if [[ -z "${CODEX_ARCHIVE_PASSPHRASE:-}" ]]; then
  echo "CODEX_ARCHIVE_PASSPHRASE is required" >&2
  exit 2
fi

mkdir -p "$portable/system-skills" "$portable/plugins"
rsync -a --delete "$codex_home/skills/.system/" "$portable/system-skills/"
rsync -a --delete \
  --exclude '.remote-plugin-install-staging/' \
  "$codex_home/plugins/" "$portable/plugins/"

items=()
for item in \
  config.toml deepseek.config.toml gpt.config.toml rules sessions history.jsonl \
  goals_1.sqlite goals_1.sqlite-shm goals_1.sqlite-wal \
  memories_1.sqlite memories_1.sqlite-shm memories_1.sqlite-wal \
  state_5.sqlite state_5.sqlite-shm state_5.sqlite-wal; do
  [[ -e "$codex_home/$item" ]] && items+=("$item")
done

tmp="$(mktemp "$portable/private-state.XXXXXX.tmp")"
stage="$(mktemp -d "$portable/private-state-stage.XXXXXX.tmp")"
trap 'rm -f "$tmp"; rm -rf "$stage"' EXIT
for item in "${items[@]}"; do
  rsync -a "$codex_home/$item" "$stage/"
done
tar -C "$stage" -cf - . \
  | zstd -q -9 -T1 \
  | openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 -md sha256 \
      -pass env:CODEX_ARCHIVE_PASSPHRASE -out "$tmp"
mv "$tmp" "$archive"
chmod 0644 "$archive"
sha256sum "$archive" > "$portable/private-state.sha256"

echo "Snapshot refreshed: $archive"
du -h "$archive"
