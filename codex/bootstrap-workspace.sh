#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
codex_home="${CODEX_HOME:-$HOME/.codex}"

mkdir -p "$codex_home/skills"
for skill in "$repo_root"/codex/skills/*; do
  [[ -d "$skill" ]] || continue
  name="$(basename "$skill")"
  target="$codex_home/skills/$name"
  if [[ -L "$target" ]]; then
    rm -f "$target"
  elif [[ -e "$target" ]]; then
    echo "保留已有技能，未覆盖：$target" >&2
    continue
  fi
  ln -s "$skill" "$target"
done

# Claude Code and Gemini can always follow the root instruction files. These
# workspace links additionally expose the same canonical skill directories to
# versions that support repository-local agent skills.
for agent_dir in "${CLAUDE_HOME:-$HOME/.claude}/skills" "${GEMINI_HOME:-$HOME/.gemini}/skills"; do
  mkdir -p "$agent_dir"
  for skill in "$repo_root"/codex/skills/*; do
    [[ -d "$skill" ]] || continue
    name="$(basename "$skill")"
    target="$agent_dir/$name"
    [[ -L "$target" ]] && rm -f "$target"
    [[ -e "$target" ]] || ln -s "$skill" "$target"
  done
done

echo "工作区小说技能已链接到 $codex_home/skills"
echo "Codex、Claude Code、Gemini 的仓库级指令和技能入口已就绪。"
echo "请始终从仓库根目录启动对应工具。"
