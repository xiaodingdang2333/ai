# Decisions

- 2026-05-27: Use a local Markdown memory folder at `F:\ai\memory` as the shared long-term memory layer across AI tools.
- 2026-05-27: Do not require Obsidian for memory; Obsidian can later open `F:\ai\memory` as a vault if visual management is useful.
- 2026-05-27: Treat valuable future task experience as shared memory by default. Categorize it into preferences, lessons, decisions, project context, or dated session notes, and keep it Obsidian-compatible.
- 2026-05-27: New sessions should read shared memory automatically from `./memory` first, falling back to `F:\ai\memory` only when needed, so the behavior works after pulling the workspace on a new computer.
# Future Web Agent

- 2026-07-03: Later, build a general web-based AI workspace modeled on the novel custom GPT: web GPT handles most reasoning and orchestration, while a controlled server Action layer performs file operations, approved scripts, tests, background jobs, and state recovery. The goal is Codex-like outcomes for standardized workflows while reducing server-side Codex token usage. Do not expose unrestricted shell execution; use scoped tools, allowlists, validation, auditing, and resumable jobs. This is recorded for later implementation, not current execution.
