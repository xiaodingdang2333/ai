# People.cn Real-Trade Monitor

Local real-trade alert monitor for `603000.SH`. It never places real orders.

Recorded position:

- Cost: 18.40 CNY
- Original shares: 700
- Sold: 200 shares at 16.60 on 2026-06-11
- Current recorded shares: 500

Rules:

- 16.05 or below while recorded position is above 300 shares: notify to sell 200 shares.
- Close below 16.10 while recorded position is above 300 shares: notify to sell 200 shares.
- 16.50-16.80 rebound while recorded position is above 300 shares: fallback notify to sell 200 shares if it was not sold earlier.
- Below 15.50: notify to sell the remaining recorded position.
- No buy-back alert is enabled.
- Alerts are deduplicated by trading date and signal kind.

Notification config:

- ServerChan/Server酱微信推送 is used by default.
- Local config is in `ntfy.env`.
- Alerts include a feedback link to the existing public QR/login page service:
  - `http://8.212.144.72:8090/renminwang.html?...`
  - If no feedback is submitted, the monitor keeps the recorded position unchanged.
  - If sell/buy feedback is submitted, `state.json` updates `position`, `cash`, and `manual_actions`.
- Before sending each alert, the monitor reruns a lightweight vibetrading-style review using the latest quote. It may revise a raw threshold signal into "wait for rebound/confirmation" when price action has changed.
- Alert bodies should include detailed reasoning: latest price action, portfolio context, triggering rule, revised conclusion, and invalidation/next-action conditions.
- Key strategy nodes are checked at 09:40, 10:30, 11:20, 13:30, 14:45, and 15:05.
- At a key node, the script only calls the optional real vibetrading/LLM review when price is near a decision level, moving sharply, near the day high/low, or already triggering a hard rule.
- If vibetrading returns valid rule updates, the monitor writes them to `state.json` under `strategy_overrides` before sending the notification. The notification includes the updated values and the reason.
- If no LLM key/command is configured, the key-node LLM layer is skipped and the existing hard-rule monitor continues normally.

Optional vibetrading config in `ntfy.env`:

```bash
VIBETRADING_API_KEY=
VIBETRADING_BASE_URL=https://api.openai.com/v1
VIBETRADING_MODEL=deepseek-chat
VIBETRADING_FAST_MODEL=deepseek-chat
VIBETRADING_REASONER_MODEL=deepseek-reasoner
VIBETRADING_REVIEW_CMD=/home/admin/ai/trade/vibetrading_review.py
```

Model routing:

- Normal key-node reviews use `VIBETRADING_FAST_MODEL`.
- Real-trade signals, large moves, or prices very close to action levels use `VIBETRADING_REASONER_MODEL`.

Manual run:

```bash
cd /home/admin/ai/trade/runs/renminwang_paper_monitor
source ./ntfy.env
FORCE_MONITOR_RUN=1 python3 ./monitor.py
```

Update recorded position after a real trade:

```bash
python3 /home/admin/ai/trade/runs/renminwang_paper_monitor/monitor.py --set-position 300
```

Install Linux cron:

```bash
bash /home/admin/ai/trade/runs/renminwang_paper_monitor/install_cron.sh
```

Files:

- `state.json`: recorded position, quote cache, sent alert keys.
- `trades.log`: sent alert log.
- `scheduler.log`: cron output.
