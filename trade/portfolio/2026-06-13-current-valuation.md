# Current Portfolio Valuation - 2026-06-13

Data refresh notes:

- Nasdaq QDII three-fund account value: 61,598.68 CNY, from user's Alipay fund account on 2026-06-26. Per-fund values: `017091` 35,549.32 CNY profit +6,249.32 CNY, yesterday -208.32 CNY, holding return 21.33%; `017093` 14,437.84 CNY profit +2,437.84 CNY, yesterday -84.84 CNY; `019118` 11,611.52 CNY profit +2,011.52 CNY, yesterday -68.07 CNY. This overrides monitor snapshots and public estimate values.
- Nasdaq QDII purchase status: suspended for purchase per user. Analysis should only consider hold, redeem/reduce, or available substitutes for new money.
- People.cn / Renminwang `603000.SH`: 500 shares, latest Tencent quote 15.34 CNY at 2026-06-25 16:14, position value about 7,670.00 CNY.
- Renminwang realized stock-account cash from earlier 200-share sale: 3,320 CNY in monitor state.
- CMB gold account: 16g with average cost 918.94 CNY/g from the user's CMB/App account as confirmed on 2026-06-25. Latest available CMB AU9999 quote on 2026-06-25 15:45 was 875.00; estimated CMB buy price 878.86 and estimated sell price 873.86, so estimated liquidation value is about 13,981.76 CNY.
- `009052`: 16,974.45 CNY from the user's latest App update on 2026-07-02, confirmed unit NAV 1.1671 and reconstructed holding 14,544.12646731 shares, with P/L -1,377.03 CNY against cost basis 18,351.48 CNY. Future values use saved shares multiplied by the latest confirmed NAV; intraday estimates must not be shown as unit NAV.
- `022430`: 10,525.04 CNY from user's securities app/account value on 2026-06-26, with app/account P/L +525.04 CNY and yesterday income +151.31 CNY. Implied cost basis remains about 10,000.00 CNY. Use this app value over public estimates. Note: prior records identify `022430` as 华夏中证A500ETF联接A; user may refer to it as "中正/中证500", so verify code if exact index exposure matters.
- Fixed wealth-management product: 50,000 CNY after 5,000 CNY was moved into `009052`; expected 4% annualized, matures 2026-07-27.
- Cash-like Lingqianbao balance: 10,022.68 CNY from user's app/account value on 2026-06-25.

Approximate portfolio value using refreshed/remembered values:

- Cash-like Lingqianbao: 10,022.68 CNY.
- Fixed wealth management: 50,000 CNY.
- A-share/fund holdings except Nasdaq: about 35,052.02 CNY using user app/account values for `009052` and `022430`, plus refreshed Renminwang price.
- Nasdaq QDII: 61,598.68 CNY from user's 2026-06-26 Alipay account values.
- Gold: about 14,120.96 CNY from latest local CMB/SGE estimate.
- Approximate total: 170,794.34 CNY.

Latest 2026-06-25 17:18 strategy review:

- Gold: no change to existing rules. Current estimated buy 878.86 is above the 870 normal add threshold, and the holding is below the 50g physical-use target, so the action is hold/no chase-buy/no sell. Keep normal small-add reminder at estimated buy <=870 and wait-for-stabilization rule at <=850 or freefall.
- `009052` dividend fund and `022430` A500: do not move all Lingqianbao cash into them in one shot. Keep at least 5,000-8,000 CNY cash-like liquidity; if deploying current cash, use 2,000-3,000 CNY in batches, tilted toward the smaller A500 position, with dividend fund additions only in smaller pullback batches.

Important rule:

- Before every future fund/stock/gold analysis, refresh prices/account values first. User app values are authoritative when provided; monitor `state.json` files are historical/rule context, not current portfolio value.
- Do not suggest adding to Nasdaq QDII while purchase is suspended; use hold/redeem/reduce logic and route new investable cash to available alternatives.
