# NDXTMC QDII Morning Monitor

Runs after the US market close, China time, to decide whether the user's 景顺纳指科技场外基金 holdings need action.

Schedule:

- Cron: Tuesday-Saturday 06:30 Asia/Shanghai.
- Only sends ServerChan notifications when an action is recommended.
- No notification means no action.

Important QDII rule:

- A morning China-time decision is based on the latest known US close.
- A same-day before-15:00 China redemption/subscription for QDII usually does not lock the already-known US close; it can still be affected by the next US session and FX.
- Therefore the monitor is conservative and only alerts on clear risk signals.

Feedback:

- Notifications include `trade-feedback.html`.
- If the user does not submit feedback, no operation is assumed.
- Submitted feedback is appended to `/home/admin/ai/output/qr-login/trade-feedback.jsonl`.
