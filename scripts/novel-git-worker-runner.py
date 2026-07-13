#!/usr/bin/env python3
"""Serialize Git-backed novel workers around one runtime worktree.

The poller, sample, server-write, and upload services all fetch, inspect, or
commit the same repository. A shared non-blocking lock prevents simultaneous
Git index access. A skipped tick is safe because each systemd timer retries on
its next interval.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_REPO = Path("/home/admin/chatgpt-novel-production-system-runtime")
DEFAULT_LOCK = Path("/tmp/novel-git-runtime.lock")
SYNC_SCRIPT = Path("/home/admin/ai/scripts/novel-git-sync.py")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Git novel worker under the shared runtime lock.")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("worker command is required after --")

    args.lock_file.parent.mkdir(parents=True, exist_ok=True)
    with args.lock_file.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "locked", "repo": str(args.repo)}, ensure_ascii=False))
            return 0

        sync = subprocess.run(
            [sys.executable, str(SYNC_SCRIPT), "--repo", str(args.repo), "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if sync.returncode:
            print(sync.stdout.strip() or json.dumps({"status": "sync_failed", "repo": str(args.repo)}))
            if sync.stderr.strip():
                print(sync.stderr.strip(), file=sys.stderr)
            return sync.returncode

        return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
