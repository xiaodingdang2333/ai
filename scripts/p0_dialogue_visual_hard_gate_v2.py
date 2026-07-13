#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Executable P0 dialogue/page-texture hard gate.

Usage:
  python3 scripts/p0_dialogue_visual_hard_gate_v2.py \
    --formal-dir novels/<book>/formal \
    --reference-from 1 --reference-to 10 \
    --target-from 11 --target-to 40 \
    --output-json novels/<book>/audits/P0_DIALOGUE_VISUAL_HARD_GATE.json

This gate is deliberately separate from literary Critic. It prevents a manual
PASS from bypassing calculable dialogue/page-texture failures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

WS = re.compile(r"\s+")
SENTENCE_END = re.compile(r"[。！？?!]+")
QUOTE_CONTENT = re.compile(r"[“‘]([^”’]*)[”’]|【([^】]*)】", re.S)
PUNCT_ONLY = re.compile(r"^[\s，。！？；：、,.!?;:\-—…（）()\[\]【】]*$")


def body_text(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        lines = lines[1:]
    return "\n".join(lines)


def paragraphs(text: str) -> list[str]:
    return [
        p.strip()
        for p in re.split(r"\n\s*\n", body_text(text))
        if p.strip() and not p.strip().startswith("<!--")
    ]


def nw(s: str) -> str:
    return WS.sub("", s)


def quote_chars(p: str) -> int:
    total = 0
    for m in QUOTE_CONTENT.finditer(p):
        total += len(nw(m.group(1) or m.group(2) or ""))
    return total


def outside_quote_text(p: str) -> str:
    return QUOTE_CONTENT.sub("", p)


def is_dialogue_only(p: str) -> bool:
    q = quote_chars(p)
    if q == 0:
        return False
    outside = nw(outside_quote_text(p))
    # Allow punctuation only; speaker/action text means not dialogue-only.
    return not outside or bool(PUNCT_ONLY.match(outside))


def is_dialogue_led(p: str) -> bool:
    total = max(len(nw(p)), 1)
    q = quote_chars(p)
    return q > 0 and (q / total >= 0.70 or p.lstrip().startswith(("“", "‘", "【")))


def sentence_count(p: str) -> int:
    parts = [x for x in SENTENCE_END.split(p) if nw(x)]
    return max(len(parts), 1)


def longest_run(flags: list[bool]) -> int:
    best = cur = 0
    for flag in flags:
        cur = cur + 1 if flag else 0
        best = max(best, cur)
    return best


def longest_sawtooth(ps: list[str]) -> int:
    """Long run dominated by short one-sentence or dialogue-led paragraphs.

    This intentionally catches alternating short narration/dialogue that a pure
    dialogue-only run misses.
    """
    flags = []
    for p in ps:
        short40 = len(nw(p)) <= 40
        one = sentence_count(p) <= 1
        flags.append(short40 and (one or is_dialogue_led(p)))
    return longest_run(flags)


def git_blob_sha(path: Path, root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "hash-object", str(path.relative_to(root))],
            cwd=root,
            text=True,
        ).strip()
    except Exception:
        data = path.read_bytes()
        header = f"blob {len(data)}\0".encode()
        return hashlib.sha1(header + data).hexdigest()


def chapter_file(formal: Path, n: int) -> Path:
    matches = sorted(formal.glob(f"CH{n:03d}_*.md"))
    if len(matches) != 1:
        raise SystemExit(f"Expected one CH{n:03d} file, got {[p.name for p in matches]}")
    return matches[0]


def measure(path: Path, root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    body = body_text(text)
    ps = paragraphs(text)
    total_chars = max(len(nw(body)), 1)
    dialog_chars = sum(quote_chars(p) for p in ps)
    dialog_only_flags = [is_dialogue_only(p) for p in ps]
    dialog_led_flags = [is_dialogue_led(p) for p in ps]
    short20_flags = [len(nw(p)) <= 20 for p in ps]
    short40_flags = [len(nw(p)) <= 40 for p in ps]
    one_flags = [sentence_count(p) <= 1 for p in ps]
    n = max(len(ps), 1)
    return {
        "path": str(path.relative_to(root)),
        "blob_sha": git_blob_sha(path, root),
        "total_body_chars": len(nw(body)),
        "total_paragraphs": len(ps),
        "single_sentence_paragraph_count": sum(one_flags),
        "single_sentence_paragraph_ratio": round(sum(one_flags) / n, 4),
        "short_paragraph_le20_count": sum(short20_flags),
        "short_paragraph_le20_ratio": round(sum(short20_flags) / n, 4),
        "short_paragraph_le40_count": sum(short40_flags),
        "short_paragraph_le40_ratio": round(sum(short40_flags) / n, 4),
        "dialogue_only_paragraph_count": sum(dialog_only_flags),
        "dialogue_only_paragraph_ratio": round(sum(dialog_only_flags) / n, 4),
        "dialogue_led_paragraph_count": sum(dialog_led_flags),
        "dialogue_led_paragraph_ratio": round(sum(dialog_led_flags) / n, 4),
        "dialogue_character_ratio": round(dialog_chars / total_chars, 4),
        "non_dialogue_narrative_character_ratio": round(1 - dialog_chars / total_chars, 4),
        "max_dialogue_only_run": longest_run(dialog_only_flags),
        "max_short_paragraph_le20_run": longest_run(short20_flags),
        "max_short_paragraph_le40_run": longest_run(short40_flags),
        "max_sawtooth_run": longest_sawtooth(ps),
    }


def ref_max(rows: list[dict[str, Any]], key: str) -> float:
    return max(float(r[key]) for r in rows)


def evaluate(row: dict[str, Any], ref: list[dict[str, Any]]) -> dict[str, Any]:
    hard: list[str] = []
    review: list[str] = []

    if row["dialogue_character_ratio"] > 0.45:
        hard.append("DIALOGUE_PAGE_DOMINANCE:dialogue_character_ratio>0.45")
    if row["dialogue_only_paragraph_ratio"] > 0.55:
        hard.append("CHAT_LOG_PAGE_TEXTURE:dialogue_only_paragraph_ratio>0.55")
    if row["max_dialogue_only_run"] >= 10:
        hard.append("SERIAL_DIALOGUE_ABSOLUTE_FAIL:max_dialogue_only_run>=10")
    if row["short_paragraph_le20_ratio"] > 0.90 and row["single_sentence_paragraph_ratio"] > 0.60:
        hard.append("SAWTOOTH_SHORT_PARAGRAPH_PAGE:short20>0.90_and_one_sentence>0.60")
    if row["max_short_paragraph_le40_run"] >= 24:
        hard.append("SAWTOOTH_SHORT_PARAGRAPH_PAGE:max_short40_run>=24")
    if row["max_sawtooth_run"] >= 20:
        hard.append("SAWTOOTH_SHORT_PARAGRAPH_PAGE:max_sawtooth_run>=20")

    # Reference-band drift requires body-level review; it cannot be a text-only PASS.
    # For CH001 there is no previous ordinary chapter.  Absolute P0 limits above
    # still apply, while relative drift is intentionally deferred until CH002.
    if ref:
        if row["dialogue_character_ratio"] > ref_max(ref, "dialogue_character_ratio") + 0.08:
            review.append("REFERENCE_DRIFT:dialogue_character_ratio")
        if row["dialogue_only_paragraph_ratio"] > ref_max(ref, "dialogue_only_paragraph_ratio") + 0.10:
            review.append("REFERENCE_DRIFT:dialogue_only_paragraph_ratio")
        if row["short_paragraph_le20_ratio"] > ref_max(ref, "short_paragraph_le20_ratio") + 0.12:
            review.append("REFERENCE_DRIFT:short20_ratio")
        # CH001 may hold a scoped exception; do not use it as the ordinary run template.
        ordinary_refs = [r for r in ref if r.get("chapter") != "CH001"]
        if ordinary_refs and row["max_dialogue_only_run"] > max(r["max_dialogue_only_run"] for r in ordinary_refs) + 2:
            review.append("REFERENCE_DRIFT:max_dialogue_only_run")
        if row["max_sawtooth_run"] > ref_max(ref, "max_sawtooth_run") + 4:
            review.append("REFERENCE_DRIFT:max_sawtooth_run")

    result = "FAIL" if hard else ("MANDATORY_BODY_REVIEW" if review else "PASS_NUMERIC")
    return {"result": result, "absolute_failures": hard, "reference_band_review_hits": review}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--formal-dir", required=True)
    p.add_argument("--reference-from", type=int, required=True)
    p.add_argument("--reference-to", type=int, required=True)
    p.add_argument("--target-from", type=int, required=True)
    p.add_argument("--target-to", type=int, required=True)
    p.add_argument("--output-json", required=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    formal = root / args.formal_dir
    refs = []
    for n in range(args.reference_from, args.reference_to + 1):
        r = measure(chapter_file(formal, n), root)
        r["chapter"] = f"CH{n:03d}"
        refs.append(r)

    targets = []
    for n in range(args.target_from, args.target_to + 1):
        row = measure(chapter_file(formal, n), root)
        row["chapter"] = f"CH{n:03d}"
        row.update(evaluate(row, refs))
        targets.append(row)

    absolute = [r["chapter"] for r in targets if r["absolute_failures"]]
    review = [r["chapter"] for r in targets if r["reference_band_review_hits"]]
    missing = [r["chapter"] for r in targets if not r.get("blob_sha")]
    payload = {
        "gate": "P0_DIALOGUE_VISUAL_HARD_GATE_V2",
        "patch_ref": "V2_2_DIALOGUE_VISUAL_ABSOLUTE_HARD_GATE_REAL_FAILURE_007",
        "input_scope": {
            "formal_dir": args.formal_dir,
            "reference_window": [args.reference_from, args.reference_to],
            "target_window": [args.target_from, args.target_to],
        },
        "check_method": "current git blobs; blank-line paragraphs; quote/message dialogue chars; dialogue-only/dialogue-led; short20/short40; one-sentence; pure-dialogue and sawtooth runs",
        "reference_metrics": refs,
        "chapters": targets,
        "core_metrics": {
            "target_chapter_count": len(targets),
            "absolute_failures": absolute,
            "mandatory_body_review_chapters": review,
            "missing_metric_chapters": missing,
            "reference_band": {
                "dialogue_character_ratio_max": ref_max(refs, "dialogue_character_ratio"),
                "dialogue_only_paragraph_ratio_max": ref_max(refs, "dialogue_only_paragraph_ratio"),
                "short20_ratio_max": ref_max(refs, "short_paragraph_le20_ratio"),
                "max_sawtooth_run_max": ref_max(refs, "max_sawtooth_run"),
            },
        },
        "hit_locations": [r["path"] for r in targets if r["absolute_failures"] or r["reference_band_review_hits"]],
        "stale_blob_chapters": [],
        "post_fix_recalculation": "REQUIRED" if absolute or review else "NOT_REQUIRED",
        "p0_manifest_result": "FAIL" if absolute or missing else ("MANDATORY_BODY_REVIEW" if review else "PASS"),
    }
    out = root / args.output_json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if absolute or missing:
        raise SystemExit(f"P0 hard gate failed. absolute={absolute} missing={missing}")
    if review:
        raise SystemExit(f"P0 reference-band body review required: {review}")


if __name__ == "__main__":
    main()
