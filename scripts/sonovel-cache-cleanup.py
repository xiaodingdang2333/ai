#!/usr/bin/env python3
import argparse
import json
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_iso(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, timezone.utc)


def inside(path, root):
    path, root = path.resolve(), root.resolve()
    return path == root or root in path.parents


def file_size(path):
    if path.is_file() or path.is_symlink():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def remove_path(path, dry_run, removed):
    size = file_size(path)
    removed.append({"path": str(path), "bytes": size})
    if not dry_run:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    return size


def cleanup(args):
    now = datetime.now(timezone.utc) if not args.now else datetime.fromisoformat(args.now)
    summary = {"at": now.isoformat(), "dry_run": args.dry_run, "removed": [], "freed_bytes": 0,
               "expired_failures": 0, "expired_packets": 0, "active_job_skip": False}
    if not args.db.exists():
        return summary
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        active = con.execute("SELECT COUNT(*) FROM jobs WHERE type='market_study' AND status IN ('queued','running')").fetchone()[0]
        if active:
            summary["active_job_skip"] = True
            return summary

        rows = con.execute("SELECT * FROM market_cache").fetchall()
        for row in rows:
            verified = parse_iso(row["verified_at"])
            last_used = parse_iso(row["last_used_at"])
            if row["status"] == "deterministic_failure" and now - verified > timedelta(hours=6):
                summary["expired_failures"] += 1
                if not args.dry_run:
                    con.execute("DELETE FROM market_cache WHERE cache_key=?", (row["cache_key"],))
            elif row["status"] == "success" and now - last_used > timedelta(days=90):
                packet = Path(row["packet_path"] or "")
                selected = packet / "selected"
                if selected.exists() and inside(selected, args.analysis_root):
                    summary["freed_bytes"] += remove_path(selected, args.dry_run, summary["removed"])
                summary["expired_packets"] += 1
                if not args.dry_run:
                    con.execute("DELETE FROM market_cache WHERE cache_key=?", (row["cache_key"],))

        stale_before = now.timestamp() - 24 * 3600
        for root, pattern in ((args.state_root, "sonovel-ranking-*.json"), (args.downloads, "*")):
            if not root.exists():
                continue
            for path in root.glob(pattern):
                if path.stat().st_mtime >= stale_before:
                    continue
                if root == args.downloads and path.suffix.lower() not in {".tmp", ".part", ".download"}:
                    continue
                if inside(path, root):
                    summary["freed_bytes"] += remove_path(path, args.dry_run, summary["removed"])

        queue_before = now.timestamp() - 30 * 86400
        if args.output.exists():
            for path in args.output.glob("ranking-queue-*.json"):
                if path.stat().st_mtime < queue_before and inside(path, args.output):
                    summary["freed_bytes"] += remove_path(path, args.dry_run, summary["removed"])
        if not args.dry_run:
            con.commit()
    finally:
        con.close()
    return summary


def main():
    parser = argparse.ArgumentParser(description="Clean bounded SoNovel cache files")
    parser.add_argument("--db", type=Path, default=Path("/home/admin/ai/runtime/novel-actions/state.sqlite3"))
    parser.add_argument("--analysis-root", type=Path, default=Path("/home/admin/ai/txt/排行榜/拆书分析"))
    parser.add_argument("--downloads", type=Path, default=Path("/home/admin/ai/tools/so-novel/downloads"))
    parser.add_argument("--output", type=Path, default=Path("/home/admin/ai/output/sonovel"))
    parser.add_argument("--state-root", type=Path, default=Path("/home/admin/ai/runtime/novel-actions"))
    parser.add_argument("--log", type=Path, default=Path("/home/admin/ai/runtime/novel-actions/logs/cache-cleanup.log"))
    parser.add_argument("--now", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = cleanup(args)
    line = json.dumps(result, ensure_ascii=False)
    print(line)
    if not args.dry_run:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


if __name__ == "__main__":
    main()
