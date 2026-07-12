# GEMINI.md

This file mirrors the durable workspace instructions and shared memory needed by Gemini or any other AI assistant.

## Qimao Submission Rule Trigger

- When the user asks to write, revise, package, or evaluate fiction for 七猫投稿/七猫内投, first read `F:\ai\memory\qimao-submission-rules.md`. Apply its ranking-derived rules: title must visibly promise the genre hook; first chapter starts inside a crisis, not a setting lecture; first 100 words need curiosity, first 300 words need emotion/conflict/gimmick; 女主 must quickly gain a visible 反制筹码; each chapter needs an immediate 局 and a chapter-end new 危机.
- For a first draft of a new 七猫投稿/七猫内投 novel, default to producing at least 20,000 Chinese characters unless the user says otherwise.

## Qimao Submission Lessons

- 2026-06-03: 七猫试投稿复盘：`坏运气寄存处`被拒理由是“综合质量一般、整体内容比较普通且缺乏吸引力”。以后写七猫内投稿要先扫同类榜单和作家交流区经验，按竖屏强情绪“三板斧”执行：句号分段、前100字给好奇点、前300字同时有情绪/冲突/噱头，背景穿插且单次不超过约50字；开篇结构优先“危机 + 金手指/反制资源 + 解决危机 + 打脸 + 共鸣 + 章尾反转留钩”。

## Shared memory

- Cross-tool shared memory lives at `F:\ai\memory`.
- If available, read `F:\ai\memory\README.md` first, then the relevant small files it points to:
  - `user-profile.md`
  - `workflow-preferences.md`
  - `project-context.md`
  - `lessons.md`
  - `decisions.md`
- When the user says “记住”, “以后都这样”, “总结经验”, or gives a durable correction/preference, update `F:\ai\memory` and also mirror the durable change into both:
  - `F:\ai\txt\CLAUDE.md`
  - `F:\ai\txt\GEMINI.md`
- Do not mirror per-novel concrete details such as pen names, character facts, plot state, or chapter-specific information into shared memory; keep those inside the corresponding novel project folder.
- Do not store secrets, passwords, tokens, API keys, or sensitive personal data unless explicitly requested.

## Stable user preferences

- Use Chinese by default unless the user asks otherwise.
- Be concise, conclusion first, then only key details needed to act.
- Prefer doing the requested local work over only explaining steps.
- Inspect the smallest relevant set of files before editing.
- Keep changes scoped to the user’s request.
- Do not overwrite or revert user changes unless explicitly asked.
- Run focused verification after changes when feasible, and briefly report command/result.

## GitHub push troubleshooting

- If `git push origin main` over HTTPS hangs, do not assume the commit is bad. First clear stale `git`, `git-remote-https`, and `git-credential-manager` processes, then test `git ls-remote --heads origin main`.
- On this machine, a successful `ls-remote` through proxy `127.0.0.1:7897` plus a hanging `push --dry-run` has indicated Git Credential Manager trouble. `git -c credential.helper= push --dry-run origin main` should return a credential error quickly if that is the blocker.
- SSH auth has worked for GitHub here. If `ssh -T git@github.com` succeeds, push with `git push git@github.com:xiaodingdang2333/ai.git main`, then run `git fetch origin main` so `origin/main` is refreshed.

## Workspace purpose

This directory is primarily a Chinese web-novel writing workspace, not a conventional software repository. Most work should happen inside individual novel project directories.

## 2026-07-09 Web/Server Novel Workflow

- The old custom GPT Action workflow under `services/novel-actions` is deprecated for novel writing, QA, revision, upload, and long-task orchestration.
- The authoritative web workflow is `/home/admin/chatgpt-novel-production-system` latest `main`, currently routed by `CURRENT.json` to the 2.2-LTS Git workflow.
- Web ChatGPT should write through Git project files by default. Server workers only consume explicit Git queues: `sample-requests/pending/*.json`, `server-write-requests/pending/*.json`, and upload-ready `novels/*/00_PROJECT.json`.
- Sample requests must use a 5x fallback pool: if N effective samples are needed, submit at least N*5 candidates with `min_effective_samples=N` and `max_attempts=N*5`; server stops once N packets are effective. Failed/insufficient sample requests should trigger same-genre fallback requests for up to 3 rounds.
- Server task progress should be viewed on the 8090 `/novel-jobs` page by default. ChatGPT should not do high-frequency polling unless the user asks for a status check.
- Server-side Codex writing is allowed only when a request declares `allow_server_codex=true`, `target_mode=continue_formal`, and `quality_profile=v2.2-LTS-strong`; it consumes server Codex quota.
- Fanqie draft upload must independently re-run server-side quality gates before upload. Do not upload based only on a chat claim that QA passed.

Common novel project structure:

```text
{书名}/
├── 设定/
│   ├── 题材定位.md
│   ├── 关系.md
│   ├── 角色/
│   ├── 世界观/
│   └── 势力/
├── 大纲/
│   ├── 大纲.md
│   ├── 卷纲_第一卷.md
│   └── 细纲_第XXX章.md
├── 正文/
├── 追踪/
│   ├── 上下文.md
│   ├── 伏笔.md
│   ├── 时间线.md
│   └── 角色状态.md
├── 封面/
└── 作品信息_番茄上传.md
```

Before continuing a novel, read at minimum:

1. `设定/题材定位.md`
2. `大纲/卷纲_第一卷.md` or current volume outline
3. `追踪/上下文.md`
4. `追踪/伏笔.md`
5. `追踪/角色状态.md`
6. the latest chapter in `正文/`

When writing new chapters, create or verify the matching `大纲/细纲_第XXX章.md` first, then write `正文/第XXX章_章名.md`, then update tracking files.

## Novel writing preferences

- Novel-writing requirements are mandatory defaults, not optional suggestions. Every time chapters are written, revised, uploaded, or evaluated, enforce them without waiting for the user to repeat them: every chapter the assistant writes must be at least 2500 Chinese characters in all circumstances, with no exceptions; formal chapters should normally target about 3000 Chinese characters; do not satisfy length by mechanically merging short chapters; avoid流水式对话, one-sentence paragraph pacing, dense template phrases, and overly functional/cliche titles; preserve strong hooks, visible conflict, concrete evidence/rules/body cost/public backlash, fuller scene texture, varied paragraph lengths, and chapter-end curiosity. Before upload or handoff, run a local chapter scan/word-count check and inspect for doubled text, title pasted into body, duplicate chapter numbers, weak title-content fit, and suspicious platform draft-list counts.
- For Fanqie upload, prioritize strong opening hooks, visible conflict, direct爽感, and chapter-end curiosity.
- Avoid formulaic/copycat book names and plots. Reference market patterns, but do not make names or premises look like obvious copies of trending books.
- Avoid流水式对话 and one-sentence-per-paragraph pacing.
- Use more细腻描写, concrete scene evidence, body cost, public witnesses, rules being read aloud, and visible backlash.
- For multi-party scenes, add three-sided reactions, body language, setting pressure, inner reactions, and varied paragraph lengths.
- Formal new/revised chapters should normally be about 3000 Chinese characters unless the user says otherwise.
- Template phrases such as `仿佛`, `一丝`, `一抹`, `缓缓`, `轻轻`, `淡淡`, `眼中闪过`, `嘴角勾起`, `这一刻` are not absolutely forbidden, but should be sparse and natural rather than dense default prose.
- Chapter titles should avoid overly functional/cliche keywords such as “病历” or “婚约” when possible; prefer fresher, more atmospheric titles with story-specific imagery.
- Do not rewrite locked existing chapters unless explicitly asked.

## Current/known novel projects

- `渡厄簿：她不替天命受罚了/` — Fanqie female-oriented quick-transmigration + xianxia revenge story. Author pen name: `桃枝醒醒`.
- `快穿：恶毒女配觉醒后，全员跪求我原谅/` — previous Fanqie quick-transmigration revenge project.
- `旧雨来信/` — structured novel project.

## Work memory note

- There is also a work-task memory file at `F:\ai\work\工作记忆.md`, mainly for professional/PPT/PDF/workflow tasks.
- For work資料、PPT、PDF、职场任务, read `F:\ai\work\工作记忆.md` if available.
- After solving any new problem, record the reusable lesson or fix pattern in shared memory and mirror durable updates here and in `txt/CLAUDE.md`, so future runs avoid repeating the same investigation and save tokens.
- Python environment: use `C:\Users\Administrator\.local\bin\python.exe` (uv-managed Python 3.12.13). Do not reinstall Python merely because `WindowsApps\python.exe` is also present.
- Voice design: this Windows machine has an AMD Radeon RX 6750 GRE. Use the installed `voice-design` skill with the official OmniVoice Hugging Face Space; do not attempt a local OmniVoice model install.
- Fanqie upload automation: if the browser asks “离开此网站”, choose “离开”; if the editor asks whether to keep editing a newly updated draft, choose “继续编辑”. Verify the final draft list once and avoid repeatedly switching pages.
- Fanqie upload automation must not trust editor-only character counts. After creating or editing each draft, verify the platform draft-list row shows a nonzero, non-suspicious word count; repair immediately if the row is 0 or clearly doubled.
- Scheduled novel uploads/publishing should be built as a reusable pipeline: keep per-platform/per-account browser caches, map each account to its cache and default declarations, verify visible account name before upload/publish, upload drafts first, publish from the draft box, stop on daily limits, generate only a bounded batch when drafts are exhausted, log each run, use a lock file for cron jobs, and replay-test any new login cache before considering it saved.
- Automated chapter generation feeding scheduled uploads must run the user's writing QA before upload: every generated chapter must be at least 2500 Chinese characters in all circumstances, normally target about 3000 Chinese characters; scan word counts; check duplicate chapter numbers, title pasted into body, doubled content, weak title-content fit, and suspicious platform draft counts.
- New web-novel projects should include cover support by default when preparing book creation materials. Always provide a polished cover prompt the user can paste into GPT/image2 to generate the cover. If the image tool exposes a file, also generate/save a vertical 2:3 PNG suitable for Fanqie/web-novel covers under the book project's `封面/` directory. Do not use local simple Pillow/vector placeholder art as the final cover.
- For new Fanqie quick-transmigration novels, reference the user's latest downloaded `txt/排行榜/番茄排行榜/` quick-transmigration ranking samples for title/intro/chapter format, wording, and rhythm. Favor direct list-style tags, strong contrast premises such as "they want X, I do Y", quick unit labels, lighter oral wording, and immediate anti-plot behavior, while still keeping original concepts rather than copying sample plots or phrasing.
- For all future quick-transmigration/快穿 novels, default chapter titles to the user's established Fanqie format: `第XXX章 小世界身份/单元名N`, where `N` is the within-world sequence number, e.g. `第001章 豪门真千金讨债1`, `第036章 古代退婚嫡女1`, or `第001章 豪门病弱真千金1`. Do not default to standalone literary/object-hook chapter titles like `雨夜门外` or `三个月病危单` for 快穿 books unless the user explicitly asks to change style.
- When giving Fanqie/Tomato book-creation info, generate the tag/category fields according to the user's screenshot of Fanqie creation options and requirements, not as free-form comma-separated tags. Use `/home/admin/ai/memory/fanqie-book-creation-tags.md` for the captured rules/options when available. If the screenshot/options are not available in the current context, say so and ask the user to re-upload or paste the options before finalizing tag info.
- For Fanqie scheduled publishing, 100,000 total published characters is the recommendation trigger. Once reached, notify via ServerChan once and then update only 1 chapter/day for that book. If Codex quota runs out during scheduled writing, delay five-hour quota failures by 5 hours; for weekly quota failures, resume at 01:00 on the parsed weekly reset date when possible. Notify the user for any unresolved scheduled-task problem with the book and log path.
- For Fanqie/Tomato uploads with multiple author accounts, keep separate browser profiles/cookie caches: `account-a` is for the `西大水怪` account; `account-b` is for the `桃枝醒醒` account. Do not use one account's profile for the other account.
- Fanqie/Tomato account map also includes `account-c` for `泡芙软呼呼`; publishing under this account defaults to declaring no AI use.
- To refresh a Fanqie/Tomato QR login for the existing public QR page, use the already-running CDP browser for the target account profile, click the visible `立即登录` button by DOM `button` text, then click the `扫码登录` element by exact text across all DOM nodes, extract the QR from the large `data:image/png;base64,...` image, and overwrite `/home/admin/ai/output/qr-login/current.png`. The public page is `http://8.212.144.72:8090/`; avoid starting a duplicate HTTP server.
- Skill storage: put all user-created or downloaded Codex skills under the AI workspace skill directory `F:\ai\codex\skills` / `/home/admin/ai/codex/skills` by default. If Codex discovery requires `~/.codex/skills`, use a symlink there and keep the canonical copy in the AI workspace.
- Fanqie automation: on the Linux server, cron runs `/home/admin/ai/scripts/fanqie-nightly-publish.sh` daily at 01:00 Asia/Shanghai. It switches Fanqie Snap Chromium caches, publishes drafts for `西大水怪/坏运气寄存处` and `桃枝醒醒/她替死人开口后，满京城都慌了`, stops on daily publish limit, and if no matching drafts exist asks Codex CLI to write 5 local chapters before uploading drafts. Publishing AI declaration is account-based: all `西大水怪` books select no AI use, all `桃枝醒醒` books select AI use. Logs are under `/home/admin/ai/output/fanqie-upload/nightly/`.
- Tiandao Fanqie automation: current Linux crontab runs `/home/admin/ai/scripts/fanqie-tiandao-daily-publish.sh` daily at 00:30 Asia/Shanghai for `天道破产后，我在修真界开养老院` under `account-c` / `泡芙软呼呼`; logs are under `/home/admin/ai/output/fanqie-upload/tiandao/`.
- Fanqie third account cache: `account-c` / `泡芙软呼呼`, Snap backup `.fanqie-profiles/snap-backups/account-c-snap`, usual CDP port `9225`; publish with no AI use by default.
- Reuse the Fanqie scheduled-upload pattern for future Fanqie or other-platform novel uploads: account cache + QR relay + draft-first upload + publish loop + daily-limit handling + bounded auto-writing + logs/lock + cache replay verification.
- Fanqie nightly state file: `/home/admin/ai/output/fanqie-upload/nightly/state.json`; next-run gate after quota exhaustion: `/home/admin/ai/output/fanqie-upload/nightly/next-allowed-epoch`. Quota delays also schedule a one-shot delayed rerun using `at`.
- Notification config: Server酱微信推送 uses `SERVER_CHAN_SENDKEY`, stored only in local env and never in Git. On 2026-06-05, Linux test message `linux第一次测试` succeeded via `https://sctapi.ftqq.com/{SERVER_CHAN_SENDKEY}.send`.
- Notification update: PushPlus is now the primary monitor notification channel, with Server酱 only as fallback. Do not store or print the PushPlus token in memory; it lives only in local env files for gold, flight, Renminwang, and QDII monitors.
- ntfy alert lesson: when sending from Python `urllib`, keep HTTP header values ASCII and put Chinese text in the message body; Chinese header values can raise `UnicodeEncodeError`. For A-share quote monitors, use a fallback source because Sina may return 403; Tencent `https://qt.gtimg.cn/q=sh603000` worked for `603000.SH`.
- QR/login webpage uploads are saved under `/home/admin/ai/output/qr-login/uploads/`; check there when the user says they uploaded something through the扫码 webpage. Flight price monitor note: `/home/admin/ai/monitors/flight-price-ckg-urc-20260815/` is scheduled by `flight-price-ckg-urc-monitor.timer` every 30 seconds for the 2026-08 CKG-URC Sichuan Airlines round trip. Ctrip mobile SEO pages can expose exact `flightNo` records; desktop/Trip.com may return anti-bot pages, and one-way-sum prices may differ from app round-trip package totals.
- CMB gold monitor note: `/home/admin/ai/monitors/cmb-gold-monitor/` is scheduled by `cmb-gold-monitor.timer` every 30 seconds. It monitors the user's 10g CMB gold account using CMB public Au99.99 quotes plus the App-vs-API calibration offset and a 5 CNY/g sell spread. Before any buy/sell WeChat alert, it fetches and analyzes the live price again; it only sends if the actionable rule still holds. Gold buy/sell notifications must include an 8090 feedback link; no feedback means no operation and no position change. Submitted gold feedback updates `config.json` `grams` and `cost_price_per_g`, and is recorded in gold `state.json` plus the unified `trade-feedback.jsonl`. The monitor now treats the first 50g as marriage physical-gold target holdings and only sends investment sell alerts for grams above 50g.
- Investment monitor LLM routing: do not call Codex from unattended cron/systemd monitors unless explicitly requested; it consumes Codex quota and is less stable for background jobs. Use script-first hard rules plus `/home/admin/ai/trade/vibetrading_review.py` with an OpenAI-compatible API. Route normal key-node reviews to `deepseek-chat` and hard action/extreme/near-threshold reviews to `deepseek-reasoner`. Never store API keys in shared memory or mirrored docs.
- Large financial backtests on the 1.6GB Aliyun VPS must be low-resource: stream by stock instead of loading all daily K data into Python dict caches, avoid huge per-trade CSVs unless requested, and run with lock/logs plus `nice`/`ionice`/`timeout`/memory cap. Reuse `/home/admin/ai/trade/runs/dip_rebound_a_share/run_filtered_safe.sh` as the safe pattern.
- Fanqie scheduled publish timeout lesson: if automation repeatedly clicks `确认发布` without returning to chapter management, save visible page/dialog text plus a CDP screenshot/body snapshot before failing. This distinguishes daily limit, content review, UI change, and platform/network submit failure instead of leaving only a generic timeout.
- 8090 QR/login toolbox upload cleanup: `/home/admin/ai/output/qr-login/server.py` serves the public page; top-page pasted/uploaded screenshots live in `/home/admin/ai/output/qr-login/uploads/`. The refresh cleanup should call `POST /api/uploads/clear` and stay scoped to `uploads/`, not the separate AI file manager under `/home/admin/ai`.
- Fanqie draft repair API: save existing/new drafts with `POST /app/book/cover_article/v0/` using form fields `book_id,item_id,title,content,volume_id,volume_name,device_platform=pc`, plus `item_version` from `edit_article.latest_version` when present. `/api/author/article/cover_article/v0/` can return empty 200 without saving. Never use `/app/book/publish_article/v0/` for draft repair because it can move content into the chapter/review list.
- Fanqie publishing default: for future Fanqie/Tomato novel publishing, use the stable backend API workflow from `/home/admin/ai/scripts/fanqie-api-publish.js` and scheduled wrapper `/home/admin/ai/scripts/fanqie-api-daily-publish.sh`, not Chrome/CDP click automation. Publish until the platform returns the daily word-limit message, verify the expected author account, and use PushPlus for scheduled failures; for draft exhaustion, notify only when a book's draft box is fully published.
- Fanqie scheduled publish notifications: default to PushPlus only. Do not send the old "remaining draft words below 20,000" alert; notify when a book's draft box is fully published and `final_draft_total` is 0.
## Investment Profile

- 2026-06-05 portfolio context: user wants this financial profile remembered across new sessions for investment and asset-allocation advice.
- Goal: maximize long-term returns in A-share stocks/funds and related funds, aiming for about 20%+ annualized return if possible, while keeping drawdown as low as possible, preferably under 10%; user prefers low-frequency operation, at most daily or every few days.
- Current investable cash flow: about 3,000 CNY per month can be added to investments.
- Current holdings as of 2026-06-11, using the user's Alipay/app values unless refreshed:
  - People.cn / Renminwang `603000.SH`: originally 700 shares at 18.40 CNY/share; on 2026-06-11 sold 200 shares at 16.60, leaving 500 shares recorded.
  - Fixed wealth-management product: 55,000 CNY, expected 4% annualized, matures 2026-07-27.
  - `009052` 易方达中证红利ETF联接C: current value 9,828.80 CNY; total return -180.22 CNY. On 2026-06-15, user submitted an additional 2,000 CNY buy/subscription application, pending confirmation.
  - `022430` 华夏中证A500ETF联接A: current value 9,828.86 CNY; total return -171.14 CNY.
  - Lingqianbao / cash-like balance: about 20,000 CNY after transferring 7,000 CNY from salary card.
  - 景顺长城纳斯达克科技基金/QDII holdings:
    - `017091`: current value 35,160.80 CNY; total return +5,860.80 CNY.
    - `017093`: current value 14,282.39 CNY; total return +2,282.39 CNY.
    - `019118`: current value 11,485.46 CNY; total return +1,185.46 CNY.
    - Total current value 60,928.65 CNY; total return +9,328.65 CNY.
  - CMB/招商银行 gold account: 10g gold, cost 936.32 CNY/g. As of 2026-06-11, app quoted buy price 896.92 CNY/g and sell price 891.92 CNY/g; use the app sell price for liquidation value when available, not only public Au99.99 quotes.
  - Gold goal update on 2026-06-15: user's base objective is to accumulate 50g CMB gold and later redeem physical gold for marriage use within about 1-2 years. Treat the first 50g as a core physical-use target position focused on low-cost accumulation, not as a trading position; only grams above 50g should be managed as investment/profit-seeking gold.
- Current strategy preference: keep Nasdaq technology QDII as core growth exposure unless major drawdown; do not add more to it while purchase is suspended; use new money and cash to build A-share broad index, dividend/low-volatility, short-duration/cash-like, and risk-balancing positions.
- Future investment analysis preference: automatically refresh latest available stock prices and fund NAV/estimates first, then analyze current market value, return, weights, and drawdown using the refreshed data plus the latest remembered app/account baseline.
- Renminwang notifications: before recommending an operation, refresh the latest quote and rerun a vibetrading-style review of current price action and portfolio context; if the recommendation changes, notify using the revised recommendation.
- Renminwang scheduled key-node reviews may run and update rules, but should stay quiet unless rules are actually changed. Do not send WeChat just because the model returns ordinary `notify=true`; hard buy/sell operation alerts remain separate.
- Gold scheduled key-node reviews run at 09:10, 10:30, 14:50, 20:10, and 23:30. They may call vibetrading and update rules, but should stay quiet unless rules actually change; ordinary model `notify=true` should not trigger WeChat. Hard buy/sell operation alerts remain separate.
- All investment buy/sell operation notifications must include a mobile-clickable feedback link and state that no feedback means no operation. This is required for gold, Nasdaq/QDII, Renminwang, and any future investment monitor.
- Investment operation recommendations must include detailed reasons: latest price/market context, portfolio impact, trigger rule, why the recommendation changed or stayed the same, and invalidation/next-action conditions.
- Any future fund or stock operation notification must include a web feedback link where the user can record what they actually did. If the user does not submit feedback, assume no operation. Submitted feedback should update the relevant local record when a dedicated state exists, otherwise append to the general trade feedback log.
- Web UI uploads: the user often provides task inputs as uploaded screenshots, files, or page captures. Treat those uploads as primary context when present. If the current session/model context cannot access an upload, say so directly and ask for re-upload or pasted key details instead of assuming the user did not provide it.
- 2026-06-27: 番茄小说默认采用人工发布协作：AI 写作并完成本地质检后，自动把新增章节上传到已核验账号和作品的草稿箱，逐章核对章节号、标题和平台字数；最终发布由用户手动完成。除非用户明确改变此规则，否则不得创建定时发布任务或调用自动发布入口。
- 2026-07-09: 旧“网页自定义GPT + `services/novel-actions`服务器Action + 服务器保存正文/上传”的小说生产流程已废弃，之后不再用于写作、修订、QA、上传或长任务执行。所有涉及`openapi-gpt.json`、4操作RPC、`runNovelWorkflow`、`runFanqieWorkflow`、`getNovelJob`、`saveNovelAssets`、`next_action.action/payload_schema`、网页Action检查点的旧规则只作为历史事故记录保留，不得作为当前执行依据。当前网页版小说生产权威流程是`/home/admin/chatgpt-novel-production-system`最新`main`中的2.2-LTS Git仓库工作流。
- 2026-07-09: 新的网页/服务器小说协作默认走 Git 队列：网页 ChatGPT 主要负责写作并提交仓库；样本请求写入`sample-requests/pending/*.json`，服务器把结果写入`sample-results/<request_id>/status.json`；小说达到上传标准后在项目`00_PROJECT.json`声明`upload_status=ready_for_draft_upload`及番茄账号/作品ID/QA证据，服务器扫描后只上传草稿。服务器 Codex 深度拆书只在请求显式`analysis_engine=server_codex`、`allow_codex=true`、`codex_scope=packet_deep_teardown`时允许。
- 2026-07-09: Git 队列服务器 worker 已落地：`/home/admin/ai/scripts/novel-git-poller.py`、`novel-git-sample-worker.py`、`novel-git-upload-worker.py`，systemd 模板在`/home/admin/ai/systemd/`。默认 dry-run；execute 才处理样本或上传草稿；`--git-commit --git-push`只提交本轮生成/更新路径，远端变化时不强推。
- 2026-07-04: 网页、Claude、Gemini、Codex 的连续写作和旧稿修订统一采用强制质量合同：每1至4章先规划主角选择、代价、状态变化、情绪回报、类型兑现与不同结构指纹；逐章独立自审、原子保存和QA，段末跨章审稿。未通过不得继续下一段或上传。
- 2026-07-05: 【已废弃：旧自定义GPT Action流程】网页GPT统一使用4操作小说RPC的规则不再作为当前执行依据；质量基准中“每章至少2500汉字、短段落比例不超过60%、主角以选择和代价推动剧情、禁止报告体循环”等仍可作为通用写作质量参考。
- 2026-07-05: 强质量写作和修订必须逐章执行“候选稿→独立批评→实际返修→重新验收→原子检查点→QA”。批评与验收需重建角色、时序、物件、年龄权限及现实约束模型；每项验收必须引用返修正文证据并给出推理，禁止只填通过。最多返修3轮，仍有中高风险问题交人工，未验收候选稿不能落盘或上传。
- 2026-07-05: 【已废弃：旧自定义GPT Action流程】`next_action.type/action/payload_schema`、scene_model隐藏字段、中央Action映射、写入后resume快照、`state_patch`检查点、`payload_json`兼容、`contract_create from/to`、`context_get`分页和小resume响应等规则不再作为当前小说生产执行依据，只作为旧流程事故记录。
- 2026-06-27: 以后新开番茄小说必须先运行 `fanqie-novel-ideation` 的“12选3”流程：只从本地榜单样本提取功能结构，生成12个结构不同的创意并评分，筛出3个后等待用户明确选择；选定前不建项目、不写正文。选定后只先写3章试读，用户再次确认后才可批量写作或上传。已有小说续写不受此门禁影响。
- 2026-06-27: 番茄扫榜拆书先以番茄官网榜单选书，再使用本地 SoNovel 选择性下载包。镜像作者显示“佚名”或章节数少于官网时不要直接排除，应核对简介或前几章标题；完全搜不到或无法确认同书就跳过，继续榜单下一本。模型只读精选章节，不整本载入。
- 2026-06-28: 女频快穿言情开篇不能把“男主帮女主解决问题”直接等同于感情线。榜文可以很早进入对话，但必须持续保持主角情感视角，交代她为何在意、如何被触动、为何想靠近。轻松甜宠写作应压缩职业流程、规则谈判和多人往返对话，每章至少形成一次双向情绪变化；背景优先补情感来历，男主偏爱必须超出职责，女主也要看见并回应他的需要。不要机械堆表情或心理词，所有描写都要推进关系。
- 2026-06-28: 快穿1v1言情中，男主不必第一章就真人长时间在场，但必须从第一章成为情绪中心，可用旧识、通信、照片、语音或共同任务制造期待。相爱默认经过“已有连接或注意—重复互动—可靠性验证—特殊优先级—自觉心动—关系确认”，不能把一次帮助直接跳写成爱情，也不要在初次见面当天无铺垫认定喜欢。优先让职业或世界机制承担新鲜前史，例如先通过长期语音协作形成默契，再转入现实靠近。
- 番茄上传解析 `第001章_标题.md` 时必须去掉“章”后的空格、点、下划线或连字符，避免把 `_` 带入平台标题；中断后需清理确认的0字未命名草稿并验收连续编号和非零字数。
- 2026-06-30: “同步到远端”默认执行可迁移复刻级同步：同步重要工作区内容、Codex skills、已安装插件、可迁移配置和历史任务/会话状态，并提供验证过的恢复脚本，使另一台服务器克隆后可基本复刻当前 Codex 能力。公开仓库中的敏感历史/状态必须使用仓库外单独保存的口令加密；不得提交认证文件、API token、浏览器 cookie/profile、服务凭据、锁、日志、二进制下载缓存或其他可再生成运行产物。
- 2026-06-30: SoNovel 聚合搜索会自行并发多个书源，市场研究外层只允许资源感知的 2/1 并发（可用内存至少 600MB 且负载低于 2.0 时为 2，否则为 1）。搜索或镜像匹配失败时自动换榜单下一本，不要求用户提供来源编号；成功章节包缓存复用。
- 2026-07-01: 【已废弃：旧自定义GPT Action流程】GPT Action市场任务终态小摘要、独立Action分页读拆书正文、35秒轮询等规则不再作为当前执行依据。
- 2026-07-01: 【已废弃：旧自定义GPT Action流程】自定义GPT生成/保存封面提示词、`createNovelProject`幂等恢复、服务器验收封面PNG等规则不再作为当前执行依据。
- 2026-07-02: novel-actions服务以admin运行，但Snap Chromium缓存属于root；后台番茄绑定/上传时仅缓存切换与保存步骤使用`sudo -n`，不要放宽`/root`权限。
- 2026-07-02: 番茄后台找书必须轮询等待作品管理页链接渲染（最多60秒，30秒无结果刷新一次），不要把慢加载的空列表误判为作品未创建。
- 2026-07-02: 番茄账号识别最长轮询30秒，只接受问候语昵称或页面唯一白名单笔名；仍为UNKNOWN时必须阻止上传，不能跳过账号校验。
- 2026-07-02: 保存和上传章节时必须剥离标题中一个或多个已有`第XXX章`前缀，避免平台标题重复章号及草稿验收超时。
- 2026-07-02: 低配服务器的Snap Chromium需使用单渲染进程、关闭扩展并限制JS/磁盘缓存；新书草稿优先逐章上传验收，出现I/O卡死或持续高CPU立即停止，禁止并发重试。
- 2026-07-02: 【已废弃：旧自定义GPT Action流程】自定义GPT首次3章、后续按4章分批、root入口逐章上传、同轮轮询后台任务、杀掉重复queued/running任务等规则不再作为当前执行依据。
- 2026-07-02: 番茄上传仅在账号核验成功后保存缓存；LOGIN_REQUIRED、UNKNOWN或账号不符时只关闭浏览器，禁止覆盖有效备份。
- 2026-07-02: 番茄草稿验收统一使用draft_list API，不依赖网页表格；保留重复记录并返回匹配数、标题、字数和item_id。
- 2026-07-02: fanqie-upload.js已内置草稿API严格验收，root包装器不再追加同会话二次列表验收；列表脚本仅用于故障诊断。
- 2026-07-02: 判断番茄草稿是否成功必须读取权威draft-status；平台成功验收快照和uploaded标记优先，failed任务不能推翻已存在草稿。
- 2026-07-03 小说原创门禁：服务器 Codex 与当前网页版2.2-LTS Git流程写任何新书时，必须执行八项硬门禁：禁用第一反应套路、12案承重结构分离、外部随机约束、跨书创意指纹、去皮换名测试、场景因果链、独立AI模板审稿、约70%类型熟悉感/30%结构创新。缺项或失败不得建书、写正文、通过QA或上传。规范见`codex/skills/fanqie-novel-ideation/references/originality-gate.md`；只能降低AI识别风险，不得承诺绝对不会识别。
- 2026-07-03 拆书榜单来源：新书男频严格按`起点→飞卢→七猫→番茄`降级，女频严格按`晋江→七猫→番茄`降级。首轮必须使用链首平台，当前平台任务失败或整批不足3本有效样本后才可自动切下一平台，不得越级或默认番茄。镜像可负责下载，但选书和身份核验必须以当前官方平台榜单为准。
- 2026-07-03 Future web agent: 原“web GPT + controlled server Actions”设想不能复用旧小说Action流程；若以后实现，必须重新设计为受控、白名单、可审计的通用工具层，并优先围绕Git仓库产物工作。
- 2026-07-03 SoNovel mass-failure lesson: 0/75 usable books was caused by a 30-second whole-packet timeout and abort-on-one-short-chapter behavior, not universal source failure. The repaired default is 60 seconds per book with adaptive 1-3 concurrency, 480-second batch cap, stop at 6 successes, and neighboring-chapter fallback when one mirror page is short. Diagnose mass timeouts as infrastructure failure before expanding book lists.
- 2026-07-03 Novel project identity rule: create requests must carry the selected candidate's exact working_title. Resume is allowed only when title, account and ideation all match. A same-title/different-ideation project must return ideation_mismatch; only a pristine trial project may be backed up and rebound in place. Never silently reuse the wrong bible or create a renamed duplicate.
- 2026-07-03 Novel chapter persistence is two-phase: write/revise recoverable temporary drafts, run all mechanical/originality/AI-pattern/continuity gates, and only then promote to formal chapters. Failed drafts remain editable. First three chapters require user approval; later batches follow auto/review mode. Staged tracking state must not overwrite canonical state before promotion.
- 2026-07-04: 【已废弃：旧自定义GPT Action流程】Web-GPT原子服务器检查点、按`book_id`模糊查书、Fanqie bulk upload轮询、`novel-actions`数据库导入旧书等规则不再作为当前执行依据。
- 2026-07-03 Fanqie bind lesson: an empty candidate list can be a finder parser bug even when the exact unpublished work is visible. The chapter-manage URL parser must avoid regex literals embedded in Runtime.evaluate template strings; parse `/chapter-manage/<book_id>&<encoded-title>` by string splitting and direct digit validation. Inspect DOM anchors before blaming title mismatch.
- 2026-07-11: 当前网页Git小说流程中，模型自报Strong QA PASS不是机器证据。网页新章必须先提交正文、绑定当前SHA的语义审稿和`章节事实账本/CHxxx.json`，事务停在`FORMAL_WRITTEN_PENDING_MACHINE_P0`；服务器脚本对current blob生成P0/READY后才允许状态应用和草稿上传。正文任何改动都使旧证据失效。
- 2026-07-11: 番茄浏览器需由`xvfb-99.service`和`fanqie-browser-lease.sh`恢复X11及`/run/user/0/snap.chromium`，并与ChatGPT浏览器串行。建书前运行额度预检；月度上限时返回`PLATFORM_CREATE_LIMIT`，用`fanqie-book-package.js`输出人工建书包，不得伪报成功。
- 2026-07-11: ChatGPT浏览器必须由开机启用的`chatgpt-web-browser.service`持久运行，不能以`systemd-run --collect`临时恢复；番茄租约释放后执行`systemctl start`并等待9224 CDP，恢复失败须返回失败。
- 2026-07-12: 网页Git拆书默认由服务器 worker 处理候选下载、清洗、质量检查与 packet 回写，网页 ChatGPT 在 packet 齐备后做深度拆书。实时状态看 8090“小说模块→拆书 Packet 进度”，避免让网页 ChatGPT 高频轮询；状态应展示候选池、尝试/有效数、逐书结果、packet 路径和更新时间，新增 packet 带`packet_generated_at`。
