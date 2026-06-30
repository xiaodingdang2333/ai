from __future__ import annotations

import csv
import gc
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib import parse

from backtest import (
    DROP_THRESHOLDS,
    MIN_AMOUNT,
    RESULT_DIR,
    START_DATE,
    http_get_json,
    fetch_price_rows,
    is_one_price_limit_down,
    sell_return,
)
from filtered_backtest import close_position, exit_returns, make_signal, pct


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT_DIR = RESULT_DIR / "industry"
CONSTITUENTS_INDUSTRY_PATH = DATA_DIR / "constituents_with_industry.csv"

INDEX_TYPES = {
    "hs300": {"type": "1", "name": "沪深300"},
    "csi500": {"type": "3", "name": "中证500"},
    "csi_a500": {"type": "6", "name": "中证A500"},
}


def load_or_fetch_constituents_with_industry(refresh: bool = False) -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CONSTITUENTS_INDUSTRY_PATH.exists() and not refresh:
        with CONSTITUENTS_INDUSTRY_PATH.open("r", encoding="utf-8", newline="") as f:
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
                if type_id != meta["type"]:
                    continue
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
                        "industry": str(row.get("INDUSTRY") or "未知行业"),
                    }
                )
        time.sleep(0.2)

    with CONSTITUENTS_INDUSTRY_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["pool", "pool_name", "code", "name", "secucode", "type", "industry"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows


def broad_module(industry: str) -> str:
    text = industry or ""
    mapping = [
        ("金融地产", ["银行", "证券", "保险", "房地产", "多元金融"]),
        ("科技成长", ["半导体", "软件", "计算机", "通信", "电子", "IT", "互联网服务", "元件"]),
        ("新能源", ["电池", "光伏", "风电", "能源金属", "电源设备", "电网设备"]),
        ("消费医药", ["白酒", "食品", "饮料", "医药", "医疗", "生物制品", "化学制药", "中药", "家电", "商贸", "美容护理", "旅游", "酒店"]),
        ("周期资源", ["煤炭", "钢铁", "有色", "化学", "化工", "石油", "贵金属", "小金属", "工业金属", "建材", "水泥", "玻璃"]),
        ("高股息/公用", ["电力", "公用事业", "燃气", "水务", "铁路", "高速", "港口", "航运", "运营商"]),
        ("传媒互联网", ["传媒", "游戏", "影视", "出版", "广告营销", "文化传媒"]),
        ("军工", ["航天", "航空", "军工", "船舶", "兵器"]),
        ("汽车制造", ["汽车", "乘用车", "商用车", "汽车零部件", "摩托车"]),
    ]
    for module, keywords in mapping:
        if any(k in text for k in keywords):
            return module
    return "其他制造/综合"


def build_group_market_pct(items: list[dict], group_key: str) -> dict[tuple[str, str], float]:
    daily_sum: dict[tuple[str, str], float] = defaultdict(float)
    daily_count: dict[tuple[str, str], int] = defaultdict(int)
    seen = set()
    for item in items:
        # Avoid double-counting the same stock in multiple index pools for group market proxy.
        dedupe_key = (item["code"], item[group_key])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows = fetch_price_rows(item["code"], refresh=False)
        for row in rows:
            if row["date"] >= START_DATE:
                key = (item[group_key], row["date"])
                daily_sum[key] += float(row["pct_chg"]) / 100
                daily_count[key] += 1
    return {key: daily_sum[key] / count for key, count in daily_count.items() if count}


def filter_specs() -> list[tuple[str, str]]:
    return [
        ("base", "基础规则"),
        ("vol_ratio_1.2_3", "量比20日均量在1.2-3倍"),
        ("close_pos_ge_0.25", "收盘位置>=25%"),
        ("vol_1.2_3_and_close25", "量比1.2-3倍 + 收盘位置>=25%"),
        ("vol_1.2_3_and_close40", "量比1.2-3倍 + 收盘位置>=40%"),
        ("vol_1.2_3_close25_ma60", "量比1.2-3倍 + 收盘位置>=25% + MA60上方"),
        ("group_gt_-1.5", "所属行业/模块当日等权跌幅>-1.5%"),
        ("group_gt_-2.0", "所属行业/模块当日等权跌幅>-2.0%"),
        ("vol_close25_group_gt_-2", "量比1.2-3倍 + 收盘位置>=25% + 所属行业/模块>-2%"),
    ]


def passed_filters(signal: dict, group_pct: float | None) -> set[str]:
    vol = signal["vol_ratio20"] is not None and 1.2 <= signal["vol_ratio20"] <= 3
    close25 = signal["close_pos"] is not None and signal["close_pos"] >= 0.25
    close40 = signal["close_pos"] is not None and signal["close_pos"] >= 0.40
    above_ma60 = bool(signal["above_ma60"])
    result = {"base"}
    if vol:
        result.add("vol_ratio_1.2_3")
    if close25:
        result.add("close_pos_ge_0.25")
    if vol and close25:
        result.add("vol_1.2_3_and_close25")
    if vol and close40:
        result.add("vol_1.2_3_and_close40")
    if vol and close25 and above_ma60:
        result.add("vol_1.2_3_close25_ma60")
    if group_pct is not None and group_pct > -0.015:
        result.add("group_gt_-1.5")
    if group_pct is not None and group_pct > -0.02:
        result.add("group_gt_-2.0")
    if vol and close25 and group_pct is not None and group_pct > -0.02:
        result.add("vol_close25_group_gt_-2")
    return result


def summarize(groups: dict[tuple, list[float]], meta: dict[tuple, dict]) -> list[dict]:
    rows = []
    for key, returns in groups.items():
        if not returns:
            continue
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        row = {
            **meta[key],
            "trades": len(returns),
            "win_rate": len(wins) / len(returns),
            "avg_return": statistics.mean(returns),
            "median_return": statistics.median(returns),
            "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) else "",
            "max_trade_loss": min(returns),
            "max_trade_gain": max(returns),
            "return_stdev": statistics.pstdev(returns) if len(returns) > 1 else 0,
        }
        rows.append(row)
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


def run_level(items: list[dict], level: str, group_key: str, group_name_key: str) -> tuple[list[dict], dict]:
    group_market = build_group_market_pct(items, group_key)
    filter_desc = dict(filter_specs())
    groups: dict[tuple, list[float]] = defaultdict(list)
    meta: dict[tuple, dict] = {}
    raw_signals = 0
    unique_seen = set()

    for idx, item in enumerate(items, 1):
        unique_key = (item["code"], level)
        if unique_key in unique_seen:
            continue
        unique_seen.add(unique_key)
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
            group_pct = group_market.get((item[group_key], today["date"]))
            signal = make_signal(item, rows, i, group_pct)
            raw_signals += 1
            pass_set = passed_filters(signal, group_pct)
            for drop in DROP_THRESHOLDS:
                if signal["signal_pct_chg"] > drop:
                    continue
                for filter_name in pass_set:
                    for exit_rule, target, ret, _hit in exit_returns(signal):
                        key = (level, item[group_key], filter_name, drop, exit_rule, target)
                        groups[key].append(ret)
                        meta[key] = {
                            "level": level,
                            "group": item[group_key],
                            "group_name": item[group_name_key],
                            "filter_name": filter_name,
                            "filter_desc": filter_desc[filter_name],
                            "drop_threshold": drop,
                            "exit_rule": exit_rule,
                            "target": target,
                        }
        if idx % 100 == 0:
            print(f"processed {level} {idx}/{len(items)} raw_signals={raw_signals}", flush=True)
            gc.collect()
    return summarize(groups, meta), {"raw_signals": raw_signals, "unique_items": len(unique_seen)}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_or_fetch_constituents_with_industry(refresh=False)
    by_code: dict[str, dict] = {}
    for row in rows:
        code = row["code"]
        if code not in by_code:
            by_code[code] = {
                "pool": "all",
                "pool_name": "三指数去重",
                "code": code,
                "name": row["name"],
                "industry": row.get("industry") or "未知行业",
            }
            by_code[code]["module"] = broad_module(by_code[code]["industry"])
    unique_items = list(by_code.values())

    industry_rows, industry_meta = run_level(unique_items, "industry", "industry", "industry")
    module_rows, module_meta = run_level(unique_items, "module", "module", "module")

    write_csv(OUT_DIR / "industry_summary.csv", industry_rows)
    write_csv(OUT_DIR / "module_summary.csv", module_rows)
    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": START_DATE,
        "end_date": datetime.now().strftime("%Y%m%d"),
        "unique_stocks": len(unique_items),
        "industry_count": len({x["industry"] for x in unique_items}),
        "module_count": len({x["module"] for x in unique_items}),
        "industry": industry_meta,
        "module": module_meta,
        "filters": dict(filter_specs()),
        "exits": ["next_close", "next_open", "target_only_close 2%", "target_only_close 3%"],
        "base_filters": f"exclude ST names, one-price limit-down days, and signal amount below {MIN_AMOUNT}",
        "note": "Industry comes from Eastmoney RPT_INDEX_TS_COMPONENT current constituent INDUSTRY field; modules are local keyword buckets.",
    }
    (OUT_DIR / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("top industry:")
    for row in industry_rows[:20]:
        print(row)
    print("top module:")
    for row in module_rows[:20]:
        print(row)


if __name__ == "__main__":
    main()
