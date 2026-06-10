from __future__ import annotations

import json
import os
from datetime import datetime, time
from pathlib import Path
from typing import Any
from urllib import parse, request


ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state.json"
LOG_PATH = ROOT / "trades.log"

SYMBOL = "sh603000"
NAME = "Renminwang"
DISPLAY_NAME = "People.cn"
CODE = "603000.SH"

INITIAL_COST = 18.40
INITIAL_SHARES = 700

BREAK_LEVEL = 16.60
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
        "position": INITIAL_SHARES,
        "cash": 0.0,
        "first_break_done": False,
        "first_break_date": None,
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
        "close_processed_dates": [],
        "actions": [],
    }


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("code", CODE)
    state.setdefault("name", NAME)
    state.setdefault("cost", INITIAL_COST)
    state.setdefault("position", INITIAL_SHARES)
    state.setdefault("cash", 0.0)
    state.setdefault("first_break_done", False)
    state.setdefault("first_break_date", None)
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
    state.setdefault("close_processed_dates", [])
    state.setdefault("actions", [])
    return state


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def send_wechat(title: str, body: str) -> None:
    webhook = os.environ.get("WECHAT_WEBHOOK_URL")
    pushplus_token = os.environ.get("PUSHPLUS_TOKEN")
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

    if pushplus_token:
        data = parse.urlencode(
            {"token": pushplus_token, "title": title, "content": body}
        ).encode("utf-8")
        req = request.Request("https://www.pushplus.plus/send", data=data, method="POST")
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
        "No notifier configured. Set WECHAT_WEBHOOK_URL, PUSHPLUS_TOKEN, or SERVER_CHAN_SENDKEY."
    )


def has_notifier() -> bool:
    return any(
        os.environ.get(name)
        for name in ("WECHAT_WEBHOOK_URL", "PUSHPLUS_TOKEN", "SERVER_CHAN_SENDKEY")
    )


def append_log(line: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


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
    return LOCAL_CHECK_START <= now.time() <= LOCAL_CHECK_END


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
    if action["type"] == "INTRADAY_ALERT":
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
        f"Initial capital {initial_value:.2f} CNY: {total_pnl:.2f} CNY ({total_pnl_pct}%)"
    )
    return title, body


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    state = normalize_state(load_state())
    quote = fetch_quote()
    if os.environ.get("FORCE_MONITOR_RUN") != "1" and not should_check_now(quote):
        print(
            f"Outside trading monitor window. Quote {quote['date']} {quote['time']}, "
            f"price {quote['price']:.2f}."
        )
        return

    daily = fetch_daily()
    state["last_checked_at"] = datetime.now().isoformat(timespec="seconds")
    state["last_quote"] = quote

    action = make_intraday_alert(state, quote, daily)
    if action is None:
        action = make_pending_sell_action(state, quote, daily)
    if action is None:
        action = make_pending_take_profit_action(state, quote, daily)
    if action is None:
        action = make_pending_buy_action(state, quote, daily)
    if action is None:
        action = make_close_action(state, quote, daily)

    if action is None:
        save_state(state)
        print(
            f"{quote['date']} {quote['time']} no paper action. "
            f"Price {quote['price']:.2f}, paper position {state['position']} shares."
        )
        return

    if not has_notifier():
        save_state(state)
        print("Action triggered, but no notifier is configured; paper position was not changed.")
        print(json.dumps(action, ensure_ascii=False, indent=2))
        return

    apply_action(state, action)
    save_state(state)
    title, body = render_message(state, action)
    append_log(f"{datetime.now().isoformat(timespec='seconds')} {title} {body}")
    send_wechat(title, body)
    print(title)
    print(body)


if __name__ == "__main__":
    main()
