from __future__ import annotations

import csv
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import parse, request


ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state.json"
LOG_PATH = ROOT / "monitor.log"
FEEDBACK_TOKEN_PATH = Path("/home/admin/ai/output/qr-login/renminwang.token")

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQNDXTMC"
FUND_GZ = "https://fundgz.1234567.com.cn/js/{code}.js?rt=1463558676006"
TENCENT_QUOTE = "https://qt.gtimg.cn/q=sz159509"

FUND_HOLDINGS = {
    # Updated from user's Alipay fund account on 2026-06-26.
    # App/account values are authoritative; public estimates are only market reference.
    "017091": {"name": "景顺纳指科技A", "value": 35549.32, "profit": 6249.32},
    "017093": {"name": "景顺纳指科技C", "value": 14437.84, "profit": 2437.84},
    "019118": {"name": "景顺纳指科技E", "value": 11611.52, "profit": 2011.52},
}
TOTAL_VALUE = sum(item["value"] for item in FUND_HOLDINGS.values())
TOTAL_PROFIT = sum(item["profit"] for item in FUND_HOLDINGS.values())
TOTAL_COST = TOTAL_VALUE - TOTAL_PROFIT


def http_get(url: str, encoding: str = "utf-8", timeout: int = 30) -> str:
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, "ignore")


def fetch_ndxtmc() -> list[dict[str, Any]]:
    rows = []
    try:
        text = http_get(FRED_CSV, timeout=60)
    except Exception:
        text = subprocess.check_output(
            ["curl", "-L", "--max-time", "75", "-s", FRED_CSV],
            text=True,
        )
    for row in csv.DictReader(text.splitlines()):
        if row.get("NASDAQNDXTMC") in {"", "."}:
            continue
        rows.append({"date": row["observation_date"], "close": float(row["NASDAQNDXTMC"])})
    return rows[-80:]


def expected_ndxtmc_date(now: datetime | None = None) -> datetime.date | None:
    now = now or datetime.now()
    candidate = now.date() - timedelta(days=1)
    if candidate.weekday() <= 4:
        return candidate
    return None


def ndxtmc_freshness_issue(ndx_rows: list[dict[str, Any]], now: datetime | None = None) -> str | None:
    if not ndx_rows:
        return "missing_ndxtmc_rows"
    expected = expected_ndxtmc_date(now)
    if expected is None:
        return "outside_expected_us_close_window"
    latest = datetime.strptime(str(ndx_rows[-1]["date"]), "%Y-%m-%d").date()
    if latest < expected:
        return f"stale_ndxtmc:latest={latest.isoformat()},expected_at_least={expected.isoformat()}"
    return None


def fetch_fund_estimate(code: str) -> dict[str, Any]:
    text = http_get(FUND_GZ.format(code=code))
    payload = text.split("(", 1)[1].rsplit(")", 1)[0]
    return json.loads(payload)


def fetch_159509_quote() -> dict[str, Any]:
    text = http_get(TENCENT_QUOTE, "gbk")
    raw = text.split('="', 1)[1].rsplit('"', 1)[0].split("~")
    return {
        "price": float(raw[3]),
        "prev_close": float(raw[4]),
        "open": float(raw[5]),
        "high": float(raw[33]),
        "low": float(raw[34]),
        "nav": float(raw[72]) if len(raw) > 72 and raw[72] else None,
        "time": raw[30],
    }


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"sent_alert_keys": [], "last_checked_at": None, "last_snapshot": None}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def moving_average(values: list[float], window: int) -> float:
    if len(values) < window:
        return sum(values) / len(values)
    return sum(values[-window:]) / window


def drawdown_from_high(values: list[float], window: int) -> float:
    recent = values[-window:]
    high = max(recent)
    return values[-1] / high - 1


def feedback_url(alert_key: str) -> str:
    base_url = os.environ.get("TRADE_FEEDBACK_BASE_URL", "http://8.212.144.72:8090")
    token = FEEDBACK_TOKEN_PATH.read_text(encoding="utf-8").strip()
    params = parse.urlencode(
        {
            "token": token,
            "source": "ndxtmc_qdii_monitor",
            "asset": "017091/017093/019118",
            "alert_key": alert_key,
        }
    )
    return f"{base_url.rstrip('/')}/trade-feedback.html?{params}"


def send_serverchan(title: str, body: str) -> None:
    pushplus_token = os.environ.get("PUSHPLUS_TOKEN")
    if pushplus_token:
        data = parse.urlencode(
            {"token": pushplus_token, "title": title, "content": body}
        ).encode("utf-8")
        req = request.Request("https://www.pushplus.plus/send", data=data, method="POST")
        with request.urlopen(req, timeout=15) as resp:
            resp.read()
        return

    key = os.environ.get("SERVER_CHAN_SENDKEY")
    if not key:
        raise RuntimeError("SERVER_CHAN_SENDKEY is not configured")
    data = parse.urlencode({"title": title, "desp": body}).encode("utf-8")
    req = request.Request(f"https://sctapi.ftqq.com/{key}.send", data=data, method="POST")
    with request.urlopen(req, timeout=15) as resp:
        resp.read()


def decide(ndx_rows: list[dict[str, Any]], etf_quote: dict[str, Any], fund_estimates: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    closes = [row["close"] for row in ndx_rows]
    last = ndx_rows[-1]
    prev = ndx_rows[-2]
    one_day = last["close"] / prev["close"] - 1
    five_day = last["close"] / closes[-6] - 1 if len(closes) >= 6 else 0.0
    dd_20 = drawdown_from_high(closes, 20)
    ma20 = moving_average(closes, 20)
    below_ma20 = last["close"] < ma20
    nav_est = float(fetch_fund_estimate("159509")["gsz"])
    premium = etf_quote["price"] / nav_est - 1 if nav_est else 0.0

    alert_key = f"{last['date']}:ndxtmc:{round(last['close'], 2)}"

    severe = one_day <= -0.05 or five_day <= -0.08
    trend_break = dd_20 <= -0.10 and below_ma20
    profit_buffer = TOTAL_PROFIT / TOTAL_COST

    if not severe and not trend_break:
        return None

    if severe and trend_break:
        amount = 10000
        action = "赎回/减仓约10000元，优先从017091或017093中选择费率和持有期更合适的一只执行。"
    else:
        amount = 5000
        action = "赎回/减仓约5000元，先兑现一小部分盈利，保留大部分核心仓。"

    reason = "\n".join(
        [
            f"NDXTMC最新收盘：{last['date']} {last['close']:.2f}，单日{one_day * 100:.2f}%，近5个交易日{five_day * 100:.2f}%，20日高点回撤{dd_20 * 100:.2f}%。",
            f"趋势复核：20日均线约{ma20:.2f}，当前{'低于' if below_ma20 else '高于'}20日均线；触发条件 severe={severe}, trend_break={trend_break}。",
            f"你的景顺三只场外合计市值{TOTAL_VALUE:.2f}元，浮盈{TOTAL_PROFIT:.2f}元，收益垫约{profit_buffer * 100:.2f}%。",
            f"场内159509价格约{etf_quote['price']:.3f}，按估算净值{nav_est:.4f}计算溢价约{premium * 100:.2f}%；高溢价时不建议改买场内ETF。",
            "场外QDII注意：早上看到的是昨晚美股收盘，但你在中国交易日15:00前提交赎回，成交净值通常还会受到今晚美股和汇率影响，不是按当前已知指数点位成交。因此只有明显风险信号才提醒操作。",
            f"建议操作：{action}",
            "不操作条件：如果你选择继续长期持有且能接受纳指科技再回撤10%左右，可以不提交反馈；系统会按未操作记录。",
        ]
    )

    return {
        "alert_key": alert_key,
        "amount": amount,
        "action": action,
        "reason": reason,
        "snapshot": {
            "ndxtmc_date": last["date"],
            "ndxtmc_close": last["close"],
            "one_day": one_day,
            "five_day": five_day,
            "dd_20": dd_20,
            "ma20": ma20,
            "etf_159509": etf_quote,
            "fund_estimates": fund_estimates,
            "premium": premium,
        },
    }


def main() -> None:
    state = load_state()
    ndx_rows = fetch_ndxtmc()
    freshness_issue = ndxtmc_freshness_issue(ndx_rows)
    state["last_checked_at"] = datetime.now().isoformat(timespec="seconds")
    if freshness_issue:
        state["last_snapshot"] = {
            "ndxtmc": ndx_rows[-3:],
            "skip_reason": freshness_issue,
        }
        save_state(state)
        print(f"{state['last_checked_at']} skip QDII monitor. {freshness_issue}")
        return

    etf_quote = fetch_159509_quote()
    fund_estimates = {code: fetch_fund_estimate(code) for code in FUND_HOLDINGS}
    state["last_snapshot"] = {
        "ndxtmc": ndx_rows[-3:],
        "etf_159509": etf_quote,
        "fund_estimates": fund_estimates,
    }

    decision = decide(ndx_rows, etf_quote, fund_estimates)
    if decision is None:
        save_state(state)
        print(f"{state['last_checked_at']} no QDII action. NDXTMC {ndx_rows[-1]['date']} {ndx_rows[-1]['close']:.2f}")
        return

    if decision["alert_key"] in set(state.get("sent_alert_keys", [])):
        save_state(state)
        print(f"{state['last_checked_at']} alert already sent: {decision['alert_key']}")
        return

    url = feedback_url(decision["alert_key"])
    body = (
        decision["reason"]
        + f"\n\n操作反馈：{url}"
        + "\n提醒：脚本只通知，不会自动下单；如果你不提交反馈，系统会继续按未操作处理。"
    )
    send_serverchan("景顺纳指科技操作提醒", body)
    state.setdefault("sent_alert_keys", []).append(decision["alert_key"])
    state.setdefault("alerts", []).append({**decision, "sent_at": state["last_checked_at"], "feedback_url": url})
    save_state(state)
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {decision['alert_key']} {decision['action']}\n")
    print(body)


if __name__ == "__main__":
    main()
