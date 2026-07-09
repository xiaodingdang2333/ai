#!/usr/bin/env python3
"""Process Git sample requests for the ChatGPT novel workflow.

This worker is deliberately conservative:

- dry-run by default
- no old custom GPT Action service
- no automatic acquisition without an explicit allowed legal basis
- optional server Codex deep teardown is recorded as a TODO unless the caller
  runs a separate human-approved Codex job on the generated packet
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPO = Path("/home/admin/chatgpt-novel-production-system")
SONOVEL_CLIENT = Path("/home/admin/ai/scripts/sonovel-client.js")

ALLOWED_BASES = {
    "public_domain",
    "open_license",
    "official_download",
    "user_authorized_material",
    "automation_allowed",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def safe_slug(value: str, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return (cleaned[:80] or fallback)


def legal_basis_for(request: dict[str, Any], book: dict[str, Any]) -> tuple[str, bool]:
    basis = book.get("legal_access_basis") or request.get("legal_access_basis") or "unknown"
    allowed = bool(book.get("automation_allowed", request.get("automation_allowed", False)))
    return str(basis), allowed


def run_packet(book: dict[str, Any], timeout_seconds: int) -> tuple[bool, str]:
    title = str(book.get("title") or "")
    author = str(book.get("author") or "")
    command = ["node", str(SONOVEL_CLIENT), "packet", title, author]
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return False, f"single book packet timed out after {timeout_seconds}s"
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode == 0:
        return True, output
    return False, error or output or f"packet command failed with exit {result.returncode}"


def status_for_request(request: dict[str, Any], request_path: Path, repo: Path, execute: bool, timeout_seconds: int) -> dict[str, Any]:
    request_id = str(request.get("request_id") or request_path.stem)
    result_dir = repo / "sample-results" / request_id
    packet_dir = result_dir / "packets"
    books = request.get("books") if isinstance(request.get("books"), list) else []
    status_books: list[dict[str, Any]] = []
    effective = 0

    for index, book in enumerate(books, 1):
        if not isinstance(book, dict):
            continue
        title = str(book.get("title") or "")
        author = str(book.get("author") or "")
        basis, automation_allowed = legal_basis_for(request, book)
        base_record = {
            "title": title,
            "author": author,
            "legal_access_status": basis,
            "identity_confidence": book.get("identity_confidence", "unknown"),
        }
        if basis not in ALLOWED_BASES or not automation_allowed:
            status_books.append({
                **base_record,
                "acquisition_status": "manual_required",
                "quality_status": "unchecked",
                "failure_reason": "MANUAL_MATERIAL_REQUIRED: no explicit allowed automated acquisition basis",
            })
            continue

        if not execute:
            status_books.append({
                **base_record,
                "acquisition_status": "pending",
                "quality_status": "unchecked",
                "failure_reason": "dry-run: packet command not executed",
            })
            continue

        ok, output = run_packet(book, timeout_seconds)
        if ok:
            packet_dir.mkdir(parents=True, exist_ok=True)
            packet_path = packet_dir / f"{index:03d}_{safe_slug(title, 'book')}.txt"
            packet_path.write_text(output + "\n", encoding="utf-8")
            effective += 1
            status_books.append({
                **base_record,
                "acquisition_status": "packet_ready",
                "quality_status": "effective",
                "packet_path": str(packet_path.relative_to(repo)),
            })
        else:
            status_books.append({
                **base_record,
                "acquisition_status": "failed",
                "quality_status": "failed",
                "failure_reason": output[:1000],
            })

    status = "completed" if effective else "manual_material_required"
    if any(item["acquisition_status"] == "failed" for item in status_books):
        status = "partially_completed" if effective else "failed"

    result = {
        "schema_version": "1.0",
        "request_id": request_id,
        "status": status if execute else "running",
        "updated_at": now_iso(),
        "effective_sample_count": effective,
        "packet_dir": str(packet_dir.relative_to(repo)),
        "books": status_books,
        "dry_run": not execute,
    }

    if request.get("analysis_engine") == "server_codex" and request.get("allow_codex") is True:
        result["server_codex_deep_teardown"] = {
            "requested": True,
            "status": "todo_after_packet_ready" if effective else "blocked_no_effective_packet",
            "scope": request.get("codex_scope"),
        }
        if execute:
            todo = result_dir / "SERVER_CODEX_DEEP_TEARDOWN_TODO.md"
            todo.write_text(
                "# Server Codex Deep Teardown TODO\n\n"
                f"- request_id: `{request_id}`\n"
                "- scope: `packet_deep_teardown`\n"
                "- Input: packet files generated by this request.\n"
                "- Rule: extract functional structure only; do not reproduce source prose.\n",
                encoding="utf-8",
            )

    return result


def process_requests(repo: Path, execute: bool, limit: int, timeout_seconds: int, git_commit: bool, git_push: bool) -> dict[str, Any]:
    pending = repo / "sample-requests" / "pending"
    processed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    changed_paths: list[Path] = []
    for request_path in sorted(pending.glob("*.json"))[:limit]:
        try:
            request = load_json(request_path)
            if request.get("status") not in {"pending", "failed"}:
                continue
            result = status_for_request(request, request_path, repo, execute, timeout_seconds)
            if execute:
                request["status"] = "completed" if result["status"] == "completed" else result["status"]
                request["updated_at"] = now_iso()
                write_json(request_path, request)
                status_path = repo / "sample-results" / result["request_id"] / "status.json"
                write_json(status_path, result)
                changed_paths.extend([request_path, status_path])
                result_dir = repo / "sample-results" / result["request_id"]
                if result_dir.exists():
                    changed_paths.extend(path for path in result_dir.rglob("*") if path.is_file())
            processed.append({
                "request_path": str(request_path.relative_to(repo)),
                "request_id": result["request_id"],
                "status": result["status"],
                "effective_sample_count": result["effective_sample_count"],
                "dry_run": not execute,
            })
        except Exception as exc:  # noqa: BLE001 - worker should continue other requests.
            errors.append({"path": str(request_path), "error": str(exc)})
    git_result = None
    if execute and git_commit:
        stamp = int(time.time())
        git_result = safe_git_record(repo, changed_paths, f"samples: process request batch {stamp}", git_push)
    return {"processed": processed, "errors": errors, "execute": execute, "git": git_result}


def main() -> int:
    parser = argparse.ArgumentParser(description="Process Git sample requests.")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--execute", action="store_true", help="Write status files and run packet acquisition.")
    parser.add_argument("--git-commit", action="store_true", help="Commit generated sample status/result files.")
    parser.add_argument("--git-push", action="store_true", help="Push committed sample result changes to origin/main.")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        print(f"not a Git repository: {repo}", file=sys.stderr)
        return 2
    result = process_requests(repo, args.execute, max(1, args.limit), max(5, args.timeout_seconds), args.git_commit, args.git_push)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        mode = "execute" if args.execute else "dry-run"
        print(f"sample worker {mode}: processed={len(result['processed'])} errors={len(result['errors'])}")
        for item in result["processed"]:
            print(f"- {item['request_id']}: {item['status']} effective={item['effective_sample_count']}")
        for error in result["errors"]:
            print(f"! {error['path']}: {error['error']}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
