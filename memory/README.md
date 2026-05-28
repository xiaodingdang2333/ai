# Shared AI Memory

This folder is the user's cross-tool memory layer. Read only the small files needed for the task.

## Read Order

At the start of every new AI conversation/session, read this file first.

1. Always read `user-profile.md` for stable user preferences.
2. Always read `workflow-preferences.md` for how to work with the user.
3. Read `project-context.md` when the request touches local paths, recurring projects, or repository conventions.
4. Read `lessons.md` when the task may benefit from past operational lessons.
5. Read `decisions.md` when long-term choices or defaults matter.

Use `sessions/` only when the user asks to continue or recover a specific past conversation.

## Update Rules

- Store durable preferences, repeated corrections, project facts, and reusable workflows.
- When updating shared memory, also mirror the durable update into `F:\ai\txt\CLAUDE.md` and `F:\ai\txt\GEMINI.md` so Claude/Gemini can recover the same long-term preferences from those files alone.
- Do not store per-novel concrete details such as pen names, character facts, plot state, or chapter-specific information in shared memory; keep those in the corresponding novel project folder (`作品信息_番茄上传.md`, `设定/`, `大纲/`, `追踪/`).
- Keep entries short and dated when useful.
- Do not store secrets, API keys, passwords, tokens, private IDs, or sensitive personal data unless the user explicitly asks.
- Prefer updating an existing bullet over adding duplicates.
- If unsure whether something belongs here, ask briefly.

## Obsidian Organization

- Use this folder as an Obsidian-compatible vault.
- Use wikilinks for related local notes when helpful, for example `[[lessons]]` or `[[workflow-preferences]]`.
- Classify new memory by default:
  - `workflow-preferences.md`: stable collaboration habits, tool-use preferences, and how the user wants work done.
  - `lessons.md`: reusable operational lessons, platform quirks, debugging findings, and workflow shortcuts.
  - `decisions.md`: explicit long-term choices the user made.
  - `project-context.md`: durable project paths, local conventions, and recurring project facts.
  - `sessions/YYYY-MM-DD.md`: dated task summaries and temporary context useful for continuation.
- Add compact tags in new structured notes when useful, such as `#memory/workflow`, `#memory/lesson`, `#project/fanqie`, or `#tool/codex`.
