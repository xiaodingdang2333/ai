# People.cn Paper Monitor

Local paper-trading monitor for `603000.SH`. It never places real orders.

Initial paper position:

- Cost: 18.40 CNY
- Shares: 700
- Initial capital: 12,880 CNY

Rules:

- Intraday price below 16.60: send a warning only, no paper sell.
- Close below 16.60: create a next-trading-day sell plan.
- Next trading day:
  - If price is still below 16.60, execute the paper sell at the observed price.
  - If price opens/recovers to 16.60 or above, cancel the paper sell plan.
- First confirmed sell: 300 shares.
- Second confirmed sell after another weak day: 200 shares.
- High-volume break below 16.20: plan to exit remaining paper shares.
- Take-profit 1: close at or above 19.30, plan to sell 200 shares next trading day if price still holds 19.30.
- Take-profit 2: close at or above 20.20, plan to sell 300 shares next trading day if price still holds 20.20.
- Take-profit 3: close at or above 21.20, plan to sell remaining shares next trading day if price still holds 21.20.
- Buy-back: after a risk reduction, close reclaiming 17.50 creates a next-trading-day buy-back plan.
  - Buy executes only if next trading day price is still at or above 17.50.
  - Buy is canceled if price is above 18.50, to avoid chasing.
  - Buy uses only recovered paper cash and only restores missing shares up to the original 700-share position.

Notifier config, choose one environment variable:

- `WECHAT_WEBHOOK_URL`
- `PUSHPLUS_TOKEN`
- `SERVER_CHAN_SENDKEY`

Manual run:

```powershell
python F:\ai\trade\runs\renminwang_paper_monitor\monitor.py
```

Files:

- `state.json`: paper position, pending plan, processed dates.
- `trades.log`: paper action log.
- `scheduler.log`: Windows scheduled-task output.
