from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from backtest.engines.base import _align
from backtest.engines.china_a import ChinaAEngine
from backtest.metrics import calc_metrics


ROOT = Path(__file__).resolve().parents[1]
PRICE_PATH = ROOT / "renminwang_ma_20_60" / "artifacts" / "ohlcv_603000.SH.csv"
OUTPUT_PATH = Path(__file__).resolve().parent / "results.csv"
CODE = "603000.SH"


@dataclass(frozen=True)
class Candidate:
    name: str
    signal: Callable[[pd.DataFrame], pd.Series]


def constant(weight: float) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda frame: pd.Series(weight, index=frame.index)


def ma_signal(short: int, long: int, weight: float) -> Callable[[pd.DataFrame], pd.Series]:
    def generate(frame: pd.DataFrame) -> pd.Series:
        close = frame["close"]
        return (close.rolling(short).mean() > close.rolling(long).mean()).astype(float) * weight
    return generate


def price_ma_signal(days: int, weight: float) -> Callable[[pd.DataFrame], pd.Series]:
    def generate(frame: pd.DataFrame) -> pd.Series:
        close = frame["close"]
        return (close > close.rolling(days).mean()).astype(float) * weight
    return generate


def ma_trailing_signal(
    short: int, long: int, stop: float, weight: float,
) -> Callable[[pd.DataFrame], pd.Series]:
    def generate(frame: pd.DataFrame) -> pd.Series:
        close = frame["close"]
        regime = close.rolling(short).mean() > close.rolling(long).mean()
        held = False
        peak = 0.0
        values = []
        for price, trend in zip(close, regime):
            if held:
                peak = max(peak, float(price))
                if not bool(trend) or float(price) <= peak * (1 - stop):
                    held = False
            elif bool(trend):
                held = True
                peak = float(price)
            values.append(weight if held else 0.0)
        return pd.Series(values, index=frame.index)
    return generate


def breakout_signal(
    entry_days: int, exit_days: int, stop: float, weight: float,
) -> Callable[[pd.DataFrame], pd.Series]:
    def generate(frame: pd.DataFrame) -> pd.Series:
        close = frame["close"]
        prior_high = frame["high"].rolling(entry_days).max().shift(1)
        prior_low = frame["low"].rolling(exit_days).min().shift(1)
        held = False
        peak = 0.0
        values = []
        for price, high, low in zip(close, prior_high, prior_low):
            if held:
                peak = max(peak, float(price))
                if float(price) < float(low) or float(price) <= peak * (1 - stop):
                    held = False
            elif pd.notna(high) and float(price) > float(high):
                held = True
                peak = float(price)
            values.append(weight if held else 0.0)
        return pd.Series(values, index=frame.index)
    return generate


def evaluate(
    frame: pd.DataFrame,
    candidate: Candidate,
    start: str,
    end: str,
) -> dict:
    full_signal = candidate.signal(frame)
    sample = frame.loc[start:end].copy()
    signal = full_signal.reindex(sample.index).fillna(0.0)
    dates, close, positions, returns = _align(
        {CODE: sample}, {CODE: signal}, [CODE],
    )
    config = {
        "initial_cash": 100_000,
        "commission_rate": 0.000115,
        "commission_min": 5.0,
        "stamp_tax": 0.0005,
        "transfer_fee": 0.00001,
        "slippage": 0.001,
    }
    engine = ChinaAEngine(config)
    engine._execute_bars(dates, {CODE: sample}, close, positions, [CODE])
    equity = pd.Series(
        [snapshot.equity for snapshot in engine.equity_snapshots],
        index=[snapshot.timestamp for snapshot in engine.equity_snapshots],
    )
    metrics = calc_metrics(equity, engine.trades, 100_000, 252, returns[CODE])
    return {
        "return": metrics["total_return"],
        "annual_return": metrics["annual_return"],
        "max_drawdown": metrics["max_drawdown"],
        "trades": metrics["trade_count"],
        "final_value": metrics["final_value"],
    }


def screen(frame: pd.DataFrame, candidate: Candidate) -> dict:
    signal = candidate.signal(frame).shift(1).fillna(0.0)
    close_return = frame["close"].pct_change().fillna(0.0)
    turnover = signal.diff().abs().fillna(signal.abs())
    # Fast screening approximation. Finalists are rerun through ChinaAEngine.
    cost = turnover * (0.000115 + 0.00001 + 0.001)
    cost += signal.diff().clip(upper=0).abs().fillna(0.0) * 0.0005
    equity = 100_000 * (1 + signal * close_return - cost).cumprod()
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    return {
        "screen_return": equity.iloc[-1] / 100_000 - 1,
        "screen_max_drawdown": drawdown.min(),
    }


def candidates() -> list[Candidate]:
    result: list[Candidate] = []
    weights = [0.15, 0.25, 0.33, 0.50, 0.67, 1.00]

    for weight in weights:
        result.append(Candidate(f"buy_hold_w{weight:.2f}", constant(weight)))

    for short in [10, 20, 40, 60]:
        for long in [60, 120, 180, 250]:
            if short >= long:
                continue
            for weight in weights:
                result.append(Candidate(
                    f"ma_{short}_{long}_w{weight:.2f}",
                    ma_signal(short, long, weight),
                ))

    for days in [20, 60, 120, 250]:
        for weight in weights:
            result.append(Candidate(
                f"price_ma_{days}_w{weight:.2f}",
                price_ma_signal(days, weight),
            ))

    for short in [10, 20, 40]:
        for long in [60, 120, 250]:
            if short >= long:
                continue
            for stop in [0.08, 0.12, 0.20]:
                for weight in weights:
                    result.append(Candidate(
                        f"ma_stop_{short}_{long}_s{stop:.2f}_w{weight:.2f}",
                        ma_trailing_signal(short, long, stop, weight),
                    ))

    for entry_days in [20, 60, 120]:
        for exit_days in [10, 20, 60]:
            if exit_days >= entry_days:
                continue
            for stop in [0.08, 0.12, 0.20]:
                for weight in weights:
                    result.append(Candidate(
                        f"breakout_{entry_days}_{exit_days}_s{stop:.2f}_w{weight:.2f}",
                        breakout_signal(entry_days, exit_days, stop, weight),
                    ))
    return result


def main() -> None:
    frame = pd.read_csv(PRICE_PATH, parse_dates=["trade_date"]).set_index("trade_date")
    all_candidates = candidates()
    screened = []
    for candidate in all_candidates:
        screened.append({"candidate": candidate, **screen(frame, candidate)})
    screened.sort(key=lambda row: row["screen_return"], reverse=True)
    shortlist = [
        row["candidate"] for row in screened
        if row["screen_max_drawdown"] >= -0.24
    ][:40]

    rows = []
    for candidate in shortlist:
        full = evaluate(frame, candidate, "2016-06-02", "2026-06-02")
        early = evaluate(frame, candidate, "2016-06-02", "2020-12-31")
        recent = evaluate(frame, candidate, "2021-01-01", "2026-06-02")
        rows.append({
            "strategy": candidate.name,
            "full_return": full["return"],
            "full_annual_return": full["annual_return"],
            "full_max_drawdown": full["max_drawdown"],
            "full_trades": full["trades"],
            "full_final_value": full["final_value"],
            "early_return": early["return"],
            "early_max_drawdown": early["max_drawdown"],
            "recent_return": recent["return"],
            "recent_max_drawdown": recent["max_drawdown"],
            "recent_trades": recent["trades"],
        })

    results = pd.DataFrame(rows).sort_values(
        ["full_return", "recent_return"], ascending=False,
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(OUTPUT_PATH, index=False)

    eligible = results[
        (results["full_max_drawdown"] >= -0.20)
        & (results["recent_max_drawdown"] >= -0.20)
    ]
    print("screened", len(all_candidates))
    print("exact_tested", len(results))
    print("eligible_full_and_recent_dd_le_20pct", len(eligible))
    print(eligible.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
