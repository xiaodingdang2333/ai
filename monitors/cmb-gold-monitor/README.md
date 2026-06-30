# CMB Gold Monitor

Local monitor for the user's CMB gold account position. It never places orders.

Recorded position:

- Holding: 10g
- Cost: 936.32 CNY/g
- Data source: CMB gold API, primary quote `AU9999`
- Estimated CMB buy price: `AU9999 + app_buy_offset_from_au9999`
- Estimated CMB sell price: estimated buy price minus `sell_spread_per_g`

Monitoring behavior:

- High-frequency price monitor runs without LLM calls.
- Key strategy nodes are configured in `config.json` under `strategy_summary_times`.
- At a key node, the script first checks whether price is near a decision level, moving sharply, near the day high/low, or already triggering a hard rule.
- Only when that pre-check is true does it call the optional vibetrading review command.
- If vibetrading returns rule updates, the script writes valid threshold updates back to `config.json` before notifying.
- A notification includes the updated rule values and the reason for the update.
- If no LLM key/command is configured, the monitor skips the LLM layer and keeps the existing hard-rule monitoring.

Optional vibetrading config is in `env`:

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
- Hard action signals, extreme moves, or prices very close to action levels use `VIBETRADING_REASONER_MODEL`.
