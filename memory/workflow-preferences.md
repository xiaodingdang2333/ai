# Workflow Preferences

- Default to action: inspect, edit, generate, or run commands when the request is clear.
- Keep updates short and practical.
- Use the least-token accurate path: avoid broad scans, redundant explanations, and unnecessary web searches.
- For local file transformations, produce the finished file and give the path.
- For media tasks, prefer local deterministic tools when available, such as FFmpeg, PowerShell, browser screenshots, or local scripts.
- For GitHub access in this environment, HTTPS remote with the configured proxy is more reliable than SSH.
- For Fanqie chapter uploads, avoid repeatedly bouncing between chapter management and draft box pages. Confirm draft state once, then continue from the current page or use targeted checks.
- For this web-novel workspace, new or revised chapters should be at least 2500 Chinese characters unless the user says otherwise. Match the early-chapter style: paragraph lengths should vary, avoid one-sentence-per-paragraph formatting, and preserve a fuller scene texture.
- 2026-05-27: After future operations, if an insight has reusable value, record it in the shared memory at `F:\ai\memory` using Obsidian-compatible Markdown and the categories in `README.md`.
- 2026-05-28: Whenever shared memory is updated, also mirror the durable change into `F:\ai\txt\CLAUDE.md` and `F:\ai\txt\GEMINI.md`, so Claude/Gemini can load the same preferences by reading those files.
- 2026-05-28: Keep per-novel concrete details inside each novel folder, not shared memory. Shared memory should store cross-cutting writing/work preferences and reusable workflows only.
