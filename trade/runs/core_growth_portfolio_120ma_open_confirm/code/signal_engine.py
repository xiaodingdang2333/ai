from typing import Dict

import pandas as pd


WEIGHTS = {
    "600941.SH": 0.25,
    "600900.SH": 0.20,
    "000333.SZ": 0.15,
    "601138.SH": 0.15,
}


class SignalEngine:
    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        signals = {}
        for code, frame in data_map.items():
            close = frame["close"]
            moving_average = close.rolling(120, min_periods=120).mean()
            trend = close > moving_average
            monthly_review = frame.index.to_series().dt.to_period("M").ne(
                frame.index.to_series().dt.to_period("M").shift(-1)
            )
            reviewed_signal = (trend & monthly_review).where(monthly_review).ffill()
            frame["entry_confirm_ma"] = moving_average.shift(1)
            signals[code] = reviewed_signal.fillna(False).astype(float) * WEIGHTS[code]
        return signals
