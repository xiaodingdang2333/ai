#!/usr/bin/env python3
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT = Path("/home/admin/ai/scripts/sonovel-cache-cleanup.py")


def main():
    with tempfile.TemporaryDirectory(prefix="sonovel-cleanup-") as temp:
        root = Path(temp)
        analysis, downloads, output, state = (root / name for name in ("analysis", "downloads", "output", "state"))
        for path in (analysis, downloads, output, state):
            path.mkdir()
        packet = analysis / "缓存书"
        selected = packet / "selected"
        selected.mkdir(parents=True)
        (selected / "chapter.txt").write_text("正文", encoding="utf-8")
        (packet / "00_拆书索引.md").write_text("索引", encoding="utf-8")
        stale_part = downloads / "failed.part"
        stale_part.write_text("partial", encoding="utf-8")
        queue_file = output / "ranking-queue-old.json"
        queue_file.write_text("[]", encoding="utf-8")
        old_epoch = (datetime.now(timezone.utc) - timedelta(days=120)).timestamp()
        os.utime(stale_part, (old_epoch, old_epoch))
        os.utime(queue_file, (old_epoch, old_epoch))
        db_path = state / "state.sqlite3"
        old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        with sqlite3.connect(db_path) as con:
            con.executescript("""
            CREATE TABLE jobs(id TEXT,type TEXT,status TEXT);
            CREATE TABLE market_cache(cache_key TEXT PRIMARY KEY,title TEXT,author TEXT,status TEXT,
              packet_path TEXT,reason TEXT,verified_at TEXT,last_used_at TEXT);
            """)
            con.execute("INSERT INTO market_cache VALUES(?,?,?,?,?,?,?,?)",
                        ("success", "缓存书", "作者", "success", str(packet), None, old, old))
            con.execute("INSERT INTO market_cache VALUES(?,?,?,?,?,?,?,?)",
                        ("failure", "失败书", "作者", "deterministic_failure", None, "无结果", old, old))
        command = [sys.executable, str(SCRIPT), "--db", str(db_path), "--analysis-root", str(analysis),
                   "--downloads", str(downloads), "--output", str(output), "--state-root", str(state),
                   "--log", str(state / "cleanup.log")]
        dry = subprocess.run(command + ["--dry-run"], text=True, capture_output=True, check=True)
        assert json.loads(dry.stdout)["expired_packets"] == 1 and selected.exists()
        done = subprocess.run(command, text=True, capture_output=True, check=True)
        result = json.loads(done.stdout)
        assert result["expired_packets"] == 1 and result["expired_failures"] == 1
        assert not selected.exists() and (packet / "00_拆书索引.md").exists()
        assert not stale_part.exists() and not queue_file.exists()
        print("cache_cleanup: PASS")


if __name__ == "__main__":
    main()
