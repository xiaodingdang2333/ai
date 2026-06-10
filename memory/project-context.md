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

- 2026-06-05: Server酱微信推送使用 `SERVER_CHAN_SENDKEY`，当前值为 `SCT359656T245KRDzgEMaHRDfMW9xG8xrz`. The Linux test message `linux第一次测试` succeeded via `https://sctapi.ftqq.com/{SERVER_CHAN_SENDKEY}.send`.

## Fanqie Automation

- 2026-06-07: Linux server cron runs `/home/admin/ai/scripts/fanqie-nightly-publish.sh` every day at 01:00 Asia/Shanghai. It switches Fanqie Snap Chromium caches, publishes drafts for `西大水怪/坏运气寄存处` and `桃枝醒醒/她替死人开口后，满京城都慌了`, stops on daily publish limit, and if no matching drafts exist asks Codex CLI to write 5 local chapters before uploading drafts. Publishing AI declaration is account-based: all `西大水怪` books select no AI use, all `桃枝醒醒` books select AI use. Logs are under `/home/admin/ai/output/fanqie-upload/nightly/`.
- 2026-06-07: Third Fanqie/Tomato account cache saved as `account-c` / `泡芙软呼呼`, Snap backup `.fanqie-profiles/snap-backups/account-c-snap`, usual CDP port `9225`. Publishing under `泡芙软呼呼` defaults to no AI use.
- 2026-06-07: Reusable scheduled-upload pattern lives in the Fanqie scripts/skill: cron script plus account-cache script, per-account AI declaration defaults, draft-first publishing, daily-limit stop condition, bounded auto-write batch, run logs, lock file, QR relay page, and mandatory cache replay verification after each new account login.
- 2026-06-07: Fanqie nightly state is tracked at `/home/admin/ai/output/fanqie-upload/nightly/state.json`. The nightly script sends ServerChan notifications for 100k published-character milestones and unresolved failures, gates future runs via `next-allowed-epoch` after Codex quota exhaustion, and uses `at` to schedule a one-shot delayed rerun when quota delays are detected. It switches a book to 1 chapter/day once its tracked published total reaches 100,000 characters. Initial tracked state: `坏运气寄存处` published through chapter 34, about 89,001 chars; `她替死人开口后，满京城都慌了` starts at 0 until automated publish records chapters.
