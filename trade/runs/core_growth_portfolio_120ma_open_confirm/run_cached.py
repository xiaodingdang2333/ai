from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

from backtest.engines.china_a import ChinaAEngine


RUN_DIR = Path(__file__).resolve().parent
CONFIG = json.loads((RUN_DIR / "config.json").read_text(encoding="utf-8"))
YAHOO_CODES = {
    "600941.SH": "600941.SS",
    "600900.SH": "600900.SS",
    "000333.SZ": "000333.SZ",
    "601138.SH": "601138.SS",
}


def load_signal_engine():
    path = RUN_DIR / "code" / "signal_engine.py"
    spec = importlib.util.spec_from_file_location("signal_engine", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.SignalEngine()


def fetch_data() -> dict[str, pd.DataFrame]:
    frames = {}
    for code, ticker in YAHOO_CODES.items():
        raw = yf.download(
            ticker,
            start="2020-01-01",
            end="2026-06-03",
            auto_adjust=True,
            progress=False,
            timeout=20,
        )
        if raw.empty:
            raise RuntimeError(f"No data returned for {ticker}")
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        frame = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        frame.index.name = "trade_date"
        frames[code] = frame.loc[CONFIG["start_date"]:CONFIG["end_date"]].copy()
    return frames


class CachedLoader:
    name = "yfinance-cache"

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        return {
            code: self.frames[code].loc[start_date:end_date].copy()
            for code in codes
        }


class OpenConfirmChinaAEngine(ChinaAEngine):
    def __init__(self, config: dict):
        super().__init__(config)
        self.blocked_entry_month: dict[str, pd.Period] = {}

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        if direction == 1 and symbol not in self.positions:
            month = pd.Timestamp(bar.name).to_period("M")
            if self.blocked_entry_month.get(symbol) == month:
                return False
            threshold = bar.get("entry_confirm_ma")
            open_price = bar.get("open")
            if pd.notna(threshold) and pd.notna(open_price) and float(open_price) <= float(threshold):
                self.blocked_entry_month[symbol] = month
                return False
        return super().can_execute(symbol, direction, bar)


def main() -> None:
    frames = fetch_data()
    CONFIG["_run_card_effective_sources"] = ["yfinance-cache"]
    engine = OpenConfirmChinaAEngine(CONFIG)
    engine.run_backtest(
        CONFIG,
        CachedLoader(frames),
        load_signal_engine(),
        RUN_DIR,
        bars_per_year=252,
    )
    print("blocked_entry_months", {
        code: str(month) for code, month in engine.blocked_entry_month.items()
    })


if __name__ == "__main__":
    main()
