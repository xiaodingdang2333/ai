#!/usr/bin/env python3
"""Upload Git-ready web novel projects to Fanqie drafts.

This worker reads `00_PROJECT.json` upload readiness fields from the
chatgpt-novel-production-system repository, exports web-format chapters to the
legacy Fanqie uploader's expected local layout, and then calls the existing
Fanqie uploader.

Default mode is dry-run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPO = Path("/home/admin/chatgpt-novel-production-system")
EXPORT_ROOT = Path("/home/admin/ai/output/novel-git-upload")
QUALITY_GATE_ROOT = EXPORT_ROOT / "quality-gates"
FANQIE_UPLOAD = Path("/home/admin/ai/codex/skills/fanqie-upload/scripts/fanqie-upload.js")

ACCOUNT_PORTS = {
    "account-a": 9223,
    "account-b": 9224,
    "account-c": 9225,
}

ACCOUNT_AUTHORS = {
    "account-a": "西大水怪",
    "account-b": "桃枝醒醒",
    "account-c": "泡芙软呼呼",
}

ACCOUNT_AI_DECLARATIONS = {
    "account-a": "no",
    "account-b": "yes",
    "account-c": "no",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compact_text(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    return re.sub(r"\s+", "", "\n".join(lines))


def han_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", compact_text(text)))


def git_blob_sha(path: Path, repo: Path) -> str:
    result = run_git(repo, ["hash-object", str(path.relative_to(repo))], check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def run_git(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def safe_git_record(repo: Path, paths: list[Path], message: str, push: bool) -> dict[str, Any]:
    rel_paths = sorted({str(path.relative_to(repo)) for path in paths if path.exists()})
    if not rel_paths:
        return {"status": "no_paths"}
    run_git(repo, ["add", "--", *rel_paths])
    diff = run_git(repo, ["diff", "--cached", "--quiet"], check=False)
    if diff.returncode == 0:
        return {"status": "no_changes", "paths": rel_paths}
    commit = run_git(repo, ["commit", "-m", message], check=False)
    if commit.returncode != 0:
        return {"status": "commit_failed", "paths": rel_paths, "stderr": commit.stderr[-2000:]}
    result = {
        "status": "committed",
        "paths": rel_paths,
        "commit": run_git(repo, ["rev-parse", "HEAD"]).stdout.strip(),
    }
    if push:
        fetch = run_git(repo, ["fetch", "origin", "main"], check=False)
        if fetch.returncode != 0:
            result["push_status"] = "fetch_failed"
            result["push_error"] = fetch.stderr[-2000:]
            return result
        behind = run_git(repo, ["rev-list", "--count", "HEAD..origin/main"], check=False)
        if behind.returncode == 0 and behind.stdout.strip() != "0":
            result["push_status"] = "remote_changed_not_pushed"
            result["push_error"] = "origin/main advanced; rebase required before push"
            return result
        push_result = run_git(repo, ["push", "origin", "HEAD:main"], check=False)
        result["push_status"] = "pushed" if push_result.returncode == 0 else "push_failed"
        if push_result.returncode != 0:
            result["push_error"] = push_result.stderr[-2000:]
    return result


def safe_name(value: str, fallback: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value).strip(" ._")
    return value[:80] or fallback


def chapter_no_from_name(path: Path) -> int | None:
    match = re.search(r"CH0*(\d+)", path.name, re.I)
    if not match:
        match = re.search(r"第\s*0*(\d+)\s*章", path.name)
    return int(match.group(1)) if match else None


def title_from_web_chapter(path: Path, text: str, no: int) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    heading = re.match(r"^#{1,6}\s*(.+?)\s*$", first)
    if heading:
        title = heading.group(1)
    else:
        title = path.stem
    title = re.sub(r"^CH0*\d+[_\s-]*", "", title, flags=re.I)
    title = re.sub(r"^第\s*0*\d+\s*章[\s._-]*", "", title)
    title = title.strip() or f"第{no:03d}章"
    return title


def validate_candidate(project_path: Path, data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("auto_upload_to_drafts") is not True:
        errors.append("auto_upload_to_drafts is not true")
    if data.get("upload_status") != "ready_for_draft_upload":
        errors.append("upload_status is not ready_for_draft_upload")
    account = data.get("fanqie_account")
    if account not in ACCOUNT_PORTS:
        errors.append(f"invalid fanqie_account: {account!r}")
    elif data.get("expected_author_name") != ACCOUNT_AUTHORS[account]:
        errors.append(f"expected_author_name must be {ACCOUNT_AUTHORS[account]!r}")
    if not str(data.get("fanqie_book_id") or "").strip():
        errors.append("fanqie_book_id is required")
    if data.get("ai_use") not in {"yes", "no"}:
        errors.append("ai_use must be yes or no")
    elif account in ACCOUNT_AI_DECLARATIONS and data.get("ai_use") != ACCOUNT_AI_DECLARATIONS[account]:
        errors.append(f"ai_use must be {ACCOUNT_AI_DECLARATIONS[account]!r} for {account}")
    evidence = data.get("ready_evidence")
    if not isinstance(evidence, dict):
        errors.append("ready_evidence is required")
    else:
        if evidence.get("qa_passed") is not True:
            errors.append("ready_evidence.qa_passed must be true")
        if evidence.get("current_blob_validated") is not True:
            errors.append("ready_evidence.current_blob_validated must be true")
        if evidence.get("human_review_required") is True and evidence.get("human_review_status") != "approved":
            errors.append("human review is required but not approved")
    if not (project_path / "formal").exists():
        errors.append("formal chapter directory is required")
    return errors


def export_project(repo: Path, project_path: Path, data: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    title = str(data.get("book_title") or project_path.name)
    upload_range = data.get("upload_range") if isinstance(data.get("upload_range"), dict) else {}
    from_chapter = int(upload_range.get("from_chapter") or 1)
    to_chapter = int(upload_range.get("to_chapter") or 999999)
    export_dir = EXPORT_ROOT / safe_name(title, "book")
    chapter_dir = export_dir / "正文"
    if export_dir.exists():
        shutil.rmtree(export_dir)
    chapter_dir.mkdir(parents=True, exist_ok=True)

    exported = []
    for source in sorted((project_path / "formal").glob("*.md")):
        no = chapter_no_from_name(source)
        if no is None or no < from_chapter or no > to_chapter:
            continue
        text = source.read_text(encoding="utf-8")
        title_part = title_from_web_chapter(source, text, no)
        target = chapter_dir / f"第{no:03d}章_{safe_name(title_part, f'ch{no:03d}')}.md"
        target.write_text(text.rstrip() + "\n", encoding="utf-8")
        exported.append({
            "chapter_no": no,
            "source": str(source.relative_to(repo)),
            "target": str(target),
            "title": title_part,
        })

    manifest = {
        "exported_at": now_iso(),
        "source_repo": str(repo),
        "project_path": str(project_path.relative_to(repo)),
        "book_title": title,
        "from_chapter": from_chapter,
        "to_chapter": to_chapter,
        "chapter_count": len(exported),
        "chapters": exported,
    }
    write_json(export_dir / "export-manifest.json", manifest)
    return export_dir, manifest


def run_command(command: list[str], execute: bool) -> dict[str, Any]:
    if not execute:
        return {"command": command, "status": "dry_run"}
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return {
        "command": command,
        "status": "ok" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "")[-4000:],
        "stderr_tail": (result.stderr or "")[-4000:],
    }


def formal_chapter_file(project_path: Path, no: int) -> Path | None:
    matches = sorted((project_path / "formal").glob(f"CH{no:03d}_*.md"))
    return matches[0] if len(matches) == 1 else None


def quality_output_dir(repo: Path, project_path: Path, execute: bool) -> Path:
    if execute:
        return project_path / "audits"
    return QUALITY_GATE_ROOT / safe_name(project_path.name, "book")


def run_repo_script(repo: Path, command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return {
        "command": command,
        "status": "ok" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "")[-4000:],
        "stderr_tail": (result.stderr or "")[-4000:],
    }


def run_quality_gate(repo: Path, project_path: Path, data: dict[str, Any], execute: bool) -> tuple[bool, dict[str, Any], list[Path]]:
    upload_range = data.get("upload_range") if isinstance(data.get("upload_range"), dict) else {}
    from_chapter = int(upload_range.get("from_chapter") or 1)
    to_chapter = int(upload_range.get("to_chapter") or 999999)
    formal = project_path / "formal"
    available = sorted(
        no
        for no in (chapter_no_from_name(path) for path in formal.glob("CH*.md"))
        if no is not None
    )
    out_dir = quality_output_dir(repo, project_path, execute)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    p0_output = out_dir / f"SERVER_UPLOAD_P0_GATE_CH{from_chapter:03d}_CH{to_chapter:03d}_{stamp}.json"
    ready_output = out_dir / f"SERVER_UPLOAD_READY_GATE_CH{from_chapter:03d}_CH{to_chapter:03d}_{stamp}.json"
    summary_output = out_dir / f"SERVER_UPLOAD_QUALITY_GATE_CH{from_chapter:03d}_CH{to_chapter:03d}_{stamp}.json"

    errors: list[str] = []
    chapter_rows: list[dict[str, Any]] = []
    if not available:
        errors.append("no formal chapters found")
    else:
        for no in range(from_chapter, to_chapter + 1):
            path = formal_chapter_file(project_path, no)
            if path is None:
                errors.append(f"missing or duplicate formal chapter CH{no:03d}")
                continue
            text = path.read_text(encoding="utf-8")
            chars = han_count(text)
            row = {
                "chapter": f"CH{no:03d}",
                "path": str(path.relative_to(repo)),
                "han_count": chars,
                "blob_sha": git_blob_sha(path, repo),
            }
            chapter_rows.append(row)
            if chars < 2500:
                errors.append(f"CH{no:03d} han_count {chars} < 2500")

    latest = max(available) if available else 0
    reference_to = min(max(1, latest), max(10, to_chapter))
    reference_to = min(reference_to, latest) if latest else 0
    reference_from = 1
    p0_result: dict[str, Any] | None = None
    ready_result: dict[str, Any] | None = None

    if not errors and reference_to >= reference_from:
        p0_cmd = [
            sys.executable,
            str(repo / "scripts" / "p0_dialogue_visual_hard_gate_v2.py"),
            "--formal-dir",
            str(formal.relative_to(repo)),
            "--reference-from",
            str(reference_from),
            "--reference-to",
            str(reference_to),
            "--target-from",
            str(from_chapter),
            "--target-to",
            str(to_chapter),
            "--output-json",
            str(p0_output.relative_to(repo) if execute else p0_output),
        ]
        p0_result = run_repo_script(repo, p0_cmd)
        if p0_result["status"] != "ok":
            errors.append("P0 dialogue visual hard gate failed to execute")
        elif p0_output.exists():
            p0_payload = load_json(p0_output)
            p0_status = p0_payload.get("p0_manifest_result")
            if p0_status != "PASS":
                errors.append(f"P0 manifest result is {p0_status}, expected PASS")

    if not errors:
        ready_cmd = [
            sys.executable,
            str(repo / "scripts" / "validate_ready_promotion_v22.py"),
            "--formal-dir",
            str(formal.relative_to(repo)),
            "--p0-manifest",
            str(p0_output.relative_to(repo) if execute else p0_output),
            "--from-chapter",
            str(from_chapter),
            "--to-chapter",
            str(to_chapter),
            "--output-json",
            str(ready_output.relative_to(repo) if execute else ready_output),
        ]
        ready_result = run_repo_script(repo, ready_cmd)
        if ready_result["status"] != "ok":
            errors.append("READY promotion current-blob validation failed")
        elif ready_output.exists():
            ready_payload = load_json(ready_output)
            if ready_payload.get("promotion_result") != "PASS" or ready_payload.get("ready_after_strong_qa_allowed") is not True:
                errors.append("READY promotion validator did not allow upload")

    evidence = data.get("ready_evidence") if isinstance(data.get("ready_evidence"), dict) else {}
    if evidence.get("qa_passed") is not True:
        errors.append("ready_evidence.qa_passed is not true")
    if evidence.get("current_blob_validated") is not True:
        errors.append("ready_evidence.current_blob_validated is not true")

    summary = {
        "gate": "SERVER_UPLOAD_QUALITY_GATE_V1",
        "checked_at": now_iso(),
        "project": str(project_path.relative_to(repo)),
        "book_title": data.get("book_title"),
        "upload_range": {"from_chapter": from_chapter, "to_chapter": to_chapter},
        "result": "PASS" if not errors else "FAIL",
        "blocking_reasons": errors,
        "chapters": chapter_rows,
        "p0_output": str(p0_output),
        "ready_output": str(ready_output),
        "p0_command": p0_result,
        "ready_command": ready_result,
    }
    write_json(summary_output, summary)
    changed = [path for path in [p0_output, ready_output, summary_output] if path.exists() and path.is_relative_to(repo)]
    return not errors, summary, changed


def process_candidate(repo: Path, project_file: Path, execute: bool) -> dict[str, Any]:
    data = load_json(project_file)
    project_path = project_file.parent
    errors = validate_candidate(project_path, data)
    if errors:
        return {"project_file": str(project_file.relative_to(repo)), "status": "invalid", "errors": errors}

    quality_ok, quality, quality_paths = run_quality_gate(repo, project_path, data, execute)
    if not quality_ok:
        return {
            "project_file": str(project_file.relative_to(repo)),
            "status": "quality_gate_failed",
            "errors": quality["blocking_reasons"],
            "quality_gate": quality,
            "quality_report_paths": [str(path.relative_to(repo)) for path in quality_paths],
        }

    export_dir, manifest = export_project(repo, project_path, data)
    if manifest["chapter_count"] <= 0:
        return {
            "project_file": str(project_file.relative_to(repo)),
            "status": "invalid",
            "errors": ["no chapters exported for upload_range"],
        }

    account = data["fanqie_account"]
    port = ACCOUNT_PORTS[account]
    book_id = str(data["fanqie_book_id"])
    expected = str(data["expected_author_name"])
    from_chapter = manifest["from_chapter"]
    to_chapter = manifest["to_chapter"]

    base = [
        "node",
        str(FANQIE_UPLOAD),
    ]
    scan = run_command([
        *base,
        "scan",
        "--book",
        str(export_dir),
        "--from",
        str(from_chapter),
        "--to",
        str(to_chapter),
    ], execute)
    if execute and scan["status"] != "ok":
        return {"project_file": str(project_file.relative_to(repo)), "status": "scan_failed", "export_dir": str(export_dir), "scan": scan}

    drafts = run_command([
        *base,
        "drafts",
        "--book",
        str(export_dir),
        "--book-id",
        book_id,
        "--port",
        str(port),
        "--expected-account",
        expected,
        "--from",
        str(from_chapter),
        "--to",
        str(to_chapter),
    ], execute)
    if execute and drafts["status"] != "ok":
        return {
            "project_file": str(project_file.relative_to(repo)),
            "status": "draft_upload_failed",
            "export_dir": str(export_dir),
            "scan": scan,
            "drafts": drafts,
        }

    verify = run_command([
        *base,
        "verify",
        "--book",
        str(export_dir),
        "--book-id",
        book_id,
        "--port",
        str(port),
        "--expected-account",
        expected,
        "--from",
        str(from_chapter),
        "--to",
        str(to_chapter),
    ], execute)

    status = "dry_run" if not execute else ("uploaded_to_drafts" if verify["status"] == "ok" else "verify_failed")
    if execute and status == "uploaded_to_drafts":
        data["upload_status"] = "uploaded_to_drafts"
        data["last_upload"] = {
            "uploaded_at": now_iso(),
            "export_dir": str(export_dir),
            "from_chapter": from_chapter,
            "to_chapter": to_chapter,
        }
        write_json(project_file, data)
    return {
        "project_file": str(project_file.relative_to(repo)),
        "status": status,
        "export_dir": str(export_dir),
        "chapter_count": manifest["chapter_count"],
        "quality_gate": quality,
        "quality_report_paths": [str(path.relative_to(repo)) for path in quality_paths],
        "scan": scan,
        "drafts": drafts,
        "verify": verify,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload Git-ready web novel projects to Fanqie drafts.")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--git-commit", action="store_true", help="Commit upload status updates after successful upload.")
    parser.add_argument("--git-push", action="store_true", help="Push committed upload status updates to origin/main.")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        print(f"not a Git repository: {repo}", file=sys.stderr)
        return 2
    candidates = []
    for project_file in sorted((repo / "novels").glob("*/00_PROJECT.json")):
        try:
            data = load_json(project_file)
        except Exception:
            continue
        if data.get("auto_upload_to_drafts") is True and data.get("upload_status") == "ready_for_draft_upload":
            candidates.append(project_file)

    selected = candidates[: max(1, args.limit)]
    results = [process_candidate(repo, path, args.execute) for path in selected]
    failed = [item for item in results if item["status"] not in {"dry_run", "uploaded_to_drafts"}]
    git_result = None
    if args.execute and args.git_commit:
        updated = [
            repo / item["project_file"]
            for item in results
            if item["status"] == "uploaded_to_drafts"
        ]
        for item in results:
            for report in item.get("quality_report_paths", []):
                updated.append(repo / report)
        git_result = safe_git_record(repo, updated, f"upload: mark Fanqie drafts uploaded {now_iso()}", args.git_push)
    output = {"execute": args.execute, "processed": results, "failed_count": len(failed), "git": git_result}
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        mode = "execute" if args.execute else "dry-run"
        print(f"upload worker {mode}: processed={len(results)} failed={len(failed)}")
        for item in results:
            print(f"- {item['project_file']}: {item['status']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
