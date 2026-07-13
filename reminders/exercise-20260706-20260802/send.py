#!/usr/bin/env python3
import argparse
import json
import os
from datetime import date
from pathlib import Path
from urllib import parse, request


START = date(2026, 7, 6)
END = date(2026, 8, 2)
ENV_FILES = (
    Path("/home/admin/ai/monitors/cmb-gold-monitor/env"),
    Path("/home/admin/ai/monitors/flight-price-ckg-urc-20260815/env"),
)


def token():
    value = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    if value:
        return value
    for path in ENV_FILES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("PUSHPLUS_TOKEN="):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError("未找到PUSHPLUS_TOKEN")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", help="仅用于测试日期边界，格式YYYY-MM-DD")
    args = parser.parse_args()
    today = date.fromisoformat(args.date) if args.date else date.today()
    if not START <= today <= END:
        print(json.dumps({"sent": False, "reason": "outside_date_range", "date": str(today)}, ensure_ascii=False))
        return
    if args.dry_run:
        print(json.dumps({"sent": False, "reason": "dry_run", "date": str(today)}, ensure_ascii=False))
        return
    payload = parse.urlencode({
        "token": token(),
        "title": "运动提醒",
        "content": "晚上八点了，该运动了。今天也给身体留一点时间。",
    }).encode("utf-8")
    req = request.Request("https://www.pushplus.plus/send", data=payload, method="POST")
    with request.urlopen(req, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    if int(result.get("code", -1)) != 200:
        raise RuntimeError(f"PushPlus发送失败：{result.get('msg', '未知错误')}")
    print(json.dumps({"sent": True, "date": str(today)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
