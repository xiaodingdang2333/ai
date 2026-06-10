from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path
from urllib import request


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results"
OUT.mkdir(parents=True, exist_ok=True)

CANDIDATES = {
    "510300": ("sh510300", "沪深300ETF"),
    "510500": ("sh510500", "中证500ETF"),
    "159915": ("sz159915", "创业板ETF"),
    "588000": ("sh588000", "科创50ETF"),
    "512890": ("sh512890", "红利低波ETF"),
    "518880": ("sh518880", "黄金ETF"),
    "511010": ("sh511010", "国债ETF"),
    "513100": ("sh513100", "纳指ETF"),
    "513500": ("sh513500", "标普500ETF"),
    "159920": ("sz159920", "恒生ETF"),
    "512760": ("sh512760", "芯片ETF"),
    "515030": ("sh515030", "新能源车ETF"),
    "512000": ("sh512000", "券商ETF"),
    "600900": ("sh600900", "长江电力"),
    "600941": ("sh600941", "中国移动"),
    "000333": ("sz000333", "美的集团"),
    "601138": ("sh601138", "工业富联"),
    "300750": ("sz300750", "宁德时代"),
}


def fetch_kline(sina_symbol: str, datalen: int = 1300) -> list[dict]:
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={sina_symbol}&scale=240&ma=no&datalen={datalen}"
    )
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        },
    )
    with request.urlopen(req, timeout=20) as resp:
        rows = json.loads(resp.read().decode("utf-8", "ignore"))
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


def max_drawdown(values: list[float]) -> float:
    peak = values[0]
    mdd = 0.0
    for value in values:
        peak = max(peak, value)
        mdd = min(mdd, value / peak - 1.0)
    return mdd


def annual_return(values: list[float], trading_days: int) -> float:
    years = max(trading_days / 252.0, 1 / 252.0)
    return values[-1] ** (1 / years) - 1


def sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    avg = sum(returns) / len(returns)
    var = sum((r - avg) ** 2 for r in returns) / (len(returns) - 1)
    sd = math.sqrt(var)
    return 0.0 if sd == 0 else avg / sd * math.sqrt(252)


def moving_average(vals: list[float], idx: int, window: int) -> float | None:
    if idx + 1 < window:
        return None
    return sum(vals[idx - window + 1 : idx + 1]) / window


def momentum(vals: list[float], idx: int, window: int) -> float | None:
    if idx < window:
        return None
    base = vals[idx - window]
    return vals[idx] / base - 1 if base else None


def write_price_files(data: dict[str, list[dict]]) -> None:
    for code, rows in data.items():
        with (OUT / f"{code}.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerows(rows)


def individual_metrics(data: dict[str, list[dict]]) -> list[dict]:
    rows = []
    for code, series in data.items():
        closes = [r["close"] for r in series]
        if len(closes) < 260:
            continue
        daily = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        values = [1.0]
        for r in daily:
            values.append(values[-1] * (1 + r))
        last_idx = len(closes) - 1
        rows.append(
            {
                "code": code,
                "name": CANDIDATES[code][1],
                "last_date": series[-1]["date"],
                "last_close": round(closes[-1], 4),
                "ann_return": annual_return(values, len(closes) - 1),
                "max_drawdown": max_drawdown(values),
                "sharpe": sharpe(daily),
                "mom60": momentum(closes, last_idx, 60),
                "above_ma120": closes[-1] > moving_average(closes, last_idx, 120),
            }
        )
    return sorted(rows, key=lambda r: (r["ann_return"] / abs(r["max_drawdown"] or -1e-9)), reverse=True)


def build_common_calendar(data: dict[str, list[dict]]) -> list[str]:
    sets = [set(row["date"] for row in rows) for rows in data.values()]
    return sorted(set.intersection(*sets))


def backtest_rotation(data: dict[str, list[dict]], start_date: str = "2021-01-01") -> tuple[list[dict], dict]:
    calendar = [d for d in build_common_calendar(data) if d >= start_date]
    close_by_code = {
        code: {row["date"]: row["close"] for row in rows}
        for code, rows in data.items()
    }
    full_dates = build_common_calendar(data)
    idx_by_date = {d: i for i, d in enumerate(full_dates)}
    closes_full = {
        code: [next(row["close"] for row in rows if row["date"] == d) for d in full_dates]
        for code, rows in data.items()
    }

    equity = 1.0
    weights = {code: 0.0 for code in data}
    curve = []
    daily_returns = []
    holdings_history = []

    for t, date in enumerate(calendar):
        if t > 0:
            prev = calendar[t - 1]
            day_ret = 0.0
            for code, weight in weights.items():
                if weight:
                    day_ret += weight * (close_by_code[code][date] / close_by_code[code][prev] - 1)
            equity *= 1 + day_ret
            daily_returns.append(day_ret)

        if t % 5 == 0:
            scores = []
            full_idx = idx_by_date[date]
            for code, vals in closes_full.items():
                ma120 = moving_average(vals, full_idx, 120)
                mom60 = momentum(vals, full_idx, 60)
                mom20 = momentum(vals, full_idx, 20)
                if ma120 is None or mom60 is None or mom20 is None:
                    continue
                if vals[full_idx] > ma120 and mom60 > 0:
                    scores.append((mom60 + 0.5 * mom20, code))
            scores.sort(reverse=True)

            selected = [code for _, code in scores[:4]]
            max_weight = 0.30
            target_risk_on = min(1.0, max_weight * len(selected))
            weights = {code: 0.0 for code in data}
            if selected:
                equal = target_risk_on / len(selected)
                for code in selected:
                    weights[code] = equal
            holdings_history.append({"date": date, "holdings": selected, "cash": round(1 - sum(weights.values()), 4)})

        curve.append({"date": date, "equity": equity, "weights": dict(weights)})

    values = [row["equity"] for row in curve]
    metrics = {
        "start": calendar[0],
        "end": calendar[-1],
        "total_return": values[-1] - 1,
        "ann_return": annual_return(values, len(values) - 1),
        "max_drawdown": max_drawdown(values),
        "sharpe": sharpe(daily_returns),
        "latest_holdings": holdings_history[-1],
    }
    return curve, metrics


def main() -> None:
    data = {}
    failures = []
    for code, (sina_symbol, _) in CANDIDATES.items():
        try:
            rows = fetch_kline(sina_symbol)
            if len(rows) >= 260:
                data[code] = rows
        except Exception as exc:
            failures.append({"code": code, "error": str(exc)})

    write_price_files(data)
    indiv = individual_metrics(data)
    curve, metrics = backtest_rotation(data)

    with (OUT / "individual_metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(indiv[0].keys()))
        writer.writeheader()
        writer.writerows(indiv)

    with (OUT / "rotation_equity.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "equity"])
        writer.writeheader()
        writer.writerows({"date": row["date"], "equity": row["equity"]} for row in curve)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics,
        "top_individual": indiv[:8],
        "failures": failures,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
