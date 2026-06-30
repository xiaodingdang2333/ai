from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from backtest import DROP_THRESHOLDS, MIN_AMOUNT, RESULT_DIR, START_DATE, fetch_price_rows, is_one_price_limit_down, sell_return
from filtered_backtest import make_signal
from industry_backtest import broad_module, load_or_fetch_constituents_with_industry


OUT_DIR = RESULT_DIR / "industry"
TARGETS = {
    ("高股息/公用", "vol_ratio_1.2_3", -0.06),
    ("高股息/公用", "vol_ratio_1.2_3", -0.07),
    ("传媒互联网", "base", -0.05),
    ("传媒互联网", "base", -0.06),
    ("传媒互联网", "base", -0.07),
    ("传媒互联网", "vol_ratio_1.2_3", -0.05),
    ("传媒互联网", "vol_ratio_1.2_3", -0.06),
    ("传媒互联网", "vol_ratio_1.2_3", -0.07),
    ("新能源", "close_pos_ge_0.25", -0.06),
    ("新能源", "close_pos_ge_0.25", -0.07),
    ("消费医药", "vol_1.2_3_and_close25", -0.07),
}


def passes(signal: dict, filter_name: str) -> bool:
    vol = signal["vol_ratio20"] is not None and 1.2 <= signal["vol_ratio20"] <= 3
    close25 = signal["close_pos"] is not None and signal["close_pos"] >= 0.25
    if filter_name == "base":
        return True
    if filter_name == "vol_ratio_1.2_3":
        return vol
    if filter_name == "close_pos_ge_0.25":
        return close25
    if filter_name == "vol_1.2_3_and_close25":
        return vol and close25
    raise ValueError(filter_name)


def summarize(group_returns: dict[tuple, list[float]]) -> list[dict]:
    rows = []
    for (module, filter_name, drop, year), returns in group_returns.items():
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        rows.append(
            {
                "module": module,
                "filter_name": filter_name,
                "drop_threshold": drop,
                "year": year,
                "trades": len(returns),
                "win_rate": len(wins) / len(returns),
                "avg_return": statistics.mean(returns),
                "median_return": statistics.median(returns),
                "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) else "",
                "max_trade_loss": min(returns),
                "max_trade_gain": max(returns),
            }
        )
    rows.sort(key=lambda r: (r["module"], r["filter_name"], float(r["drop_threshold"]), r["year"]))
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
    rows = load_or_fetch_constituents_with_industry(refresh=False)
    by_code = {}
    for row in rows:
        if row["code"] in by_code:
            continue
        module = broad_module(row.get("industry") or "")
        if module not in {"高股息/公用", "传媒互联网", "新能源", "消费医药"}:
            continue
        by_code[row["code"]] = {
            "pool": "all",
            "pool_name": "三指数去重",
            "code": row["code"],
            "name": row["name"],
            "module": module,
        }

    group_returns: dict[tuple, list[float]] = defaultdict(list)
    raw_signals = 0
    for idx, item in enumerate(by_code.values(), 1):
        price_rows = fetch_price_rows(item["code"], refresh=False)
        for i in range(1, len(price_rows) - 1):
            today = price_rows[i]
            if today["date"] < START_DATE:
                continue
            if today["amount"] < MIN_AMOUNT:
                continue
            if is_one_price_limit_down(today):
                continue
            if today["pct_chg"] > max(DROP_THRESHOLDS) * 100:
                continue
            signal = make_signal(item, price_rows, i, None)
            raw_signals += 1
            year = today["date"][:4]
            ret = sell_return(float(signal["buy_close"]), float(signal["next_close"]))
            for module, filter_name, drop in TARGETS:
                if module != item["module"]:
                    continue
                if signal["signal_pct_chg"] > drop:
                    continue
                if not passes(signal, filter_name):
                    continue
                group_returns[(module, filter_name, drop, year)].append(ret)
        if idx % 50 == 0:
            print(f"processed {idx}/{len(by_code)} raw_signals={raw_signals}", flush=True)

    result_rows = summarize(group_returns)
    write_csv(OUT_DIR / "module_yearly_breakdown.csv", result_rows)
    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "raw_signals_scanned": raw_signals,
        "stocks_scanned": len(by_code),
        "targets": sorted([list(x) for x in TARGETS]),
        "output": str(OUT_DIR / "module_yearly_breakdown.csv"),
    }
    (OUT_DIR / "yearly_breakdown_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
