#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse, request


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
LOG_PATH = ROOT / "monitor.log"
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(message: str) -> None:
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"{now()} {message}\n")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def http_get(url: str, timeout: int = 25) -> str:
    req = request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        encoding = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(encoding, "ignore")


def normalize_price(text: str) -> int | None:
    # Prefer CNY/RMB prices near the page content. Ignore years, dates, and route numbers.
    candidates: list[int] = []
    patterns = [
        r"(?:¥|￥|CNY|RMB|USD\s*)\s*([1-9][0-9]{2,5})",
        r"([1-9][0-9]{2,5})\s*(?:元|CNY|RMB)",
        r"(?:price|Price|amount|Amount|fare|Fare)[^0-9]{0,30}([1-9][0-9]{2,5})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            value = int(match.group(1))
            if 500 <= value <= 20000 and value not in {2026, 3209, 3210}:
                candidates.append(value)
    if not candidates:
        return None
    # For this task, the useful number is the total round-trip price around 2520.
    baseline = 2520
    candidates.sort(key=lambda value: (abs(value - baseline), value))
    return candidates[0]


def parse_source(name: str, html: str) -> int | None:
    if "whaleguard block" in html.lower():
        raise RuntimeError(f"{name}: blocked by whaleguard")
    compact = html.replace("\\u002F", "/")
    route_hit = any(token in compact for token in ("CKG", "URC", "Chongqing", "Urumqi", "重庆", "乌鲁木齐"))
    flight_hit = any(token in compact for token in ("3U3209", "3U3210", "Sichuan", "川航", "四川航空"))
    price = normalize_price(compact)
    if price and (route_hit or flight_hit):
        return price
    return None


def extract_ctrip_flight_price(html: str, flight_no: str) -> int:
    if "whaleguard block" in html.lower():
        raise RuntimeError("blocked by whaleguard")
    compact = html.replace("\\u002F", "/")
    idx = compact.find(f'"flightNo":"{flight_no}"')
    if idx < 0:
        raise RuntimeError(f"flight {flight_no} not found")
    start = compact.rfind('{"flightItem":', 0, idx)
    end = compact.find('{"flightItem":', idx + 1)
    if start < 0:
        start = max(0, idx - 5000)
    if end < 0:
        end = min(len(compact), idx + 9000)
    block = compact[start:end]
    patterns = [
        r'"dfltnoFlgno":"' + re.escape(flight_no) + r'","policy":\{"price":([1-9][0-9]{2,5})',
        r'"flights":\[\{"flightNo":"' + re.escape(flight_no) + r'".*?"pl":\[\{"price":([1-9][0-9]{2,5})',
        r'"policy":\{"price":([1-9][0-9]{2,5}).{0,400}"dfltnoFlgno":"' + re.escape(flight_no) + r'"',
    ]
    for pattern in patterns:
        match = re.search(pattern, block)
        if match:
            return int(match.group(1))
    raise RuntimeError(f"price for {flight_no} not found")


def check_ctrip_exact_sum(source: dict[str, Any], config: dict[str, Any]) -> tuple[int, str]:
    outbound_html = http_get(source["outbound_url"])
    return_html = http_get(source["return_url"])
    outbound_price = extract_ctrip_flight_price(outbound_html, config["outbound"]["flight_no"])
    return_price = extract_ctrip_flight_price(return_html, config["return"]["flight_no"])
    return outbound_price + return_price, f"{source['name']} ({outbound_price}+{return_price})"


def check_price(config: dict[str, Any]) -> tuple[int, str]:
    errors: list[str] = []
    for source in config.get("sources", []):
        name = source["name"]
        try:
            if source.get("type") == "ctrip_mobile_exact_sum":
                return check_ctrip_exact_sum(source, config)
            html = http_get(source["url"])
            price = parse_source(name, html)
            if price is not None:
                return price, name
            errors.append(f"{name}: no price parsed")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(errors))


def send_serverchan(title: str, body: str) -> None:
    pushplus_token = os.environ.get("PUSHPLUS_TOKEN")
    if not pushplus_token:
        env_file = ROOT / "env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("PUSHPLUS_TOKEN="):
                    pushplus_token = line.split("=", 1)[1].strip()
                    break
    if pushplus_token:
        data = parse.urlencode({"token": pushplus_token, "title": title, "content": body}).encode("utf-8")
        req = request.Request("https://www.pushplus.plus/send", data=data, method="POST")
        with request.urlopen(req, timeout=15) as resp:
            resp.read()
        return

    key = os.environ.get("SERVER_CHAN_SENDKEY")
    if not key:
        env_file = ROOT / "env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("SERVER_CHAN_SENDKEY="):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise RuntimeError("SERVER_CHAN_SENDKEY is not configured")
    data = parse.urlencode({"title": title, "desp": body}).encode("utf-8")
    req = request.Request(f"https://sctapi.ftqq.com/{key}.send", data=data, method="POST")
    with request.urlopen(req, timeout=15) as resp:
        resp.read()


def notify_change(config: dict[str, Any], old_price: int | None, new_price: int, source: str) -> None:
    delta = "" if old_price is None else f"{new_price - old_price:+d}"
    direction = "变动" if old_price is None else ("下降" if new_price < old_price else "上涨")
    title = f"航班价格{direction}：{config['route']} ¥{new_price}"
    verify_steps = config.get("mobile_verify_steps") or []
    verify_text = "\n".join(f"{idx}. {step}" for idx, step in enumerate(verify_steps, start=1))
    body = "\n".join(
        [
            f"航线：{config['route']}",
            f"去程：{config['outbound']['date']} {config['outbound']['flight_no']} {config['outbound']['depart_time']} {config['outbound']['depart_airport']} -> {config['outbound']['arrive_time']} {config['outbound']['arrive_airport']}",
            f"返程：{config['return']['date']} {config['return']['flight_no']} {config['return']['depart_time']} {config['return']['depart_airport']} -> {config['return']['arrive_time']} {config['return']['arrive_airport']}",
            f"旧价：{old_price if old_price is not None else '未知'}",
            f"新价：{new_price}",
            f"变化：{delta or '首次记录'}",
            f"来源：{source}",
            "手机核验方式：",
            verify_text,
            "提醒：脚本只监控价格变化，不会自动下单。不同平台最终支付价可能含券、基建燃油、行李或会员差异，下单前请以购票页最终金额为准。",
        ]
    )
    send_serverchan(title, body)


def last_notified_price(state: dict[str, Any]) -> int | None:
    alerts = state.get("alerts") or []
    if alerts:
        latest = alerts[-1]
        if latest.get("new_price") is not None:
            return int(latest["new_price"])
    return state.get("baseline_screenshot_price") or state.get("last_price")


def main() -> int:
    config = load_json(CONFIG_PATH)
    state = load_json(STATE_PATH)
    state["last_checked_at"] = now()
    try:
        price, source = check_price(config)
    except Exception as exc:
        state["last_error"] = str(exc)
        save_json(STATE_PATH, state)
        log(f"ERROR {exc}")
        return 2

    previous = state.get("last_price")
    state["last_success_at"] = state["last_checked_at"]
    state["last_error"] = None
    state["last_source"] = source
    state["last_price"] = price
    notify_reference = last_notified_price(state)
    min_delta = int(config.get("min_notify_delta", 0))
    notify_delta = None if notify_reference is None else price - int(notify_reference)
    should_notify = notify_reference is not None and abs(notify_delta) > min_delta

    if previous is None:
        log(f"CALIBRATE price={price} source={source}")
    elif previous != price and should_notify:
        notify_change(config, notify_reference, price, source)
        state.setdefault("alerts", []).append(
            {
                "sent_at": state["last_checked_at"],
                "old_price": notify_reference,
                "new_price": price,
                "delta": notify_delta,
                "min_notify_delta": min_delta,
                "source": source,
            }
        )
        log(f"ALERT ref={notify_reference} new={price} delta={notify_delta:+d} source={source}")
    elif previous != price:
        log(f"OK price_changed_below_threshold ref={notify_reference} new={price} delta={notify_delta:+d} threshold={min_delta} source={source}")
    else:
        log(f"OK price={price} source={source}")
    save_json(STATE_PATH, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
