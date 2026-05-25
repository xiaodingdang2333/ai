---
name: fanqie-upload
description: Upload locally written Chinese web-novel chapters to Fanqie/Tomato Novel writer center with Chrome CDP. Use when the user asks to upload, create drafts, publish drafts, continue publishing, inspect Fanqie draft or published status, or batch-handle novels stored as txt/novel-name/正文/*.md. Supports three-digit chapter numbers, basic content check, AI-use declaration, daily submission-limit stopping, and arbitrary novel folders under F:\ai\txt.
---

# Fanqie Upload

Use the bundled script first. Avoid exploratory browser automation unless the script reports a concrete blocker.

## Quick Start

Run from `F:\ai`:

```powershell
node codex\skills\fanqie-upload\scripts\fanqie-upload.js scan --book "小说名"
node codex\skills\fanqie-upload\scripts\fanqie-upload.js drafts --book "小说名" --book-id "<番茄作品ID>" --from 1 --to 30
node codex\skills\fanqie-upload\scripts\fanqie-upload.js publish --book "小说名" --book-id "<番茄作品ID>" --from 1 --to 30
```

For the current working convention, `--book` may be a full path or a folder name under `F:\ai\txt`. Chapters must live in `正文/*.md`.

## Workflow

1. Ensure a Chrome instance with the user's logged-in Fanqie session is available on CDP port `9223`.
2. Run `scan` to confirm parsed chapter numbers, titles, and word counts. Chapter numbers are written as three digits, for example `020`.
3. Run `drafts` to create missing drafts from local Markdown. The script skips chapters already visible in draft or published lists.
4. Run `publish` to publish existing drafts in ascending chapter order.
5. If Fanqie asks for a content check, choose `仅基础检测`.
6. If Fanqie asks whether AI was used, choose `是`.
7. If Fanqie reports `提交字数超出每日上限`, stop and report the remaining chapters. Do not keep retrying the same day.

## Current Book Shortcut

For `快穿：恶毒女配觉醒后，全员跪求我原谅`, use:

```powershell
node codex\skills\fanqie-upload\scripts\fanqie-upload.js publish --book "快穿：恶毒女配觉醒后，全员跪求我原谅" --book-id "7642178186335226942" --from 23 --to 30
```

## Safety Rules

- Do not click `替换全部` or any AI rewrite button.
- Do not modify chapter text during publishing.
- Prefer `publish` after drafts already exist; use `drafts` only when missing drafts need to be created.
- When blocked by login, captcha, missing work ID, or daily limit, stop and report the exact blocker.
