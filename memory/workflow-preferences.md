# Workflow Preferences

- Default to action: inspect, edit, generate, or run commands when the request is clear.
- Keep updates short and practical.
- Use the least-token accurate path: avoid broad scans, redundant explanations, and unnecessary web searches.
- For local file transformations, produce the finished file and give the path.
- For media tasks, prefer local deterministic tools when available, such as FFmpeg, PowerShell, browser screenshots, or local scripts.
- For GitHub access in this environment, prefer normal `origin` first, but if HTTPS `git push` hangs while `git ls-remote` works, suspect Git Credential Manager. Clear stale Git/GCM processes, test with `git -c credential.helper= push --dry-run origin main`, and use SSH push (`git push git@github.com:xiaodingdang2333/ai.git main`) when SSH auth is available.
- For Fanqie chapter uploads, avoid repeatedly bouncing between chapter management and draft box pages. Confirm draft state once, then continue from the current page or use targeted checks.
- For this web-novel workspace, formal new or revised chapters should normally be about 3000 Chinese characters unless the user says otherwise. Match the early-chapter style: paragraph lengths should vary, avoid one-sentence-per-paragraph formatting, and preserve a fuller scene texture.
- 2026-05-27: After future operations, if an insight has reusable value, record it in the shared memory at `F:\ai\memory` using Obsidian-compatible Markdown and the categories in `README.md`.
- 2026-05-28: Whenever shared memory is updated, also mirror the durable change into `F:\ai\txt\CLAUDE.md` and `F:\ai\txt\GEMINI.md`, so Claude/Gemini can load the same preferences by reading those files.
- 2026-05-28: Keep per-novel concrete details inside each novel folder, not shared memory. Shared memory should store cross-cutting writing/work preferences and reusable workflows only.
- 2026-06-03: When the user asks to write, revise, package, or evaluate fiction for 七猫投稿/七猫内投, first read `F:\ai\memory\qimao-submission-rules.md` and apply its ranking-derived opening rules.
- 2026-06-03: When starting a new 七猫投稿/七猫内投 novel project, default to producing at least 20,000 Chinese characters of trial-submission draft unless the user says otherwise.
