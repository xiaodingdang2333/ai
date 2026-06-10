from __future__ import annotations

from pathlib import Path

import pandas as pd

from search import Candidate, PRICE_PATH, candidates, evaluate


OUTPUT_PATH = Path(__file__).resolve().parent / "yearly_results.csv"
YEARS = [2021, 2022, 2023, 2024, 2025]


def screen_year(frame: pd.DataFrame, candidate: Candidate, year: int) -> dict:
    signal = candidate.signal(frame).shift(1).fillna(0.0)
    sample = frame.loc[f"{year}-01-01":f"{year}-12-31"]
    yearly_signal = signal.reindex(sample.index).fillna(0.0)
    close_return = sample["close"].pct_change().fillna(0.0)
    turnover = yearly_signal.diff().abs().fillna(yearly_signal.abs())
    cost = turnover * (0.000115 + 0.00001 + 0.001)
    cost += yearly_signal.diff().clip(upper=0).abs().fillna(0.0) * 0.0005
    equity = 100_000 * (1 + yearly_signal * close_return - cost).cumprod()
    drawdown = (equity - equity.cummax()) / equity.cummax()
    return {
        "return": equity.iloc[-1] / 100_000 - 1,
        "max_drawdown": drawdown.min(),
    }


def main() -> None:
    frame = pd.read_csv(PRICE_PATH, parse_dates=["trade_date"]).set_index("trade_date")
    all_candidates = candidates()
    screened_rows = []

    for candidate in all_candidates:
        row = {"candidate": candidate}
        for year in YEARS:
            metrics = screen_year(frame, candidate, year)
            row[f"{year}_return"] = metrics["return"]
            row[f"{year}_max_drawdown"] = metrics["max_drawdown"]
        row["min_year_return"] = min(row[f"{year}_return"] for year in YEARS)
        row["worst_year_drawdown"] = min(row[f"{year}_max_drawdown"] for year in YEARS)
        row["pass_year_count"] = sum(
            row[f"{year}_return"] > 0.20 and row[f"{year}_max_drawdown"] >= -0.20
            for year in YEARS
        )
        screened_rows.append(row)

    screened_rows.sort(
        key=lambda row: (row["pass_year_count"], row["min_year_return"]),
        reverse=True,
    )
    shortlist = [row["candidate"] for row in screened_rows[:40]]

    exact_rows = []
    for candidate in shortlist:
        row = {"strategy": candidate.name}
        for year in YEARS:
            metrics = evaluate(frame, candidate, f"{year}-01-01", f"{year}-12-31")
            row[f"{year}_return"] = metrics["return"]
            row[f"{year}_max_drawdown"] = metrics["max_drawdown"]
            row[f"{year}_trades"] = metrics["trades"]
        row["min_year_return"] = min(row[f"{year}_return"] for year in YEARS)
        row["worst_year_drawdown"] = min(row[f"{year}_max_drawdown"] for year in YEARS)
        row["pass_year_count"] = sum(
            row[f"{year}_return"] > 0.20 and row[f"{year}_max_drawdown"] >= -0.20
            for year in YEARS
        )
        exact_rows.append(row)

    results = pd.DataFrame(exact_rows).sort_values(
        ["pass_year_count", "min_year_return"], ascending=False,
    )
    results.to_csv(OUTPUT_PATH, index=False)

    print("screened", len(all_candidates))
    print("exact_tested", len(results))
    print("all_five_years_pass", int((results["pass_year_count"] == 5).sum()))
    print(results.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
