# Decisions

- 2026-05-27: Use a local Markdown memory folder at `F:\ai\memory` as the shared long-term memory layer across AI tools.
- 2026-05-27: Do not require Obsidian for memory; Obsidian can later open `F:\ai\memory` as a vault if visual management is useful.
- 2026-05-27: Treat valuable future task experience as shared memory by default. Categorize it into preferences, lessons, decisions, project context, or dated session notes, and keep it Obsidian-compatible.
- 2026-05-27: New sessions should read shared memory automatically from `./memory` first, falling back to `F:\ai\memory` only when needed, so the behavior works after pulling the workspace on a new computer.
# Future Web Agent

- 2026-07-03: Historical idea, revised 2026-07-09: the old novel custom GPT / `novel-actions` Action workflow is deprecated and must not be reused as the model for future novel production. If a future general web-based AI workspace is built, it must be newly designed as a scoped, allowlisted, audited tool layer around Git artifacts and explicit jobs, not a continuation of the abandoned novel Action flow. This remains a deferred idea, not current execution.
