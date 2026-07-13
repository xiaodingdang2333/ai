#!/usr/bin/env python3
"""Process explicit server-side Codex writing requests from Git.

The normal production path is web ChatGPT writing. This worker exists for
controlled handoff tests or overflow work and only runs when a request explicitly
declares `allow_server_codex=true`.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPO = Path("/home/admin/chatgpt-novel-production-system")
CODEX_BIN = Path("/root/.nvm/versions/node/v22.22.3/bin/codex")
LOCK_PATH = Path("/tmp/novel-git-write-worker.lock")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def retry_after_usage_limit(stderr: str) -> str | None:
    """Extract Codex's displayed local retry time without retrying every timer tick."""
    match = re.search(r"try again at\s+(\d{1,2}):(\d{2})\s*([AP]M)", stderr, re.I)
    if not match:
        return None
    hour = int(match.group(1)) % 12
    if match.group(3).upper() == "PM":
        hour += 12
    now = datetime.now(timezone.utc).astimezone()
    retry_at = now.replace(hour=hour, minute=int(match.group(2)), second=0, microsecond=0)
    if retry_at <= now:
        retry_at += timedelta(days=1)
    return retry_at.isoformat(timespec="seconds")


def retry_is_due(request: dict[str, Any]) -> bool:
    value = request.get("retry_after")
    if not value:
        return True
    try:
        return datetime.fromisoformat(str(value)).astimezone() <= datetime.now(timezone.utc).astimezone()
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
    rel_paths = sorted({str(path.relative_to(repo)) for path in paths if path.exists() and path.is_relative_to(repo)})
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


def git_blob_sha(repo: Path, path: Path) -> str:
    result = run_git(repo, ["hash-object", str(path.relative_to(repo))], check=False)
    if result.returncode != 0:
        raise ValueError(f"cannot calculate blob sha for {path}")
    return result.stdout.strip()


def project_layout(project_path: Path) -> dict[str, Any]:
    path = project_path / "工程元数据" / "PROJECT_LAYOUT.json"
    if not path.exists():
        # Historical E2E projects have no manifest and are deliberately not
        # eligible for new v1.1 server-write requests.
        return {}
    return load_json(path)


def formal_chapter_files(project_path: Path) -> dict[int, Path]:
    layout = project_layout(project_path)
    formal_dir = project_path / str(layout.get("formal_dir", "formal"))
    chapters: dict[int, Path] = {}
    for path in sorted(formal_dir.glob("*.md")):
        no = chapter_no_from_name(path)
        if no is not None:
            chapters[no] = path
    return chapters


def han_count(text: str) -> int:
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    compact = re.sub(r"\s+", "", "\n".join(lines))
    return len(re.findall(r"[\u4e00-\u9fff]", compact))


def run_repo_command(repo: Path, command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return {
        "command": command,
        "status": "ok" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "")[-4000:],
        "stderr_tail": (result.stderr or "")[-4000:],
    }


def run_quality(repo: Path, project_path: Path, from_chapter: int, to_chapter: int) -> tuple[bool, dict[str, Any], list[Path]]:
    layout = project_layout(project_path)
    audits = project_path / str(layout.get("audit_dir", "audits"))
    audits.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    preflight_output = audits / f"SERVER_WRITE_PREFLIGHT_CH{from_chapter:03d}_CH{to_chapter:03d}_{stamp}.json"
    p0_output = audits / f"SERVER_WRITE_METRICS_GATE_CH{from_chapter:03d}_CH{to_chapter:03d}_{stamp}.json"
    creative_output = audits / f"SERVER_WRITE_CREATIVE_CRAFT_GATE_CH{from_chapter:03d}_CH{to_chapter:03d}_{stamp}.json"
    ready_output = audits / f"SERVER_WRITE_READY_GATE_CH{from_chapter:03d}_CH{to_chapter:03d}_{stamp}.json"
    summary_output = audits / f"SERVER_WRITE_QUALITY_GATE_CH{from_chapter:03d}_CH{to_chapter:03d}_{stamp}.json"
    errors: list[str] = []
    chapters = []
    files = formal_chapter_files(project_path)
    for no in range(from_chapter, to_chapter + 1):
        path = files.get(no)
        if not path:
            errors.append(f"missing formal chapter CH{no:03d}")
            continue
        chars = han_count(path.read_text(encoding="utf-8"))
        chapters.append({"chapter_no": no, "path": str(path.relative_to(repo)), "han_count": chars})
        if chars < 2500:
            errors.append(f"CH{no:03d} han_count {chars} < 2500")

    p0_result = None
    creative_result = None
    ready_result = None
    if not errors:
        preflight_result = run_repo_command(repo, [
            sys.executable,
            str(repo / "scripts" / "novel_quality_runtime" / "validate_project_production_preflight.py"),
            "--project-dir", str(project_path.relative_to(repo)),
            "--output-json", str(preflight_output.relative_to(repo)),
        ])
        if preflight_result["status"] != "ok":
            errors.append("canonical project production preflight failed")

    if not errors:
        p0_result = run_repo_command(repo, [
            sys.executable,
            str(repo / "scripts" / "novel_quality_runtime" / "chapter_metrics_gate.py"),
            "--project-dir", str(project_path.relative_to(repo)),
            "--from-chapter", str(from_chapter),
            "--to-chapter", str(to_chapter),
            "--p0-mode", str(layout.get("p0_reference_policy", "ABSOLUTE_ONLY_BOOTSTRAP")),
            "--output-json",
            str(p0_output.relative_to(repo)),
        ])
        if p0_result["status"] != "ok":
            errors.append("P0 hard gate command failed")
        else:
            p0_payload = load_json(p0_output)
            if p0_payload.get("p0_numeric_manifest_result") not in {"PASS_NUMERIC_ONLY", "MANDATORY_BODY_REVIEW"}:
                errors.append(f"P0 hard gate result is {p0_payload.get('p0_manifest_result')}")

    if not errors:
        creative_result = run_repo_command(repo, [
            sys.executable,
            str(repo / "scripts" / "novel_quality_runtime" / "validate_creative_craft.py"),
            "--project-dir", str(project_path.relative_to(repo)),
            "--from-chapter", str(from_chapter),
            "--to-chapter", str(to_chapter),
            "--output-json", str(creative_output.relative_to(repo)),
        ])
        if creative_result["status"] != "ok":
            errors.append("Creative Craft exact-blob validation failed")

    if not errors:
        ready_result = run_repo_command(repo, [
            sys.executable,
            str(repo / "scripts" / "novel_quality_runtime" / "validate_ready_promotion_holistic.py"),
            "--project-dir", str(project_path.relative_to(repo)),
            "--from-chapter", str(from_chapter),
            "--to-chapter", str(to_chapter),
            "--output-json",
            str(ready_output.relative_to(repo)),
        ])
        if ready_result["status"] != "ok":
            errors.append("READY promotion command failed")
        else:
            ready_payload = load_json(ready_output)
            if ready_payload.get("promotion_result") != "PASS" or ready_payload.get("ready_after_strong_qa_allowed") is not True:
                errors.append("READY promotion validator did not pass")

    summary = {
        "gate": "SERVER_WRITE_QUALITY_GATE_V1",
        "checked_at": now_iso(),
        "project": str(project_path.relative_to(repo)),
        "chapter_range": {"from_chapter": from_chapter, "to_chapter": to_chapter},
        "result": "PASS" if not errors else "FAIL",
        "blocking_reasons": errors,
        "chapters": chapters,
        "p0_output": str(p0_output.relative_to(repo)),
        "creative_craft_output": str(creative_output.relative_to(repo)),
        "preflight_output": str(preflight_output.relative_to(repo)),
        "ready_output": str(ready_output.relative_to(repo)),
        "preflight_command": preflight_result if 'preflight_result' in locals() else None,
        "p0_command": p0_result,
        "creative_craft_command": creative_result,
        "ready_command": ready_result,
    }
    write_json(summary_output, summary)
    paths = [path for path in [preflight_output, p0_output, creative_output, ready_output, summary_output] if path.exists()]
    return not errors, summary, paths


def build_prompt(repo: Path, project_path: Path, request: dict[str, Any], start_after: int, count: int) -> str:
    project_rel = project_path.relative_to(repo)
    from_chapter = start_after + 1
    to_chapter = start_after + count
    layout = project_layout(project_path)
    formal_dir = str(layout.get("formal_dir", "formal"))
    return f"""你正在服务器 Codex 中执行网页版 2.2-LTS Git 小说流程的显式代写请求。

硬规则：
- 只使用 Git 仓库文件，不使用旧 custom GPT Action / services/novel-actions 流程。
- 先读取 CURRENT.json、workflow/v2.2-LTS/workflow.json、PROTOCOL_INDEX.json，以及本任务需要的写作/QA bundle。
- 读取项目：{project_rel}
- 读取 00_PROJECT.json、工程元数据/PROJECT_LAYOUT.json、工程元数据/CREATIVE_CRAFT_PROFILE.json、handoff 中最新快照、audits 中最近质量报告和正式正文最近 1-3 章。
- 续写范围：CH{from_chapter:03d} 到 CH{to_chapter:03d}，共 {count} 章。
- 每章正文至少 2500 个中文汉字，目标 3000 字左右。
- 只能按 PROJECT_LAYOUT.json 写入 {project_rel}/{formal_dir}/；不能假定 formal/CHxxx 布局，也不能覆盖已存在章节。
- 每章必须先生成候选、独立批评、实际返修、验收，再更新质量注册表、章节 ledger、提交事务和 handoff。所有正文相关门禁必须绑定正文的 exact current blob SHA；仅在 `scripts/novel_quality_runtime/validate_ready_promotion_holistic.py` 通过后才算正式就绪。
- 必须执行 `workflow/creative-craft/CREATIVE_CRAFT_EXECUTION_POLICY.md`：章节合同增加 `creative_craft` 小节和全部固定字段；候选稿按 architecture -> character_relationship -> prose_emotion -> continuity 顺序审稿；创建 `audits/CREATIVE_CRAFT_CHxxx_Rn.json` 与对应退化扫描报告；质量注册表写入同一 exact blob 的 `creative_craft_gate`。没有这些证据不得把章节标为 READY。
- 必须按 2.2-LTS 强质量标准自检：背景清楚、人物动机和情绪线明确、场景动作具体、避免报告体、避免标题/句式模板化、避免 AI 味、避免与前文重复换皮。
- 不得自行把 00_PROJECT.json 改成 ready_for_draft_upload。上传 worker 会从 exact-blob holistic receipt、人工审核和平台建书回执派生上传就绪状态。
- 不调用番茄上传脚本。上传由独立 upload worker 执行。

请求 JSON：
```json
{json.dumps(request, ensure_ascii=False, indent=2)}
```

完成后只简要说明写入了哪些文件、章节范围和是否标记待上传。"""


def run_codex(repo: Path, prompt: str, output_path: Path, timeout_seconds: int) -> dict[str, Any]:
    command = [
        str(CODEX_BIN),
        "exec",
        "--cd",
        str(repo),
        "--sandbox",
        "danger-full-access",
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
        return {"status": "timeout", "timeout_seconds": timeout_seconds, "command": command}
    return {
        "status": "ok" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "command": command,
        "stdout_tail": (result.stdout or "")[-4000:],
        "stderr_tail": (result.stderr or "")[-4000:],
    }


def validate_request(repo: Path, request: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if request.get("status") not in {"pending", "retry_scheduled"}:
        errors.append("request status is not pending/retry_scheduled")
    if request.get("allow_server_codex") is not True:
        errors.append("allow_server_codex must be true")
    if request.get("target_mode") != "continue_formal":
        errors.append("target_mode must be continue_formal")
    if request.get("quality_profile") != "v2.2-LTS-strong":
        errors.append("quality_profile must be v2.2-LTS-strong")
    if not isinstance(request.get("chapter_count"), int) or not 1 <= request.get("chapter_count", 0) <= 4:
        errors.append("chapter_count must be 1..4")
    project = request.get("project_path")
    if not isinstance(project, str) or not project.strip():
        errors.append("project_path is required")
    else:
        project_path = (repo / project).resolve()
        if not project_path.is_relative_to((repo / "novels").resolve()):
            errors.append("project_path must be under novels/")
        elif not (project_path / "00_PROJECT.json").exists():
            errors.append("project_path must contain 00_PROJECT.json")
        else:
            layout_path = project_path / "工程元数据" / "PROJECT_LAYOUT.json"
            registry_path = project_path / "工程元数据" / "QUALITY_GATE_REGISTRY.json"
            router_path = project_path / "00_作品总控.md"
            project_data = load_json(project_path / "00_PROJECT.json")
            layout = project_layout(project_path)
            creative_profile_ref = str(layout.get("creative_craft_profile_path", "工程元数据/CREATIVE_CRAFT_PROFILE.json"))
            creative_profile_path = (project_path / creative_profile_ref).resolve()
            if not creative_profile_path.is_relative_to(project_path.resolve()) or not creative_profile_path.is_file():
                errors.append("creative craft profile is missing; migrate the project before server writing")
            current = load_json(repo / "CURRENT.json")
            state = next((item for item in current.get("projects", {}).values()
                          if isinstance(item, dict) and item.get("project_path") == project), {})
            if request.get("schema_version") != "1.1":
                errors.append("schema_version must be 1.1; legacy server-write requests are not executable")
            if request.get("target_branch") != "main":
                errors.append("target_branch must be main")
            if run_git(repo, ["branch", "--show-current"], check=False).stdout.strip() != "main":
                errors.append("worker repository is not on main")
            if request.get("base_commit_sha") != run_git(repo, ["rev-parse", "HEAD"], check=False).stdout.strip():
                errors.append("base_commit_sha is stale")
            for label, path, field in [
                ("workflow_router", router_path, "workflow_router_blob_sha"),
                ("quality_registry", registry_path, "quality_gate_registry_blob_sha"),
                ("project_layout", layout_path, "project_layout_blob_sha"),
            ]:
                if not path.exists() or request.get(field) != git_blob_sha(repo, path):
                    errors.append(f"{label} pin is missing or stale")
            manifest_path = repo / "workflow" / "v2.2-LTS" / "EFFECTIVE_RULESET.json"
            if request.get("effective_ruleset_id") != project_data.get("effective_ruleset_id"):
                errors.append("effective_ruleset_id is stale")
            if request.get("effective_ruleset_manifest_sha") != git_blob_sha(repo, manifest_path):
                errors.append("effective_ruleset_manifest_sha is stale")
            if request.get("expected_formal_until") != project_data.get("formal_until"):
                errors.append("expected_formal_until is stale")
            if request.get("latest_commit_id") != state.get("latest_commit_id"):
                errors.append("latest_commit_id is stale")
    return errors


def process_request(repo: Path, request_path: Path, execute: bool, timeout_seconds: int) -> tuple[dict[str, Any], list[Path]]:
    request = load_json(request_path)
    request_id = str(request.get("request_id") or request_path.stem)
    result_dir = repo / "server-write-results" / request_id
    result_dir.mkdir(parents=True, exist_ok=True)
    changed_paths = [request_path]
    errors = validate_request(repo, request)
    if errors:
        result = {
            "schema_version": "1.0",
            "request_id": request_id,
            "status": "failed",
            "updated_at": now_iso(),
            "errors": errors,
            "dry_run": not execute,
        }
        if execute:
            request["status"] = "failed"
            request["updated_at"] = now_iso()
            write_json(request_path, request)
            status_path = result_dir / "status.json"
            write_json(status_path, result)
            changed_paths.append(status_path)
        return result, changed_paths

    project_path = (repo / request["project_path"]).resolve()
    chapter_count = int(request["chapter_count"])
    chapters_before = formal_chapter_files(project_path)
    latest_before = max(chapters_before) if chapters_before else 0
    start_after = int(request.get("start_after_chapter") or latest_before)
    from_chapter = start_after + 1
    to_chapter = start_after + chapter_count
    output_path = result_dir / "codex-last-message.md"

    if not execute:
        return {
            "schema_version": "1.0",
            "request_id": request_id,
            "status": "dry_run",
            "project_path": request["project_path"],
            "planned_range": {"from_chapter": from_chapter, "to_chapter": to_chapter},
            "dry_run": True,
        }, []

    target_status = run_git(
        repo,
        ["status", "--porcelain", "--", request["project_path"], "CURRENT.json"],
        check=False,
    ).stdout.strip()
    if target_status:
        request["status"] = "failed"
        request["updated_at"] = now_iso()
        write_json(request_path, request)
        result = {
            "schema_version": "1.0",
            "request_id": request_id,
            "status": "failed",
            "updated_at": now_iso(),
            "project_path": request["project_path"],
            "planned_range": {"from_chapter": from_chapter, "to_chapter": to_chapter},
            "errors": ["target project or CURRENT.json has uncommitted state; refusing a non-atomic server write"],
            "dirty_paths": target_status.splitlines(),
        }
        status_path = result_dir / "status.json"
        write_json(status_path, result)
        changed_paths.append(status_path)
        return result, changed_paths

    request["status"] = "running"
    request["updated_at"] = now_iso()
    write_json(request_path, request)

    prompt = build_prompt(repo, project_path, request, start_after, chapter_count)
    codex_result = run_codex(repo, prompt, output_path, timeout_seconds)
    changed_paths.append(output_path)
    if codex_result["status"] != "ok":
        retry_after = retry_after_usage_limit(codex_result.get("stderr_tail", ""))
        request["status"] = "retry_scheduled" if retry_after else "failed"
        request["updated_at"] = now_iso()
        if retry_after:
            request["retry_after"] = retry_after
        else:
            request.pop("retry_after", None)
        write_json(request_path, request)
        result = {
            "schema_version": "1.0",
            "request_id": request_id,
            "status": request["status"],
            "updated_at": now_iso(),
            "project_path": request["project_path"],
            "planned_range": {"from_chapter": from_chapter, "to_chapter": to_chapter},
            "codex": codex_result,
        }
        if retry_after:
            result["retry_after"] = retry_after
        status_path = result_dir / "status.json"
        write_json(status_path, result)
        changed_paths.append(status_path)
        return result, changed_paths

    chapters_after = formal_chapter_files(project_path)
    missing = [no for no in range(from_chapter, to_chapter + 1) if no not in chapters_after]
    new_chapter_paths = [chapters_after[no] for no in range(from_chapter, to_chapter + 1) if no in chapters_after]
    changed_paths.extend(new_chapter_paths)
    # The Codex transaction updates ledgers, contracts, handoff snapshots and
    # CURRENT.json in addition to formal prose. The target was verified clean
    # before launch, so every changed file under this project belongs to this
    # request and must be committed atomically for web-session recovery.
    changed_paths.extend(path for path in project_path.rglob("*") if path.is_file())
    current_path = repo / "CURRENT.json"
    if current_path.exists():
        changed_paths.append(current_path)
    quality_ok = False
    quality: dict[str, Any] | None = None
    quality_paths: list[Path] = []
    if not missing:
        quality_ok, quality, quality_paths = run_quality(repo, project_path, from_chapter, to_chapter)
        changed_paths.extend(quality_paths)

    # Upload readiness is not a writer-controlled boolean.  A separate upload
    # worker derives it from canonical exact-blob receipts, human review and
    # platform identity after this transaction is committed.

    request["status"] = "completed" if quality_ok and not missing else "failed"
    request["updated_at"] = now_iso()
    write_json(request_path, request)
    result = {
        "schema_version": "1.0",
        "request_id": request_id,
        "status": request["status"],
        "updated_at": now_iso(),
        "project_path": request["project_path"],
        "chapter_range": {"from_chapter": from_chapter, "to_chapter": to_chapter},
        "missing_chapters": missing,
        "quality_passed": quality_ok,
        "quality": quality,
        "auto_upload_marked": False,
        "codex": codex_result,
    }
    status_path = result_dir / "status.json"
    write_json(status_path, result)
    changed_paths.append(status_path)
    changed_paths.extend(path for path in project_path.glob("handoff/*") if path.is_file())
    return result, changed_paths


def process_requests(repo: Path, execute: bool, limit: int, timeout_seconds: int, git_commit: bool, git_push: bool) -> dict[str, Any]:
    pending = repo / "server-write-requests" / "pending"
    processed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    changed_paths: list[Path] = []
    for request_path in sorted(pending.glob("*.json"))[:limit]:
        try:
            request = load_json(request_path)
            if request.get("status") not in {"pending", "retry_scheduled"}:
                continue
            if request.get("status") == "retry_scheduled" and not retry_is_due(request):
                continue
            result, paths = process_request(repo, request_path, execute, timeout_seconds)
            processed.append({
                "request_path": str(request_path.relative_to(repo)),
                "request_id": result.get("request_id"),
                "status": result.get("status"),
                "chapter_range": result.get("chapter_range") or result.get("planned_range"),
                "quality_passed": result.get("quality_passed"),
                "dry_run": not execute,
            })
            changed_paths.extend(paths)
        except Exception as exc:  # noqa: BLE001 - keep processing other requests.
            errors.append({"path": str(request_path), "error": str(exc)})
    git_result = None
    if execute and git_commit:
        stamp = int(time.time())
        git_result = safe_git_record(repo, changed_paths, f"server-write: process request batch {stamp}", git_push)
    return {"processed": processed, "errors": errors, "execute": execute, "git": git_result}


def main() -> int:
    parser = argparse.ArgumentParser(description="Process explicit server Codex write requests.")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--git-commit", action="store_true")
    parser.add_argument("--git-push", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        print(f"not a Git repository: {repo}", file=sys.stderr)
        return 2

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            output = {"execute": args.execute, "processed": [], "errors": [], "locked": True, "git": None}
            if args.json:
                print(json.dumps(output, ensure_ascii=False, indent=2))
            else:
                print("server write worker: another instance is running")
            return 0
        result = process_requests(
            repo,
            args.execute,
            max(1, args.limit),
            max(60, args.timeout_seconds),
            args.git_commit,
            args.git_push,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        mode = "execute" if args.execute else "dry-run"
        print(f"server write worker {mode}: processed={len(result['processed'])} errors={len(result['errors'])}")
        for item in result["processed"]:
            print(f"- {item['request_id']}: {item['status']} {item.get('chapter_range')}")
        for error in result["errors"]:
            print(f"! {error['path']}: {error['error']}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
