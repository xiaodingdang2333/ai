from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import html as html_lib
import re

src_root = Path('download')
out_root = Path('download_txt')
out_root.mkdir(exist_ok=True)

TAG_RE = re.compile(r'<[^>]+>')
SCRIPT_RE = re.compile(r'<(script|style)[\s\S]*?</\1>', re.I)
BR_RE = re.compile(r'<\s*br\s*/?\s*>|</\s*p\s*>|</\s/div\s*>|</\s/h[1-6]\s*>', re.I)
SPACE_RE = re.compile(r'[ \t\r\f\v]+')
BLANK_RE = re.compile(r'\n{3,}')


def local(tag):
    return tag.rsplit('}', 1)[-1]


def decode_bytes(data):
    for enc in ('utf-8', 'utf-16', 'gb18030', 'big5'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode('utf-8', errors='ignore')


def html_to_text(raw):
    raw = SCRIPT_RE.sub('', raw)
    raw = BR_RE.sub('\n', raw)
    raw = TAG_RE.sub('', raw)
    raw = html_lib.unescape(raw)
    raw = raw.replace('\xa0', ' ')
    lines = []
    for line in raw.splitlines():
        line = SPACE_RE.sub(' ', line).strip()
        if line:
            lines.append(line)
    return BLANK_RE.sub('\n\n', '\n'.join(lines)).strip()


def natural_key(name):
    parts = re.split(r'(\d+)', name)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def get_spine_names(z):
    names = z.namelist()
    try:
        container = ET.fromstring(z.read('META-INF/container.xml'))
        rootfile = None
        for elem in container.iter():
            if local(elem.tag) == 'rootfile':
                rootfile = elem.attrib.get('full-path')
                break
        if not rootfile:
            raise ValueError('no rootfile')

        opf = ET.fromstring(z.read(rootfile))
        opf_dir = str(Path(rootfile).parent).replace('\\', '/')
        if opf_dir == '.':
            opf_dir = ''

        manifest = {}
        for elem in opf.iter():
            if local(elem.tag) == 'item':
                item_id = elem.attrib.get('id')
                href = elem.attrib.get('href')
                media = elem.attrib.get('media-type', '')
                if item_id and href and ('html' in media or href.lower().endswith(('.html', '.xhtml', '.htm'))):
                    full = f'{opf_dir}/{href}' if opf_dir else href
                    manifest[item_id] = str(Path(full)).replace('\\', '/')

        ordered = []
        for elem in opf.iter():
            if local(elem.tag) == 'itemref':
                href = manifest.get(elem.attrib.get('idref'))
                if href in names:
                    ordered.append(href)
        if ordered:
            return ordered
    except Exception:
        pass

    return sorted(
        [n for n in names if n.lower().endswith(('.html', '.xhtml', '.htm'))],
        key=natural_key,
    )


def convert_one(epub):
    rel_dir = epub.parent.relative_to(src_root)
    out_dir = out_root / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / (epub.stem + '.txt')

    with ZipFile(epub) as z:
        html_names = get_spine_names(z)
        chunks = []
        for name in html_names:
            try:
                text = html_to_text(decode_bytes(z.read(name)))
            except Exception:
                continue
            if text:
                chunks.append(text)
        if not chunks:
            raise RuntimeError('no text extracted')
        content = f'书名：{epub.stem}\n来源文件：{epub.as_posix()}\n\n' + '\n\n'.join(chunks)
        out_file.write_text(content, encoding='utf-8')

    return out_file


def main():
    converted = []
    failed = []

    for epub in sorted(src_root.rglob('*.epub')):
        try:
            converted.append(convert_one(epub))
        except Exception as e:
            failed.append((epub, str(e)))

    print(f'converted={len(converted)}')
    for p in converted:
        print(p.as_posix())

    if failed:
        print('failed=')
        for p, err in failed:
            print(f'{p.as_posix()} :: {err}')


if __name__ == '__main__':
    main()
