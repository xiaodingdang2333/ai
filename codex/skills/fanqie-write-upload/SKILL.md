---
name: fanqie-write-upload
description: Write or continue Chinese web-novel chapters in this workspace, update the novel's outline/tracking files, switch to a specified Fanqie/Tomato author account, upload the new chapters to that account's draft box, and verify platform draft counts. Use when the user asks to write/continue/revise chapters and upload them to a named Fanqie author account such as 西大水怪 or 桃枝醒醒, or asks to test/switch Fanqie account draft uploads.
---

# Fanqie Write Upload

## Core Rule

Do the full workflow, not just uploading: read the novel context, write the chapter(s), update local tracking files, run local QA, switch to the requested Fanqie account, upload drafts, then verify the draft-list row count.

## New Book Ideation Gate

- This skill may continue existing books directly.
- Before creating any future new Fanqie/Tomato book, run `fanqie-novel-ideation` and complete its mandatory `12 -> 3 -> user selection` funnel.
- Do not create the project, outline, chapters, platform work, or drafts before the user explicitly selects one of the three finalists.
- After selection, write exactly three trial chapters and return them for approval. Bulk writing and draft upload require a later explicit approval.

## Account Map

- `西大水怪`: use logical account `account-a`, Snap cache backup `.fanqie-profiles/snap-backups/account-a-snap`, usual CDP port `9223`.
- `桃枝醒醒`: use logical account `account-b`, Snap cache backup `.fanqie-profiles/snap-backups/account-b-snap`, usual CDP port `9224`.
- `泡芙软呼呼`: use logical account `account-c`, Snap cache backup `.fanqie-profiles/snap-backups/account-c-snap`, usual CDP port `9225`.

## AI Declaration Defaults

- All `西大水怪` books: publish with `--ai-use no`.
- All `桃枝醒醒` books: publish with `--ai-use yes`.
- All `泡芙软呼呼` books: publish with `--ai-use no`.

## Manual Publishing Default

- Do not schedule or automatically publish Fanqie/Tomato chapters. The user performs the final publish action in the Fanqie author console.
- When the user asks to write or continue a book, finish the writing and local QA, then upload the new chapters to the correct draft box automatically unless the user says not to upload.
- Verify every uploaded draft from the platform draft list. Report the uploaded chapter range, titles, and any suspicious count instead of publishing.
- Never delete, overwrite, or blindly retry drafts after an upload mismatch. Preserve the platform state and ask the user before destructive repair.
- A new login cache is not considered reliable until it passes replay verification: restart the browser from that cache and confirm the expected visible account name.

Important: on this Linux server, Snap Chromium ignores isolation in child processes and effectively uses `/root/snap/chromium/common/chromium`. Do not rely only on `--user-data-dir`. Restore the correct Snap cache before starting Chromium, and save it again after upload.

Use `scripts/fanqie-account-cache.sh` for cache operations.

## Writing Workflow

Before writing, read and enforce `../fanqie-novel-ideation/references/originality-gate.md`. For every chapter batch, verify scene causality, compare its plot loop with prior chapters and local books, and perform a separate adversarial AI-pattern review. A failed originality gate blocks QA and upload.

For Action-managed projects, chapter writes are two-phase. Save and revise into `草稿暂存/` first; run all mechanical, originality, AI-pattern, and continuity checks there. QA failure must remain editable. The first three chapters become formal only after explicit user approval. Later `auto` batches promote after QA; later `review` batches promote only after explicit approval. Never describe staged chapters as formally saved or uploadable.

1. Identify the book folder under `/home/admin/ai/txt`.
2. Read the smallest required context:
   - `作品信息_番茄上传.md` if present.
   - `追踪/上下文.md`, `追踪/伏笔.md`, `追踪/角色状态.md`.
   - the latest chapter in `正文/`.
   - relevant current outline if needed.
3. Continue from the latest chapter number unless the user specified a range.
4. Write each formal chapter around 3000 Chinese characters and never below 2500 unless the user explicitly allows it.
5. Avoid流水式对话, one-sentence paragraph pacing, dense template phrases, weak functional titles, and mechanical merging.
6. Add or update `大纲/细纲_第XXX章.md`.
7. Update tracking files with a compact chapter progress summary and new/advanced伏笔 or角色状态.

## Local QA

Always run the local scan before upload:

```bash
node codex/skills/fanqie-upload/scripts/fanqie-upload.js scan --root /home/admin/ai/txt --book '<书名>' --from N --to M
```

Also check at least:

- body character count is >=2500;
- title is not pasted into body;
- duplicate chapter number is not present in body;
- title matches chapter content;
- no obviously doubled content.
- body formatting is preserved as multiple non-empty paragraph nodes; never rely on simulated Enter keystrokes for ProseMirror paragraph creation.
- each major scene contains goal, obstacle, choice, cost, and state change;
- the batch does not reuse an old book's or prior unit's plot loop after names/settings are removed;
- an independent review has checked AI stock phrases, uniform paragraph rhythm, convenience coincidences, tool-character behavior, and repeated emotional payoff.

## Upload Workflow

1. Read `番茄作品ID` from `作品信息_番茄上传.md`. If missing, use the target account's `book-manage` page to find the ID, then write `作品信息_番茄上传.md`.
2. Stop Chromium and switch cache:

```bash
/root/.codex/skills/fanqie-write-upload/scripts/fanqie-account-cache.sh switch-start account-a 9223
/root/.codex/skills/fanqie-write-upload/scripts/fanqie-account-cache.sh switch-start account-b 9224
```

3. Confirm the account name before uploading:

```bash
/root/.codex/skills/fanqie-write-upload/scripts/fanqie-account-cache.sh identify 9223
/root/.codex/skills/fanqie-write-upload/scripts/fanqie-account-cache.sh identify 9224
```

4. Upload drafts with the existing uploader:

```bash
node codex/skills/fanqie-upload/scripts/fanqie-upload.js drafts --root /home/admin/ai/txt --book '<书名>' --book-id '<ID>' --port <PORT> --from N --to M
```

The `drafts` command is the default and is idempotent: it must verify the account, inspect both drafts and already-published chapters, skip valid existing content, upload only missing chapters, retry only when no partial draft was created, read saved content back, and finish with `UPLOAD_OK`. Use `verify` for a read-only repeat check. Do not substitute ad-hoc browser actions when this command is available.

Only if the user explicitly reverses the manual-publishing policy and requests a one-off automated publish, do not use Chrome/CDP clicking by default. Use the backend API publisher and obey the user's AI declaration choice:

```bash
node /home/admin/ai/scripts/fanqie-api-publish.js --account account-a --expected-account '西大水怪' --book '<书名>' --book-id '<ID>' --from N --to M --ai-use no
```

Use `--ai-use no` when the user says to select `否` or account defaults require it; otherwise use the account default. Publish until the API reports the daily limit, then stop for that day.

5. Verify the draft list row after upload. The row must show the expected chapter title and a nonzero, non-suspicious platform word count.
   Also read the saved draft content back from the platform and verify that its non-empty `<p>` count is consistent with the local paragraph count. A correct word count alone does not prove formatting is intact.
6. Save the currently active account cache after successful upload:

```bash
/root/.codex/skills/fanqie-write-upload/scripts/fanqie-account-cache.sh save account-a
/root/.codex/skills/fanqie-write-upload/scripts/fanqie-account-cache.sh save account-b
```

## QR Login

If login is required, generate/refresh the QR in `/home/admin/ai/output/qr-login/current.png`; the public page is:

```text
http://8.212.144.72:8090/
```

After the user scans, confirm the displayed account name before upload. Never upload if the displayed account is not the requested account.

## Safety

- Never upload to an account whose displayed name does not match the user's requested target.
- Never trust the editor-only count; verify from the draft list.
- If the platform row is 0, doubled, or missing, repair before reporting success.
- Do not delete existing drafts unless the user explicitly asked to clear/replace them.
- When switching accounts, save the current Snap cache first if it may contain a fresh login.

## Mandatory Incident Learning

- After repairing any draft upload incident, update the shared Fanqie memory before reporting completion.
- Record the symptom, root cause, failed method, successful repair, platform-side verification, and the concrete prevention added to code or workflow.
- Review prior incident notes before every later upload so the same failure is not repeated.
