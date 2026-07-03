#!/usr/bin/env python3
import socket
import sys


SOCKET_PATH = "/run/sonovel-control.sock"
ALLOWED = {"start", "stop"}


def main():
    command = sys.argv[1] if len(sys.argv) == 2 else ""
    if command not in ALLOWED:
        raise SystemExit("Usage: sonovel-control-client.py start|stop")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(30)
        client.connect(SOCKET_PATH)
        client.sendall((command + "\n").encode("ascii"))
        client.shutdown(socket.SHUT_WR)
        response = client.recv(4096).decode("utf-8", errors="replace").strip()
    if not response.startswith("OK "):
        raise SystemExit(response or "SoNovel control returned no response")


if __name__ == "__main__":
    main()
