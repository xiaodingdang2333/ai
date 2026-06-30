# Local SoNovel Workflow

This copy is used only as an on-demand downloader. The NovelCraft LLM plugin is not enabled.

## Commands

```bash
/home/admin/ai/scripts/sonovel.sh search '完整书名'
/home/admin/ai/scripts/sonovel.sh packet '完整书名' '官方作者'
/home/admin/ai/scripts/sonovel.sh packet-list '/path/to/official-ranking-books.json'
/home/admin/ai/scripts/sonovel.sh download '完整书名' '作者'
/home/admin/ai/scripts/sonovel.sh list
/home/admin/ai/scripts/sonovel.sh stop
```

Downloaded files are stored in `downloads/`. Prepare a token-efficient study packet with:

```bash
/home/admin/ai/scripts/prepare-novel-study.py downloads/example.epub
```

The recommended `packet` command uses SoNovel search and source rules, then downloads only the first 10, middle 3, and last 3 chapters into `selected/`. This avoids the bundled JAR's stalled full-EPUB aggregation on some sources. If a complete EPUB is already available, the parser extracts every chapter locally but copies only those same ranges into `selected/`.

The ranking queue input is a JSON array such as:

```json
[
  {"rank": 1, "title": "书名", "author": "番茄官方作者", "official_url": "https://fanqienovel.com/page/..."}
]
```

The queue records failures and continues with the next ranked title. A downloaded packet remains `needs_official_verification` until its synopsis or first chapter titles are checked against the official page.

## Source Policy

- Choose books from the official Fanqie ranking before searching SoNovel.
- Treat SoNovel sources as third-party mirrors, not proof of rank or canonical text.
- Compare title, author, chapter count, and sampled chapters against the official public book page.
- Do not reject a match only because the mirror says `佚名` or has fewer chapters. Confirm it by synopsis keywords or the first chapter titles. If it cannot be confirmed or no exact book is found, skip it and continue with the next ranked title.
- Do not expose port 7765 publicly. The service is on demand and protected by a loopback-only firewall rule.
- Store analysis notes and functional patterns. Do not copy source prose into new fiction.
