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
FANQIE_BROWSER_LEASE = Path("/home/admin/ai/scripts/fanqie-browser-lease.sh")

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


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def chapter_number(value: Any) -> int:
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else 0


def project_formal_dir(project_path: Path) -> Path:
    layout_path = project_path / "工程元数据" / "PROJECT_LAYOUT.json"
    if layout_path.exists():
        layout = load_json(layout_path)
        formal_dir = project_path / str(layout.get("formal_dir") or "")
        if formal_dir.exists():
            return formal_dir
    return project_path / "formal"


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
    if not project_formal_dir(project_path).exists():
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
    for source in sorted(project_formal_dir(project_path).glob("*.md")):
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
    matches = sorted(path for path in project_formal_dir(project_path).glob("*.md") if chapter_no_from_name(path) == no)
    return matches[0] if len(matches) == 1 else None


def strong_qa_for_blob(project_path: Path, digest: str, blob_sha: str) -> Path | None:
    for path in reversed(sorted((project_path / "audits").glob("CHAPTER_STRONG_QA_*.md"))):
        text = path.read_text(encoding="utf-8")
        if digest in text and blob_sha in text and "NO_EFFECTIVE_ISSUE" in text:
            return path
    return None


def evaluate_pending_web_machine_gates(repo: Path, execute: bool) -> list[dict[str, Any]]:
    """Run current-blob P0 for web chapters that explicitly await the server.

    This phase never uploads and never applies semantic state deltas. It only
    turns a committed web candidate into machine PASS/FAIL evidence and routes
    the next web session to either repair or state application.
    """
    updates: list[dict[str, Any]] = []
    current_path = repo / "CURRENT.json"
    current = load_json(current_path) if current_path.exists() else {}
    for project_file in sorted((repo / "novels").glob("*/00_PROJECT.json")):
        try:
            data = load_json(project_file)
        except Exception:
            continue
        if data.get("next_action") != "SERVER_RUN_MACHINE_P0_FOR_CH003_CURRENT_BLOB" and not str(data.get("next_action") or "").startswith("SERVER_RUN_MACHINE_P0_FOR_CH"):
            continue
        project_path = project_file.parent
        no = chapter_number(data.get("pending_machine_gate", {}).get("chapter"))
        if no <= 0:
            no = chapter_number(data.get("formal_until")) + 1
        chapter = f"CH{no:03d}"
        formal_path = formal_chapter_file(project_path, no)
        transaction_path = project_path / "提交事务" / f"COMMIT_{chapter}_R1.json"
        ledger_path = project_path / "章节事实账本" / f"{chapter}.json"
        if formal_path is None or not transaction_path.exists() or not ledger_path.exists():
            continue
        transaction = load_json(transaction_path)
        if transaction.get("status") not in {"FORMAL_WRITTEN", "FORMAL_WRITTEN_PENDING_MACHINE_P0"}:
            continue
        digest = file_sha256(formal_path)
        blob_sha = git_blob_sha(formal_path, repo)
        machine = transaction.get("machine_p0") if isinstance(transaction.get("machine_p0"), dict) else {}
        if machine.get("formal_git_blob_sha") == blob_sha and machine.get("result") in {"PASS", "FAIL"}:
            continue

        available = [
            n for n in (chapter_no_from_name(path) for path in project_formal_dir(project_path).glob("*.md"))
            if n is not None
        ]
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        p0_path = project_path / "audits" / f"SERVER_WEB_P0_{chapter}_{stamp}.json"
        ready_path = project_path / "audits" / f"SERVER_WEB_READY_{chapter}_{stamp}.json"
        errors: list[str] = []
        if han_count(formal_path.read_text(encoding="utf-8")) < 2500:
            errors.append("chapter has fewer than 2500 Chinese Han characters")
        p0_result = None
        ready_result = None
        if not errors:
            p0_result = run_repo_script(repo, [
                sys.executable,
                str(repo / "scripts" / "p0_dialogue_visual_hard_gate_v2.py"),
                "--formal-dir", str(project_formal_dir(project_path).relative_to(repo)),
                "--reference-from", "1",
                "--reference-to", str(max(available)),
                "--target-from", str(no),
                "--target-to", str(no),
                "--output-json", str(p0_path.relative_to(repo)),
            ]) if execute else {"status": "dry_run"}
            if execute and p0_result["status"] != "ok":
                errors.append("machine P0 failed")
        if execute and not errors:
            ready_result = run_repo_script(repo, [
                sys.executable,
                str(repo / "scripts" / "validate_ready_promotion_v22.py"),
                "--formal-dir", str(project_formal_dir(project_path).relative_to(repo)),
                "--p0-manifest", str(p0_path.relative_to(repo)),
                "--from-chapter", str(no),
                "--to-chapter", str(no),
                "--output-json", str(ready_path.relative_to(repo)),
            ])
            if ready_result["status"] != "ok":
                errors.append("READY current-blob validation failed")

        passed = execute and not errors
        changed_paths = [p for p in [p0_path, ready_path] if p.exists()]
        if execute:
            qa_path = strong_qa_for_blob(project_path, digest, blob_sha)
            result = "PASS" if passed else "FAIL"
            transaction["status"] = "MACHINE_P0_PASSED" if passed else "FORMAL_WRITTEN_PENDING_MACHINE_P0"
            transaction["qa_result"] = "PASS" if passed and qa_path else ("PENDING_MACHINE_P0" if passed else "FAIL")
            transaction["machine_p0"] = {
                "result": result,
                "formal_git_blob_sha": blob_sha,
                "manifest_path": str(p0_path.relative_to(project_path)),
                "ready_manifest_path": str(ready_path.relative_to(project_path)) if ready_path.exists() else "",
                "strong_qa_path": str(qa_path.relative_to(project_path)) if qa_path else "",
                "validation_required": False,
                "blocking_reasons": errors,
            }
            write_json(transaction_path, transaction)
            ledger = load_json(ledger_path)
            ledger["qa_result"] = "PASS" if passed and qa_path else ("PENDING_MACHINE_P0" if passed else "FAIL")
            write_json(ledger_path, ledger)
            if passed and qa_path:
                next_action = "WEB_APPLY_CHAPTER_STATE_AND_CLOSE_TRANSACTION"
            elif passed:
                next_action = "WEB_COMPLETE_STRONG_QA_AND_APPLY_CHAPTER_STATE"
            else:
                next_action = "WEB_REVISE_CHAPTER_FROM_MACHINE_P0_FAILURE"
            status = f"{chapter}_MACHINE_P0_PASSED_WEB_STATE_APPLY_REQUIRED" if passed else f"{chapter}_MACHINE_P0_FAILED_WEB_REPAIR_REQUIRED"
            data["project_status"] = status
            data["next_action"] = next_action
            data["auto_upload_to_drafts"] = False
            data["upload_status"] = "not_ready_machine_p0_passed_state_pending" if passed else "not_ready_machine_p0_failed"
            data["pending_machine_gate"] = {
                "chapter": chapter,
                "result": result,
                "formal_utf8_sha256": digest,
                "formal_git_blob_sha": blob_sha,
                "manifest_path": str(p0_path.relative_to(project_path)),
                "ready_manifest_path": str(ready_path.relative_to(project_path)) if ready_path.exists() else "",
                "strong_qa_path": str(qa_path.relative_to(project_path)) if qa_path else "",
                "repair_required": not passed,
                "server_validation_required": False,
            }
            data["updated_at"] = now_iso()
            write_json(project_file, data)
            project_rel = str(project_path.relative_to(repo))
            record = current.get("novels", {}).get(data.get("book_id")) if isinstance(current, dict) else None
            if isinstance(record, dict):
                record["status"] = status
                record["next_action"] = next_action
            task = current.get("current_task") if isinstance(current, dict) else None
            if isinstance(task, dict) and task.get("project_path") == project_rel:
                task["phase"] = status
                task["next_action"] = next_action
            if isinstance(current, dict):
                current["updated_at"] = now_iso()
                write_json(current_path, current)
            changed_paths.extend([transaction_path, ledger_path, project_file, current_path])
        updates.append({
            "project_file": str(project_file.relative_to(repo)),
            "chapter": chapter,
            "status": "passed" if passed else ("failed" if execute else "pending_dry_run"),
            "errors": errors,
            "p0": p0_result,
            "ready": ready_result,
            "paths": [str(path.relative_to(repo)) for path in changed_paths if path.exists()],
        })
    return updates


def recoverable_formal_evidence(project_path: Path, no: int, formal_path: Path) -> tuple[bool, dict[str, Any]]:
    """Accept only a web formal chapter whose committed evidence matches its bytes.

    This is the interruption-recovery path.  It deliberately does not infer
    quality from the existence of a Markdown file: the web transaction must
    already have produced matching content-gate, strong-QA and chapter-ledger
    evidence before a server can restore the missing project-state commit.
    """
    chapter = f"CH{no:03d}"
    digest = file_sha256(formal_path)
    blob_sha = git_blob_sha(formal_path, project_path.parents[1])
    transaction_path = project_path / "提交事务" / f"COMMIT_{chapter}_R1.json"
    ledger_path = project_path / "章节事实账本" / f"{chapter}.json"
    if not transaction_path.exists() or not ledger_path.exists():
        return False, {"reason": "transaction_or_sharded_ledger_missing", "formal_sha256": digest}
    transaction = load_json(transaction_path)
    ledger = load_json(ledger_path)
    if transaction.get("state_applied") is not True or transaction.get("status") not in {"STATE_APPLIED", "ROUTE_UPDATED"}:
        return False, {"reason": "semantic_state_not_applied", "formal_sha256": digest}
    if transaction.get("formal_utf8_sha256") != digest or ledger.get("formal_utf8_sha256") != digest:
        return False, {"reason": "formal_hash_mismatch", "formal_sha256": digest}
    machine = transaction.get("machine_p0") if isinstance(transaction.get("machine_p0"), dict) else {}
    if machine.get("result") != "PASS" or machine.get("formal_git_blob_sha") != blob_sha:
        return False, {"reason": "current_blob_machine_p0_missing", "formal_sha256": digest}
    if ledger.get("qa_result") != "PASS":
        return False, {"reason": "chapter_ledger_not_passed", "formal_sha256": digest}
    qa_path = project_path / str(machine.get("strong_qa_path") or "")
    p0_path = project_path / str(machine.get("manifest_path") or "")
    ready_path = project_path / str(machine.get("ready_manifest_path") or "")
    if not qa_path.is_file() or not p0_path.is_file() or not ready_path.is_file():
        return False, {"reason": "machine_or_strong_qa_evidence_missing", "formal_sha256": digest}
    return True, {
        "formal_sha256": digest,
        "content_gate_path": qa_path,
        "qa_path": qa_path,
        "ledger_path": ledger_path,
        "hanzi_count": han_count(formal_path.read_text(encoding="utf-8")),
    }


def recover_interrupted_web_transactions(repo: Path, execute: bool) -> list[dict[str, Any]]:
    """Restore a state commit after a web conversation ended between commits.

    The recovery is intentionally narrow: it only advances one consecutive
    formal chapter, uses byte-matching evidence, and never publishes.  In
    review-mode projects a human-review requirement remains authoritative.
    """
    updates: list[dict[str, Any]] = []
    for project_file in sorted((repo / "novels").glob("*/00_PROJECT.json")):
        try:
            data = load_json(project_file)
        except Exception:
            continue
        project_path = project_file.parent
        previous = chapter_number(data.get("formal_until"))
        no = previous + 1
        formal_path = formal_chapter_file(project_path, no)
        if formal_path is None:
            continue
        valid, evidence = recoverable_formal_evidence(project_path, no, formal_path)
        if not valid:
            continue
        chapter = f"CH{no:03d}"
        recovery_path = project_path / "证据" / f"{chapter}_SERVER_TRANSACTION_RECOVERY.json"
        payload = {
            "recovery_id": f"SERVER_TRANSACTION_RECOVERY_{chapter}",
            "reason": "web_formal_and_evidence_committed_before_project_state",
            "recovered_at": now_iso(),
            "chapter": chapter,
            "formal_path": str(formal_path.relative_to(repo)),
            "formal_sha256": evidence["formal_sha256"],
            "content_gate_path": str(evidence["content_gate_path"].relative_to(repo)),
            "qa_path": str(evidence["qa_path"].relative_to(repo)),
            "ledger_path": str(evidence["ledger_path"].relative_to(repo)),
            "hanzi_count": evidence.get("hanzi_count"),
            "result": "PASS",
        }
        changed_paths = [recovery_path, project_file]
        if execute:
            write_json(recovery_path, payload)
            data["formal_until"] = no
            data["formal_text_created"] = True
            data["project_status"] = f"{chapter}_FORMAL_QA_RECOVERED"
            data["next_action"] = f"SERVER_UPLOAD_{chapter}_DRAFTS"
            ready = data.setdefault("ready_evidence", {})
            ready["qa_passed"] = True
            ready["current_blob_validated"] = True
            review_required = ready.get("human_review_required") is True
            if review_required and ready.get("human_review_status") != "approved":
                data["auto_upload_to_drafts"] = False
                data["upload_status"] = "awaiting_human_review"
            else:
                data["auto_upload_to_drafts"] = True
                data["upload_status"] = "ready_for_draft_upload"
                data["upload_range"] = {"from_chapter": no, "to_chapter": no}
            data["last_transaction_recovery"] = payload
            data["updated_at"] = now_iso()
            write_json(project_file, data)
            current_path = repo / "CURRENT.json"
            if current_path.exists():
                current = load_json(current_path)
                record = current.get("novels", {}).get(data.get("book_id"))
                if isinstance(record, dict):
                    record["status"] = data["project_status"]
                    record["formal_until"] = no
                    record["next_action"] = data["next_action"]
                task = current.get("current_task")
                if isinstance(task, dict) and task.get("project_path") == str(project_path.relative_to(repo)):
                    task["phase"] = data["project_status"]
                    task["formal_until"] = no
                    task["next_action"] = data["next_action"]
                current["updated_at"] = now_iso()
                write_json(current_path, current)
                changed_paths.append(current_path)
        updates.append({
            "project_file": str(project_file.relative_to(repo)),
            "chapter": chapter,
            "status": "recovered" if execute else "recoverable",
            "paths": [str(path.relative_to(repo)) for path in changed_paths if path.exists()],
            "evidence": payload,
        })
    return updates


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


def run_canonical_upload_quality(repo: Path, project_path: Path, data: dict[str, Any], execute: bool) -> tuple[bool, dict[str, Any], list[Path]]:
    """Revalidate upload range from the 2.2-LTS exact-blob registry.

    This path deliberately does not accept writer-created booleans or invoke
    the legacy formal/CHxxx validators.  A layout manifest opts a project in.
    """
    upload_range = data.get("upload_range") if isinstance(data.get("upload_range"), dict) else {}
    start = int(upload_range.get("from_chapter") or 1)
    end = int(upload_range.get("to_chapter") or 0)
    out_dir = quality_output_dir(repo, project_path, execute)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output = out_dir / f"SERVER_UPLOAD_CANONICAL_READY_CH{start:03d}_CH{end:03d}_{stamp}.json"
    summary_path = out_dir / f"SERVER_UPLOAD_CANONICAL_GATE_CH{start:03d}_CH{end:03d}_{stamp}.json"
    errors: list[str] = []
    result: dict[str, Any] | None = None
    if end < start:
        errors.append("upload_range is missing or invalid")
    else:
        command = [
            sys.executable, str(repo / "scripts" / "novel_quality_runtime" / "validate_ready_promotion_holistic.py"),
            "--project-dir", str(project_path.relative_to(repo)),
            "--from-chapter", str(start), "--to-chapter", str(end),
            "--output-json", str(output.relative_to(repo) if execute else output),
        ]
        result = run_repo_script(repo, command) if execute else {"status": "dry_run", "command": command}
        if execute:
            if result["status"] != "ok" or not output.exists():
                errors.append("canonical holistic READY validation failed to execute")
            else:
                payload = load_json(output)
                if payload.get("promotion_result") != "PASS" or payload.get("ready_after_strong_qa_allowed") is not True:
                    errors.append("canonical holistic READY validation did not pass")
    summary = {
        "gate": "SERVER_UPLOAD_CANONICAL_QUALITY_GATE_V1",
        "checked_at": now_iso(),
        "project": str(project_path.relative_to(repo)),
        "upload_range": {"from_chapter": start, "to_chapter": end},
        "result": "PASS" if not errors else "FAIL",
        "blocking_reasons": errors,
        "canonical_ready_output": str(output),
        "canonical_command": result,
        "trusts_free_ready_booleans": False,
    }
    write_json(summary_path, summary)
    changed = [p for p in [output, summary_path] if p.exists() and p.is_relative_to(repo)]
    return not errors, summary, changed


def run_quality_gate(repo: Path, project_path: Path, data: dict[str, Any], execute: bool) -> tuple[bool, dict[str, Any], list[Path]]:
    if (project_path / "工程元数据" / "PROJECT_LAYOUT.json").exists():
        return run_canonical_upload_quality(repo, project_path, data, execute)
    upload_range = data.get("upload_range") if isinstance(data.get("upload_range"), dict) else {}
    from_chapter = int(upload_range.get("from_chapter") or 1)
    to_chapter = int(upload_range.get("to_chapter") or 999999)
    formal = project_formal_dir(project_path)
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

    drafts_command = [
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
    ]
    # The host has room for only one full browser.  The lease serializes
    # Fanqie uploads with the web ChatGPT browser and restores the latter when
    # the account operation is complete.
    if execute:
        drafts_command = [str(FANQIE_BROWSER_LEASE), "run", account, str(port), *drafts_command]
    drafts = run_command(drafts_command, execute)
    if execute and drafts["status"] != "ok":
        return {
            "project_file": str(project_file.relative_to(repo)),
            "status": "draft_upload_failed",
            "export_dir": str(export_dir),
            "scan": scan,
            "drafts": drafts,
        }

    verify_command = [
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
    ]
    if execute:
        verify_command = [str(FANQIE_BROWSER_LEASE), "run", account, str(port), *verify_command]
    verify = run_command(verify_command, execute)

    status = "dry_run" if not execute else ("uploaded_to_drafts" if verify["status"] == "ok" else "verify_failed")
    state_paths: list[Path] = []
    if execute and status == "uploaded_to_drafts":
        uploaded_status = f"CH{to_chapter:03d}_UPLOADED_TO_DRAFTS"
        next_action = f"CONTINUE_NOVEL_FROM_CH{to_chapter + 1:03d}"
        current_path = repo / "CURRENT.json"
        current = load_json(current_path) if current_path.exists() else None
        if isinstance(current, dict):
            current_task = current.get("current_task")
            if (
                isinstance(current_task, dict)
                and current_task.get("project_path") == str(project_file.parent.relative_to(repo))
                and current_task.get("type") == "WEB_SERVER_E2E_MALE_HAREM_NOVEL_PRODUCTION_TEST"
                and to_chapter == 2
            ):
                uploaded_status = "CH002_UPLOADED_TO_DRAFTS_READY_FOR_WEB_CH003"
                next_action = "WEB_NEW_CHAT_RESUME_AND_WRITE_CH003"
            elif (
                isinstance(current_task, dict)
                and current_task.get("project_path") == str(project_file.parent.relative_to(repo))
                and current_task.get("type") == "WEB_SERVER_E2E_MALE_HAREM_NOVEL_PRODUCTION_TEST"
                and to_chapter == 3
            ):
                uploaded_status = "CH003_UPLOADED_TO_DRAFTS_E2E_COMPLETE"
                next_action = "CONTINUE_NOVEL_FROM_CH004"
        data["auto_upload_to_drafts"] = False
        data["upload_status"] = "uploaded_to_drafts"
        data["project_status"] = uploaded_status
        data["next_action"] = next_action
        data["updated_at"] = now_iso()
        data["last_upload"] = {
            "uploaded_at": now_iso(),
            "export_dir": str(export_dir),
            "from_chapter": from_chapter,
            "to_chapter": to_chapter,
        }
        write_json(project_file, data)
        state_paths.append(project_file)
        if isinstance(current, dict):
            project_rel = str(project_file.parent.relative_to(repo))
            novels = current.get("novels")
            if isinstance(novels, dict):
                for novel in novels.values():
                    if isinstance(novel, dict) and novel.get("project_path") == project_rel:
                        novel["status"] = uploaded_status
                        novel["formal_until"] = max(int(novel.get("formal_until") or 0), to_chapter)
                        novel["next_action"] = next_action
            current_task = current.get("current_task")
            if isinstance(current_task, dict) and current_task.get("project_path") == project_rel:
                current_task["phase"] = uploaded_status
                current_task["status"] = "COMPLETED" if uploaded_status.endswith("E2E_COMPLETE") else uploaded_status
                current_task["upload_status"] = "uploaded_to_drafts"
                current_task["formal_until"] = max(int(current_task.get("formal_until") or 0), to_chapter)
                current_task["next_action"] = next_action
            short_command = current.get("short_command_protocol")
            if isinstance(short_command, dict) and uploaded_status.endswith("E2E_COMPLETE"):
                short_command["current_required_terminal_state"] = uploaded_status
            current["updated_at"] = now_iso()
            write_json(current_path, current)
            state_paths.append(current_path)
    return {
        "project_file": str(project_file.relative_to(repo)),
        "status": status,
        "export_dir": str(export_dir),
        "chapter_count": manifest["chapter_count"],
        "quality_gate": quality,
        "quality_report_paths": [str(path.relative_to(repo)) for path in quality_paths],
        "state_paths": [str(path.relative_to(repo)) for path in state_paths],
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
    machine_gate_updates = evaluate_pending_web_machine_gates(repo, args.execute)
    recovery_updates = recover_interrupted_web_transactions(repo, args.execute)
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
            updated.extend(repo / path for path in item.get("state_paths", []))
        for recovery in recovery_updates:
            updated.extend(repo / path for path in recovery.get("paths", []))
        for machine_gate in machine_gate_updates:
            updated.extend(repo / path for path in machine_gate.get("paths", []))
        for item in results:
            for report in item.get("quality_report_paths", []):
                updated.append(repo / report)
        git_result = safe_git_record(repo, updated, f"upload: mark Fanqie drafts uploaded {now_iso()}", args.git_push)
    output = {
        "execute": args.execute,
        "machine_gates": machine_gate_updates,
        "recovery": recovery_updates,
        "processed": results,
        "failed_count": len(failed),
        "git": git_result,
    }
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
