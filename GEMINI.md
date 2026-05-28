# Gemini Instructions

## Shared Memory

At the start of every new conversation/session, read the shared memory index at `./memory/README.md` from the current repository/workspace root, then read `user-profile.md` and `workflow-preferences.md`.

Also read `project-context.md`, `lessons.md`, `decisions.md`, or dated `sessions/` notes only when relevant to the user's request.

If `./memory` is not present, fall back to `F:\ai\memory` when available.

Use `./memory` as the shared long-term memory layer across AI tools so the behavior survives pulling this directory on a new computer. When the user says "记住", "以后都这样", "总结经验", asks to record shared memory, or gives a durable correction/preference, update the relevant memory file.

Do not store secrets, passwords, tokens, API keys, or sensitive personal data unless explicitly requested.

## Working Style

- Prefer concise Chinese responses unless the user asks otherwise.
- Prefer doing clear local tasks over only explaining.
- Minimize token usage while preserving correctness.
