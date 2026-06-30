from __future__ import annotations

import csv
import json
import math
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib import parse, request


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PRICE_DIR = DATA_DIR / "prices"
RESULT_DIR = ROOT / "results"
CONSTITUENTS_PATH = DATA_DIR / "constituents.csv"

INDEX_TYPES = {
    "hs300": {"type": "1", "name": "沪深300"},
    "csi500": {"type": "3", "name": "中证500"},
    "csi_a500": {"type": "6", "name": "中证A500"},
}

START_DATE = "2021-01-01"
END_DATE = datetime.now().strftime("%Y%m%d")
MIN_AMOUNT = 50_000_000
DROP_THRESHOLDS = [-0.05, -0.06, -0.07, -0.08]
TARGETS = [0.015, 0.02, 0.03, 0.04]
STOPS = [0.02, 0.03, 0.04]

COMMISSION = 0.000115
STAMP_TAX = 0.0005
SLIPPAGE = 0.0005


def http_get_json(url: str, referer: str, timeout: int = 30) -> dict:
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def eastmoney_secid(code: str) -> str:
    if code.startswith(("6", "5", "9")):
        return f"1.{code}"
    return f"0.{code}"


def load_or_fetch_constituents(refresh: bool = False) -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CONSTITUENTS_PATH.exists() and not refresh:
        with CONSTITUENTS_PATH.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    rows: list[dict] = []
    for page in range(1, 20):
        params = {
            "reportName": "RPT_INDEX_TS_COMPONENT",
            "columns": "ALL",
            "pageNumber": str(page),
            "pageSize": "500",
            "sortColumns": "TYPE,SECURITY_CODE",
            "sortTypes": "1,1",
        }
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + parse.urlencode(params)
        obj = http_get_json(url, "https://data.eastmoney.com/")
        page_rows = (obj.get("result") or {}).get("data") or []
        if not page_rows:
            break
        for row in page_rows:
            type_id = str(row.get("TYPE") or "")
            for pool, meta in INDEX_TYPES.items():
                if type_id == meta["type"]:
                    name = str(row.get("SECURITY_NAME_ABBR") or "")
                    if "ST" in name.upper():
                        continue
                    rows.append(
                        {
                            "pool": pool,
                            "pool_name": meta["name"],
                            "code": str(row.get("SECURITY_CODE") or ""),
                            "name": name,
                            "secucode": str(row.get("SECUCODE") or ""),
                            "type": type_id,
                        }
                    )
        time.sleep(0.2)

    with CONSTITUENTS_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["pool", "pool_name", "code", "name", "secucode", "type"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def fetch_price_rows(code: str, refresh: bool = False) -> list[dict]:
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    path = PRICE_DIR / f"{code}.csv"
    if path.exists() and not refresh:
        with path.open("r", encoding="utf-8", newline="") as f:
            return [normalize_price_row(row) for row in csv.DictReader(f)]

    symbol = ("sh" if code.startswith(("6", "5", "9")) else "sz") + code
    params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": "1300"}
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData?"
        + parse.urlencode(params)
    )
    req = request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
    )
    with request.urlopen(req, timeout=20) as resp:
        klines = json.loads(resp.read().decode("utf-8", "ignore"))
    rows = []
    prev_close = None
    for row in klines:
        close = float(row["close"])
        pct_chg = 0.0 if not prev_close else close / prev_close * 100 - 100
        volume = float(row.get("volume") or 0)
        amount = volume * close
        rows.append(
            {
                "date": row["day"],
                "open": row["open"],
                "close": row["close"],
                "high": row["high"],
                "low": row["low"],
                "volume": volume,
                "amount": amount,
                "amplitude": 0,
                "pct_chg": pct_chg,
                "chg": 0 if not prev_close else close - prev_close,
                "turnover": 0,
            }
        )
        prev_close = close
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "open", "close", "high", "low", "volume", "amount", "amplitude", "pct_chg", "chg", "turnover"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return [normalize_price_row(row) for row in rows]


def normalize_price_row(row: dict) -> dict:
    result = {"date": row["date"]}
    for key in ["open", "close", "high", "low", "volume", "amount", "amplitude", "pct_chg", "chg", "turnover"]:
        try:
            result[key] = float(row.get(key) or 0)
        except ValueError:
            result[key] = 0.0
    return result


def sell_return(buy_close: float, raw_sell_price: float) -> float:
    buy_cost = buy_close * (1 + COMMISSION + SLIPPAGE)
    sell_cash = raw_sell_price * (1 - COMMISSION - STAMP_TAX - SLIPPAGE)
    return sell_cash / buy_cost - 1


def is_one_price_limit_down(row: dict) -> bool:
    if row["pct_chg"] > -9.5:
        return False
    return row["open"] == row["high"] == row["low"] == row["close"]


def generate_trades(pool_rows: list[dict], price_cache: dict[str, list[dict]]) -> list[dict]:
    trades = []
    for item in pool_rows:
        code = item["code"]
        rows = price_cache.get(code) or []
        for i in range(1, len(rows) - 1):
            today = rows[i]
            tomorrow = rows[i + 1]
            if today["date"] < START_DATE:
                continue
            if today["amount"] < MIN_AMOUNT:
                continue
            if is_one_price_limit_down(today):
                continue
            if today["pct_chg"] > max(DROP_THRESHOLDS) * 100:
                continue
            for drop in DROP_THRESHOLDS:
                if today["pct_chg"] <= drop * 100:
                    trades.append(
                        {
                            "pool": item["pool"],
                            "pool_name": item["pool_name"],
                            "code": code,
                            "name": item["name"],
                            "signal_date": today["date"],
                            "exit_date": tomorrow["date"],
                            "drop_threshold": drop,
                            "signal_pct_chg": today["pct_chg"] / 100,
                            "signal_amount": today["amount"],
                            "buy_close": today["close"],
                            "next_open": tomorrow["open"],
                            "next_high": tomorrow["high"],
                            "next_low": tomorrow["low"],
                            "next_close": tomorrow["close"],
                        }
                    )
    return trades


def enrich_trade_returns(trade: dict) -> list[dict]:
    results = []
    buy = float(trade["buy_close"])
    open_ret = sell_return(buy, float(trade["next_open"]))
    close_ret = sell_return(buy, float(trade["next_close"]))
    results.append({**trade, "exit_rule": "next_open", "target": "", "stop": "", "return": open_ret, "hit": "open"})
    results.append({**trade, "exit_rule": "next_close", "target": "", "stop": "", "return": close_ret, "hit": "close"})

    high = float(trade["next_high"])
    low = float(trade["next_low"])
    close = float(trade["next_close"])
    for target in TARGETS:
        for stop in STOPS:
            target_price = buy * (1 + target)
            stop_price = buy * (1 - stop)
            if low <= stop_price:
                raw_sell = stop_price
                hit = "stop"
            elif high >= target_price:
                raw_sell = target_price
                hit = "target"
            else:
                raw_sell = close
                hit = "close"
            results.append(
                {
                    **trade,
                    "exit_rule": "target_stop_close",
                    "target": target,
                    "stop": stop,
                    "return": sell_return(buy, raw_sell),
                    "hit": hit,
                }
            )
    return results


def max_drawdown_from_returns(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for ret in returns:
        equity *= 1 + ret
        peak = max(peak, equity)
        mdd = min(mdd, equity / peak - 1)
    return mdd


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["pool"], row["pool_name"], row["drop_threshold"], row["exit_rule"], row["target"], row["stop"])
        groups[key].append(row)

    summary = []
    for (pool, pool_name, drop, rule, target, stop), items in groups.items():
        returns = [float(x["return"]) for x in items]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        hit_counts = defaultdict(int)
        year_counts = defaultdict(int)
        for item in items:
            hit_counts[str(item["hit"])] += 1
            year_counts[str(item["signal_date"])[:4]] += 1
        avg = statistics.mean(returns)
        sd = statistics.pstdev(returns) if len(returns) > 1 else 0.0
        downside = [min(0.0, r) for r in returns]
        downside_sd = statistics.pstdev(downside) if len(downside) > 1 else 0.0
        summary.append(
            {
                "pool": pool,
                "pool_name": pool_name,
                "drop_threshold": drop,
                "exit_rule": rule,
                "target": target,
                "stop": stop,
                "trades": len(items),
                "win_rate": len(wins) / len(items),
                "avg_return": avg,
                "median_return": statistics.median(returns),
                "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) else "",
                "max_trade_loss": min(returns),
                "max_trade_gain": max(returns),
                "sample_equity_return": math.prod(1 + r for r in returns) - 1,
                "sample_max_drawdown": max_drawdown_from_returns(returns),
                "return_stdev": sd,
                "sortino_like": avg / downside_sd if downside_sd else "",
                "hit_counts": json.dumps(dict(hit_counts), ensure_ascii=False),
                "year_counts": json.dumps(dict(sorted(year_counts.items())), ensure_ascii=False),
            }
        )
    summary.sort(key=lambda r: (r["avg_return"], r["trades"]), reverse=True)
    return summary


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    constituents = load_or_fetch_constituents(refresh=False)
    wanted = [row for row in constituents if row["pool"] in INDEX_TYPES]
    unique_codes = sorted({row["code"] for row in wanted})

    price_cache: dict[str, list[dict]] = {}
    failures = []
    for idx, code in enumerate(unique_codes, 1):
        try:
            price_cache[code] = fetch_price_rows(code, refresh=False)
        except Exception as exc:
            failures.append({"code": code, "error": str(exc)})
        if idx % 50 == 0:
            print(f"fetched {idx}/{len(unique_codes)} codes, failures={len(failures)}", flush=True)
        time.sleep(0.08)

    trades = []
    for pool in INDEX_TYPES:
        pool_rows = [row for row in wanted if row["pool"] == pool]
        trades.extend(generate_trades(pool_rows, price_cache))

    expanded = []
    for trade in trades:
        expanded.extend(enrich_trade_returns(trade))

    summary = summarize(expanded)
    write_csv(RESULT_DIR / "trades.csv", expanded)
    write_csv(RESULT_DIR / "summary.csv", summary)
    write_csv(RESULT_DIR / "failures.csv", failures)

    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": START_DATE,
        "end_date": END_DATE,
        "index_types": INDEX_TYPES,
        "unique_codes": len(unique_codes),
        "constituent_rows": len(wanted),
        "raw_signals": len(trades),
        "expanded_trade_rows": len(expanded),
        "failures": len(failures),
        "assumptions": {
            "entry": "signal day close",
            "exit": "next day open, next day close, or next day target/stop/close",
            "target_stop_order": "conservative: stop is assumed hit before target if both occur intraday",
            "filters": f"exclude ST names, one-price limit-down days, and signal amount below {MIN_AMOUNT}",
            "costs": {"commission": COMMISSION, "stamp_tax": STAMP_TAX, "slippage_each_side": SLIPPAGE},
        },
    }
    (RESULT_DIR / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("top summary rows:")
    for row in summary[:10]:
        print(row)


if __name__ == "__main__":
    main()
