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
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPO = Path("/home/admin/chatgpt-novel-production-system-runtime")
SONOVEL_COMMAND = Path("/home/admin/ai/scripts/sonovel.sh")
SONOVEL_CLIENT = Path("/home/admin/ai/scripts/sonovel-client.js")
NODE_BIN = Path("/root/.nvm/versions/node/v22.22.3/bin/node")
CODEX_BIN = Path("/root/.nvm/versions/node/v22.22.3/bin/codex")

ALLOWED_BASES = {
    "public_domain",
    "open_license",
    "official_download",
    "user_authorized_material",
}
RUNNING_LEASE_SECONDS = 15 * 60
DEFAULT_BOOK_CONCURRENCY = 2
DEFAULT_PACKET_CHAPTER_CONCURRENCY = 6
FULL_TEXT_ROOT = Path("/home/admin/ai/txt/download")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def running_lease_expired(request: dict[str, Any]) -> bool:
    value = request.get("lease_expires_at")
    if not isinstance(value, str):
        return True
    try:
        return datetime.fromisoformat(value).astimezone() <= datetime.now(timezone.utc).astimezone()
    except ValueError:
        return True


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


def positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def legal_basis_for(request: dict[str, Any], book: dict[str, Any]) -> tuple[str, bool]:
    basis = book.get("legal_access_basis") or request.get("legal_access_basis") or "unknown"
    allowed = bool(book.get("automation_allowed", request.get("automation_allowed", False)))
    return str(basis), allowed


def packet_scope_for(request: dict[str, Any]) -> dict[str, int | str]:
    """Normalize the bounded structural packet contract.

    A packet is intentionally not a whole-book download.  Request fields are
    optional to retain compatibility with existing Git requests.
    """
    scope = str(request.get("material_scope") or "key_chapter_packet")
    if scope == "full_authorized_text":
        return {"scope": scope, "front": 0, "middle": 0, "tail": 0, "chapter_concurrency": 1}
    if scope != "key_chapter_packet":
        raise ValueError(f"unsupported material_scope: {scope}")
    return {
        "scope": scope,
        "front": min(8, positive_int(request.get("packet_front_chapters"), 5)),
        "middle": min(4, positive_int(request.get("packet_middle_chapters"), 2)),
        "tail": min(4, positive_int(request.get("packet_tail_chapters"), 2)),
        "chapter_concurrency": min(12, positive_int(request.get("packet_chapter_concurrency"), DEFAULT_PACKET_CHAPTER_CONCURRENCY)),
    }


def run_packet(book: dict[str, Any], timeout_seconds: int, packet_scope: dict[str, int | str]) -> tuple[bool, str]:
    title = str(book.get("title") or "")
    author = str(book.get("author") or "")
    # Do not take sonovel.sh's global operation lock here.  Packet jobs use the
    # native service only for identity search, then fetch a small bounded
    # chapter set.  This permits two independent books to progress while the
    # 8090 official UI remains available for interactive full downloads.
    command = [str(NODE_BIN), str(SONOVEL_CLIENT), "packet", title, author]
    environment = os.environ.copy()
    environment.update({
        "NOVEL_PACKET_FRONT": str(packet_scope["front"]),
        "NOVEL_PACKET_MIDDLE": str(packet_scope["middle"]),
        "NOVEL_PACKET_TAIL": str(packet_scope["tail"]),
        "NOVEL_PACKET_CHAPTER_CONCURRENCY": str(packet_scope["chapter_concurrency"]),
    })
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=timeout_seconds + 15,
        )
    except subprocess.TimeoutExpired:
        return False, f"single book packet timed out after {timeout_seconds}s"
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode == 0:
        return True, output
    return False, error or output or f"packet command failed with exit {result.returncode}"


def run_full_download(book: dict[str, Any], timeout_seconds: int) -> tuple[bool, dict[str, Any] | str]:
    """Download an authorized whole book locally; Git never receives its body."""
    command = [str(NODE_BIN), str(SONOVEL_CLIENT), "download", str(book.get("title") or ""), str(book.get("author") or ""), "txt"]
    try:
        result = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=max(timeout_seconds, 600))
    except subprocess.TimeoutExpired:
        return False, f"full-text download timed out after {max(timeout_seconds, 600)}s"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "full-text download failed").strip()[-1500:]
    try:
        payload = json.loads((result.stdout or "").strip())
    except json.JSONDecodeError:
        return False, f"full-text downloader returned invalid JSON: {(result.stdout or '')[-500:]}"
    selected = payload.get("selected") if isinstance(payload.get("selected"), dict) else {}
    if selected.get("bookName") != book.get("title") or selected.get("author") != book.get("author"):
        return False, "FULL_TEXT_IDENTITY_MISMATCH: downloader did not return the requested exact title and author"
    file_info = payload.get("file") if isinstance(payload.get("file"), dict) else {}
    name = str(file_info.get("name") or "")
    local_path = FULL_TEXT_ROOT / name
    if not name or not local_path.exists():
        return False, f"full-text downloader did not create expected local file: {name or 'unknown'}"
    return True, {"path": local_path, "selected": selected, "file": file_info}


def _read_local_full_text(path: Path) -> tuple[str, list[tuple[str, str]]]:
    files = sorted(path.rglob("*.txt")) if path.is_dir() else [path]
    chunks: list[str] = []
    rows: list[tuple[str, str]] = []
    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if text.strip():
            chunks.append(text)
            rows.append((file_path.name, text))
    return "\n".join(chunks), rows


def audit_full_authorized_text(download: dict[str, Any], book: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create an index/audit from server-local full text without exporting prose."""
    path = Path(download["path"])
    text, file_rows = _read_local_full_text(path)
    chapter_rows: list[dict[str, Any]] = []
    heading = re.compile(r"(?m)^\s*(第\s*(\d+)\s*章[^\n]{0,100})")
    for _filename, file_text in file_rows:
        matches = list(heading.finditer(file_text))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(file_text)
            chapter_rows.append({"chapter_no": int(match.group(2)), "title": match.group(1).strip(), "characters": len(re.sub(r"\s+", "", file_text[match.start():end]))})
    if not chapter_rows and path.is_dir():
        for index, (filename, file_text) in enumerate(file_rows, 1):
            match = re.search(r"(?:^|_)0*(\d+)_", filename)
            chapter_rows.append({"chapter_no": int(match.group(1)) if match else index, "title": Path(filename).stem[:120], "characters": len(re.sub(r"\s+", "", file_text))})
    numbers = [row["chapter_no"] for row in chapter_rows]
    duplicate_count = len(numbers) - len(set(numbers))
    disorder_count = sum(1 for left, right in zip(numbers, numbers[1:]) if right <= left)
    total_characters = len(re.sub(r"\s+", "", text))
    reasons: list[str] = []
    if total_characters < 10000:
        reasons.append(f"full text too short: {total_characters} characters")
    if len(chapter_rows) < 3:
        reasons.append(f"too few indexed chapters: {len(chapter_rows)}")
    if duplicate_count:
        reasons.append(f"duplicate chapter numbers: {duplicate_count}")
    if disorder_count:
        reasons.append(f"chapter order disorder: {disorder_count}")
    audit = {
        "schema_version": "1.0",
        "audit_kind": "full_authorized_text_quality",
        "title": book.get("title"),
        "author": book.get("author"),
        "material_scope": "full_authorized_text",
        "storage": "server_local_only",
        "source_ref": {"url": download["selected"].get("url"), "source_id": download["selected"].get("sourceId")},
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "total_characters": total_characters,
        "indexed_chapter_count": len(chapter_rows),
        "duplicate_chapter_number_count": duplicate_count,
        "chapter_order_disorder_count": disorder_count,
        "passed": not reasons,
        "reasons": reasons,
    }
    return audit, chapter_rows


def run_full_text_teardown(repo: Path, request: dict[str, Any], result_dir: Path, audit_path: Path, index_path: Path, local_path: Path, timeout_seconds: int) -> tuple[bool, str, Path | None]:
    output_path = result_dir / "teardowns" / "FULL_AUTHORIZED_TEXT_TEARDOWN.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = (
        "你是中文网文市场拆书分析助手。用户已授权处理服务器本地完整文本。读取完整文本与其Git内的章节索引/质量审计，"
        "仅输出功能结构化拆书：生命周期、章节节奏、钩子、人物与关系引擎、升级/兑现机制、风险与非复制启发。"
        "不得引用或复述原文，不得复用专名、标志性事件或连续情节。\n\n"
        f"本地完整文本（不得提交）：{local_path}\n"
        f"质量审计：{audit_path.relative_to(repo)}\n章节索引：{index_path.relative_to(repo)}\n"
        "输出中文 Markdown。"
    )
    command = [str(CODEX_BIN), "exec", "--cd", str(repo), "--sandbox", "read-only", "--add-dir", str(local_path.parent), "--output-last-message", str(output_path), prompt]
    try:
        result = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return False, f"full-text Codex teardown timed out after {timeout_seconds}s", None
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 200:
        return True, str(output_path.relative_to(repo)), output_path
    return False, ((result.stderr or "") + "\n" + (result.stdout or "")).strip()[-2000:], None


NON_STORY_CHAPTER_TITLE = re.compile(
    r"感谢信|创作思路|创作总结|明天会更新|明天中午更新|理一下思绪|请假|完结感言|读者群|上架感言"
)


def audit_local_study_packet(raw_output: str) -> dict[str, Any]:
    """Reject mirror packets that are mostly notices, duplicates, or tiny fragments."""
    raw_path = Path(raw_output.strip())
    if not raw_path.is_dir():
        return {"passed": True, "kind": "adapter_text_response", "reasons": []}

    source_path = raw_path / "source.json"
    if not source_path.exists():
        return {"passed": False, "kind": "local_study_packet", "reasons": ["missing source.json"]}
    source = load_json(source_path)
    chapters = source.get("chapters") if isinstance(source.get("chapters"), list) else []
    usable = [item for item in chapters if isinstance(item, dict)]
    sizes = [int(item["characters"]) for item in usable if isinstance(item.get("characters"), int)]
    notice_titles = [str(item.get("title") or "") for item in usable if NON_STORY_CHAPTER_TITLE.search(str(item.get("title") or ""))]
    tiny_count = sum(1 for size in sizes if size < 500)
    chapter_numbers = []
    for item in usable:
        match = re.search(r"第\s*(\d+)\s*章", str(item.get("title") or ""))
        if match:
            chapter_numbers.append(match.group(1))
    duplicate_numbers = len(chapter_numbers) - len(set(chapter_numbers))
    reasons: list[str] = []
    if len(usable) < 6:
        reasons.append(f"too few selected chapters: {len(usable)}")
    if sum(sizes) < 10000:
        reasons.append(f"selected characters too low: {sum(sizes)}")
    if len(notice_titles) >= 2:
        reasons.append(f"non-story notices in selected chapters: {len(notice_titles)}")
    if tiny_count >= 2:
        reasons.append(f"tiny selected fragments: {tiny_count}")
    if duplicate_numbers >= 2:
        reasons.append(f"duplicate chapter numbers in selection: {duplicate_numbers}")
    return {
        "passed": not reasons,
        "kind": "local_study_packet",
        "selected_chapter_count": len(usable),
        "selected_characters": sum(sizes),
        "non_story_notice_count": len(notice_titles),
        "tiny_fragment_count": tiny_count,
        "duplicate_chapter_number_count": duplicate_numbers,
        "reasons": reasons,
    }


def export_web_packet(raw_output: str, packet_path: Path, book: dict[str, Any]) -> dict[str, Any]:
    """Export a Git-readable, non-full-text packet from a local study directory.

    ``sonovel-client packet`` currently prints the local output directory.  The
    former worker wrote that directory name into Git, which made a successful
    acquisition unusable to web ChatGPT.  Keep the full source locally and
    publish only machine-readable metadata, chapter structure and aggregate
    statistics to the shared repository.
    """
    raw_path = Path(raw_output.strip())
    title = str(book.get("title") or "")
    author = str(book.get("author") or "")

    source_quality = audit_local_study_packet(raw_output)
    if raw_path.is_dir():
        source_path = raw_path / "source.json"
        source = load_json(source_path) if source_path.exists() else {}
        chapters = source.get("chapters") if isinstance(source.get("chapters"), list) else []
        chapter_rows = [
            {
                "index": item.get("index"),
                "title": item.get("title"),
                "characters": item.get("characters"),
            }
            for item in chapters
            if isinstance(item, dict)
        ]
        chapter_sizes = [
            int(item["characters"])
            for item in chapter_rows
            if isinstance(item.get("characters"), int)
        ]
        packet = {
            "schema_version": "1.0",
            "packet_kind": "web_readable_structural_metadata",
            "title": source.get("title") or title,
            "author": source.get("official_author") or author,
            "source": {
                "source_type": "server_local_study_packet",
                "mirror_book_url": source.get("mirror_book_url"),
                "mirror_chapter_count": source.get("mirror_chapter_count"),
                "identity_verification_required": True,
                "full_text_storage": "server_local_only",
                "acquisition": source.get("acquisition", {}),
            },
            "source_quality_audit": source_quality,
            "selection": {
                "selected_chapter_count": source.get("selected_chapter_count", len(chapter_rows)),
                "selected_characters": source.get("selected_characters", sum(chapter_sizes)),
                "chapter_size": {
                    "minimum": min(chapter_sizes) if chapter_sizes else None,
                    "maximum": max(chapter_sizes) if chapter_sizes else None,
                    "average": round(sum(chapter_sizes) / len(chapter_sizes), 2) if chapter_sizes else None,
                },
                "front_chapter_titles": source.get("mirror_first_chapter_titles", [])[:10],
                "selected_chapters": chapter_rows,
            },
            "web_analysis_ready": False,
            "next_step": (
                "Use existing KB for ideation. Request server_codex packet_deep_teardown "
                "when this sample must contribute semantic market analysis."
            ),
        }
    else:
        # Preserve non-path adapters as a bounded textual packet.  The current
        # adapter emits a directory, but this keeps the contract usable for
        # future official/open-license sources that return structured text.
        compact = re.sub(r"\s+", " ", raw_output).strip()
        packet = {
            "schema_version": "1.0",
            "packet_kind": "adapter_text_response",
            "title": title,
            "author": author,
            "adapter_response": compact[:12000],
            "web_analysis_ready": bool(compact),
            "source_quality_audit": source_quality,
        }

    write_json(packet_path, packet)
    return packet


def run_codex_teardown(repo: Path, request: dict[str, Any], result_dir: Path, packet_paths: list[Path], timeout_seconds: int) -> tuple[bool, str, Path | None]:
    if not packet_paths:
        return False, "no packet files available for Codex teardown", None
    teardown_dir = result_dir / "teardowns"
    teardown_dir.mkdir(parents=True, exist_ok=True)
    output_path = teardown_dir / "SERVER_CODEX_DEEP_TEARDOWN.md"
    relative_packets = [str(path.relative_to(repo)) for path in packet_paths]
    prompt = (
        "你是中文网文市场拆书分析助手。只读取下面 packet 文件，提取功能结构、钩子、节奏、情绪回报、"
        "角色引擎、差异化风险和可迁移创作启发。不得复用原文措辞、人物名、标志性事件或完整情节序列。\n\n"
        f"目标平台：{request.get('target_platform')}\n"
        f"题材：{request.get('genre')}\n"
        f"研究目的：{request.get('research_purpose')}\n"
        "packet 文件：\n"
        + "\n".join(f"- {item}" for item in relative_packets)
        + "\n\n输出中文 Markdown，包含：样本有效性、共性结构、差异结构、开篇钩子、"
        "商业转化建议、原创避雷、可用于新书的非复制型机制。"
    )
    command = [
        str(CODEX_BIN),
        "exec",
        "--cd",
        str(repo),
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(output_path),
        prompt,
    ]
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
        return False, f"Codex teardown timed out after {timeout_seconds}s", None
    if result.returncode == 0 and output_path.exists():
        return True, str(output_path.relative_to(repo)), output_path
    return False, ((result.stderr or "") + "\n" + (result.stdout or "")).strip()[-2000:], None


def result_status(effective: int, target: int, books: list[dict[str, Any]]) -> str:
    if effective >= target:
        return "completed"
    if effective:
        return "partially_completed"
    if books and all(item.get("acquisition_status") == "manual_required" for item in books):
        return "manual_material_required"
    return "failed"


def progress_payload(
    request: dict[str, Any],
    request_path: Path,
    repo: Path,
    stage: str,
    message: str,
    status_books: list[dict[str, Any]],
    current_index: int | None = None,
    current_book: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_id = str(request.get("request_id") or request_path.stem)
    result_dir = repo / "sample-results" / request_id
    books = request.get("books") if isinstance(request.get("books"), list) else []
    min_effective = positive_int(request.get("min_effective_samples"), 1)
    max_attempts = positive_int(request.get("max_attempts"), max(min_effective * 5, len(books) or 1))
    total_candidates = min(max_attempts, len(books))
    effective = sum(1 for item in status_books if item.get("quality_status") == "effective")
    return {
        "schema_version": "1.0",
        "request_id": request_id,
        "status": "running",
        "updated_at": now_iso(),
        "effective_sample_count": effective,
        "packet_dir": str((result_dir / "packets").relative_to(repo)),
        "progress": {
            "stage": stage,
            "message": message,
            "current_index": current_index,
            "total_candidates": total_candidates,
            "effective_sample_count": effective,
            "target_effective_sample_count": min_effective,
            "max_attempts": max_attempts,
            "current_book": current_book,
        },
        "books": status_books,
        "dry_run": False,
    }


def publish_progress(
    repo: Path,
    request_path: Path,
    request: dict[str, Any],
    payload: dict[str, Any],
    git_commit: bool,
    git_push: bool,
    message: str,
    extra_paths: list[Path] | None = None,
) -> dict[str, Any] | None:
    status_path = repo / "sample-results" / payload["request_id"] / "status.json"
    write_json(request_path, request)
    write_json(status_path, payload)
    if not git_commit:
        return None
    return safe_git_record(repo, [request_path, status_path, *(extra_paths or [])], message, git_push)


def status_for_request(
    request: dict[str, Any],
    request_path: Path,
    repo: Path,
    execute: bool,
    timeout_seconds: int,
    run_codex: bool,
    codex_timeout_seconds: int,
    git_commit: bool = False,
    git_push: bool = False,
) -> dict[str, Any]:
    request_id = str(request.get("request_id") or request_path.stem)
    result_dir = repo / "sample-results" / request_id
    packet_dir = result_dir / "packets"
    all_books = request.get("books") if isinstance(request.get("books"), list) else []
    min_effective = positive_int(request.get("min_effective_samples"), 1)
    max_attempts = positive_int(request.get("max_attempts"), max(min_effective * 5, len(all_books) or 1))
    books = all_books[:max_attempts]
    status_books: list[dict[str, Any]] = []
    packet_paths: list[Path] = []
    full_teardown_paths: list[Path] = []
    effective = 0

    packet_scope = packet_scope_for(request)
    requested_provider = str(request.get("acquisition_provider") or "auto")

    def candidate_result(index: int, book: dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
        title = str(book.get("title") or "")
        author = str(book.get("author") or "")
        basis, automation_allowed = legal_basis_for(request, book)
        base_record = {
            "title": title,
            "author": author,
            "legal_access_status": basis,
            "identity_confidence": book.get("identity_confidence", "unknown"),
            "provider": "sonovel_key_chapter_packet" if packet_scope["scope"] == "key_chapter_packet" else "sonovel_full_authorized_text",
            "material_scope": packet_scope["scope"],
        }
        if requested_provider not in {"auto", "sonovel_key_chapter_packet"}:
            return ({
                **base_record,
                "acquisition_status": "manual_required",
                "quality_status": "unchecked",
                "failure_reason": (
                    f"PROVIDER_NOT_PROMOTED: {requested_provider} is benchmark-only; "
                    "run an authorized source benchmark before production routing"
                ),
            }, None)
        if basis not in ALLOWED_BASES or not automation_allowed:
            return ({
                **base_record,
                "acquisition_status": "manual_required",
                "quality_status": "unchecked",
                "failure_reason": "MANUAL_MATERIAL_REQUIRED: no explicit allowed automated acquisition basis",
            }, None)
        if not execute:
            return ({
                **base_record,
                "acquisition_status": "pending",
                "quality_status": "unchecked",
                "failure_reason": f"dry-run: {packet_scope['scope']} acquisition not executed",
            }, None)
        started_at = time.monotonic()
        if packet_scope["scope"] == "full_authorized_text":
            ok, outcome = run_full_download(book, timeout_seconds)
            elapsed_seconds = round(time.monotonic() - started_at, 2)
            if not ok:
                return ({**base_record, "acquisition_status": "failed", "quality_status": "failed", "failure_reason": str(outcome)[:1000], "performance": {"elapsed_seconds": elapsed_seconds}}, None)
            download = outcome
            audit, chapter_rows = audit_full_authorized_text(download, book)
            audit_dir = result_dir / "full-text-audits"
            audit_dir.mkdir(parents=True, exist_ok=True)
            stem = f"{index:03d}_{safe_slug(title, 'book')}"
            audit_path = audit_dir / f"{stem}.quality.json"
            index_path = audit_dir / f"{stem}.chapter-index.json"
            write_json(audit_path, audit)
            write_json(index_path, {"schema_version": "1.0", "title": title, "author": author, "material_scope": "full_authorized_text", "storage": "server_local_only", "chapters": chapter_rows})
            if not audit["passed"]:
                return ({**base_record, "acquisition_status": "failed", "quality_status": "quality_rejected", "failure_reason": "FULL_TEXT_QUALITY_AUDIT: " + "; ".join(audit["reasons"]), "source_quality_audit": audit, "performance": {"elapsed_seconds": elapsed_seconds, "selected_chapter_count": len(chapter_rows), "chapter_concurrency": 1}}, None)
            if not run_codex:
                return ({**base_record, "acquisition_status": "downloaded", "quality_status": "failed", "failure_reason": "FULL_TEXT_TEARDOWN_REQUIRED: rerun with --run-codex; no packet downgrade is allowed", "source_quality_audit": audit, "performance": {"elapsed_seconds": elapsed_seconds, "selected_chapter_count": len(chapter_rows), "chapter_concurrency": 1}}, None)
            teardown_ok, teardown_detail, teardown_path = run_full_text_teardown(repo, request, result_dir, audit_path, index_path, Path(download["path"]), codex_timeout_seconds)
            if not teardown_ok:
                return ({**base_record, "acquisition_status": "downloaded", "quality_status": "failed", "failure_reason": "FULL_TEXT_TEARDOWN_FAILED: " + teardown_detail[:1000], "source_quality_audit": audit, "performance": {"elapsed_seconds": elapsed_seconds, "selected_chapter_count": len(chapter_rows), "chapter_concurrency": 1}}, None)
            full_teardown_paths.append(teardown_path)
            return ({**base_record, "acquisition_status": "teardown_ready", "quality_status": "effective", "teardown_path": teardown_detail, "packet_git_push_status": "pending", "source_quality_audit": audit, "performance": {"elapsed_seconds": elapsed_seconds, "selected_chapter_count": len(chapter_rows), "chapter_concurrency": 1}}, teardown_path)
        ok, output = run_packet(book, timeout_seconds, packet_scope)
        elapsed_seconds = round(time.monotonic() - started_at, 2)
        if not ok:
            return ({
                **base_record,
                "acquisition_status": "failed",
                "quality_status": "failed",
                "failure_reason": output[:1000],
                "performance": {"elapsed_seconds": elapsed_seconds},
            }, None)
        source_quality = audit_local_study_packet(output)
        if not source_quality["passed"]:
            return ({
                **base_record,
                "acquisition_status": "failed",
                "quality_status": "quality_rejected",
                "failure_reason": "SOURCE_QUALITY_AUDIT: " + "; ".join(source_quality["reasons"]),
                "source_quality_audit": source_quality,
                "performance": {"elapsed_seconds": elapsed_seconds},
            }, None)
        packet_dir.mkdir(parents=True, exist_ok=True)
        packet_path = packet_dir / f"{index:03d}_{safe_slug(title, 'book')}.json"
        packet = export_web_packet(output, packet_path, book)
        acquisition = packet.get("source", {}).get("acquisition", {})
        return ({
            **base_record,
            "acquisition_status": "packet_ready",
            "quality_status": "effective",
            "packet_path": str(packet_path.relative_to(repo)),
            "packet_kind": packet.get("packet_kind"),
            "packet_generated_at": now_iso(),
            "packet_git_push_status": "pending",
            "web_analysis_ready": packet.get("web_analysis_ready"),
            "source_quality_audit": source_quality,
            "performance": {
                "elapsed_seconds": elapsed_seconds,
                "selected_chapter_count": acquisition.get("requested_positions"),
                "chapter_concurrency": acquisition.get("chapter_concurrency"),
            },
        }, packet_path)

    attempted_indexes: set[int] = set()
    cursor = 0
    while cursor < len(books) and effective < min_effective:
        remaining = min_effective - effective
        # Directional children are strict ordered fallbacks: never start the
        # second book until the first one is conclusively rejected.
        batch_limit = 1 if request.get("parent_request_id") else DEFAULT_BOOK_CONCURRENCY
        batch_size = min(batch_limit, remaining, len(books) - cursor)
        batch = [(cursor + offset + 1, books[cursor + offset]) for offset in range(batch_size)
                 if isinstance(books[cursor + offset], dict)]
        cursor += batch_size
        if not batch:
            continue
        if execute:
            pending = [
                {
                    "title": str(book.get("title") or ""),
                    "author": str(book.get("author") or ""),
                    "legal_access_status": legal_basis_for(request, book)[0],
                    "identity_confidence": book.get("identity_confidence", "unknown"),
                    "provider": "sonovel_key_chapter_packet",
                    "material_scope": packet_scope["scope"],
                    "acquisition_status": "running",
                    "quality_status": "checking",
                }
                for _, book in batch
            ]
            publish_progress(
                repo, request_path, request,
                progress_payload(
                    request, request_path, repo, "acquiring_sample_batch",
                    f"Attempting {len(batch)} candidate(s) in required order; target is {min_effective} effective result(s).",
                    [*status_books, *pending], batch[0][0],
                    {"title": str(batch[0][1].get("title") or ""), "author": str(batch[0][1].get("author") or ""), "channel": batch[0][1].get("channel")},
                ), git_commit, git_push, f"samples: started batch {request_id} {batch[0][0]}",
            )
        results: dict[int, tuple[dict[str, Any], Path | None]] = {}
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {pool.submit(candidate_result, index, book): index for index, book in batch}
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        for index, book in batch:
            record, created_packet_path = results[index]
            attempted_indexes.add(index)
            status_books.append(record)
            if record.get("quality_status") == "effective":
                effective += 1
                if created_packet_path:
                    packet_paths.append(created_packet_path)
            if execute:
                git_result = publish_progress(
                    repo, request_path, request,
                    progress_payload(
                        request, request_path, repo, "candidate_finished",
                        f"Finished candidate {index}/{len(books)}.", status_books, index,
                        {"title": record["title"], "author": record["author"], "channel": book.get("channel")},
                    ), git_commit, git_push, f"samples: progress {request_id} effective {effective}",
                    [created_packet_path] if created_packet_path else None,
                )
                if created_packet_path:
                    push_status = "not_requested" if not git_commit else (
                        str(git_result.get("push_status") or "committed_local")
                        if git_result and git_result.get("status") == "committed" else "commit_failed"
                    )
                    record["packet_git_push_status"] = push_status
                    if push_status in {"pushed", "committed_local"}:
                        record["packet_uploaded_at"] = now_iso()
                    publish_progress(
                        repo, request_path, request,
                        progress_payload(
                            request, request_path, repo, "packet_git_status",
                            f"Packet Git status: {push_status}.", status_books, index,
                            {"title": record["title"], "author": record["author"], "channel": book.get("channel")},
                        ), git_commit, git_push, f"samples: packet Git status {request_id} {index}",
                    )

    skipped = [
        {
            "title": str(book.get("title") or ""),
            "author": str(book.get("author") or ""),
            "channel": book.get("channel"),
            "acquisition_status": "not_attempted",
            "quality_status": "not_attempted",
            "skip_reason": "target_effective_sample_count reached" if effective >= min_effective else "max_attempts reached",
        }
        for index, book in enumerate(all_books, 1)
        if isinstance(book, dict) and index not in attempted_indexes
    ]

    status = result_status(effective, min_effective, status_books)

    result = {
        "schema_version": "1.0",
        "request_id": request_id,
        "status": status if execute else "running",
        "updated_at": now_iso(),
        "effective_sample_count": effective,
        "target_effective_sample_count": min_effective,
        "attempted_count": len(status_books),
        "total_candidate_count": len(all_books),
        "max_attempts": max_attempts,
        "packet_dir": str(packet_dir.relative_to(repo)),
        "books": status_books + skipped,
        "dry_run": not execute,
    }

    if packet_scope["scope"] == "full_authorized_text":
        result["teardown_dir"] = str((result_dir / "teardowns").relative_to(repo))
        result["full_text_audit_dir"] = str((result_dir / "full-text-audits").relative_to(repo))
        result["server_codex_deep_teardown"] = {"requested": True, "status": "completed" if effective else "failed", "scope": "full_authorized_text", "teardown_paths": [str(path.relative_to(repo)) for path in full_teardown_paths]}
    elif request.get("analysis_engine") == "server_codex" and request.get("allow_codex") is True:
        codex_status = "todo_after_packet_ready" if effective else "blocked_no_effective_packet"
        codex_teardown_path = None
        codex_error = None
        if execute and run_codex and effective:
            ok, detail, output_path = run_codex_teardown(repo, request, result_dir, packet_paths, codex_timeout_seconds)
            if ok:
                codex_status = "completed"
                codex_teardown_path = detail
                result["teardown_dir"] = str((result_dir / "teardowns").relative_to(repo))
                changed_path = output_path
            else:
                codex_status = "failed"
                codex_error = detail
                changed_path = None
        else:
            changed_path = None
        result["server_codex_deep_teardown"] = {
            "requested": True,
            "status": codex_status,
            "scope": request.get("codex_scope"),
        }
        if codex_teardown_path:
            result["server_codex_deep_teardown"]["teardown_path"] = codex_teardown_path
        if codex_error:
            result["server_codex_deep_teardown"]["error"] = codex_error
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
            if changed_path:
                result.setdefault("_extra_changed_paths", []).append(str(changed_path))

    return result


def running_status_for_request(request: dict[str, Any], request_path: Path, repo: Path) -> dict[str, Any]:
    request_id = str(request.get("request_id") or request_path.stem)
    books = request.get("books") if isinstance(request.get("books"), list) else []
    min_effective = positive_int(request.get("min_effective_samples"), 1)
    max_attempts = positive_int(request.get("max_attempts"), max(min_effective * 5, len(books) or 1))
    scope = str(request.get("material_scope") or "key_chapter_packet")
    status_books = []
    for book in books[:max_attempts]:
        if not isinstance(book, dict):
            continue
        basis, automation_allowed = legal_basis_for(request, book)
        status_books.append({
            "title": str(book.get("title") or ""),
            "author": str(book.get("author") or ""),
            "legal_access_status": basis,
            "automation_allowed": automation_allowed,
            "identity_confidence": book.get("identity_confidence", "unknown"),
            "material_scope": scope,
            "acquisition_status": "pending",
            "quality_status": "unchecked",
        })
    payload = progress_payload(
        request,
        request_path,
        repo,
        "server_sample_worker_started",
        f"Server worker has claimed this request and is attempting legal {scope} acquisition.",
        status_books,
    )
    payload["request_id"] = request_id
    return payload


def process_requests(
    repo: Path,
    execute: bool,
    limit: int,
    timeout_seconds: int,
    git_commit: bool,
    git_push: bool,
    run_codex: bool,
    codex_timeout_seconds: int,
) -> dict[str, Any]:
    pending = repo / "sample-requests" / "pending"
    processed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    changed_paths: list[Path] = []
    for request_path in sorted(pending.glob("*.json"))[:limit]:
        try:
            request = load_json(request_path)
            status = request.get("status")
            retrying_stale_lease = status == "running" and running_lease_expired(request)
            if status != "pending" and not (status == "failed" and request.get("retry_requested") is True) and not retrying_stale_lease:
                continue
            if retrying_stale_lease:
                request["status"] = "pending"
                request["recovered_from_expired_lease_at"] = now_iso()
            if execute:
                request["status"] = "running"
                request["updated_at"] = now_iso()
                request["lease_expires_at"] = (datetime.now(timezone.utc).astimezone() + timedelta(seconds=RUNNING_LEASE_SECONDS)).isoformat(timespec="seconds")
                running = running_status_for_request(request, request_path, repo)
                status_path = repo / "sample-results" / running["request_id"] / "status.json"
                write_json(request_path, request)
                write_json(status_path, running)
                if git_commit:
                    safe_git_record(
                        repo,
                        [request_path, status_path],
                        f"samples: mark request running {running['request_id']}",
                        git_push,
                    )
            result = status_for_request(
                request,
                request_path,
                repo,
                execute,
                timeout_seconds,
                run_codex,
                codex_timeout_seconds,
                git_commit,
                git_push,
            )
            if execute:
                request["status"] = "completed" if result["status"] == "completed" else result["status"]
                request["updated_at"] = now_iso()
                request.pop("lease_expires_at", None)
                extra_paths = [Path(extra) for extra in result.pop("_extra_changed_paths", [])]
                write_json(request_path, request)
                status_path = repo / "sample-results" / result["request_id"] / "status.json"
                write_json(status_path, result)
                changed_paths.extend([request_path, status_path])
                result_dir = repo / "sample-results" / result["request_id"]
                if result_dir.exists():
                    changed_paths.extend(path for path in result_dir.rglob("*") if path.is_file())
                changed_paths.extend(extra_paths)
            processed.append({
                "request_path": str(request_path.relative_to(repo)),
                "request_id": result["request_id"],
                "status": result["status"],
                "effective_sample_count": result["effective_sample_count"],
                "dry_run": not execute,
            })
        except Exception as exc:  # noqa: BLE001 - worker should continue other requests.
            if execute and 'request' in locals() and 'request_path' in locals():
                request_id = str(request.get("request_id") or request_path.stem)
                request["status"] = "failed"
                request["updated_at"] = now_iso()
                request["worker_error"] = str(exc)[:2000]
                request.pop("lease_expires_at", None)
                status_path = repo / "sample-results" / request_id / "status.json"
                write_json(request_path, request)
                write_json(status_path, {
                    "schema_version": "1.1",
                    "request_id": request_id,
                    "status": "failed",
                    "updated_at": now_iso(),
                    "failure_reason": "WORKER_EXCEPTION",
                    "error": str(exc)[:2000],
                })
                changed_paths.extend([request_path, status_path])
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
    parser.add_argument("--run-codex", action="store_true", help="Run server Codex deep teardown when explicitly requested.")
    parser.add_argument("--codex-timeout-seconds", type=int, default=1800)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        print(f"not a Git repository: {repo}", file=sys.stderr)
        return 2
    result = process_requests(
        repo,
        args.execute,
        max(1, args.limit),
        max(5, args.timeout_seconds),
        args.git_commit,
        args.git_push,
        args.run_codex,
        max(60, args.codex_timeout_seconds),
    )
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
