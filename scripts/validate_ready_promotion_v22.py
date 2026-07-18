#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate READY_AFTER_STRONG_QA against a current-blob P0 manifest.

This validator intentionally ignores prose audit Markdown PASS strings. A READY
promotion is valid only when current formal blob SHAs match a machine P0 manifest
whose result is PASS and whose failure/stale/missing lists are empty.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def git_blob_sha(path: Path, root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "hash-object", str(path.relative_to(root))], cwd=root, text=True
        ).strip()
    except Exception:
        data = path.read_bytes()
        return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def chapter_file(formal: Path, n: int) -> Path:
    matches = sorted(formal.glob(f"CH{n:03d}_*.md"))
    if len(matches) != 1:
        raise SystemExit(f"chapter file mismatch CH{n:03d}: {[p.name for p in matches]}")
    return matches[0]


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--formal-dir", required=True)
    p.add_argument("--p0-manifest", required=True)
    p.add_argument("--from-chapter", type=int, required=True)
    p.add_argument("--to-chapter", type=int, required=True)
    p.add_argument("--output-json", required=True)
    return p.parse_args()


def main() -> None:
    a = args()
    root = Path(__file__).resolve().parents[1]
    formal = root / a.formal_dir
    manifest_path = root / a.p0_manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_ch = {r["chapter"]: r for r in manifest.get("chapters", [])}

    stale = []
    missing = []
    current = []
    for n in range(a.from_chapter, a.to_chapter + 1):
        ch = f"CH{n:03d}"
        path = chapter_file(formal, n)
        sha = git_blob_sha(path, root)
        current.append({"chapter": ch, "path": str(path.relative_to(root)), "blob_sha": sha})
        row = by_ch.get(ch)
        if row is None or not row.get("blob_sha"):
            missing.append(ch)
        elif row["blob_sha"] != sha:
            stale.append(ch)

    absolute = manifest.get("core_metrics", {}).get("absolute_failures", [])
    body_review = manifest.get("core_metrics", {}).get("mandatory_body_review_chapters", [])
    manifest_missing = manifest.get("core_metrics", {}).get("missing_metric_chapters", [])
    manifest_stale = manifest.get("stale_blob_chapters", [])
    manifest_result = manifest.get("p0_manifest_result")

    reasons = []
    if manifest_result != "PASS":
        reasons.append(f"p0_manifest_result={manifest_result}")
    if absolute:
        reasons.append(f"absolute_failures={absolute}")
    if body_review:
        reasons.append(f"mandatory_body_review_chapters={body_review}")
    if manifest_missing or missing:
        reasons.append(f"missing_metric_chapters={sorted(set(manifest_missing + missing))}")
    if manifest_stale or stale:
        reasons.append(f"stale_blob_chapters={sorted(set(manifest_stale + stale))}")

    payload = {
        "gate": "READY_PROMOTION_CURRENT_P0_MANIFEST_LOCK",
        "patch_ref": "V2_2_DIALOGUE_VISUAL_ABSOLUTE_HARD_GATE_REAL_FAILURE_007",
        "input_scope": {"from": a.from_chapter, "to": a.to_chapter, "formal_dir": a.formal_dir},
        "p0_manifest": a.p0_manifest,
        "current_blobs": current,
        "stale_blob_chapters": stale,
        "missing_metric_chapters": missing,
        "absolute_failures": absolute,
        "mandatory_body_review_chapters": body_review,
        "promotion_result": "PASS" if not reasons else "FAIL",
        "ready_after_strong_qa_allowed": not reasons,
        "blocking_reasons": reasons,
    }
    out = root / a.output_json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if reasons:
        raise SystemExit("READY promotion blocked: " + "; ".join(reasons))


if __name__ == "__main__":
    main()
