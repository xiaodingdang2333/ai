from typing import Dict

import pandas as pd


class SignalEngine:
    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        signals = {}
        for code, frame in data_map.items():
            close = frame["close"]
            short_ma = close.rolling(window=20, min_periods=20).mean()
            long_ma = close.rolling(window=60, min_periods=60).mean()
            signals[code] = (short_ma > long_ma).astype(float).fillna(0.0)
        return signals
