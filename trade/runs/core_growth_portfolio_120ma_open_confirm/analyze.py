from pathlib import Path

import pandas as pd


RUN_DIR = Path(__file__).resolve().parent


def main() -> None:
    equity = pd.read_csv(RUN_DIR / "artifacts" / "equity.csv", parse_dates=["timestamp"])
    equity = equity.set_index("timestamp")["equity"]
    for year in range(2021, 2026):
        yearly = equity.loc[f"{year}-01-01":f"{year}-12-31"]
        yearly_return = yearly.iloc[-1] / yearly.iloc[0] - 1
        max_drawdown = (yearly / yearly.cummax() - 1).min()
        print(year, f"return={yearly_return:.2%}", f"max_drawdown={max_drawdown:.2%}")


if __name__ == "__main__":
    main()
