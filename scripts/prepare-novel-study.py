#!/usr/bin/env python3

import argparse
import html
import json
import re
import shutil
import statistics
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath


BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "div", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
    "nav", "p", "pre", "section", "table", "tr",
}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def text(self):
        value = html.unescape("".join(self.parts)).replace("\xa0", " ")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def safe_name(value, fallback):
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value).strip(" ._")
    return value[:80] or fallback


def parse_html(data):
    for encoding in ("utf-8", "gb18030"):
        try:
            source = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        source = data.decode("utf-8", errors="replace")
    parser = TextExtractor()
    parser.feed(source)
    return parser.text()


def epub_chapters(path):
    with zipfile.ZipFile(path) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(node for node in container.iter() if node.tag.endswith("rootfile"))
        opf_path = rootfile.attrib["full-path"]
        opf = ET.fromstring(archive.read(opf_path))
        base = PurePosixPath(opf_path).parent

        manifest = {}
        for node in opf.iter():
            if node.tag.endswith("item") and node.attrib.get("id"):
                manifest[node.attrib["id"]] = node.attrib

        metadata = {}
        for node in opf.iter():
            key = node.tag.rsplit("}", 1)[-1]
            if key in {"title", "creator", "language", "publisher"} and node.text:
                metadata.setdefault(key, node.text.strip())

        chapters = []
        for itemref in (node for node in opf.iter() if node.tag.endswith("itemref")):
            item = manifest.get(itemref.attrib.get("idref", ""), {})
            media_type = item.get("media-type", "")
            href = item.get("href")
            if not href or "html" not in media_type:
                continue
            member = str(base / PurePosixPath(href))
            text = parse_html(archive.read(member))
            if len(text) < 80:
                continue
            title = next((line for line in text.splitlines() if line.strip()), f"chapter-{len(chapters)+1}")
            chapters.append({"title": title[:120], "text": text, "source": member})
        return metadata, chapters


def txt_chapters(path):
    source = path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(r"(?m)^(第[0-9零一二三四五六七八九十百千万两〇○]+[章节回卷][^\n]{0,80})\s*$")
    matches = list(pattern.finditer(source))
    if not matches:
        return {"title": path.stem}, [{"title": path.stem, "text": source.strip(), "source": path.name}]
    chapters = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        chapters.append({"title": match.group(1).strip(), "text": source[match.start():end].strip(), "source": path.name})
    return {"title": path.stem}, chapters


def chapter_stats(chapter):
    text = chapter["text"]
    paragraphs = [line for line in text.splitlines() if line.strip()]
    lengths = [len(re.sub(r"\s+", "", line)) for line in paragraphs]
    dialogue = sum(len(line) for line in paragraphs if any(mark in line for mark in ("“", "”", '「', '」', '『', '』')))
    compact = len(re.sub(r"\s+", "", text))
    return {
        "characters": compact,
        "paragraphs": len(paragraphs),
        "median_paragraph_chars": round(statistics.median(lengths), 1) if lengths else 0,
        "dialogue_percent": round(dialogue * 100 / max(1, sum(len(line) for line in paragraphs)), 1),
    }


def selection_indices(total, front, middle, tail):
    selected = set(range(min(front, total)))
    if middle and total:
        start = max(0, total // 2 - middle // 2)
        selected.update(range(start, min(total, start + middle)))
    if tail:
        selected.update(range(max(0, total - tail), total))
    return sorted(selected)


def main():
    parser = argparse.ArgumentParser(description="Create a token-efficient novel study packet")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--front", type=int, default=10)
    parser.add_argument("--middle", type=int, default=3)
    parser.add_argument("--tail", type=int, default=3)
    args = parser.parse_args()

    source = args.input.resolve()
    if source.suffix.lower() == ".epub":
        metadata, chapters = epub_chapters(source)
    elif source.suffix.lower() == ".txt":
        metadata, chapters = txt_chapters(source)
    else:
        raise SystemExit("Only EPUB and TXT are supported")
    if not chapters:
        raise SystemExit("No readable chapters found")

    book_title = metadata.get("title", source.stem)
    output = args.output or Path("/home/admin/ai/txt/排行榜/拆书分析") / safe_name(book_title, source.stem)
    chapter_dir = output / "chapters"
    selected_dir = output / "selected"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    if selected_dir.exists():
        shutil.rmtree(selected_dir)
    selected_dir.mkdir(parents=True)

    manifest = {"source": str(source), "metadata": metadata, "chapters": []}
    for index, chapter in enumerate(chapters, 1):
        filename = f"{index:04d}-{safe_name(chapter['title'], 'chapter')}.txt"
        target = chapter_dir / filename
        target.write_text(chapter["text"] + "\n", encoding="utf-8")
        manifest["chapters"].append({
            "index": index,
            "title": chapter["title"],
            "file": str(target),
            **chapter_stats(chapter),
        })

    selected = selection_indices(len(chapters), args.front, args.middle, args.tail)
    for index in selected:
        source_file = Path(manifest["chapters"][index]["file"])
        shutil.copy2(source_file, selected_dir / source_file.name)

    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total_chars = sum(item["characters"] for item in manifest["chapters"])
    selected_chars = sum(manifest["chapters"][index]["characters"] for index in selected)
    rows = [
        f"# {book_title} 拆书索引",
        "",
        f"- 作者：{metadata.get('creator', '未知')}",
        f"- 总章节：{len(chapters)}",
        f"- 正文字符：{total_chars}",
        f"- 本次精选章节：{len(selected)}",
        f"- 精选字符：{selected_chars}",
        f"- 原文件：`{source}`",
        "",
        "## 精选范围",
        "",
    ]
    for index in selected:
        item = manifest["chapters"][index]
        rows.append(f"- {item['index']:04d} {item['title']}：{item['characters']}字，对话约{item['dialogue_percent']}%，段落中位数{item['median_paragraph_chars']}字")
    rows.extend([
        "",
        "## 使用规则",
        "",
        "优先读取 `selected/`，需要验证中段或结尾结构时再读取 `chapters/`。不得把整本正文一次性送入模型上下文。分析只提取功能结构、节奏和情绪机制，不复用原文措辞或标志性情节。",
        "",
    ])
    (output / "00_拆书索引.md").write_text("\n".join(rows), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
