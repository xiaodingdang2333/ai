#!/usr/bin/env python3
"""Safely fast-forward the dedicated Git runtime worktree.

Workers use this before processing a queue. It intentionally refuses to touch
a dirty or locally-ahead checkout, so a failed push or manual change remains
visible instead of being overwritten by an implicit reset or rebase.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_REPO = Path("/home/admin/chatgpt-novel-production-system-runtime")


def run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def git_value(repo: Path, args: list[str]) -> str:
    result = run_git(repo, args)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def sync(repo: Path) -> dict[str, Any]:
    if not (repo / ".git").exists():
        raise RuntimeError(f"not a Git worktree: {repo}")

    dirty = git_value(repo, ["status", "--porcelain"])
    if dirty:
        raise RuntimeError("runtime worktree is dirty; refusing to overwrite local changes")

    fetch = run_git(repo, ["fetch", "origin", "main", "--prune"])
    if fetch.returncode:
        raise RuntimeError(fetch.stderr.strip() or "git fetch failed")

    head_before = git_value(repo, ["rev-parse", "HEAD"])
    origin_main = git_value(repo, ["rev-parse", "origin/main"])
    ahead = int(git_value(repo, ["rev-list", "--count", "origin/main..HEAD"]) or "0")
    behind = int(git_value(repo, ["rev-list", "--count", "HEAD..origin/main"]) or "0")
    if ahead:
        raise RuntimeError("runtime worktree is ahead of origin/main; resolve the unpushed commit before retrying")

    fast_forwarded = False
    if behind:
        merge = run_git(repo, ["merge", "--ff-only", "origin/main"])
        if merge.returncode:
            raise RuntimeError(merge.stderr.strip() or "fast-forward merge failed")
        fast_forwarded = True

    head_after = git_value(repo, ["rev-parse", "HEAD"])
    if head_after != origin_main:
        raise RuntimeError("runtime worktree is not aligned with origin/main after safe sync")
    return {
        "repo": str(repo),
        "branch": git_value(repo, ["branch", "--show-current"]),
        "head_before": head_before,
        "head_after": head_after,
        "origin_main": origin_main,
        "fast_forwarded": fast_forwarded,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely sync the Git novel runtime worktree.")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        payload = sync(args.repo.resolve())
    except RuntimeError as exc:
        payload = {"status": "blocked", "error": str(exc), "repo": str(args.repo)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"novel git sync blocked: {payload['error']}", file=sys.stderr)
        return 2

    payload["status"] = "synced"
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"novel git sync: {payload['head_after'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
