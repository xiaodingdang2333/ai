from __future__ import annotations

from pathlib import Path

import pandas as pd


RUN_DIR = Path(__file__).resolve().parent
YEARS = [2021, 2022, 2023, 2024, 2025]


def stats(series: pd.Series) -> tuple[float, float]:
    series = series.dropna()
    return float(series.iloc[-1] / series.iloc[0] - 1), float((series / series.cummax() - 1).min())


def main() -> None:
    equity = pd.read_csv(RUN_DIR / "artifacts" / "equity.csv", parse_dates=["timestamp"])
    equity = equity.set_index("timestamp")["equity"]
    print("strategy")
    for year in YEARS:
        yearly = equity.loc[f"{year}-01-01":f"{year}-12-31"]
        yearly_return, max_drawdown = stats(yearly)
        print(year, f"return={yearly_return:.2%}", f"max_drawdown={max_drawdown:.2%}")

    print("current_signals")
    positions = pd.read_csv(RUN_DIR / "artifacts" / "positions.csv", parse_dates=["timestamp"])
    print(positions.tail(1).to_string(index=False))


if __name__ == "__main__":
    main()
