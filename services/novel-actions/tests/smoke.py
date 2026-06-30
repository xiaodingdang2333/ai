#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base, path, token=None, method="GET", body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            return response.status, content_type, json.loads(raw) if "json" in content_type else raw.decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, exc.headers.get("Content-Type", ""), json.loads(raw)


def data(result):
    status, _, payload = result
    assert status == 200, payload
    assert payload["ok"] is True, payload
    return payload["data"]


def main():
    with tempfile.TemporaryDirectory(prefix="novel-actions-") as temp:
        root = Path(temp)
        state = root / "state"
        txt = root / "txt"
        state.mkdir()
        txt.mkdir()
        token = "smoke-test-token"
        (state / "action.token").write_text(token, encoding="utf-8")
        port = free_port()
        env = os.environ.copy()
        env.update({
            "NOVEL_ACTIONS_STATE_ROOT": str(state),
            "NOVEL_ACTIONS_TXT_ROOT": str(txt),
            "NOVEL_ACTIONS_PORT": str(port),
        })
        process = subprocess.Popen(
            [sys.executable, str(SERVICE_ROOT / "server.py")],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(50):
                try:
                    if request(base, "/health")[0] == 200:
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("service did not start")

            assert request(base, "/v1/defaults")[0] == 401
            assert request(base, "/openapi.json")[0] == 200
            privacy = request(base, "/privacy")
            assert privacy[0] == 200 and privacy[1].startswith("text/html")

            candidates = [{"number": i, "title": f"候选{i}", "score": 80 + i} for i in range(1, 13)]
            idea = data(request(base, "/v1/ideations", token, "POST", {"genre": "女频快穿", "candidates": candidates}))
            selected = data(request(base, f"/v1/ideations/{idea['ideation_id']}/select", token, "POST", {"candidate_no": 1}))
            assert selected["stage"] == "selected"

            book = data(request(base, "/v1/books", token, "POST", {
                "ideation_id": idea["ideation_id"], "title": "冒烟测试新书", "account": "account-b",
                "metadata": {"synopsis": "仅用于隔离测试"},
            }))
            assert book["stage"] == "trial_writing" and book["revision"] == 1
            book_id = book["id"]

            chapters = []
            for no, char in enumerate("天地人", 1):
                chapters.append({
                    "chapter_no": no,
                    "title": f"试读单元{no}",
                    "body": char * 2600,
                    "summary": f"第{no}章隔离测试摘要",
                })
            book = data(request(base, f"/v1/books/{book_id}/chapters", token, "POST", {
                "expected_revision": 1, "chapters": chapters,
            }))
            assert book["stage"] == "awaiting_trial_approval" and book["revision"] == 2

            blocked = request(base, f"/v1/books/{book_id}/chapters", token, "POST", {
                "expected_revision": 2,
                "chapters": [{"chapter_no": 4, "title": "试读单元4", "body": "玄" * 2600, "summary": "不得提前保存"}],
            })
            assert blocked[0] == 409

            qa = data(request(base, f"/v1/books/{book_id}/qa", token, "POST", {"from": 1, "to": 3}))
            assert qa["passed"] is True
            approved = data(request(base, f"/v1/books/{book_id}/trial-approval", token, "POST", {}))
            assert approved["stage"] == "bulk_writing"

            chapter4 = data(request(base, f"/v1/books/{book_id}/chapters", token, "POST", {
                "expected_revision": 2,
                "chapters": [{"chapter_no": 4, "title": "新世界开端", "body": "玄" * 2600, "summary": "第4章"}],
            }))
            assert chapter4["revision"] == 3
            stale = request(base, f"/v1/books/{book_id}/state", token, "PUT", {"expected_revision": 2, "state": {}})
            assert stale[0] == 409
            assert request(base, f"/v1/books/{book_id}/publish", token, "POST", {})[0] == 404
            print("smoke: PASS")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
