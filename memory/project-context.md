# Project Context

- Main workspace root: `F:\ai`.
- Common working directory: `F:\ai\anything`.
- Codex skills directory: store all user-created or downloaded skills under the workspace at `F:\ai\codex\skills` / `/home/admin/ai/codex/skills`; keep `~/.codex/skills` only for system skills or symlinks needed for Codex discovery.
- Existing shared instruction file: `F:\ai\AGENTS.md`.
- Installed custom skill: `video-chord-sheet`.
- Installed Obsidian-related skills: `obsidian-markdown`, `obsidian-bases`, `json-canvas`, `obsidian-cli`, `defuddle`.
- Python command entrypoint: `C:\Users\Administrator\.local\bin\python.exe` (uv-managed Python 3.12.13). Do not assume Python is missing just because `WindowsApps\python.exe` exists.
- Voice design runtime: `F:\ai\anything\voice-design-runtime`. Use the installed `voice-design` skill and official OmniVoice Hugging Face Space; do not install local OmniVoice on this Windows AMD GPU machine.

## Notification Config

- 2026-06-05: Server酱微信推送使用 `SERVER_CHAN_SENDKEY`，值仅保存在本地 env，不写入仓库。 The Linux test message `linux第一次测试` succeeded via `https://sctapi.ftqq.com/{SERVER_CHAN_SENDKEY}.send`.
- 2026-06-12: 监控通知主通道改为 PushPlus，Server酱只作兜底；token 写在各监控本地 env 文件中，不写入共享记忆。已接入黄金、航班、人民网、QDII 监控。
- 2026-06-11: 招行黄金监控运行在 `/home/admin/ai/monitors/cmb-gold-monitor/`，由 `cmb-gold-monitor.timer` 每 30 秒执行一次；使用招行公开黄金接口 `https://m.cmbchina.com/api/rate/gold` 的 Au99.99 实时价，加上用户当时 App 买入价与接口价的校准偏差，并按卖出价低 5 元/克估算可卖价。触发前会再次实时抓价复核，只有买入/卖出建议仍成立才 ServerChan 微信通知。
- 2026-06-15: 招行黄金买/卖通知也必须带 8090 反馈链接。用户不提交反馈时默认没有操作，不得因为发过提醒就改持仓；提交反馈后，`/api/trade-feedback` 会按实际克数和成交价更新 `/home/admin/ai/monitors/cmb-gold-monitor/config.json` 的 `grams` 和 `cost_price_per_g`，并把记录写入黄金 `state.json` 与统一 `trade-feedback.jsonl`。
- 2026-06-15: 黄金监控策略改为区分婚用实物目标仓和投资仓：用户计划1-2年内攒够并兑换50克招行实物黄金用于结婚，当前50克以内不因小浮盈卖出；只有超过50克的部分才触发投资型止盈/止损卖出提醒。
- 2026-06-15: 人民网监控的盘中关键节点复核仍可在固定时间运行并调用 vibetrading，但不要因为模型普通 `notify=true` 就推微信；只有实际更新后续规则时才推复核通知，真正买卖操作提醒继续由硬规则单独推送。
- 2026-06-15: 黄金监控也有固定盘中/夜盘复核点（09:10、10:30、14:50、20:10、23:30）。复核可调用 vibetrading，但普通 `notify=true` 不推微信；只有规则实际更新时才推复核通知，真正买卖提醒继续由独立决策规则发送。
- 2026-06-15: 所有投资类买卖操作提醒都必须带手机可点的反馈链接，并明确“不提交反馈则按未操作处理”。已检查并覆盖黄金、纳斯达克/QDII、人民网三个监控；新增监控也要沿用该规则。
- 2026-06-15: A股“大跌买入、次日反弹卖出”回测位于 `/home/admin/ai/trade/runs/dip_rebound_a_share/`。当前标准库脚本覆盖沪深300/中证500/中证A500当前成分股 2021-01-01 至 2026-06-15；裸策略只有“-5% 跌幅、次日收盘卖”出现极薄正收益，中证500平均约 +0.0256%/笔，-6%/-7%/-8%、次日开盘卖、简单止盈止损整体转差。该方向只能作为研究候选，不能直接上线为买卖提醒，后续需先加趋势、大盘、流动性、承接形态和利空过滤。

## Fanqie Automation

- 2026-06-17: Current Linux crontab includes `/home/admin/ai/scripts/fanqie-tiandao-daily-publish.sh` every day at 00:30 Asia/Shanghai for `天道破产后，我在修真界开养老院` under `account-c` / `泡芙软呼呼`; logs are under `/home/admin/ai/output/fanqie-upload/tiandao/`.
- 2026-06-07: Linux server cron runs `/home/admin/ai/scripts/fanqie-nightly-publish.sh` every day at 01:00 Asia/Shanghai. It switches Fanqie Snap Chromium caches, publishes drafts for `西大水怪/坏运气寄存处` and `桃枝醒醒/她替死人开口后，满京城都慌了`, stops on daily publish limit, and if no matching drafts exist asks Codex CLI to write 5 local chapters before uploading drafts. Publishing AI declaration is account-based: all `西大水怪` books select no AI use, all `桃枝醒醒` books select AI use. Logs are under `/home/admin/ai/output/fanqie-upload/nightly/`.
- 2026-06-07: Third Fanqie/Tomato account cache saved as `account-c` / `泡芙软呼呼`, Snap backup `.fanqie-profiles/snap-backups/account-c-snap`, usual CDP port `9225`. Publishing under `泡芙软呼呼` defaults to no AI use.
- 2026-06-07: Reusable scheduled-upload pattern lives in the Fanqie scripts/skill: cron script plus account-cache script, per-account AI declaration defaults, draft-first publishing, daily-limit stop condition, bounded auto-write batch, run logs, lock file, QR relay page, and mandatory cache replay verification after each new account login.
- 2026-06-07: Fanqie nightly state is tracked at `/home/admin/ai/output/fanqie-upload/nightly/state.json`. The nightly script sends ServerChan notifications for 100k published-character milestones and unresolved failures, gates future runs via `next-allowed-epoch` after Codex quota exhaustion, and uses `at` to schedule a one-shot delayed rerun when quota delays are detected. It switches a book to 1 chapter/day once its tracked published total reaches 100,000 characters. Initial tracked state: `坏运气寄存处` published through chapter 34, about 89,001 chars; `她替死人开口后，满京城都慌了` starts at 0 until automated publish records chapters.
