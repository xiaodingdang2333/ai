# Vibe-Trading Local Runtime

- The user wants this machine to have Vibe-Trading capabilities for stock/fund/portfolio research.
- Use the local skill at `/home/admin/ai/codex/skills/vibe-trading`.
- The dedicated runtime is `/home/admin/ai/codex/skills/vibe-trading/.venv`, built with Python 3.11.
- Prefer these stable entrypoints:
  - `vibetrading`
  - `vibetrading-local`
  - `vibe-trading`
  - `vibe-trading-mcp`
- Do not use `/home/admin/ai/trade/vibetrading_review.py` for requests where the user explicitly asks for Vibe-Trading itself rather than the DeepSeek wrapper.
- For future portfolio analysis, first read the current local holdings and monitor state, then use the Vibe-Trading skill docs/tools such as `asset-allocation`, `risk-analysis`, `fund-analysis`, `etf-analysis`, `technical-basic`, and market data loaders.
- For every fund/stock/gold holding analysis, refresh current prices/account values before analyzing. Monitor `state.json` files are historical/rule state only, not authoritative current market value.
- If the user provides a current value from an app, prefer that app value over interface estimates or monitor snapshots. Current known override: Nasdaq QDII three-fund total value is `64545.34` CNY from the user's Alipay fund account on 2026-06-23.
- The user's Nasdaq QDII holdings are currently suspended for purchase. Future analysis must not suggest adding to Nasdaq QDII or "stop adding"; valid choices are hold, redeem/reduce, or redirect new money to available alternatives.
- Stock/fund/gold advice memory lives in `/root/ai/memory/stock-finance.md`; read and update it for every future portfolio advice task.
