from pathlib import Path

root = Path(__file__).parent
files = [root / '简介.md'] + [
    root / '正文' / '第001章_墙里有信.md',
    root / '正文' / '第002章_不要信陆家.md',
    root / '正文' / '第003章_别开灯.md',
    root / '正文' / '第004章_提前拆除.md',
    root / '正文' / '第005章_雨夜旧影.md',
    root / '正文' / '第006章_账册残页.md',
    root / '正文' / '第007章_名单换过.md',
    root / '正文' / '第008章_木箱夹层.md',
    root / '正文' / '第009章_他藏了后半段.md',
    root / '正文' / '第010章_雨停以前.md',
]

parts = []
for file in files:
    if not file.exists():
        raise FileNotFoundError(file)
    parts.append(file.read_text(encoding='utf-8').strip())

out = root / '前十章合并稿.md'
out.write_text('\n\n---\n\n'.join(parts) + '\n', encoding='utf-8')

print(out)
for file in files[1:]:
    print(file.name, len(file.read_text(encoding='utf-8')))
print(out.name, len(out.read_text(encoding='utf-8')))

