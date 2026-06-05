# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qimao Submission Rule Trigger

- When the user asks to write, revise, package, or evaluate fiction for 七猫投稿/七猫内投, first read `F:\ai\memory\qimao-submission-rules.md`. Apply its ranking-derived rules: title must visibly promise the genre hook; first chapter starts inside a crisis, not a setting lecture; first 100 words need curiosity, first 300 words need emotion/conflict/gimmick; 女主 must quickly gain a visible 反制筹码; each chapter needs an immediate 局 and a chapter-end new 危机.
- For a first draft of a new 七猫投稿/七猫内投 novel, default to producing at least 20,000 Chinese characters unless the user says otherwise.

## Qimao Submission Lessons

- 2026-06-03: 七猫试投稿复盘：`坏运气寄存处`被拒理由是“综合质量一般、整体内容比较普通且缺乏吸引力”。以后写七猫内投稿要先扫同类榜单和作家交流区经验，按竖屏强情绪“三板斧”执行：句号分段、前100字给好奇点、前300字同时有情绪/冲突/噱头，背景穿插且单次不超过约50字；开篇结构优先“危机 + 金手指/反制资源 + 解决危机 + 打脸 + 共鸣 + 章尾反转留钩”。

## Workspace purpose

This directory is primarily a Chinese web-novel writing workspace, not a conventional software repository. Most work should happen inside individual novel project directories, each of which uses the same artifact structure for long-form writing.

Active novel projects include:

- `渡厄簿：她不替天命受罚了/` — current priority project. Female-oriented Fanqie quick-transmigration + xianxia revenge story by pen name `桃枝醒醒`. The first 10 chapters, settings, outlines, upload info, and tracking files exist.
- `快穿：恶毒女配觉醒后，全员跪求我原谅/` — previous Fanqie quick-transmigration revenge project.
- `旧雨来信/` — another structured novel project.

## Novel project structure

Each novel project is organized as:

```text
{书名}/
├── 设定/              # book-level setting files
│   ├── 题材定位.md
│   ├── 关系.md
│   ├── 角色/
│   ├── 世界观/
│   └── 势力/
├── 大纲/              # book outline, volume outline, per-chapter outlines
│   ├── 大纲.md
│   ├── 卷纲_第一卷.md
│   └── 细纲_第XXX章.md
├── 正文/              # one Markdown file per chapter
├── 追踪/              # continuity tracking
│   ├── 上下文.md
│   ├── 伏笔.md
│   ├── 时间线.md
│   └── 角色状态.md
├── 封面/              # generated cover images when available
└── 作品信息_番茄上传.md # platform upload metadata when prepared
```

Before continuing a novel, read at minimum:

1. `设定/题材定位.md`
2. `大纲/卷纲_第一卷.md` or the current volume outline
3. `追踪/上下文.md`
4. `追踪/伏笔.md`
5. `追踪/角色状态.md`
6. the latest chapter in `正文/`

When writing new chapters, create or verify the matching `大纲/细纲_第XXX章.md` first, then write `正文/第XXX章_章名.md`, then update the tracking files.

## Current priority project notes

For `渡厄簿：她不替天命受罚了/`:

- Author pen name: `桃枝醒醒`.
- Platform: 番茄小说.
- Core hook: 闻照夜 no longer substitutes herself for fate-favored people’s punishments; she uses the `渡厄簿` to return transferred thunder tribulations, illness, infamy, and death debts to the real debtors.
- Existing progress: chapters 001–010 are written. Chapter 010 ends with the first thunder tribulation returned to 沈霁川 and the `渡厄簿` marking 姜闻素 as the largest remaining Snow-Bone debt owner.
- Next continuation should start from the aftermath of the thunder platform, with 姜闻素 trying to suppress the public evidence while outer disciples and branch-family disciples begin to waver.
- Style target: female-oriented commercial爽文 with a fresh xianxia/quick-transmigration debt-collection mechanism. Keep dialogue relatively sparse; rely on objects, bodily cost, rules, evidence, and public reversals for tension and爽点.

## Common commands

This workspace has no build, lint, or test suite. Use Python for local utility scripts and counting text.

Count total characters for a novel’s chapters:

```bash
python - <<'PY'
from pathlib import Path
base = Path('渡厄簿：她不替天命受罚了/正文')
total = 0
for p in sorted(base.glob('第*.md')):
    n = len(p.read_text(encoding='utf-8'))
    total += n
    print(f'{p.name}: {n}')
print('TOTAL:', total)
PY
```

Generate the current configured cover image:

```bash
python gen_avatar.py
```

`gen_avatar.py` currently targets `gpt-image-2` through `https://code.newcli.com/codex/v1/images/generations` and writes the output path embedded in the script. The image endpoint has recently returned Cloudflare 524 timeouts, so failures may be service-side rather than prompt-side.

## Publishing and transfer workflow

To continue on another computer, copy or sync the whole workspace, not just chapter files. For the current book, the minimum useful set is:

```text
D:\txt\CLAUDE.md
D:\txt\.gitignore
D:\txt\渡厄簿：她不替天命受罚了
```

If future Claude sessions need conversation context, point them to `CLAUDE.md` and `渡厄簿：她不替天命受罚了/追踪/上下文.md`. The tracking files are the durable continuation state; the chat transcript itself is not required if these files are up to date.

For Git sync, initialize this workspace only after reviewing `.gitignore`:

```bash
git init
git status
git add CLAUDE.md .gitignore "渡厄簿：她不替天命受罚了" "快穿：恶毒女配觉醒后，全员跪求我原谅" "旧雨来信"
git commit -m "Add novel writing workspace"
```

Do not commit `gen_avatar.py` unless it no longer contains secrets and you intentionally want to version the image-generation helper. It now reads `GPT_IMAGE_API_KEY` from the environment.

## GitHub push troubleshooting

- If `git push origin main` over HTTPS hangs, do not assume the novel commit is bad. First clear stale `git`, `git-remote-https`, and `git-credential-manager` processes, then test `git ls-remote --heads origin main`.
- On this machine, a successful `ls-remote` through proxy `127.0.0.1:7897` plus a hanging `push --dry-run` has indicated Git Credential Manager trouble. `git -c credential.helper= push --dry-run origin main` should return a credential error quickly if that is the blocker.
- SSH auth has worked for GitHub here. If `ssh -T git@github.com` succeeds, push with `git push git@github.com:xiaodingdang2333/ai.git main`, then run `git fetch origin main` so `origin/main` is refreshed.

## Writing constraints

- For Fanqie upload, prioritize strong opening hooks, visible conflict, direct爽感, and chapter-end curiosity.
- Avoid template-like AI prose. Existing checks used banned phrases such as `仿佛`, `一丝`, `一抹`, `缓缓`, `轻轻`, `淡淡`, `眼中闪过`, `嘴角勾起`, and summary endings like `这一刻`.
- Prefer concrete scene evidence over explanation: physical artifacts, injuries, public witnesses, rules being read aloud, and visible backlash.
- Do not rewrite locked existing chapters unless explicitly asked; continue from tracking files and latest chapter.

## Shared memory mirror

- Cross-tool shared memory lives at `F:\ai\memory`; if available, read `F:\ai\memory\README.md` first, then the relevant small files it points to.
- When the user says “记住”, “以后都这样”, “总结经验”, or gives a durable correction/preference, update `F:\ai\memory` and also mirror the durable change into both `F:\ai\txt\CLAUDE.md` and `F:\ai\txt\GEMINI.md`.
- Do not mirror per-novel concrete details such as pen names, character facts, plot state, or chapter-specific information into shared memory; keep those inside the corresponding novel project folder.
- Current stable preferences: communicate in Chinese by default; be concise and action-oriented; inspect relevant files before editing; keep changes scoped; never overwrite user work unless explicitly asked; run focused verification when feasible.
- Novel writing defaults: female-oriented commercial fiction should avoid formulaic copycat names/plots, avoid流水式对话, avoid one-sentence-per-paragraph pacing, use more细腻描写, strong hooks, concrete evidence, bodily cost, rules, public reversals, and visible consequences.
- Novel chapters: unless the user says otherwise, formal new/revised chapters should normally be about 3000 Chinese characters.
- Template phrases such as `仿佛`, `一丝`, `一抹`, `缓缓`, `轻轻`, `淡淡`, `眼中闪过`, `嘴角勾起`, `这一刻` are not absolutely forbidden, but should be sparse and natural rather than dense default prose.
- Chapter titles: avoid overly functional/cliche title keywords such as “病历” or “婚约” when possible; prefer fresher, more atmospheric titles with story-specific imagery.
- Multi-party novel scenes: add three-sided reactions, body language, setting pressure, inner reactions, and varied paragraph lengths instead of relying on流水式对话.
- Python environment: use `C:\Users\Administrator\.local\bin\python.exe` (uv-managed Python 3.12.13). Do not reinstall Python merely because `WindowsApps\python.exe` is also present.
- Voice design: this Windows machine has an AMD Radeon RX 6750 GRE. Use the installed `voice-design` skill with the official OmniVoice Hugging Face Space; do not attempt a local OmniVoice model install.
- Fanqie upload automation: if the browser asks “离开此网站”, choose “离开”; if the editor asks whether to keep editing a newly updated draft, choose “继续编辑”. Verify the final draft list once and avoid repeatedly switching pages.
- Fanqie upload automation must not trust editor-only character counts. After creating or editing each draft, verify the platform draft-list row shows a nonzero, non-suspicious word count; repair immediately if the row is 0 or clearly doubled.
## Investment Profile

- 2026-06-05 portfolio context: user wants this financial profile remembered across new sessions for investment and asset-allocation advice.
- Goal: maximize long-term returns in A-share stocks/funds and related funds, aiming for about 20%+ annualized return if possible, while keeping drawdown as low as possible, preferably under 10%; user prefers low-frequency operation, at most daily or every few days.
- Current investable cash flow: about 3,000 CNY per month can be added to investments.
- Current holdings as of 2026-06-05:
  - People.cn / Renminwang `603000.SH`: 700 shares, cost 18.40 CNY/share.
  - Fixed wealth-management product: 55,000 CNY, expected 4% annualized, matures 2026-07-27.
  - `009052` 易方达中证红利ETF联接C: 9,966 CNY position, current unrealized loss about 42 CNY.
  - `022430` 华夏中证A500ETF联接A: 10,000 CNY position, bought on 2026-06-05.
  - Lingqianbao / cash-like balance: about 20,000 CNY after transferring 7,000 CNY from salary card.
  - 景顺长城纳斯达克科技市值加权ETF联接(QDII)A: current value about 65,000 CNY, cost 51,000 CNY; currently suspended for purchases, so avoid selling lightly because it may be hard to buy back.
- Current strategy preference: keep Nasdaq technology QDII as core growth exposure unless major drawdown; do not add more to it while purchase is suspended; use new money and cash to build A-share broad index, dividend/low-volatility, short-duration/cash-like, and risk-balancing positions.
