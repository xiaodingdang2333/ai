#!/usr/bin/env python3
import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import sys

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
import server


def make_packet(root):
    packet = root / "ranking" / "拆书分析" / "sample"
    selected = packet / "selected"
    selected.mkdir(parents=True)
    (selected / "0001-第一章.txt").write_text("第一章\n\n" + "样本" * 1000, encoding="utf-8")
    (packet / "00_拆书索引.md").write_text("# 拆书索引\n", encoding="utf-8")
    (packet / "source.json").write_text(json.dumps({
        "official_author": "佚名",
        "mirror_chapter_count": 80,
        "mirror_intro": "镜像简介",
        "mirror_first_chapter_titles": ["第一章", "第二章", "第三章"],
    }, ensure_ascii=False), encoding="utf-8")
    return packet


def main():
    with tempfile.TemporaryDirectory(prefix="novel-market-") as temp:
        root = Path(temp)
        packet = make_packet(root)
        queue_result = root / "queue.json"
        rows = [{
            "rank": i, "title": f"榜单书{i}", "author": "作者",
            "status": "downloaded_needs_official_verification", "packet": str(packet),
        } for i in range(1, 4)]
        queue_result.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        old_values = (server.ROOT, server.RANKING_ROOT, server.DB_PATH, server.LOG_DIR)
        server.ROOT, server.RANKING_ROOT = root / "state", root / "ranking"
        server.DB_PATH, server.LOG_DIR = server.ROOT / "state.sqlite3", server.ROOT / "logs"
        server.init_db()
        try:
            with patch.object(server, "available_memory_mb", return_value=900), \
                    patch.object(server.os, "getloadavg", return_value=(0.5, 0.5, 0.5)):
                assert server.choose_market_concurrency()["concurrency"] == 3
            with patch.object(server, "available_memory_mb", return_value=600), \
                    patch.object(server.os, "getloadavg", return_value=(1.0, 1.0, 1.0)):
                assert server.choose_market_concurrency()["concurrency"] == 2
            with patch.object(server, "available_memory_mb", return_value=400), \
                    patch.object(server.os, "getloadavg", return_value=(0.5, 0.5, 0.5)):
                assert server.choose_market_concurrency()["concurrency"] == 1

            wait_job = "b" * 32
            stamp = server.now_iso()
            with server.db() as con:
                con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
                            (wait_job, "market_study", "queued", "{}", None, None, stamp, stamp))
            threading.Thread(target=lambda: (time.sleep(0.2), server.job_update(
                wait_job, "completed", {"study_status": "ready"})), daemon=True).start()
            began = time.monotonic()
            assert server.wait_for_job(wait_job, 2)["status"] == "completed"
            assert time.monotonic() - began < 1

            def stream_result(args, timeout, callback):
                callback({"event": "progress", "processed": 3, "total": 3, "succeeded": 3,
                          "skipped": 0, "active_titles": [], "concurrency": 3})
                return str(queue_result) + "\n"

            with patch.object(server, "find_local_ranking", return_value=None), \
                    patch.object(server, "run_streaming_command", side_effect=stream_result) as stream, \
                    patch.object(server, "run_command", return_value="") as command:
                result = server.market_study_job({
                    "genre": "女频快穿", "audience": "女频", "ranking_platform": "晋江", "attempted_platforms": [], "sample_limit": 3,
                    "ranking_books": [{"rank": i, "title": f"榜单书{i}", "author": "作者"} for i in range(1, 4)],
                })
            assert stream.call_count == 1
            assert stream.call_args.args[0][1] == "packet-list"
            assert command.call_count == 1 and command.call_args.args[0][1] == "stop"
            assert result["study_status"] == "ready" and result["usable_samples"] == 3
            assert result["samples"][0]["identity_evidence"]["mirror_author"] == "佚名"
            with patch.object(server, "find_local_ranking", return_value=None), \
                    patch.object(server, "run_streaming_command") as cached_stream:
                cached_result = server.market_study_job({
                    "genre": "女频快穿", "audience": "女频", "ranking_platform": "晋江", "attempted_platforms": [], "sample_limit": 3,
                    "ranking_books": [{"rank": i, "title": f"榜单书{i}", "author": "作者"} for i in range(1, 4)],
                })
            assert cached_stream.call_count == 0
            assert all(item["cache_hit"] for item in cached_result["samples"])

            skipped = root / "skipped.json"
            skipped.write_text(json.dumps([{
                "rank": 1, "title": "搜不到", "author": "作者", "status": "skipped",
                "reason": "sonovel-client: No exact source result for: 搜不到",
            }], ensure_ascii=False), encoding="utf-8")
            with patch.object(server, "find_local_ranking", return_value=None), \
                    patch.object(server, "run_streaming_command", return_value=str(skipped) + "\n"), \
                    patch.object(server, "run_command", return_value=""):
                result = server.market_study_job({
                    "genre": "女频快穿", "audience": "女频", "ranking_platform": "晋江", "attempted_platforms": [], "sample_limit": 3,
                    "ranking_books": [{"rank": 1, "title": "搜不到", "author": "作者"}],
                })
            assert result["study_status"] == "needs_more_books" and result["usable_samples"] == 0
            with patch.object(server, "find_local_ranking", return_value=None), \
                    patch.object(server, "run_streaming_command") as failure_stream:
                cached_failure = server.market_study_job({
                    "genre": "女频快穿", "audience": "女频", "ranking_platform": "晋江", "attempted_platforms": [], "sample_limit": 3,
                    "ranking_books": [{"rank": 1, "title": "搜不到", "author": "作者"}],
                })
            assert failure_stream.call_count == 1 and cached_failure["skipped"][0].get("cache_hit") is not True
            try:
                server.market_study_job({
                    "genre": "男频玄幻", "audience": "男频", "ranking_platform": "番茄",
                    "attempted_platforms": [], "sample_limit": 3,
                    "ranking_books": [{"rank": 1, "title": "越级书", "author": "作者"}],
                })
                raise AssertionError("男频首轮越级到番茄应被拒绝")
            except RuntimeError as exc:
                assert "当前必须使用起点" in str(exc)
            print("market_job: PASS")
        finally:
            server.ROOT, server.RANKING_ROOT, server.DB_PATH, server.LOG_DIR = old_values


if __name__ == "__main__":
    main()
