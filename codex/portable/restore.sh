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

(cd "$portable" && sha256sum -c private-state.sha256)
mkdir -p "$codex_home"
backup="$codex_home/migration-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"

for item in config.toml deepseek.config.toml gpt.config.toml rules sessions history.jsonl \
  goals_1.sqlite goals_1.sqlite-shm goals_1.sqlite-wal \
  memories_1.sqlite memories_1.sqlite-shm memories_1.sqlite-wal \
  state_5.sqlite state_5.sqlite-shm state_5.sqlite-wal; do
  [[ -e "$codex_home/$item" ]] && mv "$codex_home/$item" "$backup/"
done

openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 \
    -pass env:CODEX_ARCHIVE_PASSPHRASE -in "$archive" \
  | zstd -q -d \
  | tar -C "$codex_home" -xf -

mkdir -p "$codex_home/skills" "$codex_home/plugins"
rsync -a --delete "$portable/system-skills/" "$codex_home/skills/.system/"
rsync -a --delete "$portable/plugins/" "$codex_home/plugins/"

git -C "$repo_root" submodule update --init --recursive
sonovel_patch="$repo_root/tools/sonovel-tool-local.patch"
sonovel_dir="$repo_root/tools/sonovel-tool"
if [[ -f "$sonovel_patch" ]] && \
   [[ -d "$sonovel_dir/.git" || -f "$sonovel_dir/.git" ]]; then
  if git -C "$sonovel_dir" apply --check "$sonovel_patch" 2>/dev/null; then
    git -C "$sonovel_dir" apply "$sonovel_patch"
  fi
fi

for skill in "$repo_root"/codex/skills/*; do
  [[ -d "$skill" ]] || continue
  name="$(basename "$skill")"
  [[ "$name" == "portable" ]] && continue
  [[ -e "$codex_home/skills/$name" || -L "$codex_home/skills/$name" ]] && \
    rm -rf "$codex_home/skills/$name"
  ln -s "$skill" "$codex_home/skills/$name"
done

shared_memory_source="$repo_root/memory/root-machine"
shared_memory_target="${ROOT_AI_HOME:-/root/ai}/memory"
if [[ -d "$shared_memory_source" ]] && mkdir -p "$shared_memory_target" 2>/dev/null; then
  rsync -a "$shared_memory_source/" "$shared_memory_target/"
fi

echo "Codex state restored to $codex_home"
echo "Previous conflicting state: $backup"
echo "Run 'codex login' before using OpenAI-backed features."
