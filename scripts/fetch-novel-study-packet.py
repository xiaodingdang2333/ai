#!/usr/bin/env python3

import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


USER_AGENT = "Mozilla/5.0 (compatible; local-novel-study/1.0)"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
        content_type = response.headers.get_content_charset()
    for encoding in (content_type, "utf-8", "gb18030"):
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


class ChapterTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "content":
            self.depth = 1
            return
        if self.depth:
            self.depth += 1
            if tag in {"p", "br", "div"}:
                self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.depth:
            if tag in {"p", "div"}:
                self.parts.append("\n")
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def text(self):
        value = html.unescape("".join(self.parts)).replace("\xa0", " ")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
        noise = re.compile(r"^(请收藏本站|最新网址|手机用户请|本章完|喜欢.*请大家收藏|天才一秒记住)")
        return "\n".join(line for line in lines if line and not noise.search(line)).strip()


def safe_name(value):
    return re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value).strip(" ._")[:100]


def toc_pages(book_url, first_html):
    urls = {book_url}
    for value in re.findall(r"<option[^>]+value=[\"']([^\"']+)[\"']", first_html, flags=re.I):
        urls.add(urllib.parse.urljoin(book_url, value))
    return sorted(urls)


def chapter_links(base_url, source):
    links = []
    pattern = re.compile(r"<a[^>]+href=[\"']([^\"']+\.html)[\"'][^>]*>(.*?)</a>", re.I | re.S)
    for href, label in pattern.findall(source):
        title = re.sub(r"<[^>]+>", "", label)
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        if not title or title in {"首页", "上一章", "下一章", "章节目录"}:
            continue
        url = urllib.parse.urljoin(base_url, href)
        chapter_path = urllib.parse.urlparse(url).path
        if (re.search(r"/biqu\d+/\d+\.html$", chapter_path)
                or re.search(r"/\d+/\d+\.html$", chapter_path)):
            links.append((title, url))
    return links


def chapter_number(item):
    match = re.search(r"第\s*(\d+)\s*章", item[0])
    return int(match.group(1)) if match else 10**9


def meta_description(source):
    patterns = [
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.I | re.S)
        if match:
            return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return ""


def selected_indices(total, front, middle, tail):
    result = set(range(min(front, total)))
    if middle:
        start = max(0, total // 2 - middle // 2)
        result.update(range(start, min(total, start + middle)))
    if tail:
        result.update(range(max(0, total - tail), total))
    return sorted(result)


def main():
    parser = argparse.ArgumentParser(description="Fetch only the chapters needed for structural novel study")
    parser.add_argument("url")
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", default="未知")
    parser.add_argument("--front", type=int, default=10)
    parser.add_argument("--middle", type=int, default=3)
    parser.add_argument("--tail", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    first_html = fetch(args.url)
    links = []
    seen = set()
    for page_url in toc_pages(args.url, first_html):
        source = first_html if page_url == args.url else fetch(page_url)
        for title, url in chapter_links(page_url, source):
            if url not in seen:
                links.append((title, url))
                seen.add(url)
    links.sort(key=chapter_number)
    if not links:
        raise SystemExit("No supported chapter links found in the mirror table of contents")

    output = args.output or Path("/home/admin/ai/txt/排行榜/拆书分析") / safe_name(args.title)
    selected_dir = output / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    for old in selected_dir.glob("*.txt"):
        old.unlink()

    indices = selected_indices(len(links), args.front, args.middle, args.tail)
    records = []
    for position, index in enumerate(indices, 1):
        title, url = links[index]
        parser_ = ChapterTextParser()
        parser_.feed(fetch(url))
        text = parser_.text()
        if len(text) < 100:
            raise SystemExit(f"Chapter text too short: {title} ({url})")
        filename = f"{index + 1:04d}-{safe_name(title)}.txt"
        (selected_dir / filename).write_text(f"{title}\n\n{text}\n", encoding="utf-8")
        records.append({
            "index": index + 1,
            "title": title,
            "url": url,
            "characters": len(re.sub(r"\s+", "", text)),
            "file": str(selected_dir / filename),
        })
        if position < len(indices):
            time.sleep(0.5)

    metadata = {
        "title": args.title,
        "official_author": args.author,
        "mirror_book_url": args.url,
        "mirror_chapter_count": len(links),
        "mirror_intro": meta_description(first_html),
        "mirror_first_chapter_titles": [title for title, _ in links[:3]],
        "selected_chapter_count": len(records),
        "selected_characters": sum(item["characters"] for item in records),
        "chapters": records,
    }
    (output / "source.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# {args.title} 拆书索引",
        "",
        f"- 官方作者：{args.author}",
        f"- 第三方镜像目录：{len(links)}章",
        f"- 精选章节：{len(records)}章",
        f"- 精选正文字符：{metadata['selected_characters']}",
        f"- 镜像来源：`{args.url}`",
        "- 校验状态：必须再与番茄官方作品页核对作者、最新章节和抽样正文。",
        f"- 镜像简介开头：{metadata['mirror_intro'][:240] or '未提取到'}",
        f"- 镜像前三章：{'；'.join(metadata['mirror_first_chapter_titles'])}",
        "",
        "## 精选章节",
        "",
    ]
    lines.extend(f"- {item['index']:04d} {item['title']}：{item['characters']}字" for item in records)
    lines.extend([
        "",
        "## 使用规则",
        "",
        "只读取 `selected/` 做结构分析。提取开篇速度、关系推进、情绪回报和章节节奏，不复制原句、标志性桥段或人物组合。",
        "",
    ])
    (output / "00_拆书索引.md").write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
