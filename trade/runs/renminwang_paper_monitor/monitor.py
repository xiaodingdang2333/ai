from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state.json"
LOG_PATH = ROOT / "trades.log"
FEEDBACK_TOKEN_PATH = Path("/home/admin/ai/output/qr-login/renminwang.token")

SYMBOL = "sh603000"
NAME = "Renminwang"
DISPLAY_NAME = "People.cn"
CODE = "603000.SH"

INITIAL_COST = 18.40
INITIAL_SHARES = 700
CURRENT_SHARES = 500
SOLD_SHARES_AT_1660 = 200
LATEST_PORTFOLIO_BASELINE = 178906.31

BREAK_LEVEL = 16.60
REBOUND_SELL_LOW = 16.50
REBOUND_SELL_HIGH = 16.80
ACTIVE_SELL_LEVEL = 16.05
CLOSE_WEAK_LEVEL = 16.10
CLEAR_LEVEL = 15.50
SECOND_LEVEL = 16.20
RECLAIM_LEVEL = 17.50
BUY_CEILING = 18.50
TAKE_PROFIT_1 = 19.30
TAKE_PROFIT_2 = 20.20
TAKE_PROFIT_3 = 21.20
LOT_SIZE = 100
INTRADAY_START = "09:30:00"
MARKET_CLOSE = "15:00:00"
LOCAL_CHECK_START = time(9, 25)
LOCAL_CHECK_END = time(15, 20)
STRATEGY_SUMMARY_TIMES = {"09:40", "10:30", "11:20", "13:30", "14:45", "15:05"}
OVERRIDABLE_RULES = {
    "rebound_sell_low",
    "rebound_sell_high",
    "active_sell_level",
    "close_weak_level",
    "clear_level",
}


def _http_get(url: str, encoding: str = "utf-8") -> str:
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        },
    )
    with request.urlopen(req, timeout=15) as resp:
        return resp.read().decode(encoding, "ignore")


def fetch_quote() -> dict[str, Any]:
    try:
        text = _http_get(f"https://hq.sinajs.cn/list={SYMBOL}", "gbk")
        raw = text.split('="', 1)[1].rsplit('"', 1)[0].split(",")
        return {
            "name": raw[0],
            "open": float(raw[1]),
            "prev_close": float(raw[2]),
            "price": float(raw[3]),
            "high": float(raw[4]),
            "low": float(raw[5]),
            "volume": float(raw[8]),
            "amount": float(raw[9]),
            "date": raw[30],
            "time": raw[31],
        }
    except (IndexError, ValueError, error.URLError):
        return fetch_quote_tencent()


def fetch_quote_tencent() -> dict[str, Any]:
    text = _http_get(f"https://qt.gtimg.cn/q={SYMBOL}", "gbk")
    raw = text.split('="', 1)[1].rsplit('"', 1)[0].split("~")
    timestamp = raw[30]
    quote_date = f"{timestamp[0:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
    quote_time = f"{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}"
    return {
        "name": raw[1],
        "open": float(raw[5]),
        "prev_close": float(raw[4]),
        "price": float(raw[3]),
        "high": float(raw[33]),
        "low": float(raw[34]),
        "volume": float(raw[6]),
        "amount": float(raw[37]) * 10000 if raw[37] else 0.0,
        "date": quote_date,
        "time": quote_time,
    }


def fetch_daily(datalen: int = 80) -> list[dict[str, Any]]:
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={SYMBOL}&scale=240&ma=no&datalen={datalen}"
    )
    rows = json.loads(_http_get(url))
    return [
        {
            "date": row["day"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for row in rows
    ]


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "code": CODE,
        "name": NAME,
        "cost": INITIAL_COST,
        "position": CURRENT_SHARES,
        "cash": round(SOLD_SHARES_AT_1660 * BREAK_LEVEL, 2),
        "first_break_done": True,
        "first_break_date": "2026-06-11",
        "second_break_done": False,
        "clear_done": False,
        "reclaim_alerted": False,
        "pending_sell": None,
        "pending_buy": None,
        "pending_take_profit": None,
        "take_profit_1_done": False,
        "take_profit_2_done": False,
        "take_profit_3_done": False,
        "intraday_alert_dates": [],
        "real_alert_keys": [],
        "close_processed_dates": [],
        "sent_strategy_summaries": [],
        "strategy_overrides": {},
        "actions": [],
    }


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("code", CODE)
    state.setdefault("name", NAME)
    state.setdefault("cost", INITIAL_COST)
    if int(state.get("position", INITIAL_SHARES)) == INITIAL_SHARES and not state.get("actions"):
        state["position"] = CURRENT_SHARES
        state["cash"] = round(SOLD_SHARES_AT_1660 * BREAK_LEVEL, 2)
        state["first_break_done"] = True
        state["first_break_date"] = "2026-06-11"
    state.setdefault("position", CURRENT_SHARES)
    state.setdefault("cash", round(SOLD_SHARES_AT_1660 * BREAK_LEVEL, 2))
    state.setdefault("first_break_done", True)
    state.setdefault("first_break_date", "2026-06-11")
    state.setdefault("second_break_done", False)
    state.setdefault("clear_done", False)
    state.setdefault("reclaim_alerted", False)
    state.setdefault("pending_sell", None)
    state.setdefault("pending_buy", None)
    state.setdefault("pending_take_profit", None)
    state.setdefault("take_profit_1_done", False)
    state.setdefault("take_profit_2_done", False)
    state.setdefault("take_profit_3_done", False)
    state.setdefault("intraday_alert_dates", [])
    state.setdefault("real_alert_keys", [])
    state.setdefault("close_processed_dates", [])
    state.setdefault("sent_strategy_summaries", [])
    state.setdefault("strategy_overrides", {})
    state.setdefault("actions", [])
    return state


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def send_notification(title: str, body: str) -> None:
    pushplus_token = os.environ.get("PUSHPLUS_TOKEN")
    if pushplus_token:
        data = parse.urlencode(
            {"token": pushplus_token, "title": title, "content": body}
        ).encode("utf-8")
        req = request.Request("https://www.pushplus.plus/send", data=data, method="POST")
        with request.urlopen(req, timeout=15) as resp:
            resp.read()
        return

    ntfy_topic = os.environ.get("NTFY_TOPIC")
    ntfy_server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    ntfy_token = os.environ.get("NTFY_TOKEN")

    if ntfy_topic:
        headers = {
            "Title": "Renminwang Alert",
            "Priority": "max",
            "Tags": "warning,chart_with_downwards_trend",
        }
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

    webhook = os.environ.get("WECHAT_WEBHOOK_URL")
    server_chan_key = os.environ.get("SERVER_CHAN_SENDKEY")

    if webhook:
        payload = json.dumps(
            {"msgtype": "text", "text": {"content": f"{title}\n\n{body}"}},
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            webhook,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=15) as resp:
            resp.read()
        return

    if server_chan_key:
        data = parse.urlencode({"title": title, "desp": body}).encode("utf-8")
        req = request.Request(
            f"https://sctapi.ftqq.com/{server_chan_key}.send",
            data=data,
            method="POST",
        )
        with request.urlopen(req, timeout=15) as resp:
            resp.read()
        return

    raise RuntimeError(
        "No notifier configured. Set NTFY_TOPIC, WECHAT_WEBHOOK_URL, PUSHPLUS_TOKEN, or SERVER_CHAN_SENDKEY."
    )


def has_notifier() -> bool:
    return any(
        os.environ.get(name)
        for name in ("NTFY_TOPIC", "WECHAT_WEBHOOK_URL", "PUSHPLUS_TOKEN", "SERVER_CHAN_SENDKEY")
    )


def append_log(line: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def feedback_url(action: dict[str, Any]) -> str:
    base_url = os.environ.get("RENMINWANG_FEEDBACK_BASE_URL", "http://8.212.144.72:8090")
    token = FEEDBACK_TOKEN_PATH.read_text(encoding="utf-8").strip()
    params = parse.urlencode(
        {
            "token": token,
            "alert_key": action.get("alert_key", ""),
        }
    )
    return f"{base_url.rstrip('/')}/renminwang.html?{params}"


def set_position_from_cli(argv: list[str]) -> bool:
    if len(argv) != 3 or argv[1] != "--set-position":
        return False
    shares = int(argv[2])
    state = normalize_state(load_state())
    state["position"] = shares
    state["manual_position_updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    print(f"Position updated to {shares} shares.")
    return True


def is_intraday_check(quote: dict[str, Any]) -> bool:
    time = str(quote["time"])
    return INTRADAY_START <= time < MARKET_CLOSE


def is_close_check(quote: dict[str, Any]) -> bool:
    return str(quote["time"]) >= MARKET_CLOSE


def should_check_now(quote: dict[str, Any]) -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if now.date().isoformat() != str(quote["date"]):
        return False
    try:
        quote_dt = datetime.fromisoformat(f"{quote['date']}T{quote['time']}")
    except ValueError:
        return False
    if quote_dt > now + timedelta(minutes=2):
        return False
    if now - quote_dt > timedelta(minutes=25):
        return False
    return LOCAL_CHECK_START <= now.time() <= LOCAL_CHECK_END


def rule_levels(state: dict[str, Any]) -> dict[str, float]:
    overrides = state.get("strategy_overrides") or {}

    def override(name: str, default: float) -> float:
        try:
            return float(overrides.get(name, default))
        except (TypeError, ValueError):
            return default

    return {
        "rebound_sell_low": override("rebound_sell_low", REBOUND_SELL_LOW),
        "rebound_sell_high": override("rebound_sell_high", REBOUND_SELL_HIGH),
        "active_sell_level": override("active_sell_level", ACTIVE_SELL_LEVEL),
        "close_weak_level": override("close_weak_level", CLOSE_WEAK_LEVEL),
        "clear_level": override("clear_level", CLEAR_LEVEL),
    }


def volume_ratio(quote: dict[str, Any], daily: list[dict[str, Any]]) -> float:
    vol_ma20 = sum(row["volume"] for row in daily[-20:]) / 20
    return float(quote["volume"]) / vol_ma20 if vol_ma20 else 0.0


def lot_floor(shares: int) -> int:
    return max(0, shares // LOT_SIZE * LOT_SIZE)


def available_buy_shares(state: dict[str, Any], price: float) -> int:
    missing = max(0, INITIAL_SHARES - int(state["position"]))
    cash_shares = int(float(state.get("cash", 0.0)) // price)
    return lot_floor(min(missing, cash_shares))


def make_intraday_alert(
    state: dict[str, Any],
    quote: dict[str, Any],
    daily: list[dict[str, Any]],
) -> dict[str, Any] | None:
    price = float(quote["price"])
    date = str(quote["date"])
    if int(state["position"]) <= 0:
        return None
    if date in set(state.get("intraday_alert_dates", [])):
        return None
    if not is_intraday_check(quote):
        return None
    if price < BREAK_LEVEL:
        return {
            "type": "INTRADAY_ALERT",
            "shares": 0,
            "reason": "Intraday price is below 16.60. This is only a warning; no paper sale before close confirmation.",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(volume_ratio(quote, daily), 2),
        }
    return None


def make_real_trade_alert(state: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any] | None:
    price = float(quote["price"])
    date = str(quote["date"])
    position = int(state.get("position", 0))
    levels = rule_levels(state)
    if position <= 0:
        return None
    if not is_intraday_check(quote) and not is_close_check(quote):
        return None

    if price < levels["clear_level"]:
        kind = "clear_below_1550"
        return {
            "type": "REAL_TRADE_ALERT",
            "kind": kind,
            "shares": position,
            "reason": f"跌破 {levels['clear_level']:.2f}，弱势继续扩大；建议卖出剩余观察仓，不再摊成本。",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": None,
            "alert_key": f"{date}:{kind}",
        }

    if is_close_check(quote) and price < levels["close_weak_level"] and position > 300:
        kind = "close_below_1610"
        return {
            "type": "REAL_TRADE_ALERT",
            "kind": kind,
            "shares": min(200, position - 300),
            "reason": f"收盘低于 {levels['close_weak_level']:.2f}，弱势没有修复；建议卖出 200 股，把人民网降到 300 股观察仓。",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": None,
            "alert_key": f"{date}:{kind}",
        }

    if price <= levels["active_sell_level"] and position > 300:
        kind = "sell_200_at_or_below_1605"
        return {
            "type": "REAL_TRADE_ALERT",
            "kind": kind,
            "shares": min(200, position - 300),
            "reason": f"价格已到 {levels['active_sell_level']:.2f} 或以下，人民网仍是组合里的高波动非核心仓；建议卖出 200 股，把仓位降到 300 股。",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": None,
            "alert_key": f"{date}:{kind}",
        }

    if levels["rebound_sell_low"] <= price <= levels["rebound_sell_high"] and position > 300:
        kind = "sell_200_rebound_1650_1680"
        return {
            "type": "REAL_TRADE_ALERT",
            "kind": kind,
            "shares": min(200, position - 300),
            "reason": f"反抽到 {levels['rebound_sell_low']:.2f}-{levels['rebound_sell_high']:.2f} 区间；如果前面还没卖，建议趁反抽卖出 200 股，把仓位降到 300 股。",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": None,
            "alert_key": f"{date}:{kind}",
        }

    return None


def apply_vibetrading_review(
    state: dict[str, Any],
    quote: dict[str, Any],
    action: dict[str, Any],
) -> dict[str, Any] | None:
    price = float(quote["price"])
    prev_close = float(quote.get("prev_close") or 0)
    open_price = float(quote.get("open") or 0)
    high = float(quote.get("high") or price)
    low = float(quote.get("low") or price)
    position = int(state.get("position", 0))
    sold_cash = float(state.get("cash", 0.0))
    people_total = position * price + sold_cash
    people_pnl = people_total - INITIAL_COST * INITIAL_SHARES
    people_weight = position * price / LATEST_PORTFOLIO_BASELINE * 100
    pct = (price / prev_close - 1) * 100 if prev_close else 0.0
    day_range = high - low
    rebound_from_low = price - low
    close_check = is_close_check(quote)
    levels = rule_levels(state)

    details = [
        f"行情：最新价{price:.2f}，较昨收{pct:.2f}%，开盘{open_price:.2f}，日内区间{low:.2f}-{high:.2f}。",
        f"组合：记录持仓{position}股，剩余市值约{position * price:.0f}元，占最新组合基准约{people_weight:.1f}%；人民网这笔含已卖现金约盈亏{people_pnl:.0f}元。",
        "原则：人民网是高波动非核心个股，不补仓摊成本；目标是找机会把500股降到300股观察仓，同时避免在明显反抽前追最低卖。",
    ]

    if position > 300 and action.get("kind") in {"sell_200_at_or_below_1605", "close_below_1610"}:
        if not close_check and price >= 15.90 and rebound_from_low >= max(0.10, day_range * 0.25):
            return {
                **action,
                "kind": "wait_rebound_after_vibetrading_review",
                "shares": 0,
                "reason": (
                    "\n".join(
                        details
                        + [
                            f"复核结论：当前不是继续急杀，且从日内低点有修复；本次修正为先等反抽到{levels['active_sell_level'] + 0.25:.2f}-{levels['rebound_sell_low']:.2f}再卖200股。",
                            "失效条件：如果后续跌破15.90且不能快速回到16.00上方，改为纪律卖出200股。",
                        ]
                    )
                ),
                "alert_key": f"{action['date']}:wait_rebound_after_vibetrading_review",
            }
        if close_check and price >= 16.00:
            return {
                **action,
                "reason": (
                    "\n".join(
                        details
                        + [
                            f"复核结论：收盘仍低于{levels['close_weak_level']:.2f}但没有跌破16.00，不建议在尾盘最低附近追卖。",
                            f"操作条件：明天优先等{levels['active_sell_level'] + 0.25:.2f}-{levels['rebound_sell_low']:.2f}反抽卖200股；若跌破15.90且10:00前拉不回16.00，再纪律卖出200股。",
                        ]
                    )
                ),
            }

    return {
        **action,
        "reason": "\n".join(details + [f"触发规则：{action['reason']}"]),
    }


def summary_key_now(quote: dict[str, Any]) -> tuple[str, str] | None:
    current = datetime.now().strftime("%H:%M")
    if current not in STRATEGY_SUMMARY_TIMES:
        return None
    return f"{quote['date']}:{current}", current


def renminwang_needs_vibetrading_review(state: dict[str, Any], quote: dict[str, Any]) -> bool:
    price = float(quote["price"])
    prev_close = float(quote.get("prev_close") or 0)
    high = float(quote.get("high") or price)
    low = float(quote.get("low") or price)
    levels = rule_levels(state)
    proximity = float(os.environ.get("RENMINWANG_VIBETRADING_PROXIMITY", "0.25"))
    important_levels = list(levels.values())
    near_level = any(abs(price - level) <= proximity for level in important_levels)
    pct_move = abs(price / prev_close - 1) * 100 if prev_close else 0.0
    near_extreme = price >= high - 0.08 or price <= low + 0.08
    return near_level or pct_move >= 2.0 or near_extreme or make_real_trade_alert(state, quote) is not None


def renminwang_review_tier(state: dict[str, Any], quote: dict[str, Any]) -> tuple[str, str]:
    price = float(quote["price"])
    prev_close = float(quote.get("prev_close") or 0)
    levels = rule_levels(state)
    hard_action = make_real_trade_alert(state, quote) is not None
    pct_move = abs(price / prev_close - 1) * 100 if prev_close else 0.0
    close_to_action = (
        abs(price - levels["active_sell_level"]) <= 0.08
        or abs(price - levels["clear_level"]) <= 0.15
        or abs(price - levels["close_weak_level"]) <= 0.08
    )
    if hard_action or pct_move >= 4.0 or close_to_action:
        return "reasoner", os.environ.get("VIBETRADING_REASONER_MODEL", "deepseek-reasoner")
    return "fast", os.environ.get("VIBETRADING_FAST_MODEL", os.environ.get("VIBETRADING_MODEL", "deepseek-chat"))


def run_vibetrading_review(payload: dict[str, Any]) -> dict[str, Any] | None:
    enabled = bool(
        os.environ.get("VIBETRADING_REVIEW_CMD")
        or os.environ.get("VIBETRADING_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    if not enabled:
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
        append_log(f"{datetime.now().isoformat(timespec='seconds')} VIBETRADING_ERROR command_failed {exc}")
        return None
    if proc.returncode != 0:
        append_log(
            f"{datetime.now().isoformat(timespec='seconds')} VIBETRADING_ERROR exit={proc.returncode} stderr={proc.stderr.strip()[:500]}"
        )
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        append_log(
            f"{datetime.now().isoformat(timespec='seconds')} VIBETRADING_ERROR bad_json {exc} stdout={proc.stdout[:500]}"
        )
        return None


def apply_renminwang_rule_updates(state: dict[str, Any], review: dict[str, Any]) -> dict[str, float]:
    updates = review.get("rule_updates") or {}
    if not isinstance(updates, dict):
        return {}
    current = rule_levels(state)
    applied: dict[str, float] = {}
    for key, value in updates.items():
        if key not in OVERRIDABLE_RULES:
            continue
        try:
            new_value = round(float(value), 2)
        except (TypeError, ValueError):
            continue
        old_value = current[key]
        if not 10.0 <= new_value <= 30.0:
            continue
        if abs(new_value - old_value) > 1.0:
            continue
        applied[key] = new_value
    if applied:
        merged = dict(state.get("strategy_overrides") or {})
        merged.update(applied)
        if (
            "rebound_sell_low" in merged
            and "rebound_sell_high" in merged
            and float(merged["rebound_sell_low"]) > float(merged["rebound_sell_high"])
        ):
            return {}
        state["strategy_overrides"] = merged
        state["last_vibetrading_update"] = {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "applied": applied,
            "reason": str(review.get("update_reason", "")),
        }
    return applied


def maybe_send_strategy_summary(state: dict[str, Any], quote: dict[str, Any]) -> None:
    due = summary_key_now(quote)
    if not due:
        return
    key, time_label = due
    if key in set(state.get("sent_strategy_summaries", [])):
        return
    if not renminwang_needs_vibetrading_review(state, quote):
        state.setdefault("sent_strategy_summaries", []).append(key)
        append_log(f"{datetime.now().isoformat(timespec='seconds')} SUMMARY_SKIP quiet {key}")
        return

    levels = rule_levels(state)
    review_tier, preferred_model = renminwang_review_tier(state, quote)
    payload = {
        "asset": "renminwang",
        "time_label": time_label,
        "review_tier": review_tier,
        "preferred_model": preferred_model,
        "quote": quote,
        "position": int(state.get("position", 0)),
        "cash": float(state.get("cash", 0.0)),
        "cost": INITIAL_COST,
        "current_rules": levels,
        "allowed_rule_updates": sorted(OVERRIDABLE_RULES),
        "instruction": "只在接近减仓/清仓/反抽卖出关键位、波动明显或原规则需要调整时通知。若更新规则，必须说明理由。",
    }
    review = run_vibetrading_review(payload)
    if not review:
        state.setdefault("sent_strategy_summaries", []).append(key)
        append_log(f"{datetime.now().isoformat(timespec='seconds')} SUMMARY_REVIEW_SKIPPED no_llm_or_failed {key}")
        return
    applied = apply_renminwang_rule_updates(state, review)
    # The model can be eager to mark near-level reviews as notify=true. Keep
    # scheduled reviews quiet unless they actually change future rules; hard
    # buy/sell alerts are sent by the real-trade alert path below.
    should_notify = bool(applied)
    state.setdefault("sent_strategy_summaries", []).append(key)
    if not should_notify:
        append_log(
            f"{datetime.now().isoformat(timespec='seconds')} SUMMARY_REVIEW no_notify {key} "
            f"model_notify={bool(review.get('notify'))} analysis={str(review.get('analysis', ''))[:200]}"
        )
        return
    if not has_notifier():
        append_log(f"{datetime.now().isoformat(timespec='seconds')} SUMMARY_REVIEW no_notifier {key} applied={applied}")
        return
    update_text = "无规则更新。"
    if applied:
        update_text = "规则已更新：" + "，".join(f"{name}={value:.2f}" for name, value in applied.items())
    title = str(review.get("notification_title") or f"人民网策略已复核 {time_label}")
    body = "\n".join(
        [
            str(review.get("notification_body") or review.get("analysis") or "vibetrading 认为需要关注。"),
            update_text,
            f"更新理由：{review.get('update_reason', '未提供')}",
            "提醒：脚本只通知，不会自动下单；真实操作后请用操作反馈链接同步持仓。",
        ]
    )
    send_notification(title, body)
    append_log(f"{datetime.now().isoformat(timespec='seconds')} SUMMARY_REVIEW_NOTIFY {key} applied={applied} {body}")


def make_pending_sell_action(
    state: dict[str, Any],
    quote: dict[str, Any],
    daily: list[dict[str, Any]],
) -> dict[str, Any] | None:
    pending = state.get("pending_sell")
    if not pending:
        return None

    date = str(quote["date"])
    if date <= str(pending["signal_date"]):
        return None

    price = float(quote["price"])
    vol_ratio = volume_ratio(quote, daily)
    shares = min(int(pending["shares"]), int(state["position"]))

    if shares <= 0:
        return {
            "type": "CANCEL_PENDING",
            "shares": 0,
            "reason": "Pending paper sell canceled because no paper position remains.",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
        }

    if price >= BREAK_LEVEL:
        return {
            "type": "CANCEL_PENDING",
            "shares": 0,
            "reason": "Next trading day price opened/recovered above 16.60; pending paper sell canceled.",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
        }

    return {
        "type": "SELL",
        "shares": shares,
        "reason": (
            f"Previous close triggered a paper sell plan below 16.60; "
            f"next trading day price is still below 16.60, execute paper sell. "
            f"Original signal: {pending['reason']}"
        ),
        "price": price,
        "date": date,
        "time": quote["time"],
        "vol_ratio": round(vol_ratio, 2),
        "signal_date": pending["signal_date"],
        "pending_kind": pending.get("kind"),
    }


def make_pending_take_profit_action(
    state: dict[str, Any],
    quote: dict[str, Any],
    daily: list[dict[str, Any]],
) -> dict[str, Any] | None:
    pending = state.get("pending_take_profit")
    if not pending:
        return None

    date = str(quote["date"])
    if date <= str(pending["signal_date"]):
        return None

    price = float(quote["price"])
    vol_ratio = volume_ratio(quote, daily)
    shares = min(int(pending["shares"]), int(state["position"]))

    if shares <= 0:
        return {
            "type": "CANCEL_TAKE_PROFIT",
            "shares": 0,
            "reason": "Pending take-profit canceled because no paper position remains.",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
        }

    if price < float(pending["trigger_price"]):
        return {
            "type": "CANCEL_TAKE_PROFIT",
            "shares": 0,
            "reason": "Next trading day price is below the take-profit trigger; pending take-profit canceled.",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
        }

    return {
        "type": "SELL",
        "shares": shares,
        "reason": (
            f"Previous close triggered take-profit level {pending['level']}; "
            f"next trading day price still satisfies the trigger, execute paper take-profit."
        ),
        "price": price,
        "date": date,
        "time": quote["time"],
        "vol_ratio": round(vol_ratio, 2),
        "signal_date": pending["signal_date"],
        "pending_kind": pending.get("kind"),
        "take_profit_level": pending["level"],
    }


def make_pending_buy_action(
    state: dict[str, Any],
    quote: dict[str, Any],
    daily: list[dict[str, Any]],
) -> dict[str, Any] | None:
    pending = state.get("pending_buy")
    if not pending:
        return None

    date = str(quote["date"])
    if date <= str(pending["signal_date"]):
        return None

    price = float(quote["price"])
    vol_ratio = volume_ratio(quote, daily)
    shares = min(int(pending["shares"]), available_buy_shares(state, price))

    if price < RECLAIM_LEVEL:
        return {
            "type": "CANCEL_BUY",
            "shares": 0,
            "reason": "Next trading day price failed to hold 17.50; pending paper buy canceled.",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
        }

    if price > BUY_CEILING:
        return {
            "type": "CANCEL_BUY",
            "shares": 0,
            "reason": "Next trading day price is above 18.50 buy ceiling; pending paper buy canceled to avoid chasing.",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
        }

    if shares <= 0:
        return {
            "type": "CANCEL_BUY",
            "shares": 0,
            "reason": "Pending paper buy canceled because there is no enough paper cash or missing position.",
            "price": price,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
        }

    return {
        "type": "BUY",
        "shares": shares,
        "reason": "Previous close reclaimed 17.50 after a reduction; next trading day still holds 17.50 and is not above 18.50, execute paper buy-back.",
        "price": price,
        "date": date,
        "time": quote["time"],
        "vol_ratio": round(vol_ratio, 2),
        "signal_date": pending["signal_date"],
    }


def make_close_action(
    state: dict[str, Any],
    quote: dict[str, Any],
    daily: list[dict[str, Any]],
) -> dict[str, Any] | None:
    close = float(quote["price"])
    date = str(quote["date"])
    position = int(state["position"])
    vol_ratio = volume_ratio(quote, daily)

    if position <= 0 and float(state.get("cash", 0.0)) <= 0:
        return None
    if date in set(state.get("close_processed_dates", [])):
        return None
    if not is_close_check(quote):
        return None

    if position > 0:
        if close >= TAKE_PROFIT_3 and not state.get("take_profit_3_done"):
            return {
                "type": "PLAN_TAKE_PROFIT_NEXT_OPEN",
                "shares": position,
                "reason": "Close reached 21.20 or above; plan to paper sell remaining shares next trading day if price still holds 21.20.",
                "price": close,
                "date": date,
                "time": quote["time"],
                "vol_ratio": round(vol_ratio, 2),
                "kind": "take_profit_3",
                "level": "TP3",
                "trigger_price": TAKE_PROFIT_3,
            }

        if close >= TAKE_PROFIT_2 and not state.get("take_profit_2_done"):
            return {
                "type": "PLAN_TAKE_PROFIT_NEXT_OPEN",
                "shares": min(300, position),
                "reason": "Close reached 20.20 or above; plan to paper sell 300 shares next trading day if price still holds 20.20.",
                "price": close,
                "date": date,
                "time": quote["time"],
                "vol_ratio": round(vol_ratio, 2),
                "kind": "take_profit_2",
                "level": "TP2",
                "trigger_price": TAKE_PROFIT_2,
            }

        if close >= TAKE_PROFIT_1 and not state.get("take_profit_1_done"):
            return {
                "type": "PLAN_TAKE_PROFIT_NEXT_OPEN",
                "shares": min(200, position),
                "reason": "Close reached 19.30 or above; plan to paper sell 200 shares next trading day if price still holds 19.30.",
                "price": close,
                "date": date,
                "time": quote["time"],
                "vol_ratio": round(vol_ratio, 2),
                "kind": "take_profit_1",
                "level": "TP1",
                "trigger_price": TAKE_PROFIT_1,
            }

    if close <= SECOND_LEVEL and vol_ratio >= 1.2 and not state.get("clear_done"):
        return {
            "type": "PLAN_SELL_NEXT_OPEN",
            "shares": position,
            "reason": "Close confirmed a high-volume break below 16.20; plan to paper exit remaining shares next trading day if price is still below 16.60.",
            "price": close,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
            "kind": "clear",
        }

    if close < BREAK_LEVEL and not state.get("first_break_done"):
        return {
            "type": "PLAN_SELL_NEXT_OPEN",
            "shares": min(300, position),
            "reason": "Close confirmed below 16.60; plan to paper sell 300 shares next trading day if price is still below 16.60.",
            "price": close,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
            "kind": "first_break",
        }

    if (
        close < BREAK_LEVEL
        and state.get("first_break_done")
        and not state.get("second_break_done")
        and state.get("first_break_date") != date
    ):
        return {
            "type": "PLAN_SELL_NEXT_OPEN",
            "shares": min(200, position),
            "reason": "Second close below 16.60 after the first break; plan to paper sell another 200 shares next trading day if price is still below 16.60.",
            "price": close,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
            "kind": "second_break",
        }

    if (
        close >= RECLAIM_LEVEL
        and state.get("first_break_done")
        and not state.get("reclaim_alerted")
    ):
        buy_shares = available_buy_shares(state, close)
        if buy_shares > 0 and close <= BUY_CEILING:
            return {
                "type": "PLAN_BUY_NEXT_OPEN",
                "shares": min(300, buy_shares),
                "reason": "Close reclaimed 17.50 after a risk reduction; plan to paper buy back shares next trading day if price holds 17.50 and does not exceed 18.50.",
                "price": close,
                "date": date,
                "time": quote["time"],
                "vol_ratio": round(vol_ratio, 2),
            }
        return {
            "type": "ALERT",
            "shares": 0,
            "reason": "Price reclaimed 17.50. Consider whether to rebuy reduced paper shares; no automatic paper buy.",
            "price": close,
            "date": date,
            "time": quote["time"],
            "vol_ratio": round(vol_ratio, 2),
        }

    return None


def apply_action(state: dict[str, Any], action: dict[str, Any]) -> None:
    if action["type"] == "REAL_TRADE_ALERT":
        state.setdefault("real_alert_keys", []).append(action["alert_key"])
    elif action["type"] == "INTRADAY_ALERT":
        state.setdefault("intraday_alert_dates", []).append(action["date"])
    elif action["type"] == "PLAN_SELL_NEXT_OPEN":
        state["pending_sell"] = {
            "signal_date": action["date"],
            "shares": int(action["shares"]),
            "reason": action["reason"],
            "kind": action.get("kind"),
            "signal_price": float(action["price"]),
        }
        state.setdefault("close_processed_dates", []).append(action["date"])
    elif action["type"] == "PLAN_TAKE_PROFIT_NEXT_OPEN":
        state["pending_take_profit"] = {
            "signal_date": action["date"],
            "shares": int(action["shares"]),
            "reason": action["reason"],
            "kind": action.get("kind"),
            "level": action.get("level"),
            "trigger_price": float(action["trigger_price"]),
            "signal_price": float(action["price"]),
        }
        state.setdefault("close_processed_dates", []).append(action["date"])
    elif action["type"] == "PLAN_BUY_NEXT_OPEN":
        state["pending_buy"] = {
            "signal_date": action["date"],
            "shares": int(action["shares"]),
            "reason": action["reason"],
            "signal_price": float(action["price"]),
        }
        state["reclaim_alerted"] = True
        state.setdefault("close_processed_dates", []).append(action["date"])
    elif action["type"] == "CANCEL_PENDING":
        state["pending_sell"] = None
    elif action["type"] == "CANCEL_TAKE_PROFIT":
        state["pending_take_profit"] = None
    elif action["type"] == "CANCEL_BUY":
        state["pending_buy"] = None
    elif action["type"] == "SELL":
        shares = int(action["shares"])
        price = float(action["price"])
        state["position"] = int(state["position"]) - shares
        state["cash"] = round(float(state.get("cash", 0.0)) + shares * price, 2)
        state["pending_sell"] = None
        state["pending_take_profit"] = None
        pending_kind = action.get("pending_kind")
        if pending_kind in {"first_break", "second_break", "clear"}:
            if not state.get("first_break_done"):
                state["first_break_done"] = True
                state["first_break_date"] = action.get("signal_date", action["date"])
            elif not state.get("second_break_done"):
                state["second_break_done"] = True
        take_profit_level = action.get("take_profit_level")
        if take_profit_level == "TP1":
            state["take_profit_1_done"] = True
        elif take_profit_level == "TP2":
            state["take_profit_2_done"] = True
        elif take_profit_level == "TP3":
            state["take_profit_3_done"] = True
        if state["position"] <= 0:
            state["clear_done"] = True
    elif action["type"] == "BUY":
        shares = int(action["shares"])
        price = float(action["price"])
        state["position"] = int(state["position"]) + shares
        state["cash"] = round(float(state.get("cash", 0.0)) - shares * price, 2)
        state["pending_buy"] = None
        if state["position"] >= INITIAL_SHARES:
            state["reclaim_alerted"] = False
    elif action["type"] == "ALERT":
        state["reclaim_alerted"] = True
        state.setdefault("close_processed_dates", []).append(action["date"])
    state["actions"].append(action)


def render_message(state: dict[str, Any], action: dict[str, Any]) -> tuple[str, str]:
    price = float(action["price"])
    position = int(state["position"])
    market_value = round(position * price, 2)
    realized_cash = round(float(state.get("cash", 0.0)), 2)
    total_now = round(market_value + realized_cash, 2)
    initial_value = round(INITIAL_COST * INITIAL_SHARES, 2)
    total_pnl = round(total_now - initial_value, 2)
    total_pnl_pct = round(total_pnl / initial_value * 100, 2)

    if action["type"] == "REAL_TRADE_ALERT":
        action_text = (
            f"卖出 {action['shares']} 股"
            if int(action.get("shares", 0)) > 0
            else "暂不操作，等待反抽/确认"
        )
        title = f"人民网操作提醒：{action_text}"
        body = (
            f"股票：人民网 ({CODE})\n"
            f"时间：{action['date']} {action.get('time', '')}\n"
            f"现价：{price:.2f}\n"
            f"建议操作：{action_text}\n"
            f"原因：{action['reason']}\n"
            f"当前记录持仓：{position} 股\n"
            f"原始成本：{INITIAL_COST:.2f}，已记录 16.60 卖出 200 股\n"
            f"操作反馈：{feedback_url(action)}\n"
            f"提醒：脚本只通知，不会自动下单；如果你不提交反馈，系统会继续按未操作处理。"
        )
        return title, body

    title = f"{DISPLAY_NAME} paper monitor: {action['type']}"
    body = (
        f"Stock: {DISPLAY_NAME} ({CODE})\n"
        f"Date/time: {action['date']} {action.get('time', '')}\n"
        f"Price: {price:.2f}\n"
        f"Action shares: {action['shares']}\n"
        f"Reason: {action['reason']}\n"
        f"Volume / 20D avg volume: {action['vol_ratio']}\n"
        f"Paper position after action: {position} shares\n"
        f"Paper cash recovered: {realized_cash:.2f} CNY\n"
        f"Estimated total paper equity: {total_now:.2f} CNY\n"
        f"Initial capital {initial_value:.2f} CNY: {total_pnl:.2f} CNY ({total_pnl_pct}%)\n"
        f"操作反馈：{feedback_url(action)}\n"
        f"提醒：脚本只通知，不会自动下单；如果你不提交反馈，系统会继续按未操作处理。"
    )
    return title, body


def main() -> None:
    if set_position_from_cli(sys.argv):
        return

    ROOT.mkdir(parents=True, exist_ok=True)
    state = normalize_state(load_state())
    quote = fetch_quote()
    if os.environ.get("FORCE_MONITOR_RUN") != "1" and not should_check_now(quote):
        print(
            f"Outside trading monitor window. Quote {quote['date']} {quote['time']}, "
            f"price {quote['price']:.2f}."
        )
        return

    state["last_checked_at"] = datetime.now().isoformat(timespec="seconds")
    state["last_quote"] = quote
    maybe_send_strategy_summary(state, quote)

    real_action = make_real_trade_alert(state, quote)
    action = None
    if real_action is not None and real_action["alert_key"] not in set(state.get("real_alert_keys", [])):
        action = apply_vibetrading_review(state, quote, real_action)
        if action["alert_key"] in set(state.get("real_alert_keys", [])):
            action = None

    if action is None:
        save_state(state)
        print(
            f"{quote['date']} {quote['time']} no real-trade alert. "
            f"Price {quote['price']:.2f}, recorded position {state['position']} shares."
        )
        return

    if not has_notifier():
        save_state(state)
        print("Action triggered, but no notifier is configured.")
        print(json.dumps(action, ensure_ascii=False, indent=2))
        return

    apply_action(state, action)
    save_state(state)
    title, body = render_message(state, action)
    append_log(f"{datetime.now().isoformat(timespec='seconds')} {title} {body}")
    send_notification(title, body)
    print(title)
    print(body)


if __name__ == "__main__":
    main()
