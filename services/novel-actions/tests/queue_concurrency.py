#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


QUEUE = Path("/home/admin/ai/scripts/sonovel-ranking-queue.js")
NODE = Path("/usr/local/bin/node")


def main():
    with tempfile.TemporaryDirectory(prefix="sonovel-queue-") as temp:
        root = Path(temp)
        event_log = root / "events.jsonl"
        client = root / "fake-client.js"
        client.write_text("""
const fs = require('node:fs');
const title = process.argv[3];
const log = process.env.FAKE_EVENT_LOG;
fs.appendFileSync(log, JSON.stringify({type:'start', title, at:Date.now(), pid:process.pid}) + '\\n');
const delay = title.startsWith('慢') ? 6000 : 300;
setTimeout(() => {
  fs.appendFileSync(log, JSON.stringify({type:'end', title, at:Date.now(), pid:process.pid}) + '\\n');
  process.stdout.write('/tmp/packet-' + title + '\\n');
}, delay);
""", encoding="utf-8")
        input_path = root / "books.json"
        input_path.write_text(json.dumps([{"title": f"书{i}", "author": "作者"} for i in range(6)],
                                         ensure_ascii=False), encoding="utf-8")
        env = os.environ.copy()
        env.update({"SONOVEL_CLIENT": str(client), "SONOVEL_OUTPUT_DIR": str(root),
                    "FAKE_EVENT_LOG": str(event_log)})
        began = time.monotonic()
        run = subprocess.run([
            str(NODE), str(QUEUE), str(input_path), "--concurrency", "3", "--success-limit", "3",
            "--book-timeout-seconds", "5", "--batch-timeout-seconds", "10",
        ], env=env, text=True, capture_output=True, timeout=15)
        assert run.returncode == 0, run.stderr or run.stdout
        elapsed = time.monotonic() - began
        events = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
        complete = next(item for item in events if item.get("event") == "complete")
        rows = json.loads(Path(complete["output"]).read_text(encoding="utf-8"))
        assert sum(item["status"] == "downloaded_needs_official_verification" for item in rows) == 3
        assert sum(item["status"] == "not_attempted" for item in rows) == 3
        intervals = {}
        for event in map(json.loads, event_log.read_text(encoding="utf-8").splitlines()):
            intervals.setdefault(event["pid"], {})[event["type"]] = event["at"]
        points = []
        for item in intervals.values():
            points.extend([(item["start"], 1), (item["end"], -1)])
        active = maximum = 0
        for _, delta in sorted(points, key=lambda item: (item[0], -item[1])):
            active += delta
            maximum = max(maximum, active)
        assert maximum == 3
        assert elapsed < 2

        slow_input = root / "slow-books.json"
        slow_input.write_text(json.dumps([{"title": f"慢书{i}"} for i in range(3)], ensure_ascii=False), encoding="utf-8")
        slow = subprocess.run([
            str(NODE), str(QUEUE), str(slow_input), "--concurrency", "3", "--success-limit", "3",
            "--book-timeout-seconds", "5", "--batch-timeout-seconds", "6",
        ], env=env, text=True, capture_output=True, timeout=10)
        assert slow.returncode == 0, slow.stderr or slow.stdout
        slow_events = [json.loads(line) for line in slow.stdout.splitlines() if line.startswith("{")]
        slow_complete = next(item for item in slow_events if item.get("event") == "complete")
        slow_rows = json.loads(Path(slow_complete["output"]).read_text(encoding="utf-8"))
        assert all(item["status"] == "skipped" and item["timed_out"] for item in slow_rows)
        assert slow_complete["elapsed_seconds"] <= 7
        print("queue_concurrency: PASS")


if __name__ == "__main__":
    main()
