# Global Codex Instructions

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
