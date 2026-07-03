# Global Codex Instructions

## Shared Memory

- At the start of every new conversation/session, read the shared memory index at `./memory/README.md` from the current repository/workspace root, then read `user-profile.md` and `workflow-preferences.md`.
- Also read `project-context.md`, `lessons.md`, `decisions.md`, or dated `sessions/` notes only when relevant to the user's request.
- If `./memory` is not present, fall back to `F:\ai\memory` when available.
- Treat `./memory` as the shared long-term memory layer across AI tools so the behavior survives pulling this directory on a new computer.
- When the user says "记住", "以后都这样", "总结经验", asks to record shared memory, or gives a durable correction/preference, update the relevant file under `./memory`.
- Do not store secrets, passwords, tokens, API keys, or sensitive personal data unless explicitly requested.

## Mandatory Novel Workflow

- For any request to ideate, create, plan, write, revise, evaluate, continue, package, or upload a novel, first read `./memory/novel-writing-workflow.md` and every file it marks as required for that stage.
- Novel workflow rules are hard gates, not suggestions. This includes ranking-source fallback, the eight-part originality gate, 12-to-3 selection, three-chapter trial, chapter-length/style QA, continuity tracking, account verification, and draft-only upload defaults.
- Apply the same rules regardless of Codex account, host machine, or whether skills are globally installed. If a skill is not discovered globally, read and execute its repository `SKILL.md` directly.
- Repository files are authoritative over chat memory. Do not silently weaken a gate because a new machine lacks prior conversation history.

## Working Agreements

- Default to concise answers: conclusion first, then only the key details needed to act.
- Prefer doing the requested work over explaining a broad plan, unless the task is ambiguous or risky.
- When a task is ambiguous, state the smallest necessary assumption or ask one focused question.
- Keep changes scoped to the user's request. Do not refactor, reformat, rename, or move unrelated code.
- Before editing, inspect the smallest relevant set of files. Use `rg` / `rg --files` first and avoid broad recursive reads.
- Do not read or summarize large generated folders unless explicitly requested. Avoid `.git`, `node_modules`, `dist`, `build`, `coverage`, `output`, `tmp`, caches, and virtual environments.
- For logs, read the last 100 lines by default unless the user asks for more.
- For large files, search for relevant symbols first, then read nearby sections instead of opening the whole file.
- Prefer existing project patterns and dependencies over adding new abstractions or packages.
- Ask before adding production dependencies or changing project-wide configuration.
- Run focused verification after code changes when feasible, and report the exact command and result briefly.
- If verification cannot be run, say why and name the residual risk.

## Token Budget

- Minimize token usage without reducing correctness: avoid long restatements, broad directory scans, and repeated context dumps.
- Summarize intermediate findings instead of pasting large command outputs.
- When continuing a long task, maintain a compact state summary: goal, relevant files, decisions, blockers, and next action.
- Use web search only when current or source-backed information is needed, and cite the sources used.

## Code Review

- In review requests, lead with findings ordered by severity.
- Include file and line references when possible.
- If no issues are found, say so clearly and mention any unverified risk.

## Git Safety

- Never revert or overwrite user changes unless explicitly asked.
- Before staging or committing, check `git status --short`.
- Keep commits focused on the requested work.
