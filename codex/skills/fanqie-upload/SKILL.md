---
name: fanqie-upload
description: Upload locally written Chinese web-novel chapters to Fanqie/Tomato Novel writer center. Use when the user asks to upload, create drafts, publish drafts, continue publishing, inspect Fanqie draft or published status, or batch-handle novels stored as txt/novel-name/正文/*.md. Draft creation may use Chrome CDP, but publishing defaults to the backend API script used by the current stable Linux workflow. Supports three-digit chapter numbers, AI-use declaration, daily submission-limit stopping, and arbitrary novel folders under F:\ai\txt.
---

# Fanqie Upload

Use the bundled script first. For publishing, default to the API publishing path; avoid exploratory browser automation unless the API script reports a concrete blocker.

## Quick Start

Run from `F:\ai`:

```powershell
node codex\skills\fanqie-upload\scripts\fanqie-upload.js scan --book "小说名"
node codex\skills\fanqie-upload\scripts\fanqie-upload.js drafts --book "小说名" --book-id "<番茄作品ID>" --from 1 --to 30
node codex\skills\fanqie-upload\scripts\fanqie-upload.js publish --book "小说名" --book-id "<番茄作品ID>" --account account-a --expected-account "西大水怪" --from 1 --to 30 --ai-use no
```

For the current working convention, `--book` may be a full path or a folder name under `F:\ai\txt`. Chapters must live in `正文/*.md`.

## Workflow

1. For publishing, use the backend API publisher through `fanqie-upload.js publish`, or call `/home/admin/ai/scripts/fanqie-api-publish.js` directly on Linux.
2. Run `scan` to confirm parsed chapter numbers, titles, and word counts. Chapter numbers are written as three digits, for example `020`.
3. Run `drafts` to create missing drafts from local Markdown. The script skips chapters already visible in draft or published lists.
4. Run `publish` to publish existing drafts in ascending chapter order. This command now delegates to `/home/admin/ai/scripts/fanqie-api-publish.js` and uses decrypted cookies from `/root/snap/chromium/common/fanqie-profiles/live/<account>/Default/Cookies`.
5. Always verify the expected author account before publishing. Use `--account` and `--expected-account`, or rely on the port mapping only when it is unambiguous: `9223 -> account-a/西大水怪`, `9224 -> account-b/桃枝醒醒`, `9225 -> account-c/泡芙软呼呼`.
6. If Fanqie asks whether AI was used, follow the command parameter: default `--ai-use yes`; use `--ai-use no` when the user asks to select `否` or account defaults require no AI declaration.
7. If Fanqie returns `提交字数超出每日上限`, stop and report the remaining chapters. Do not keep retrying the same day.

## Current Book Shortcut

For `快穿：恶毒女配觉醒后，全员跪求我原谅`, use:

```powershell
node codex\skills\fanqie-upload\scripts\fanqie-upload.js publish --book "快穿：恶毒女配觉醒后，全员跪求我原谅" --book-id "7642178186335226942" --account account-b --expected-account "桃枝醒醒" --from 23 --to 30 --ai-use yes
```

To publish while selecting `否` for AI usage:

```powershell
node codex\skills\fanqie-upload\scripts\fanqie-upload.js publish --book "小说名" --book-id "<番茄作品ID>" --account account-a --expected-account "西大水怪" --from 1 --to 1 --ai-use no
```

## Safety Rules

- Do not click `替换全部` or any AI rewrite button.
- Do not modify chapter text during publishing.
- For publishing, default to the backend API script used in June 2026; do not go back to Chrome/CDP clicking unless API publishing is blocked and the blocker is recorded.
- Prefer `publish` after drafts already exist; use `drafts` only when missing drafts need to be created.
- When blocked by login, captcha, missing work ID, or daily limit, stop and report the exact blocker.
