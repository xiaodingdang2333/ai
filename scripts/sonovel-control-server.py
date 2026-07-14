#!/usr/bin/env python3
"""Handle the narrow start/stop command accepted by the SoNovel control socket."""

import subprocess
import sys


ALLOWED = {"start", "stop"}


def main():
    command = sys.stdin.readline(32).strip()
    if command not in ALLOWED:
        print("ERROR unsupported command", flush=True)
        return 2
    result = subprocess.run(
        ["/bin/systemctl", command, "sonovel.service"],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        message = (result.stderr or result.stdout or "systemctl failed").strip().replace("\n", " ")
        print("ERROR " + message[:1000], flush=True)
        return result.returncode
    print("OK " + command, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
