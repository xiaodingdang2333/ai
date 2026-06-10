from typing import Dict

import pandas as pd


class SignalEngine:
    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        signals = {}
        for code, frame in data_map.items():
            close = frame["close"]
            prior_high = frame["high"].rolling(20).max().shift(1)
            prior_low = frame["low"].rolling(10).min().shift(1)
            held = False
            peak = 0.0
            values = []

            for price, high, low in zip(close, prior_high, prior_low):
                if held:
                    peak = max(peak, float(price))
                    if float(price) < float(low) or float(price) <= peak * 0.92:
                        held = False
                elif pd.notna(high) and float(price) > float(high):
                    held = True
                    peak = float(price)
                values.append(0.33 if held else 0.0)

            signals[code] = pd.Series(values, index=frame.index)
        return signals
