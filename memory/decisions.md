# Decisions

- 2026-05-27: Use a local Markdown memory folder at `F:\ai\memory` as the shared long-term memory layer across AI tools.
- 2026-05-27: Do not require Obsidian for memory; Obsidian can later open `F:\ai\memory` as a vault if visual management is useful.
- 2026-05-27: Treat valuable future task experience as shared memory by default. Categorize it into preferences, lessons, decisions, project context, or dated session notes, and keep it Obsidian-compatible.
- 2026-05-27: New sessions should read shared memory automatically from `./memory` first, falling back to `F:\ai\memory` only when needed, so the behavior works after pulling the workspace on a new computer.
