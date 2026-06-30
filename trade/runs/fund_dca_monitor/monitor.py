#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse, request


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
LOG_PATH = ROOT / "monitor.log"
FUND_GZ = "https://fundgz.1234567.com.cn/js/{code}.js?rt={ts}"


def now_dt() -> datetime:
    return datetime.now()


def now() -> str:
    return now_dt().isoformat(timespec="seconds")


def log(message: str) -> None:
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"{now()} {message}\n")


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default or {}


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def http_get(url: str, encoding: str = "utf-8", timeout: int = 20) -> str:
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, "ignore")


def fetch_fund_estimate(code: str) -> dict[str, Any]:
    text = http_get(FUND_GZ.format(code=code, ts=int(time.time() * 1000)))
    payload = text.split("(", 1)[1].rsplit(")", 1)[0]
    return json.loads(payload)


def send_notification(title: str, body: str) -> None:
    pushplus_token = os.environ.get("PUSHPLUS_TOKEN")
    if pushplus_token:
        data = parse.urlencode({"token": pushplus_token, "title": title, "content": body}).encode("utf-8")
        req = request.Request("https://www.pushplus.plus/send", data=data, method="POST")
        with request.urlopen(req, timeout=15) as resp:
            resp.read()
        return

    ntfy_topic = os.environ.get("NTFY_TOPIC")
    ntfy_server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    ntfy_token = os.environ.get("NTFY_TOKEN")
    if ntfy_topic:
        headers = {"Title": title, "Priority": "default", "Tags": "moneybag,calendar"}
        if ntfy_token:
            headers["Authorization"] = f"Bearer {ntfy_token}"
        req = request.Request(
            f"{ntfy_server}/{parse.quote(ntfy_topic)}",
            data=body.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=15) as resp:
            resp.read()
        return

    key = os.environ.get("SERVER_CHAN_SENDKEY")
    if key:
        data = parse.urlencode({"title": title, "desp": body}).encode("utf-8")
        req = request.Request(f"https://sctapi.ftqq.com/{key}.send", data=data, method="POST")
        with request.urlopen(req, timeout=15) as resp:
            resp.read()
        return

    raise RuntimeError("No notifier configured. Set PUSHPLUS_TOKEN, NTFY_TOPIC, or SERVER_CHAN_SENDKEY.")


def due_tranche(config: dict[str, Any], state: dict[str, Any], dt: datetime) -> tuple[bool, str, dict[str, Any] | None]:
    month_key = dt.strftime("%Y-%m")
    if dt.weekday() > 4:
        return False, "weekend", None

    tranches = config.get("tranches") or [
        {
            "id": "T1",
            "label": "工资后第一笔",
            "start_day": int(config.get("salary_day", 10)),
            "end_day": int(config.get("salary_day", 10)) + 6,
            "amount": float(config.get("monthly_base_amount", 2000)),
        }
    ]
    sent = set(state.get("sent_tranches", []))
    for tranche in tranches:
        start = int(tranche.get("start_day", 1))
        end = int(tranche.get("end_day", start))
        key = f"{month_key}:{tranche.get('id', start)}"
        if key in sent:
            continue
        if start <= dt.day <= end:
            return True, key, tranche
    return False, f"outside_tranche_windows:{dt.day}", None


def valid_same_day_estimates(estimates: dict[str, dict[str, Any]], dt: datetime) -> bool:
    today = dt.strftime("%Y-%m-%d")
    return all(str(item.get("gztime", "")).startswith(today) for item in estimates.values())


def suggested_amounts(config: dict[str, Any], estimates: dict[str, dict[str, Any]], tranche: dict[str, Any]) -> dict[str, Any]:
    cash = float(config.get("cash_balance", 0))
    reduce_threshold = float(config.get("cash_reduce_threshold", 6500))
    floor = float(config.get("cash_floor", 6000))
    base = float(tranche.get("amount", 1000))

    if cash <= reduce_threshold:
        total = 0.0
        reason = f"零钱宝余额 {cash:.2f} 接近/低于现金底线 {floor:.2f}，本笔建议暂停定投。"
        paused = True
    else:
        total = min(base, max(0.0, cash - floor))
        reason = f"零钱宝余额 {cash:.2f} 高于现金底线，本笔按计划定投。"
        paused = False

    funds = config.get("funds", {})
    raw_amounts = {}
    for code, fund in funds.items():
        raw_amounts[code] = round(total * float(fund.get("target_weight", 0.5)), 2)

    notes = [reason]
    deferred = False
    a500_code = "022430"
    if raw_amounts.get(a500_code, 0) > 0:
        a500_change = float(estimates.get(a500_code, {}).get("gszzl") or 0)
        defer_threshold = float(config.get("defer_if_022430_up_pct", 1.5))
        execute_pullback = float(config.get("execute_if_022430_down_pct", -1.0))
        if a500_change >= defer_threshold:
            raw_amounts[a500_code] = 0.0
            deferred = True
            notes.append(f"022430 今日估算涨幅 {a500_change:.2f}% 较大，本笔建议延后 1-3 个交易日，避免追高。")
        elif a500_change <= execute_pullback:
            notes.append(f"022430 今日估算涨幅 {a500_change:.2f}%，属于回调日，本笔适合按计划执行。")

    dividend_code = "009052"
    if raw_amounts.get(dividend_code, 0) > 0:
        dividend_change = float(estimates.get(dividend_code, {}).get("gszzl") or 0)
        if dividend_change <= -1.0:
            notes.append("009052 今日回调，按计划小额定投即可，不额外加码。")

    total_after_adjust = round(sum(raw_amounts.values()), 2)
    return {
        "amounts": raw_amounts,
        "total": total_after_adjust,
        "cash_after": round(cash - total_after_adjust, 2),
        "notes": notes,
        "deferred": deferred,
        "paused": paused,
    }


def feedback_url(config: dict[str, Any], kind: str, payload: dict[str, Any] | None = None) -> str:
    base_url = str(config.get("feedback_base_url") or "http://8.212.144.72:8090").rstrip("/")
    token_path = Path(str(config.get("feedback_token_path") or "/home/admin/ai/output/qr-login/renminwang.token"))
    token = token_path.read_text(encoding="utf-8").strip()
    params = {
        "token": token,
        "source": "fund_dca_monitor",
        "asset": "零钱宝" if kind == "cash" else "009052/022430",
        "feedback_type": "cash_update" if kind == "cash" else "fund_dca",
    }
    if payload:
        params.update(payload)
    return f"{base_url}/trade-feedback.html?{parse.urlencode(params)}"


def build_body(config: dict[str, Any], estimates: dict[str, dict[str, Any]], suggestion: dict[str, Any], month_key: str) -> str:
    funds = config.get("funds", {})
    lines = [
        f"基金定投提醒：{month_key}",
        "",
        f"当前记录零钱宝：{float(config.get('cash_balance', 0)):.2f} 元",
        f"本期建议总定投：{float(suggestion['total']):.2f} 元",
        f"定投后预计零钱宝：{float(suggestion['cash_after']):.2f} 元",
        "",
        "基金估值：",
    ]
    for code, fund in funds.items():
        est = estimates.get(code, {})
        amount = float(suggestion["amounts"].get(code, 0))
        lines.append(
            f"- {fund.get('display_name', code)}：估值 {est.get('gsz')}，"
            f"今日 {est.get('gszzl')}%，时间 {est.get('gztime')}；"
            f"当前记录市值 {float(fund.get('value', 0)):.2f}，收益 {float(fund.get('profit', 0)):.2f}；"
            f"本期建议 {amount:.2f} 元。"
        )
    lines.extend(["", "判断：", *[f"- {note}" for note in suggestion["notes"]]])
    lines.extend(
        [
            "",
            "操作反馈：",
            feedback_url(config, "dca", {f"amount_{code}": str(amount) for code, amount in suggestion["amounts"].items()}),
            "",
            "工资/零钱宝余额刷新：",
            feedback_url(config, "cash"),
            "",
            "提醒：脚本只通知，不会自动申购基金；如果你提交已定投反馈，系统默认从零钱宝扣减同等金额。",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    config = load_json(CONFIG_PATH)
    state = load_json(STATE_PATH, {"sent_months": [], "last_checked_at": None})
    dt = now_dt()
    state["last_checked_at"] = now()

    due, key_or_reason, tranche = due_tranche(config, state, dt)
    if not due:
        save_json(STATE_PATH, state)
        print(f"{state['last_checked_at']} skip fund DCA monitor: {key_or_reason}")
        return

    estimates = {code: fetch_fund_estimate(code) for code in config.get("funds", {})}
    state["last_estimates"] = estimates
    if not valid_same_day_estimates(estimates, dt):
        state["last_skip_reason"] = "stale_or_missing_same_day_estimates"
        save_json(STATE_PATH, state)
        print(f"{state['last_checked_at']} skip fund DCA monitor: stale_or_missing_same_day_estimates")
        return

    suggestion = suggested_amounts(config, estimates, tranche or {})
    month_key = key_or_reason
    body = build_body(config, estimates, suggestion, month_key)
    send_notification("基金定投提醒", body)

    if not suggestion.get("deferred"):
        state.setdefault("sent_tranches", []).append(month_key)
    else:
        state.setdefault("deferred_tranche_checks", []).append(
            {
                "checked_at": state["last_checked_at"],
                "tranche": month_key,
                "reason": "022430_up_too_much",
                "suggestion": suggestion,
            }
        )
    state.setdefault("sent_months", [])
    state["last_suggestion"] = {
        "created_at": state["last_checked_at"],
        "tranche": month_key,
        "tranche_config": tranche,
        "suggestion": suggestion,
        "estimates": estimates,
    }
    save_json(STATE_PATH, state)
    log(f"SENT month={month_key} total={suggestion['total']} cash_after={suggestion['cash_after']}")
    print(body)


if __name__ == "__main__":
    main()
