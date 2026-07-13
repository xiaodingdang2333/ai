#!/usr/bin/env python3
"""Scan the ChatGPT novel workflow repository for server-side jobs.

This is the server entry point for the Git-based workflow. It does not use the
deprecated custom GPT Action service.

Default behavior is read-only. Use a scheduler to run this frequently; expensive
download/upload work should only start when new queue files are detected.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_REPO = Path("/home/admin/chatgpt-novel-production-system-runtime")

ACCOUNT_AUTHORS = {
    "account-a": "西大水怪",
    "account-b": "桃枝醒醒",
    "account-c": "泡芙软呼呼",
}


@dataclass
class ScanError:
    path: str
    error: str


def load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - CLI should report exact bad file.
        return None, str(exc)
    if not isinstance(data, dict):
        return None, "top-level JSON value must be an object"
    return data, None


def run_git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def fetch_if_requested(repo: Path, fetch: bool) -> dict[str, str]:
    info = {
        "repo": str(repo),
        "head": run_git(repo, ["rev-parse", "HEAD"]),
        "branch": run_git(repo, ["branch", "--show-current"]),
    }
    if fetch:
        run_git(repo, ["fetch", "origin", "--prune"])
        info["origin_main"] = run_git(repo, ["rev-parse", "origin/main"])
        info["after_fetch_head"] = run_git(repo, ["rev-parse", "HEAD"])
        status = run_git(repo, ["status", "--porcelain"])
        behind = int(run_git(repo, ["rev-list", "--count", "HEAD..origin/main"]) or "0")
        ahead = int(run_git(repo, ["rev-list", "--count", "origin/main..HEAD"]) or "0")
        info["behind_origin_main"] = str(behind)
        info["ahead_origin_main"] = str(ahead)
        if behind and not ahead and not status:
            run_git(repo, ["merge", "--ff-only", "origin/main"])
            info["fast_forwarded_to"] = run_git(repo, ["rev-parse", "HEAD"])
        elif behind:
            info["fast_forward_skipped"] = "local changes or local commits present"
    return info


def scan_sample_jobs(repo: Path, errors: list[ScanError]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    pending = repo / "sample-requests" / "pending"
    if not pending.exists():
        return jobs
    for path in sorted(pending.glob("*.json")):
        data, err = load_json(path)
        if err:
            errors.append(ScanError(str(path), err))
            continue
        status = data.get("status")
        if status not in {"pending", "failed"}:
            continue
        books = data.get("books")
        if not isinstance(books, list):
            errors.append(ScanError(str(path), "books must be an array"))
            continue
        codex_requested = (
            data.get("analysis_engine") == "server_codex"
            and data.get("allow_codex") is True
            and data.get("codex_scope") == "packet_deep_teardown"
        )
        jobs.append(
            {
                "request_path": str(path.relative_to(repo)),
                "request_id": data.get("request_id"),
                "status": status,
                "genre": data.get("genre"),
                "target_platform": data.get("target_platform"),
                "min_effective_samples": data.get("min_effective_samples"),
                "max_attempts": data.get("max_attempts"),
                "codex_deep_teardown_requested": codex_requested,
                "books": [
                    {
                        "title": book.get("title"),
                        "author": book.get("author"),
                        "channel": book.get("channel"),
                        "identity_confidence": book.get("identity_confidence"),
                    }
                    for book in books
                    if isinstance(book, dict)
                ],
            }
        )
    return jobs


def upload_candidate_from_project(repo: Path, path: Path, errors: list[ScanError]) -> dict[str, Any] | None:
    data, err = load_json(path)
    if err:
        errors.append(ScanError(str(path), err))
        return None
    if data.get("auto_upload_to_drafts") is not True:
        return None
    if data.get("upload_status") != "ready_for_draft_upload":
        return None

    account = data.get("fanqie_account")
    expected_author = data.get("expected_author_name")
    if account not in ACCOUNT_AUTHORS:
        errors.append(ScanError(str(path), f"invalid fanqie_account: {account!r}"))
        return None
    if expected_author != ACCOUNT_AUTHORS[account]:
        errors.append(
            ScanError(str(path), f"expected_author_name must be {ACCOUNT_AUTHORS[account]!r} for {account}")
        )
        return None

    evidence = data.get("ready_evidence")
    if not isinstance(evidence, dict):
        errors.append(ScanError(str(path), "ready_evidence is required"))
        return None
    if evidence.get("qa_passed") is not True or evidence.get("current_blob_validated") is not True:
        errors.append(ScanError(str(path), "qa_passed and current_blob_validated must both be true"))
        return None
    if evidence.get("human_review_required") is True and evidence.get("human_review_status") != "approved":
        errors.append(ScanError(str(path), "human review is required but not approved"))
        return None

    upload_range = data.get("upload_range") if isinstance(data.get("upload_range"), dict) else {}
    return {
        "project_path": str(path.parent.relative_to(repo)),
        "project_file": str(path.relative_to(repo)),
        "book_id": data.get("book_id"),
        "book_title": data.get("book_title"),
        "fanqie_account": account,
        "expected_author_name": expected_author,
        "fanqie_book_id": data.get("fanqie_book_id"),
        "ai_use": data.get("ai_use"),
        "from_chapter": upload_range.get("from_chapter"),
        "to_chapter": upload_range.get("to_chapter"),
    }


def scan_upload_candidates(repo: Path, errors: list[ScanError]) -> list[dict[str, Any]]:
    novels = repo / "novels"
    if not novels.exists():
        return []
    candidates: list[dict[str, Any]] = []
    for path in sorted(novels.glob("*/00_PROJECT.json")):
        candidate = upload_candidate_from_project(repo, path, errors)
        if candidate:
            candidates.append(candidate)
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan web novel Git repository for server jobs.")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--fetch", action="store_true", help="Fetch origin before scanning.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON. Without this, a short human summary is printed.",
    )
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        print(f"not a Git repository: {repo}", file=sys.stderr)
        return 2

    errors: list[ScanError] = []
    try:
        git_info = fetch_if_requested(repo, args.fetch)
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or str(exc), file=sys.stderr)
        return 2

    sample_jobs = scan_sample_jobs(repo, errors)
    upload_candidates = scan_upload_candidates(repo, errors)

    result = {
        "git": git_info,
        "sample_jobs": sample_jobs,
        "upload_candidates": upload_candidates,
        "errors": [error.__dict__ for error in errors],
        "summary": {
            "sample_job_count": len(sample_jobs),
            "upload_candidate_count": len(upload_candidates),
            "error_count": len(errors),
        },
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "novel git scan: "
            f"samples={len(sample_jobs)} uploads={len(upload_candidates)} errors={len(errors)}"
        )
        for job in sample_jobs:
            print(f"- sample {job['request_id']}: {len(job['books'])} books, codex={job['codex_deep_teardown_requested']}")
        for candidate in upload_candidates:
            print(
                "- upload "
                f"{candidate['book_title']} -> {candidate['fanqie_account']} "
                f"chapters {candidate['from_chapter']}..{candidate['to_chapter']}"
            )
        for error in errors:
            print(f"! {error.path}: {error.error}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
