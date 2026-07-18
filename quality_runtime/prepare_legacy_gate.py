#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, shutil, subprocess
from pathlib import Path
from statistics import mean, median

WS = re.compile(r"\s+")
CH_RE = re.compile(r"^第(\d{3})章(?:_|\.)")
INDEX_RE = re.compile(r"^- 第(\d{3})章[：:](.+?)\s*$")


def git_blob_sha(path: Path, root: Path) -> str:
    try:
        return subprocess.check_output(["git", "hash-object", str(path.relative_to(root))], cwd=root, text=True).strip()
    except Exception:
        data = path.read_bytes()
        return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def body_text(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        lines = lines[1:]
    return "\n".join(lines)


def pct(vals: list[int], p: float) -> int:
    if not vals:
        return 0
    xs = sorted(vals)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * p
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    frac = pos - lo
    return round(xs[lo] * (1 - frac) + xs[hi] * frac)


def bucket(rows: list[dict], pred) -> list[dict]:
    return [
        {"chapter": r["chapter"], "body_chars": r["body_chars"], "blob_sha": r["blob_sha"]}
        for r in sorted(rows, key=lambda x: (x["body_chars"], x["number"]))
        if pred(r["body_chars"])
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-dir", required=True)
    ap.add_argument("--from-chapter", type=int, default=1)
    ap.add_argument("--to-chapter", type=int, default=74)
    ap.add_argument("--formal-out", required=True)
    ap.add_argument("--output-json", required=True)
    a = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    book = root / a.book_dir
    src = book / "正文"
    out = root / a.formal_out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    found = {}
    for p in src.glob("*.md"):
        m = CH_RE.match(p.name)
        if m:
            n = int(m.group(1))
            found.setdefault(n, []).append(p)
    missing = []
    duplicates = []
    rows = []
    for n in range(a.from_chapter, a.to_chapter + 1):
        ps = found.get(n, [])
        if len(ps) != 1:
            (missing if not ps else duplicates).append({"chapter": f"CH{n:03d}", "files": [str(x.relative_to(root)) for x in ps]})
            continue
        p = ps[0]
        text = p.read_text(encoding="utf-8")
        body = body_text(text)
        suffix = re.sub(r"[^\w\-]+", "_", p.stem, flags=re.UNICODE).strip("_")
        q = out / f"CH{n:03d}_{suffix}.md"
        q.write_bytes(p.read_bytes())
        first = text.splitlines()[0].strip() if text.splitlines() else ""
        body_chars = len(WS.sub("", body))
        rows.append({
            "chapter": f"CH{n:03d}",
            "number": n,
            "source_path": str(p.relative_to(root)),
            "formal_path": str(q.relative_to(root)),
            "blob_sha": git_blob_sha(p, root),
            "normalized_copy_blob_sha": git_blob_sha(q, root),
            "body_chars": body_chars,
            "first_line": first,
            "has_markdown_title": first.startswith(f"# 第{n:03d}章 "),
            "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "empty_body": body_chars == 0,
        })
    index_path = book / "追踪" / "章节索引.md"
    index = {}
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            m = INDEX_RE.match(line.strip())
            if m and int(m.group(1)) not in index:
                index[int(m.group(1))] = m.group(2).strip()
    index_missing = []
    title_mismatch = []
    missing_markdown_titles = []
    for r in rows:
        n = r["number"]
        if not r["has_markdown_title"]:
            missing_markdown_titles.append(r["chapter"])
        expected = index.get(n)
        if expected is None:
            index_missing.append(r["chapter"])
            continue
        header = re.sub(r"^#\s*第\d{3}章\s*", "", r["first_line"]).strip()
        if header.rstrip("？?") != expected.rstrip("？?"):
            title_mismatch.append({"chapter": r["chapter"], "header": header, "index": expected})
    by_body = {}
    for r in rows:
        by_body.setdefault(r["body_sha256"], []).append(r["chapter"])
    exact_duplicate_groups = [v for v in by_body.values() if len(v) > 1]
    vals = [r["body_chars"] for r in rows]
    blob_copy_mismatches = [r["chapter"] for r in rows if r["blob_sha"] != r["normalized_copy_blob_sha"]]
    empty = [r["chapter"] for r in rows if r["empty_body"]]
    payload = {
        "gate": "LEGACY_BOOK_PREPARE_AND_DIAGNOSTIC_V2",
        "scope": {"book_dir": a.book_dir, "from": a.from_chapter, "to": a.to_chapter},
        "chapters": rows,
        "missing_chapters": missing,
        "duplicate_number_files": duplicates,
        "index_missing_chapters": index_missing,
        "missing_markdown_titles": missing_markdown_titles,
        "title_index_mismatches": title_mismatch,
        "exact_duplicate_body_groups": exact_duplicate_groups,
        "blob_copy_mismatches": blob_copy_mismatches,
        "empty_body_chapters": empty,
        "length_profile": {
            "count_method": "NON_WHITESPACE_BODY_CHARACTERS",
            "valid_chapter_count": len(vals),
            "min": min(vals) if vals else 0,
            "p10": pct(vals, .10),
            "p25": pct(vals, .25),
            "median": median(vals) if vals else 0,
            "mean": round(mean(vals), 2) if vals else 0,
            "p75": pct(vals, .75),
            "p90": pct(vals, .90),
            "max": max(vals) if vals else 0,
            "early_10_mean": round(mean(vals[:10]), 2) if len(vals) >= 10 else None,
            "early_30_mean": round(mean(vals[:30]), 2) if len(vals) >= 30 else None,
        },
        "length_threshold_buckets": {
            "below_1400": bucket(rows, lambda n: n < 1400),
            "below_1800": bucket(rows, lambda n: n < 1800),
            "below_2200": bucket(rows, lambda n: n < 2200),
            "above_3200": bucket(rows, lambda n: n > 3200),
            "above_3600": bucket(rows, lambda n: n > 3600),
        },
    }
    blockers = [missing, duplicates, index_missing, missing_markdown_titles, title_mismatch, exact_duplicate_groups, blob_copy_mismatches, empty]
    payload["structural_result"] = "PASS" if not any(blockers) else "FAIL"
    op = root / a.output_json
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"length_profile": payload["length_profile"], "length_threshold_buckets": payload["length_threshold_buckets"]}, ensure_ascii=False))
    if payload["structural_result"] != "PASS":
        raise SystemExit("structural diagnostic failed")


if __name__ == "__main__":
    main()
