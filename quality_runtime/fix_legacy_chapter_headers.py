#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path

BOOK = Path('txt/重生六岁，我带空间抢回军区大院')
BODY = BOOK / '正文'
TITLES = {
    37: '我也能讲一道',
    48: '七双手',
    49: '铁门之外',
    50: '八十一分，不算赢',
    51: '七十三分里的“猜对”',
    52: '喜娃不是陈小喜',
    53: '别叫我小喜',
    54: '门锁在哪儿',
    55: '那张“走？”',
    56: '半碗玉米糊',
    57: '她漏掉了两个字',
    58: '下次，来',
    59: '空白本有了名字',
    60: '纸上画着一只左手',
    61: '粮本空着一格',
    62: '地窖里多了一道线',
    63: '那天她没有去互助桌',
    64: '第一棵白菜写着她的名字',
}


def chapter_file(n: int) -> Path:
    matches = sorted(BODY.glob(f'第{n:03d}章*.md'))
    if len(matches) != 1:
        raise SystemExit(f'chapter file mismatch CH{n:03d}: {[p.name for p in matches]}')
    return matches[0]


def main() -> None:
    changed = []
    for n, title in TITLES.items():
        p = chapter_file(n)
        raw = p.read_text(encoding='utf-8')
        lines = raw.splitlines()
        expected = f'# 第{n:03d}章 {title}'
        if lines and lines[0].startswith('# 第'):
            if lines[0] == expected:
                continue
            lines[0] = expected
            new = '\n'.join(lines)
        else:
            new = expected + '\n\n' + raw
        # Preserve the repository's no-final-newline convention.
        p.write_text(new.rstrip('\n'), encoding='utf-8')
        changed.append(str(p))
    print('\n'.join(changed) if changed else 'no header changes')


if __name__ == '__main__':
    main()
