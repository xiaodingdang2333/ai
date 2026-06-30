from __future__ import annotations

import csv
import gc
import json
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Callable

from backtest import (
    COMMISSION,
    CONSTITUENTS_PATH,
    DROP_THRESHOLDS,
    INDEX_TYPES,
    MIN_AMOUNT,
    PRICE_DIR,
    RESULT_DIR,
    SLIPPAGE,
    STAMP_TAX,
    START_DATE,
    fetch_price_rows,
    is_one_price_limit_down,
    load_or_fetch_constituents,
    sell_return,
)


OUT_DIR = RESULT_DIR / "filtered"
TARGET_ONLY = [0.02, 0.03]


def mean(values: list[float]) -> float | None:
    clean = [x for x in values if x > 0]
    if not clean:
        return None
    return statistics.mean(clean)


def close_position(row: dict) -> float | None:
    high = float(row["high"])
    low = float(row["low"])
    if high <= low:
        return None
    return (float(row["close"]) - low) / (high - low)


def pct(a: float, b: float) -> float | None:
    if b <= 0:
        return None
    return a / b - 1


def build_pool_market_pct(wanted: list[dict]) -> dict[tuple[str, str], float]:
    daily_sum: dict[tuple[str, str], float] = defaultdict(float)
    daily_count: dict[tuple[str, str], int] = defaultdict(int)
    for item in wanted:
        rows = fetch_price_rows(item["code"], refresh=False)
        for row in rows:
            if row["date"] >= START_DATE:
                key = (item["pool"], row["date"])
                daily_sum[key] += float(row["pct_chg"]) / 100
                daily_count[key] += 1
    return {key: daily_sum[key] / count for key, count in daily_count.items() if count}


def make_signal(item: dict, rows: list[dict], i: int, market_pct: float | None) -> dict:
    today = rows[i]
    tomorrow = rows[i + 1]
    prev = rows[i - 1]
    prev20 = rows[max(0, i - 20) : i]
    prev60 = rows[max(0, i - 60) : i]
    prev120 = rows[max(0, i - 120) : i]
    avg_vol20 = mean([float(x["volume"]) for x in prev20])

    signal = {
        "pool": item["pool"],
        "pool_name": item["pool_name"],
        "code": item["code"],
        "name": item["name"],
        "signal_date": today["date"],
        "exit_date": tomorrow["date"],
        "signal_pct_chg": float(today["pct_chg"]) / 100,
        "signal_amount": float(today["amount"]),
        "buy_close": float(today["close"]),
        "next_open": float(tomorrow["open"]),
        "next_high": float(tomorrow["high"]),
        "next_close": float(tomorrow["close"]),
        "market_pct": market_pct,
        "close_pos": close_position(today),
        "vol_ratio20": float(today["volume"]) / avg_vol20 if avg_vol20 else None,
        "gap": pct(float(today["open"]), float(prev["close"])),
        "ma60_prev": mean([float(x["close"]) for x in prev60]) if len(prev60) >= 60 else None,
        "ma120_prev": mean([float(x["close"]) for x in prev120]) if len(prev120) >= 120 else None,
        "low20_prev": min(float(x["low"]) for x in prev20) if len(prev20) >= 20 else None,
        "low60_prev": min(float(x["low"]) for x in prev60) if len(prev60) >= 60 else None,
        "cum3_incl": pct(float(today["close"]), float(rows[i - 3]["close"])) if i >= 3 else None,
        "cum5_incl": pct(float(today["close"]), float(rows[i - 5]["close"])) if i >= 5 else None,
    }
    signal["above_ma60"] = signal["ma60_prev"] is not None and signal["buy_close"] > signal["ma60_prev"]
    signal["above_ma120"] = signal["ma120_prev"] is not None and signal["buy_close"] > signal["ma120_prev"]
    signal["no_new_low20"] = signal["low20_prev"] is not None and signal["buy_close"] > signal["low20_prev"]
    signal["no_new_low60"] = signal["low60_prev"] is not None and signal["buy_close"] > signal["low60_prev"]
    return signal


def filter_specs() -> list[tuple[str, str, Callable[[dict], bool]]]:
    return [
        ("base", "仅基础过滤：非ST、非一字跌停、成交额>=5000万", lambda s: True),
        ("market_gt_-1.5", "对应股票池当日等权跌幅 > -1.5%", lambda s: s["market_pct"] is not None and s["market_pct"] > -0.015),
        ("market_gt_-2.0", "对应股票池当日等权跌幅 > -2.0%", lambda s: s["market_pct"] is not None and s["market_pct"] > -0.02),
        ("above_ma60", "信号日收盘仍在前60日均线上方", lambda s: bool(s["above_ma60"])),
        ("above_ma120", "信号日收盘仍在前120日均线上方", lambda s: bool(s["above_ma120"])),
        ("no_new_low20", "信号日收盘未跌破前20日最低价", lambda s: bool(s["no_new_low20"])),
        ("no_new_low60", "信号日收盘未跌破前60日最低价", lambda s: bool(s["no_new_low60"])),
        ("close_pos_ge_0.25", "收盘位置>=25%，尾盘不是贴近最低", lambda s: s["close_pos"] is not None and s["close_pos"] >= 0.25),
        ("close_pos_ge_0.40", "收盘位置>=40%，有更强承接", lambda s: s["close_pos"] is not None and s["close_pos"] >= 0.40),
        ("close_pos_ge_0.50", "收盘位置>=50%，长下影/下半场修复", lambda s: s["close_pos"] is not None and s["close_pos"] >= 0.50),
        ("vol_ratio_1.2_3", "量比20日均量在1.2-3倍", lambda s: s["vol_ratio20"] is not None and 1.2 <= s["vol_ratio20"] <= 3),
        ("vol_ratio_1.5_4", "量比20日均量在1.5-4倍", lambda s: s["vol_ratio20"] is not None and 1.5 <= s["vol_ratio20"] <= 4),
        ("amount_ge_1e8", "成交额>=1亿", lambda s: s["signal_amount"] >= 100_000_000),
        ("amount_ge_2e8", "成交额>=2亿", lambda s: s["signal_amount"] >= 200_000_000),
        ("cum3_ge_-10", "含信号日近3日累计跌幅不超过10%", lambda s: s["cum3_incl"] is not None and s["cum3_incl"] >= -0.10),
        ("cum5_ge_-15", "含信号日近5日累计跌幅不超过15%", lambda s: s["cum5_incl"] is not None and s["cum5_incl"] >= -0.15),
        ("gap_ge_-3", "信号日低开不超过3%", lambda s: s["gap"] is not None and s["gap"] >= -0.03),
        ("gap_ge_-5", "信号日低开不超过5%", lambda s: s["gap"] is not None and s["gap"] >= -0.05),
        (
            "combo_mkt15_ma60_pos40_amt1e8",
            "组合：大盘>-1.5% + MA60上方 + 收盘位置>=40% + 成交额>=1亿",
            lambda s: (
                s["market_pct"] is not None
                and s["market_pct"] > -0.015
                and bool(s["above_ma60"])
                and s["close_pos"] is not None
                and s["close_pos"] >= 0.40
                and s["signal_amount"] >= 100_000_000
            ),
        ),
        (
            "combo_mkt20_ma60_pos25_amt1e8",
            "组合：大盘>-2.0% + MA60上方 + 收盘位置>=25% + 成交额>=1亿",
            lambda s: (
                s["market_pct"] is not None
                and s["market_pct"] > -0.02
                and bool(s["above_ma60"])
                and s["close_pos"] is not None
                and s["close_pos"] >= 0.25
                and s["signal_amount"] >= 100_000_000
            ),
        ),
        (
            "combo_mkt20_pos40_vol_amt1e8",
            "组合：大盘>-2.0% + 收盘位置>=40% + 量比1.2-3 + 成交额>=1亿",
            lambda s: (
                s["market_pct"] is not None
                and s["market_pct"] > -0.02
                and s["close_pos"] is not None
                and s["close_pos"] >= 0.40
                and s["vol_ratio20"] is not None
                and 1.2 <= s["vol_ratio20"] <= 3
                and s["signal_amount"] >= 100_000_000
            ),
        ),
    ]


def exit_returns(signal: dict) -> list[tuple[str, str, float, str]]:
    buy = float(signal["buy_close"])
    results = [
        ("next_close", "", sell_return(buy, float(signal["next_close"])), "close"),
        ("next_open", "", sell_return(buy, float(signal["next_open"])), "open"),
    ]
    for target in TARGET_ONLY:
        target_price = buy * (1 + target)
        if float(signal["next_high"]) >= target_price:
            results.append(("target_only_close", str(target), sell_return(buy, target_price), "target"))
        else:
            results.append(("target_only_close", str(target), sell_return(buy, float(signal["next_close"])), "close"))
    return results


def summarize(groups: dict[tuple, list[float]], meta: dict[tuple, dict]) -> list[dict]:
    rows = []
    for key, returns in groups.items():
        if not returns:
            continue
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        row_meta = meta[key]
        rows.append(
            {
                **row_meta,
                "trades": len(returns),
                "win_rate": len(wins) / len(returns),
                "avg_return": statistics.mean(returns),
                "median_return": statistics.median(returns),
                "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) else "",
                "max_trade_loss": min(returns),
                "max_trade_gain": max(returns),
                "return_stdev": statistics.pstdev(returns) if len(returns) > 1 else 0,
            }
        )
    rows.sort(key=lambda r: (r["avg_return"], r["trades"]), reverse=True)
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    constituents = load_or_fetch_constituents(refresh=False)
    wanted = [row for row in constituents if row["pool"] in INDEX_TYPES]

    market_pct = build_pool_market_pct(wanted)
    specs = filter_specs()

    groups: dict[tuple, list[float]] = defaultdict(list)
    group_meta: dict[tuple, dict] = {}
    filter_descriptions = {name: desc for name, desc, _ in specs}
    raw_signals = 0
    matched = defaultdict(int)

    for pool in INDEX_TYPES:
        pool_rows = [row for row in wanted if row["pool"] == pool]
        for item_idx, item in enumerate(pool_rows, 1):
            rows = fetch_price_rows(item["code"], refresh=False)
            for i in range(1, len(rows) - 1):
                today = rows[i]
                if today["date"] < START_DATE:
                    continue
                if today["amount"] < MIN_AMOUNT:
                    continue
                if is_one_price_limit_down(today):
                    continue
                if today["pct_chg"] > max(DROP_THRESHOLDS) * 100:
                    continue
                signal = make_signal(item, rows, i, market_pct.get((item["pool"], today["date"])))
                raw_signals += 1
                passed = [(name, desc) for name, desc, fn in specs if fn(signal)]
                for drop in DROP_THRESHOLDS:
                    if signal["signal_pct_chg"] > drop:
                        continue
                    for filter_name, filter_desc in passed:
                        matched[(filter_name, drop)] += 1
                        for exit_rule, target, ret, hit in exit_returns(signal):
                            key = (pool, filter_name, drop, exit_rule, target)
                            groups[key].append(ret)
                            group_meta[key] = {
                                "pool": pool,
                                "pool_name": INDEX_TYPES[pool]["name"],
                                "filter_name": filter_name,
                                "filter_desc": filter_desc,
                                "drop_threshold": drop,
                                "exit_rule": exit_rule,
                                "target": target,
                            }
            if item_idx % 50 == 0:
                print(f"processed {pool} {item_idx}/{len(pool_rows)} raw_signals={raw_signals}", flush=True)
                gc.collect()

    rows = summarize(groups, group_meta)
    write_csv(OUT_DIR / "filtered_summary.csv", rows)
    (OUT_DIR / "run_meta.json").write_text(
        json.dumps(
            {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "start_date": START_DATE,
                "end_date": datetime.now().strftime("%Y%m%d"),
                "raw_signals": raw_signals,
                "summary_rows": len(rows),
                "filter_descriptions": filter_descriptions,
                "matched_signal_counts": {f"{k[0]}|{k[1]}": v for k, v in sorted(matched.items())},
                "assumptions": {
                    "market_filter": "uses current constituent equal-weight daily pct change by pool as market proxy",
                    "entry": "signal day close",
                    "exits": ["next close", "next open", "target-only then close"],
                    "target_only": TARGET_ONLY,
                    "base_filters": f"exclude ST names, one-price limit-down days, and signal amount below {MIN_AMOUNT}",
                    "costs": {"commission": COMMISSION, "stamp_tax": STAMP_TAX, "slippage_each_side": SLIPPAGE},
                    "source_files": {
                        "constituents": str(CONSTITUENTS_PATH),
                        "prices": str(PRICE_DIR),
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {OUT_DIR / 'filtered_summary.csv'} rows={len(rows)} raw_signals={raw_signals}")
    for row in rows[:15]:
        print(row)


if __name__ == "__main__":
    main()
