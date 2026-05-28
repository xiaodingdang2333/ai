# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
- Novel chapters: unless the user says otherwise, formal new/revised chapters should be at least 2500 Chinese characters.
- Template phrases such as `仿佛`, `一丝`, `一抹`, `缓缓`, `轻轻`, `淡淡`, `眼中闪过`, `嘴角勾起`, `这一刻` are not absolutely forbidden, but should be sparse and natural rather than dense default prose.
- Chapter titles: avoid overly functional/cliche title keywords such as “病历” or “婚约” when possible; prefer fresher, more atmospheric titles with story-specific imagery.
- Multi-party novel scenes: add three-sided reactions, body language, setting pressure, inner reactions, and varied paragraph lengths instead of relying on流水式对话.
