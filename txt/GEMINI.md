# GEMINI.md

This file mirrors the durable workspace instructions and shared memory needed by Gemini or any other AI assistant.

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

## Workspace purpose

This directory is primarily a Chinese web-novel writing workspace, not a conventional software repository. Most work should happen inside individual novel project directories.

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

- For Fanqie upload, prioritize strong opening hooks, visible conflict, direct爽感, and chapter-end curiosity.
- Avoid formulaic/copycat book names and plots. Reference market patterns, but do not make names or premises look like obvious copies of trending books.
- Avoid流水式对话 and one-sentence-per-paragraph pacing.
- Use more细腻描写, concrete scene evidence, body cost, public witnesses, rules being read aloud, and visible backlash.
- For multi-party scenes, add three-sided reactions, body language, setting pressure, inner reactions, and varied paragraph lengths.
- Formal new/revised chapters should be at least 2500 Chinese characters unless the user says otherwise.
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
