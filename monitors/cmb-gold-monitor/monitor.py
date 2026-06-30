#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import parse, request


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
LOG_PATH = ROOT / "monitor.log"
FEEDBACK_TOKEN_PATH = Path("/home/admin/ai/output/qr-login/renminwang.token")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36"


def now_dt() -> datetime:
    return datetime.now()


def now() -> str:
    return now_dt().isoformat(timespec="seconds")


def log(message: str) -> None:
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"{now()} {message}\n")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def feedback_url(alert_key: str) -> str:
    base_url = os.environ.get("TRADE_FEEDBACK_BASE_URL", "http://8.212.144.72:8090").rstrip("/")
    token = FEEDBACK_TOKEN_PATH.read_text(encoding="utf-8").strip()
    params = parse.urlencode(
        {
            "token": token,
            "source": "cmb_gold_monitor",
            "asset": "招行黄金",
            "alert_key": alert_key,
        }
    )
    return f"{base_url}/trade-feedback.html?{params}"


def to_float(value: Any) -> float:
    return float(str(value).replace(",", "").strip())


def fetch_gold(config: dict[str, Any]) -> dict[str, Any]:
    req = request.Request(
        config["source_url"],
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8", "ignore"))
    if payload.get("returnCode") != "SUC0000":
        raise RuntimeError(f"CMB API returned {payload.get('returnCode')}: {payload.get('errorMsg')}")

    rows = payload.get("body", {}).get("data", [])
    by_no = {row.get("goldNo"): row for row in rows}
    primary = by_no.get(config["primary_gold_no"])
    secondary = by_no.get(config.get("secondary_gold_no"))
    if not primary:
        raise RuntimeError(f"primary gold {config['primary_gold_no']} not found")

    def normalized(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "gold_no": row.get("goldNo"),
            "variety": row.get("variety"),
            "price": to_float(row.get("curPrice", 0)),
            "up_down": to_float(row.get("upDown", 0)),
            "open": to_float(row.get("open", 0)),
            "pre_close": to_float(row.get("preClose", 0)),
            "high": to_float(row.get("high", 0)),
            "low": to_float(row.get("low", 0)),
            "average": to_float(row.get("avePrice", 0)),
            "trade_count": to_float(row.get("tradeCount", 0)),
            "quote_time": row.get("time"),
        }

    return {
        "api_time": payload.get("body", {}).get("time"),
        "primary": normalized(primary),
        "secondary": normalized(secondary),
    }


def build_snapshot(config: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
    primary = quote["primary"]
    app_buy = primary["price"] + float(config["app_buy_offset_from_au9999"])
    app_sell = app_buy - float(config["sell_spread_per_g"])
    cost = float(config["cost_price_per_g"])
    grams = float(config["grams"])
    core_target = float(config.get("core_physical_target_grams", 0))
    return {
        "checked_at": now(),
        "api_time": quote["api_time"],
        "primary": primary,
        "secondary": quote.get("secondary"),
        "estimated_app_buy_price": round(app_buy, 2),
        "estimated_app_sell_price": round(app_sell, 2),
        "cost_price_per_g": cost,
        "grams": grams,
        "core_physical_target_grams": core_target,
        "investment_surplus_grams": round(max(0.0, grams - core_target), 4),
        "cost_total": round(cost * grams, 2),
        "liquidation_value": round(app_sell * grams, 2),
        "floating_pnl": round((app_sell - cost) * grams, 2),
        "floating_pnl_pct": round(app_sell / cost - 1, 6),
        "breakeven_app_buy_price": round(cost + float(config["sell_spread_per_g"]), 2),
    }


def price_band(price: float, width: float = 5.0) -> int:
    return int(price // width * width)


def sge_session(dt: datetime) -> str | None:
    minutes = dt.hour * 60 + dt.minute
    weekday = dt.weekday()
    if 9 * 60 <= minutes <= 15 * 60 + 30 and weekday <= 4:
        return "day"
    if minutes >= 20 * 60 and weekday <= 4:
        return "night"
    if minutes <= 2 * 60 + 30 and 1 <= weekday <= 5:
        return "early"
    return None


def is_sge_session_open(dt: datetime) -> bool:
    return sge_session(dt) is not None


def quote_time_minutes(snapshot: dict[str, Any]) -> int | None:
    value = str(snapshot.get("primary", {}).get("quote_time") or "")
    try:
        hour, minute, *_ = [int(part) for part in value.split(":")]
    except ValueError:
        return None
    return hour * 60 + minute


def sge_quote_freshness_issue(snapshot: dict[str, Any], dt: datetime) -> str | None:
    session = sge_session(dt)
    if session is None:
        return "outside_sge_session"

    quote_minutes = quote_time_minutes(snapshot)
    if quote_minutes is None:
        return "missing_quote_time"

    current_minutes = dt.hour * 60 + dt.minute
    age: int | None = None
    if session == "day" and 9 * 60 <= quote_minutes <= 15 * 60 + 30:
        age = current_minutes - quote_minutes
    elif session == "night" and quote_minutes >= 20 * 60:
        age = current_minutes - quote_minutes
    elif session == "early":
        if quote_minutes <= 2 * 60 + 30:
            age = current_minutes - quote_minutes
        elif quote_minutes >= 20 * 60:
            age = current_minutes + 24 * 60 - quote_minutes

    if age is None:
        return f"quote_time_outside_current_session:{snapshot['primary'].get('quote_time')}"
    if age < 0 or age > 20:
        return f"stale_quote_time:{snapshot['primary'].get('quote_time')},age_minutes={age}"
    return None


def summary_key(dt: datetime) -> str | None:
    current = dt.strftime("%H:%M")
    return current


def due_strategy_summary(config: dict[str, Any], state: dict[str, Any]) -> tuple[str, str] | None:
    dt = now_dt()
    current = summary_key(dt)
    if current not in set(config.get("strategy_summary_times", [])):
        return None
    key = f"{dt.date().isoformat()}:{current}"
    if key in set(state.get("sent_strategy_summaries", [])):
        return None
    return key, current


def build_strategy_summary(config: dict[str, Any], snapshot: dict[str, Any], time_label: str) -> tuple[str, str]:
    t = config["thresholds"]
    buy = float(snapshot["estimated_app_buy_price"])
    sell = float(snapshot["estimated_app_sell_price"])
    pnl = float(snapshot["floating_pnl"])
    pct = float(snapshot["floating_pnl_pct"]) * 100
    p = snapshot["primary"]
    core_target = float(config.get("core_physical_target_grams", 0))
    below_core_target = core_target > 0 and float(snapshot["grams"]) <= core_target
    session_note = (
        "上金所Au99.99处于常规交易时段，报价参考性较好。"
        if is_sge_session_open(now_dt())
        else "当前不在上金所Au99.99常规交易时段，AU9999可能是陈旧报价；招行App成交页价格仍需单独确认。"
    )

    if below_core_target and buy <= float(t["buy_add_price"]):
        stance = "仍低于婚用实物目标50克，进入补仓观察区，只适合分批小额增加底仓。"
    elif below_core_target:
        stance = "仍低于婚用实物目标50克，当前底仓不因小浮盈卖出，等待更低成本分批补足。"
    elif sell >= float(t["sell_take_profit_price"]):
        stance = "触及明显止盈区，优先准备卖出兑现。"
    elif sell >= float(t["sell_breakeven_price"]):
        stance = "接近/达到回本区，优先考虑减仓降风险。"
    elif sell <= float(t["sell_risk_price"]):
        stance = "处于风险区，若同时放量下破或贴近日低，应准备减仓。"
    elif buy <= float(t["buy_wait_freefall_price"]):
        stance = "低于急跌等待线，暂不急着补仓，等企稳。"
    elif buy <= float(t["buy_add_price"]):
        stance = "进入小额补仓观察区，只适合轻仓试探。"
    else:
        stance = "未触发买卖阈值，继续观察。"

    title = f"招行黄金盘中策略摘要 {time_label}"
    body = "\n".join(
        [
            f"标的：{config['display_name']}，持仓{snapshot['grams']:.2f}克，成本{snapshot['cost_price_per_g']:.2f}元/克。",
            f"目标：婚用实物黄金{core_target:.2f}克；超过目标的部分才按投资仓止盈止损。",
            f"AU9999：{p['price']:.2f}，较昨收{p['up_down']:+.2f}，今开{p['open']:.2f}，区间{p['low']:.2f}-{p['high']:.2f}，行情时间{p['quote_time']}。",
            f"估算招行买入价{buy:.2f}，估算卖出价{sell:.2f}；若此刻卖出，浮动盈亏{pnl:+.2f}元（{pct:+.2f}%）。",
            f"策略判断：{stance}",
            f"关键线：补仓观察{float(t['buy_add_price']):.2f}，急跌等待{float(t['buy_wait_freefall_price']):.2f}，风险减仓{float(t['sell_risk_price']):.2f}，回本{float(t['sell_breakeven_price']):.2f}，止盈{float(t['sell_take_profit_price']):.2f}。",
            session_note,
            "提醒：脚本只做监测和通知，不会自动下单；操作前以招行App实际成交页为准。",
        ]
    )
    return title, body


def vibetrading_enabled() -> bool:
    return bool(
        os.environ.get("VIBETRADING_REVIEW_CMD")
        or os.environ.get("VIBETRADING_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )


def gold_needs_vibetrading_review(config: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    t = config["thresholds"]
    buy = float(snapshot["estimated_app_buy_price"])
    sell = float(snapshot["estimated_app_sell_price"])
    p = snapshot["primary"]
    proximity = float(config.get("vibetrading_proximity_yuan", 15.0))
    important_levels = [
        float(t["buy_add_price"]),
        float(t["buy_wait_freefall_price"]),
        float(t["sell_risk_price"]),
        float(t["sell_breakeven_price"]),
        float(t["sell_take_profit_price"]),
    ]
    near_level = any(abs(buy - level) <= proximity or abs(sell - level) <= proximity for level in important_levels)
    large_move = abs(float(p["up_down"])) >= float(t.get("risk_daily_drop_abs", 8.0))
    near_extreme = float(p["high"]) > 0 and (
        float(p["price"]) >= float(p["high"]) - 2 or float(p["price"]) <= float(p["low"]) + 2
    )
    return near_level or large_move or near_extreme or decide(config, snapshot) is not None


def gold_review_tier(config: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, str]:
    p = snapshot["primary"]
    t = config["thresholds"]
    buy = float(snapshot["estimated_app_buy_price"])
    sell = float(snapshot["estimated_app_sell_price"])
    hard_decision = decide(config, snapshot) is not None
    extreme_move = abs(float(p["up_down"])) >= float(t.get("deep_drop_abs", 15.0))
    close_to_action = any(
        abs(value - level) <= 5.0
        for value in (buy, sell)
        for level in (
            float(t["buy_add_price"]),
            float(t["sell_risk_price"]),
            float(t["sell_breakeven_price"]),
            float(t["sell_take_profit_price"]),
        )
    )
    if hard_decision or extreme_move or close_to_action:
        return "reasoner", os.environ.get("VIBETRADING_REASONER_MODEL", "deepseek-reasoner")
    return "fast", os.environ.get("VIBETRADING_FAST_MODEL", os.environ.get("VIBETRADING_MODEL", "deepseek-chat"))


def run_vibetrading_review(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not vibetrading_enabled():
        return None
    command = os.environ.get("VIBETRADING_REVIEW_CMD") or "/home/admin/ai/trade/vibetrading_review.py"
    try:
        proc = subprocess.run(
            command.split(),
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=int(os.environ.get("VIBETRADING_REVIEW_TIMEOUT", "60")),
            check=False,
        )
    except Exception as exc:
        log(f"VIBETRADING_ERROR command_failed {exc}")
        return None
    if proc.returncode != 0:
        log(f"VIBETRADING_ERROR exit={proc.returncode} stderr={proc.stderr.strip()[:500]}")
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        log(f"VIBETRADING_ERROR bad_json {exc} stdout={proc.stdout[:500]}")
        return None


def apply_gold_rule_updates(
    config: dict[str, Any],
    review: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, float]:
    ranges = {
        "buy_add_price": (500.0, 1300.0),
        "buy_wait_freefall_price": (500.0, 1300.0),
        "sell_risk_price": (500.0, 1300.0),
        "sell_breakeven_price": (500.0, 1300.0),
        "sell_take_profit_price": (500.0, 1300.0),
        "risk_daily_drop_abs": (1.0, 50.0),
        "deep_drop_abs": (1.0, 80.0),
    }
    updates = review.get("rule_updates") or {}
    applied: dict[str, float] = {}
    if not isinstance(updates, dict):
        return applied
    for key, value in updates.items():
        if key not in ranges:
            continue
        try:
            new_value = round(float(value), 2)
            old_value = float(config["thresholds"][key])
        except (TypeError, ValueError):
            continue
        min_value, max_value = ranges[key]
        if not min_value <= new_value <= max_value:
            continue
        max_delta = 50.0 if key.endswith("_price") else 10.0
        if abs(new_value - old_value) > max_delta:
            continue
        config["thresholds"][key] = new_value
        applied[key] = new_value
    if applied:
        config["last_vibetrading_update"] = {
            "updated_at": now(),
            "applied": applied,
            "reason": str(review.get("update_reason", "")),
            "snapshot": snapshot,
        }
        save_json(CONFIG_PATH, config)
    return applied


def maybe_send_vibetrading_update(
    config: dict[str, Any],
    state: dict[str, Any],
    snapshot: dict[str, Any],
    key: str,
    time_label: str,
) -> bool:
    if not gold_needs_vibetrading_review(config, snapshot):
        log(f"SUMMARY_SKIP quiet {key}")
        return False
    review_tier, preferred_model = gold_review_tier(config, snapshot)
    payload = {
        "asset": "cmb_gold",
        "time_label": time_label,
        "review_tier": review_tier,
        "preferred_model": preferred_model,
        "snapshot": snapshot,
        "current_rules": config["thresholds"],
        "allowed_rule_updates": list(config["thresholds"].keys()),
        "instruction": "只在接近买卖决策点、波动明显或原规则需要调整时通知。若更新规则，必须说明理由。",
    }
    review = run_vibetrading_review(payload)
    if not review:
        log(f"SUMMARY_REVIEW_SKIPPED no_llm_or_failed {key}")
        return False
    applied = apply_gold_rule_updates(config, review, snapshot)
    # Keep scheduled reviews quiet unless they actually change future rules.
    # Actionable buy/sell alerts are handled by the separate decision path.
    should_notify = bool(applied)
    if not should_notify:
        log(
            f"SUMMARY_REVIEW no_notify {key} "
            f"model_notify={bool(review.get('notify'))} analysis={str(review.get('analysis', ''))[:200]}"
        )
        return False
    update_text = "无规则更新。"
    if applied:
        update_text = "规则已更新：" + "，".join(f"{name}={value:.2f}" for name, value in applied.items())
    title = str(review.get("notification_title") or f"招行黄金策略已复核 {time_label}")
    body = "\n".join(
        [
            str(review.get("notification_body") or review.get("analysis") or "vibetrading 认为需要关注。"),
            update_text,
            f"更新理由：{review.get('update_reason', '未提供')}",
            f"操作反馈：{feedback_url(key)}",
            "不提交反馈则系统继续按未操作处理。",
            "提醒：脚本只通知，不会自动下单；操作前以招行App实际成交页为准。",
        ]
    )
    send_serverchan(title, body)
    log(f"SUMMARY_REVIEW_NOTIFY {key} applied={applied}")
    return True


def maybe_send_strategy_summary(config: dict[str, Any], state: dict[str, Any], snapshot: dict[str, Any]) -> None:
    due = due_strategy_summary(config, state)
    if not due:
        return
    key, time_label = due
    try:
        maybe_send_vibetrading_update(config, state, snapshot, key, time_label)
    except Exception as exc:
        log(f"SUMMARY_ERROR {key} {exc}")
        return
    state.setdefault("sent_strategy_summaries", []).append(key)
    log(f"SUMMARY_DONE {key}")


def decide(config: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any] | None:
    t = config["thresholds"]
    buy = float(snapshot["estimated_app_buy_price"])
    sell = float(snapshot["estimated_app_sell_price"])
    cost = float(snapshot["cost_price_per_g"])
    pnl = float(snapshot["floating_pnl"])
    pct = float(snapshot["floating_pnl_pct"]) * 100
    p = snapshot["primary"]
    up_down = float(p["up_down"])
    low = float(p["low"])
    high = float(p["high"])
    pre_close = float(p["pre_close"])
    core_target = float(config.get("core_physical_target_grams", 0))
    investment_surplus = max(0.0, float(snapshot["grams"]) - core_target)
    can_sell_investment_surplus = core_target <= 0 or investment_surplus > 0

    common = [
        f"标的：{config['display_name']}，持仓{snapshot['grams']:.2f}克，成本{cost:.2f}元/克。",
        f"目标：先低成本攒够婚用实物黄金{core_target:.2f}克；当前还差{max(0.0, core_target - snapshot['grams']):.2f}克，超过目标的部分才按投资仓交易。",
        f"当前估算招行买入价{buy:.2f}，估算卖出价{sell:.2f}（按实时Au99.99 {p['price']:.2f} + 校准{config['app_buy_offset_from_au9999']:.2f} - 卖出差价{config['sell_spread_per_g']:.2f}）。",
        f"若此刻卖出，约{snapshot['liquidation_value']:.2f}元，浮动盈亏{pnl:+.2f}元（{pct:+.2f}%）。",
        f"行情复核：Au99.99昨收{pre_close:.2f}，今高{high:.2f}，今低{low:.2f}，当前较昨收{up_down:+.2f}元。",
    ]

    if sell >= float(t["sell_take_profit_price"]) and can_sell_investment_surplus:
        sell_grams = min(10.0, investment_surplus)
        action = f"卖出{sell_grams:g}克投资仓，先兑现明显盈利；婚用目标仓不动。"
        key = f"sell_take_profit:{price_band(sell)}"
        reason = common + [
            f"触发：估算卖出价{sell:.2f} >= 止盈线{t['sell_take_profit_price']:.2f}，已明显高于成本{cost:.2f}。",
            f"建议：{action}",
            "依据：这笔仓位此前处于亏损，回到明显盈利区后优先锁定收益，避免黄金高位波动把利润吐回。",
            f"失效条件：二次复核时卖出价跌回{cost:.2f}下方，或招行App实际卖出价明显低于估算价。",
        ]
        return {"action_type": "sell", "alert_key": key, "title": "招行黄金卖出提醒：明显盈利", "body": "\n".join(reason), "snapshot": snapshot}

    if sell >= float(t["sell_breakeven_price"]) and can_sell_investment_surplus:
        sell_grams = min(5.0, investment_surplus)
        action = f"可卖出{sell_grams:g}克投资仓降风险；婚用目标仓不动。"
        key = f"sell_breakeven:{price_band(sell)}"
        reason = common + [
            f"触发：估算卖出价{sell:.2f} >= 回本线{t['sell_breakeven_price']:.2f}。",
            f"建议：{action}",
            "依据：你的持仓成本较高，价格回到可回本区后，先把亏损风险降下来，比继续硬扛更符合低频、低回撤目标。",
            f"失效条件：二次复核时卖出价跌回{cost:.2f}下方。",
        ]
        return {"action_type": "sell", "alert_key": key, "title": "招行黄金回本卖出提醒", "body": "\n".join(reason), "snapshot": snapshot}

    weak_break = (
        can_sell_investment_surplus
        and sell <= float(t["sell_risk_price"])
        and up_down <= -float(t["risk_daily_drop_abs"])
        and p["price"] <= low + 2
    )
    if weak_break:
        action = "卖出或减仓10克，若不想全卖，至少先减5克。"
        key = f"sell_risk:{price_band(sell)}"
        reason = common + [
            f"触发：估算卖出价{sell:.2f} <= 风险线{t['sell_risk_price']:.2f}，且日内跌幅{up_down:+.2f}元、价格贴近日内低点{low:.2f}。",
            f"建议：{action}",
            "依据：这是亏损仓位，若价格继续破位且没有反弹迹象，先控制回撤优先于摊低成本。",
            f"失效条件：二次复核时价格收回风险线{t['sell_risk_price']:.2f}上方，或不再贴近日内低点。",
        ]
        return {"action_type": "sell", "alert_key": key, "title": "招行黄金风险减仓提醒", "body": "\n".join(reason), "snapshot": snapshot}

    stable_pullback = buy <= float(t["buy_add_price"]) and buy > float(t["buy_wait_freefall_price"]) and up_down > -float(t["deep_drop_abs"])
    if stable_pullback:
        action = "可考虑小额补仓5克，不建议一次性加太多。"
        key = f"buy_add:{price_band(buy)}"
        new_cost = (cost * snapshot["grams"] + buy * 5) / (snapshot["grams"] + 5)
        reason = common + [
            f"触发：估算买入价{buy:.2f} <= 补仓观察线{t['buy_add_price']:.2f}，且未达到急跌等待线{t['buy_wait_freefall_price']:.2f}。",
            f"建议：{action}",
            f"依据：若补5克，估算总持仓15克，平均成本约{new_cost:.2f}元/克；只做小额补仓，避免在下跌趋势里越跌越买。",
            f"失效条件：二次复核时买入价回到{t['buy_add_price']:.2f}上方，或跌破{t['buy_wait_freefall_price']:.2f}附近进入急跌状态。",
        ]
        return {"action_type": "buy", "alert_key": key, "title": "招行黄金小额补仓提醒", "body": "\n".join(reason), "snapshot": snapshot}

    return None


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


def recent_alert_sent(state: dict[str, Any], decision: dict[str, Any], cooldown_minutes: int) -> bool:
    cutoff = now_dt() - timedelta(minutes=cooldown_minutes)
    for alert in state.get("sent_alerts", []):
        if alert.get("alert_key") != decision["alert_key"]:
            continue
        sent_at = alert.get("sent_at")
        if not sent_at:
            continue
        try:
            if datetime.fromisoformat(sent_at) >= cutoff:
                return True
        except ValueError:
            continue
    return False


def refreshed_decision(config: dict[str, Any]) -> dict[str, Any] | None:
    quote = fetch_gold(config)
    snapshot = build_snapshot(config, quote)
    if sge_quote_freshness_issue(snapshot, now_dt()):
        return None
    decision = decide(config, snapshot)
    if decision:
        decision["snapshot"] = snapshot
    return decision


def main() -> int:
    config = load_json(CONFIG_PATH)
    state = load_json(STATE_PATH)
    state["last_checked_at"] = now()

    try:
        quote = fetch_gold(config)
        snapshot = build_snapshot(config, quote)
    except Exception as exc:
        state["last_error"] = str(exc)
        save_json(STATE_PATH, state)
        log(f"ERROR {exc}")
        return 2

    state["last_success_at"] = state["last_checked_at"]
    state["last_error"] = None
    state["last_snapshot"] = snapshot
    freshness_issue = sge_quote_freshness_issue(snapshot, now_dt())
    if freshness_issue:
        save_json(STATE_PATH, state)
        log(
            "SKIP market_closed_or_stale "
            f"{freshness_issue} "
            f"quote_time={snapshot['primary'].get('quote_time')} "
            f"buy={snapshot['estimated_app_buy_price']:.2f} "
            f"sell={snapshot['estimated_app_sell_price']:.2f}"
        )
        return 0

    maybe_send_strategy_summary(config, state, snapshot)
    decision = decide(config, snapshot)
    if not decision:
        save_json(STATE_PATH, state)
        log(
            "OK no_action "
            f"buy={snapshot['estimated_app_buy_price']:.2f} "
            f"sell={snapshot['estimated_app_sell_price']:.2f} "
            f"pnl={snapshot['floating_pnl']:+.2f}"
        )
        return 0

    if recent_alert_sent(state, decision, int(config["alert_cooldown_minutes"])):
        save_json(STATE_PATH, state)
        log(f"SKIP cooldown {decision['alert_key']}")
        return 0

    time.sleep(float(config["recheck_delay_seconds"]))
    second = refreshed_decision(config)
    if not second:
        state["last_snapshot"] = snapshot
        save_json(STATE_PATH, state)
        log(f"SKIP no_action_after_recheck first={decision['alert_key']}")
        return 0

    if recent_alert_sent(state, second, int(config["alert_cooldown_minutes"])):
        save_json(STATE_PATH, state)
        log(f"SKIP cooldown_after_recheck {second['alert_key']}")
        return 0

    rule_note = (
        f"二次实时复核：首次触发规则为 {decision['alert_key']}；"
        f"最终按复核后的 {second['alert_key']} 执行通知。"
    )
    url = feedback_url(second["alert_key"])
    body = (
        second["body"]
        + f"\n\n{rule_note}"
        + f"\n操作反馈：{url}"
        + "\n不提交反馈则系统继续按未操作处理。"
        + "\n提醒：脚本不会自动下单，执行前以招行App实际成交页为准。"
    )
    send_serverchan(second["title"], body)
    alert_record = {
        "sent_at": now(),
        "alert_key": second["alert_key"],
        "action_type": second["action_type"],
        "feedback_status": "pending",
        "feedback_url": url,
        "snapshot": second["snapshot"],
    }
    state.setdefault("sent_alerts", []).append(alert_record)
    state["last_snapshot"] = second["snapshot"]
    save_json(STATE_PATH, state)
    log(f"ALERT {second['alert_key']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
