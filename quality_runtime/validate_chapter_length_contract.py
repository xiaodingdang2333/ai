#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, subprocess
from pathlib import Path
from statistics import mean, median

WS = re.compile(r"\s+")


def body_text(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        lines = lines[1:]
    return "\n".join(lines)


def git_blob_sha(path: Path, root: Path) -> str:
    try:
        return subprocess.check_output(["git", "hash-object", str(path.relative_to(root))], cwd=root, text=True).strip()
    except Exception:
        data = path.read_bytes()
        return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def chapter_file(formal: Path, n: int) -> Path:
    matches = sorted(formal.glob(f"CH{n:03d}_*.md"))
    if len(matches) != 1:
        raise SystemExit(f"chapter file mismatch CH{n:03d}: {[p.name for p in matches]}")
    return matches[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--formal-dir", required=True)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--from-chapter", type=int, required=True)
    ap.add_argument("--to-chapter", type=int, required=True)
    ap.add_argument("--output-json", required=True)
    a = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    formal = root / a.formal_dir
    contract_path = root / a.contract
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    required = [
        "chapter_length_contract_id", "count_method", "normal_target_min",
        "normal_target_max", "hard_min", "short_exception_min",
        "short_exception_allowed_functions", "soft_max_review_threshold", "status"
    ]
    missing_fields = [k for k in required if k not in contract]
    if missing_fields:
        raise SystemExit(f"contract missing fields: {missing_fields}")
    if contract["status"] != "LOCKED":
        raise SystemExit("contract status must be LOCKED")
    if contract["count_method"] != "NON_WHITESPACE_BODY_CHARACTERS":
        raise SystemExit("unsupported count method")

    below_review = {x["chapter"]: x for x in contract.get("legacy_reviewed_below_normal", [])}
    short_ex = {x["chapter"]: x for x in contract.get("short_exceptions", [])}
    over_review = {x["chapter"]: x for x in contract.get("legacy_reviewed_over_soft_max", [])}
    rows = []
    failures = []
    below_normal = []
    below_hard = []
    over_soft = []
    stale_review = []

    for n in range(a.from_chapter, a.to_chapter + 1):
        ch = f"CH{n:03d}"
        p = chapter_file(formal, n)
        text = p.read_text(encoding="utf-8")
        chars = len(WS.sub("", body_text(text)))
        blob = git_blob_sha(p, root)
        status = "NORMAL_RANGE"
        reason = None
        if chars < contract["hard_min"]:
            below_hard.append(ch)
            ex = short_ex.get(ch)
            if not ex:
                failures.append({"chapter": ch, "code": "CHAPTER_LENGTH_BELOW_HARD_MIN", "body_chars": chars})
                status = "FAIL_BELOW_HARD_MIN"
            elif (
                chars < contract["short_exception_min"]
                or ex.get("chapter_function") not in contract["short_exception_allowed_functions"]
                or not ex.get("reason")
                or ex.get("review_result") != "PASS"
                or ex.get("blob_sha") != blob
            ):
                failures.append({"chapter": ch, "code": "INVALID_SHORT_CHAPTER_EXCEPTION", "body_chars": chars})
                status = "FAIL_INVALID_EXCEPTION"
            else:
                status = "VALID_SHORT_EXCEPTION"
                reason = ex["reason"]
        elif chars < contract["normal_target_min"]:
            below_normal.append(ch)
            review = below_review.get(ch)
            if not review or review.get("review_result") != "PASS" or not review.get("reason") or review.get("blob_sha") != blob:
                failures.append({"chapter": ch, "code": "CHAPTER_LENGTH_CONTRACT_MISS", "body_chars": chars, "detail": "missing current-blob legacy below-normal review"})
                status = "FAIL_BELOW_NORMAL_UNREVIEWED"
            else:
                status = "BELOW_NORMAL_REVIEWED_PASS"
                reason = review["reason"]
        elif chars > contract["soft_max_review_threshold"]:
            over_soft.append(ch)
            review = over_review.get(ch)
            if not review or review.get("review_result") != "PASS" or not review.get("reason") or review.get("blob_sha") != blob:
                failures.append({"chapter": ch, "code": "CHAPTER_LENGTH_OVERLOAD_REVIEW", "body_chars": chars})
                status = "FAIL_OVER_SOFT_UNREVIEWED"
            else:
                status = "OVER_SOFT_REVIEWED_PASS"
                reason = review["reason"]
        elif chars > contract["normal_target_max"]:
            status = "ABOVE_NORMAL_WITHIN_SOFT_MAX"

        rows.append({
            "chapter": ch,
            "path": str(p.relative_to(root)),
            "blob_sha": blob,
            "body_chars": chars,
            "status": status,
            "review_reason": reason,
        })

    current_chapters = {r["chapter"] for r in rows}
    for group_name, group in (("legacy_reviewed_below_normal", below_review), ("short_exceptions", short_ex), ("legacy_reviewed_over_soft_max", over_review)):
        for ch, item in group.items():
            if ch not in current_chapters:
                stale_review.append({"group": group_name, "chapter": ch, "detail": "outside current scope"})

    vals = [r["body_chars"] for r in rows]
    result = "PASS" if not failures and not stale_review else "FAIL"
    payload = {
        "gate": "CHAPTER_LENGTH_CONTRACT_GATE_V1",
        "contract_path": a.contract,
        "contract_id": contract["chapter_length_contract_id"],
        "contract_status": contract["status"],
        "count_method": contract["count_method"],
        "input_scope": {"from": a.from_chapter, "to": a.to_chapter, "formal_dir": a.formal_dir},
        "thresholds": {
            "normal_target_min": contract["normal_target_min"],
            "normal_target_max": contract["normal_target_max"],
            "hard_min": contract["hard_min"],
            "short_exception_min": contract["short_exception_min"],
            "soft_max_review_threshold": contract["soft_max_review_threshold"],
        },
        "chapters": rows,
        "summary": {
            "chapter_count": len(rows),
            "min": min(vals) if vals else 0,
            "mean": round(mean(vals), 2) if vals else 0,
            "median": median(vals) if vals else 0,
            "below_normal_chapters": below_normal,
            "below_hard_min_chapters": below_hard,
            "over_soft_max_chapters": over_soft,
            "failure_count": len(failures),
        },
        "failures": failures,
        "stale_review_entries": stale_review,
        "length_gate_result": result,
    }
    out = root / a.output_json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result != "PASS":
        raise SystemExit(f"length gate failed: {failures}; stale={stale_review}")


if __name__ == "__main__":
    main()
