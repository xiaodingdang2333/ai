#!/usr/bin/env python3
import hashlib
import hmac
import io
import json
import mimetypes
import os
import queue
import re
import selectors
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import traceback
import urllib.request
import urllib.error
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image, UnidentifiedImageError

SERVICE_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("NOVEL_ACTIONS_STATE_ROOT", str(SERVICE_ROOT))).resolve()
AI_ROOT = Path(os.environ.get("NOVEL_ACTIONS_AI_ROOT", "/home/admin/ai")).resolve()
TXT_ROOT = Path(os.environ.get("NOVEL_ACTIONS_TXT_ROOT", str(AI_ROOT / "txt"))).resolve()
RANKING_ROOT = TXT_ROOT / "排行榜"
DB_PATH = ROOT / "state.sqlite3"
TOKEN_PATH = ROOT / "action.token"
LOG_DIR = ROOT / "logs"
PORT = int(os.environ.get("NOVEL_ACTIONS_PORT", "8091"))
MAX_REQUEST = 90_000
MAX_RESPONSE = 95_000
MAX_CHAPTER_BATCH = 4
MAX_ASSET = 20 * 1024 * 1024
PUBLIC_PATHS = {"/health", "/openapi.json", "/privacy"}
ACCOUNT_MAP = {
    "account-a": {"name": "西大水怪", "port": 9223},
    "account-b": {"name": "桃枝醒醒", "port": 9224},
    "account-c": {"name": "泡芙软呼呼", "port": 9225},
}
STATE_FILES = {
    "context": "追踪/上下文.md",
    "characters": "追踪/角色状态.md",
    "timeline": "追踪/时间线.md",
    "foreshadowing": "追踪/伏笔.md",
    "chapter_index": "追踪/章节索引.md",
    "structured": "追踪/结构化状态.json",
    "outline": "大纲/大纲.md",
    "current_volume": "大纲/当前卷纲.md",
    "book_bible": "设定/作品圣经.md",
}
JOB_QUEUE = queue.Queue()
JOB_CONDITION = threading.Condition()
FANQIE_LOCK = threading.Lock()
MARKET_CACHE_DAYS = 30
MARKET_FAILURE_HOURS = 6
# Backend work may continue across several 35-second Action polls. Six usable
# samples stop the queue early; 8 minutes covers all 15 titles even at the
# resource-safe single-worker fallback (15 * 30 seconds plus startup margin).
MARKET_BATCH_SECONDS = 480
MARKET_BOOK_SECONDS = 60
ACTION_WAIT_SECONDS = 35


class ApiError(Exception):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    ROOT.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS ideations (
          id TEXT PRIMARY KEY, genre TEXT NOT NULL, stage TEXT NOT NULL,
          candidates_json TEXT NOT NULL, selected_no INTEGER,
          market_job_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS books (
          id TEXT PRIMARY KEY, title TEXT NOT NULL UNIQUE, path TEXT NOT NULL UNIQUE,
          ideation_id TEXT NOT NULL, account TEXT NOT NULL, stage TEXT NOT NULL,
          revision INTEGER NOT NULL DEFAULT 1, platform_book_id TEXT,
          last_qa_revision INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(ideation_id) REFERENCES ideations(id)
        );
        CREATE TABLE IF NOT EXISTS chapters (
          book_id TEXT NOT NULL, chapter_no INTEGER NOT NULL, title TEXT NOT NULL,
          file_path TEXT NOT NULL, body_chars INTEGER NOT NULL, cjk_chars INTEGER NOT NULL,
          summary TEXT NOT NULL DEFAULT '', qa_json TEXT, qa_passed INTEGER NOT NULL DEFAULT 0,
          uploaded INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
          PRIMARY KEY(book_id, chapter_no), FOREIGN KEY(book_id) REFERENCES books(id)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chapter_fts USING fts5(
          book_id UNINDEXED, chapter_no UNINDEXED, title, summary, body
        );
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL,
          payload_json TEXT NOT NULL, result_json TEXT, error TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, action TEXT NOT NULL,
          book_id TEXT, details_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS market_cache (
          cache_key TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL,
          status TEXT NOT NULL, packet_path TEXT, reason TEXT,
          verified_at TEXT NOT NULL, last_used_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS writing_batches (
          book_id TEXT PRIMARY KEY, from_chapter INTEGER NOT NULL,
          target_chapters INTEGER NOT NULL, approximate_words INTEGER NOT NULL,
          upload_mode TEXT NOT NULL, status TEXT NOT NULL,
          completed_chapters INTEGER NOT NULL DEFAULT 0,
          qa_status TEXT NOT NULL DEFAULT 'pending',
          upload_status TEXT NOT NULL DEFAULT 'pending',
          upload_job_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(book_id) REFERENCES books(id)
        );
        """)
        con.execute("UPDATE jobs SET status='needs_review', error='服务重启中断，禁止自动重试' WHERE status='running'")


def audit(action, book_id=None, details=None):
    with db() as con:
        con.execute("INSERT INTO audit(at,action,book_id,details_json) VALUES(?,?,?,?)",
                    (now_iso(), action, book_id, json_text(details or {})))


def safe_title(value):
    if value is None or not str(value).strip():
        raise ApiError(400, "书名或章节标题不能为空")
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", str(value)).strip(" ._")
    if not value or len(value) > 80:
        raise ApiError(400, "书名或章节标题无效")
    return value


def cjk_count(text):
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def row_dict(row):
    return dict(row) if row else None


def get_book(book_id):
    with db() as con:
        row = con.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not row:
        raise ApiError(404, "书籍不存在")
    item = row_dict(row)
    item["path"] = str(Path(item["path"]).resolve())
    return item


def book_dir(book):
    path = Path(book["path"]).resolve()
    if TXT_ROOT.resolve() not in path.parents:
        raise ApiError(500, "书籍路径越界")
    return path


def cover_paths(book):
    directory = book_dir(book) / "封面"
    return {
        "directory": directory,
        "config": directory / "封面配置.json",
        "prompt": directory / "封面生成提示词.md",
        "cover": directory / "封面.png",
    }


def cover_recovery_context(book):
    directory = book_dir(book)
    synopsis = ""
    info = read_limited(directory / "作品信息_番茄上传.md", 12_000)
    match = re.search(r"简介：\s*(.*?)(?:\n\s*创建状态：|\Z)", info, re.S)
    if match:
        synopsis = match.group(1).strip()
    selected = {}
    with db() as con:
        idea = con.execute("SELECT candidates_json,selected_no,genre FROM ideations WHERE id=?",
                           (book["ideation_id"],)).fetchone()
    if idea:
        candidates = json.loads(idea["candidates_json"])
        number = int(idea["selected_no"] or 0)
        if 1 <= number <= len(candidates):
            selected = candidates[number - 1]
        genre = idea["genre"]
    else:
        genre = ""
    return {
        "title": book["title"],
        "author": ACCOUNT_MAP[book["account"]]["name"],
        "account": book["account"],
        "genre": genre,
        "synopsis": synopsis,
        "selected_candidate": selected,
        "target": {"format": "PNG", "width": 600, "height": 800},
    }


def get_cover_spec(book_id):
    book = get_book(book_id)
    paths = cover_paths(book)
    if paths["config"].exists():
        try:
            spec = json.loads(paths["config"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ApiError(500, "封面配置文件损坏，需人工检查") from exc
        spec["cover_status"] = "cover_saved" if paths["cover"].exists() else "prompt_saved"
        spec["cover_path"] = str(paths["cover"]) if paths["cover"].exists() else None
        spec["prompt_path"] = str(paths["prompt"])
        spec["must_use_saved_prompt_verbatim"] = True
        spec["manual_generation_required"] = True
        spec["instruction"] = (
            "封面已保存，不要重复生成。" if spec["cover_status"] == "cover_saved" else
            "把cover_prompt逐字放入单独代码块发给用户，等待用户在全新的普通ChatGPT图片会话生成并上传；禁止调用当前GPT的图片生成能力。"
        )
        return spec
    return {
        "book_id": book_id,
        "cover_status": "missing",
        "recovery_context": cover_recovery_context(book),
        "instruction": "先依据recovery_context生成完整封面提示词并调用saveNovelCoverSpec保存；随后将已保存提示词完整发给用户手动生成，禁止调用内置图片生成。",
    }


def save_cover_spec(book_id, payload):
    book = get_book(book_id)
    prompt = str(payload.get("cover_prompt") or "").strip()
    author = ACCOUNT_MAP[book["account"]]["name"]
    if len(prompt) < 80:
        raise ApiError(400, "封面提示词过短，必须包含完整画面和文字要求")
    if book["title"] not in prompt or author not in prompt:
        raise ApiError(400, "封面提示词必须完整包含当前书名和作者名", {
            "required_title": book["title"], "required_author": author,
        })
    normalized_size = prompt.lower().replace("×", "x").replace("*", "x").replace(" ", "")
    if "600x800" not in normalized_size:
        raise ApiError(400, "封面提示词必须明确要求600×800")
    visual_brief = payload.get("visual_brief") or {}
    if not isinstance(visual_brief, dict):
        raise ApiError(400, "visual_brief必须是对象")
    paths = cover_paths(book)
    paths["directory"].mkdir(parents=True, exist_ok=True)
    stamp = now_iso()
    spec = {
        "book_id": book_id,
        "title": book["title"],
        "author": author,
        "account": book["account"],
        "cover_prompt": prompt,
        "visual_brief": visual_brief,
        "target": {"format": "PNG", "width": 600, "height": 800},
        "generator": "ChatGPT Images 2.0",
        "updated_at": stamp,
    }
    atomic_write(paths["config"], json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
    atomic_write(paths["prompt"],
                 f"# 封面生成提示词\n\n书名：{book['title']}\n\n作者：{author}\n\n"
                 f"目标尺寸：600×800 PNG\n\n{prompt}\n")
    audit("cover_spec_saved", book_id, {"prompt_chars": len(prompt)})
    return get_cover_spec(book_id)


def book_project_response(book, resumed=False):
    result = dict(book)
    result["cover_status"] = get_cover_spec(book["id"])["cover_status"]
    if resumed:
        result["resumed"] = True
        result["resume_reason"] = "同一书名和账号的项目已存在，已复用原项目"
    return result


def selected_candidate_for_ideation(idea):
    candidates = json.loads(idea["candidates_json"])
    number = int(idea["selected_no"] or 0)
    if idea["stage"] != "selected" or not 1 <= number <= len(candidates):
        raise ApiError(409, "选题记录不存在或尚未完成选择")
    return candidates[number - 1]


def validate_selected_working_title(payload, selected):
    supplied = str(payload.get("selected_working_title") or "").strip()
    expected = str(selected.get("working_title") or "").strip()
    if not supplied or normalize_title(supplied) != normalize_title(expected):
        raise ApiError(409, "建书请求中的候选标题与已选方案不一致", {
            "expected_selected_working_title": expected,
            "received_selected_working_title": supplied,
        })


def rebind_blockers(book):
    directory = book_dir(book)
    blockers = []
    with db() as con:
        chapter_count = int(con.execute(
            "SELECT COUNT(*) n FROM chapters WHERE book_id=?", (book["id"],)
        ).fetchone()["n"])
    body_files = list((directory / "正文").glob("*.md")) if (directory / "正文").exists() else []
    if book["stage"] != "trial_writing":
        blockers.append(f"stage={book['stage']}")
    if book.get("platform_book_id"):
        blockers.append("已绑定番茄作品")
    if chapter_count or body_files:
        blockers.append(f"已有正文或章节记录:{max(chapter_count, len(body_files))}")
    if cover_paths(book)["cover"].exists():
        blockers.append("已有正式封面")
    return blockers


def rebind_book_ideation(book_id, payload):
    book = get_book(book_id)
    if payload.get("confirm_rebuild") is not True:
        raise ApiError(400, "必须明确confirm_rebuild=true才能重建项目")
    title = safe_title(payload.get("title"))
    account = str(payload.get("account") or "")
    ideation_id = str(payload.get("ideation_id") or "")
    if title != book["title"] or account != book["account"]:
        raise ApiError(409, "重建请求的书名或账号与现有项目不一致", {
            "existing_title": book["title"], "existing_account": book["account"],
        })
    with db() as con:
        idea = con.execute("SELECT * FROM ideations WHERE id=?", (ideation_id,)).fetchone()
    if not idea:
        raise ApiError(404, "目标选题记录不存在")
    selected = selected_candidate_for_ideation(idea)
    validate_selected_working_title(payload, selected)
    if book["ideation_id"] == ideation_id:
        result = book_project_response(book, resumed=True)
        result.update({"rebound": False, "already_bound": True,
                       "selected_working_title": selected.get("working_title")})
        return result
    blockers = rebind_blockers(book)
    if blockers:
        raise ApiError(409, "现有项目包含不可覆盖内容，禁止重绑选题", {
            "book_id": book_id, "rebind_allowed": False, "blockers": blockers,
        })

    directory = book_dir(book)
    recovery_root = ROOT / "recovery" / "project-rebind"
    recovery_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = recovery_root / f"{book_id}-{stamp}"
    shutil.copytree(directory, backup)

    metadata = payload.get("metadata") or {}
    atomic_write(directory / "作品信息_番茄上传.md", "# 作品信息\n\n" +
                 f"书名：{title}\n\n作者笔名：{ACCOUNT_MAP[account]['name']}\n\n番茄作品ID：待绑定\n\n" +
                 f"简介：\n\n{metadata.get('synopsis','')}\n\n创建状态：本地三章试读阶段。\n")
    atomic_write(directory / "设定/作品圣经.md",
                 "# 作品圣经\n\n" + json.dumps(selected, ensure_ascii=False, indent=2) + "\n")
    for key, rel in STATE_FILES.items():
        path = directory / rel
        if key == "book_bible":
            continue
        if key == "structured":
            atomic_write(path, json.dumps({"current_world": "", "characters": [], "worlds": [], "facts": []},
                                          ensure_ascii=False, indent=2) + "\n")
        else:
            atomic_write(path, f"# {path.stem}\n\n")
    paths = cover_paths(book)
    paths["config"].unlink(missing_ok=True)
    paths["prompt"].unlink(missing_ok=True)
    with db() as con:
        con.execute("UPDATE books SET ideation_id=?,revision=revision+1,last_qa_revision=NULL,updated_at=? WHERE id=?",
                    (ideation_id, now_iso(), book_id))
    audit("book_ideation_rebound", book_id, {
        "old_ideation_id": book["ideation_id"], "new_ideation_id": ideation_id,
        "backup": str(backup),
    })
    result = book_project_response(get_book(book_id))
    result.update({"rebound": True, "already_bound": False, "backup_path": str(backup),
                   "selected_working_title": selected.get("working_title")})
    return result


def check_revision(book, expected):
    if int(expected or 0) != int(book["revision"]):
        raise ApiError(409, "书籍版本已变化，请重新读取上下文",
                       {"expected": expected, "current": book["revision"]})


def bump_revision(con, book_id):
    con.execute("UPDATE books SET revision=revision+1, updated_at=? WHERE id=?", (now_iso(), book_id))


def read_limited(path, limit=18_000):
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:limit]


def normalize_title(text):
    return re.sub(r"[^0-9a-z\u3400-\u4dbf\u4e00-\u9fff]", "", str(text).lower())


IDEA_FIELDS = {
    "number", "working_title", "hook", "emotional_promise", "heroine_engine",
    "relationship_engine", "serialization_engine", "risk", "scores",
    "novelty_constraints", "structural_fingerprint", "prior_work_comparison",
    "costume_swap_test", "scene_causality", "adversarial_review",
}
SCORE_FIELDS = {
    "originality", "emotional_fit", "opening_hook", "serialization",
    "heroine_agency", "romantic_chemistry", "fanqie_fit", "total",
}


def validate_ideation_payload(payload):
    genre = str(payload.get("genre") or "").strip()
    market_job_id = str(payload.get("market_job_id") or "").strip()
    candidates = payload.get("candidates") or []
    banned_defaults = payload.get("banned_defaults") or []
    entropy_pool = payload.get("entropy_pool") or []
    prior_work_scope = str(payload.get("prior_work_scope") or "").strip()
    if not genre:
        raise ApiError(400, "题材不能为空")
    if not market_job_id:
        raise ApiError(409, "必须关联已完成且样本充足的市场研究任务")
    if not isinstance(banned_defaults, list) or len([x for x in banned_defaults if str(x).strip()]) < 10:
        raise ApiError(400, "八项原创门禁失败：必须列出至少10个默认套路")
    if not isinstance(entropy_pool, list) or len([x for x in entropy_pool if str(x).strip()]) < 3:
        raise ApiError(400, "八项原创门禁失败：必须提供至少3个外部随机约束来源")
    if len(prior_work_scope) < 10:
        raise ApiError(400, "八项原创门禁失败：必须说明既有作品对比范围")
    with db() as con:
        job = con.execute("SELECT * FROM jobs WHERE id=?", (market_job_id,)).fetchone()
    if not job or job["type"] != "market_study" or job["status"] != "completed":
        raise ApiError(409, "市场研究任务不存在或尚未完成", {"market_job_id": market_job_id})
    result = json.loads(job["result_json"] or "{}")
    if result.get("study_status") != "ready" or int(result.get("usable_samples") or 0) < 3:
        raise ApiError(409, "市场样本不足，必须继续获取榜单书目", {
            "market_job_id": market_job_id,
            "study_status": result.get("study_status") or "unknown",
            "usable_samples": int(result.get("usable_samples") or 0),
            "required_samples": 3,
        })
    if not isinstance(candidates, list) or len(candidates) != 12:
        raise ApiError(400, "必须提交且只能提交12个候选", {
            "received_count": len(candidates) if isinstance(candidates, list) else 0,
            "required_count": 12,
        })
    errors, numbers = [], []
    for index, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, dict):
            errors.append({"index": index, "missing": sorted(IDEA_FIELDS)})
            continue
        missing = sorted(field for field in IDEA_FIELDS if field not in candidate)
        scores = candidate.get("scores")
        if isinstance(scores, dict):
            missing.extend(f"scores.{field}" for field in sorted(SCORE_FIELDS) if field not in scores)
            invalid_scores = [field for field in SCORE_FIELDS
                              if field in scores and not isinstance(scores[field], (int, float))]
            missing.extend(f"scores.{field}必须是数字" for field in sorted(invalid_scores))
        else:
            missing.append("scores")
        empty = [field for field in IDEA_FIELDS - {"number", "scores"}
                 if field in candidate and not str(candidate[field]).strip()]
        missing.extend(f"{field}不能为空" for field in sorted(empty))
        constraints = candidate.get("novelty_constraints")
        if not isinstance(constraints, list) or len([x for x in constraints if str(x).strip()]) < 2:
            missing.append("novelty_constraints至少2项")
        if isinstance(scores, dict):
            if float(scores.get("total") or 0) < 75:
                missing.append("scores.total必须至少75")
            if float(scores.get("originality") or 0) < 18:
                missing.append("scores.originality必须至少18")
            if float(scores.get("emotional_fit") or 0) < 16:
                missing.append("scores.emotional_fit必须至少16")
        if missing:
            errors.append({"index": index, "missing": sorted(set(missing))})
        try:
            numbers.append(int(candidate.get("number")))
        except (TypeError, ValueError):
            errors.append({"index": index, "invalid": "number"})
    if sorted(numbers) != list(range(1, 13)):
        errors.append({"invalid": "number必须唯一且完整覆盖1到12", "received": numbers})
    if errors:
        raise ApiError(400, "候选结构不完整", {"candidate_errors": errors[:20]})
    fingerprints = [normalize_title(x["structural_fingerprint"]) for x in candidates]
    if len(set(fingerprints)) != 12:
        raise ApiError(400, "八项原创门禁失败：候选结构指纹重复，疑似换皮")
    return genre, market_job_id, candidates


def enqueue_job(kind, payload):
    job_id = uuid.uuid4().hex
    stamp = now_iso()
    with db() as con:
        con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
                    (job_id, kind, "queued", json_text(payload), None, None, stamp, stamp))
    JOB_QUEUE.put(job_id)
    return job_id


def enqueue_upload_job(payload):
    book_id = str(payload["book_id"])
    book = get_book(book_id)
    superseded = []
    with db() as con:
        rows = con.execute("SELECT id,payload_json FROM jobs WHERE type='upload_drafts' AND status IN ('queued','running')").fetchall()
        for row in rows:
            try:
                old_payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                continue
            if str(old_payload.get("book_id")) == book_id:
                superseded.append(row["id"])
        if superseded:
            marks = ",".join("?" for _ in superseded)
            con.execute(f"UPDATE jobs SET status='superseded',error=?,updated_at=? WHERE id IN ({marks})",
                        ("被同一本书的最新上传任务取代", now_iso(), *superseded))
    if superseded and book.get("platform_book_id"):
        try:
            run_command(["sudo", "-n", "/usr/local/sbin/novel-actions-fanqie", "cancel",
                         str(book["platform_book_id"])], 30)
        except Exception:
            pass
    if superseded:
        with JOB_CONDITION:
            JOB_CONDITION.notify_all()
    job_id = enqueue_job("upload_drafts", payload)
    audit("upload_jobs_superseded", book_id, {"superseded": superseded, "latest": job_id})
    return job_id, superseded


def job_update(job_id, status, result=None, error=None):
    with db() as con:
        con.execute("UPDATE jobs SET status=?, result_json=?, error=?, updated_at=? WHERE id=?",
                    (status, json_text(result) if result is not None else None, error, now_iso(), job_id))
    with JOB_CONDITION:
        JOB_CONDITION.notify_all()


def compact_market_result(result):
    if not isinstance(result, dict):
        return result
    compact = {key: value for key, value in result.items() if key != "samples"}
    compact["samples"] = []
    for index, sample in enumerate(result.get("samples") or [], 1):
        excerpts = sample.get("excerpts") or []
        compact["samples"].append({
            "sample_index": index,
            "rank": sample.get("rank"),
            "official_title": sample.get("official_title"),
            "official_author": sample.get("official_author"),
            "cache_hit": bool(sample.get("cache_hit")),
            "excerpt_count": len(excerpts),
            "sample_detail_action": "getMarketStudySample",
        })
    compact["result_mode"] = "summary_only"
    compact["sample_detail_note"] = (
        "抽样正文保存在服务器。分析时按sample_index调用getMarketStudySample；"
        "面向用户只汇报结论，不展示抽样正文。"
    )
    return compact


def market_sample_snapshot(job_id, sample_index, excerpt_offset=0, excerpt_limit=2):
    with db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row or row["type"] != "market_study":
        raise ApiError(404, "市场研究任务不存在")
    if row["status"] != "completed":
        raise ApiError(409, "市场研究任务尚未完成", {"status": row["status"]})
    result = json.loads(row["result_json"] or "{}")
    samples = result.get("samples") or []
    if not 1 <= sample_index <= len(samples):
        raise ApiError(404, "拆书样本序号不存在", {
            "sample_index": sample_index,
            "sample_count": len(samples),
        })
    sample = samples[sample_index - 1]
    excerpts = sample.get("excerpts") or []
    excerpt_offset = max(0, int(excerpt_offset or 0))
    excerpt_limit = max(1, min(2, int(excerpt_limit or 2)))
    page = excerpts[excerpt_offset:excerpt_offset + excerpt_limit]
    next_offset = excerpt_offset + len(page)
    return {
        "job_id": job_id,
        "sample_index": sample_index,
        "sample_count": len(samples),
        "official_title": sample.get("official_title"),
        "official_author": sample.get("official_author"),
        "identity_evidence": sample.get("identity_evidence") or {},
        "structure_index": sample.get("index") or "",
        "excerpt_offset": excerpt_offset,
        "excerpt_limit": excerpt_limit,
        "excerpt_count": len(excerpts),
        "excerpts": page,
        "next_offset": next_offset if next_offset < len(excerpts) else None,
        "has_more": next_offset < len(excerpts),
        "usage_rule": "仅提取结构、节奏、钩子和情绪机制；不得向用户展示正文或复用原句。",
    }


def job_snapshot(job_id):
    with db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise ApiError(404, "任务不存在")
    item = row_dict(row)
    item["job_id"] = item["id"]
    item["payload"] = json.loads(item.pop("payload_json"))
    item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
    if item["type"] == "market_study" and item["result"]:
        item["result"] = compact_market_result(item["result"])
    return item


def wait_for_job(job_id, wait_seconds=0):
    wait_seconds = max(0, min(ACTION_WAIT_SECONDS, int(wait_seconds or 0)))
    deadline = time.monotonic() + wait_seconds
    while True:
        item = job_snapshot(job_id)
        if item["status"] not in {"queued", "running"} or time.monotonic() >= deadline:
            return item
        with JOB_CONDITION:
            JOB_CONDITION.wait(timeout=min(0.5, max(0, deadline - time.monotonic())))


def run_command(args, timeout=300, cwd=AI_ROOT):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "命令失败")[-3000:])
    return result.stdout


def run_streaming_command(args, timeout, on_event=None, cwd=AI_ROOT):
    process = subprocess.Popen(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True, bufsize=1)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    lines = []
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline:
                os.killpg(process.pid, 15)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, 9)
                raise RuntimeError(f"命令超过{timeout}秒")
            for key, _ in selector.select(timeout=0.5):
                line = key.fileobj.readline()
                if not line:
                    continue
                line = line.rstrip("\n")
                lines.append(line)
                if len(lines) > 200:
                    lines = lines[-200:]
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = None
                if event and on_event:
                    on_event(event)
        for line in process.stdout:
            lines.append(line.rstrip("\n"))
        if process.returncode:
            raise RuntimeError("\n".join(lines)[-3000:] or "命令失败")
        return "\n".join(lines)
    finally:
        selector.close()


def packet_from_directory(out_dir):
    out_dir = Path(out_dir).resolve()
    if RANKING_ROOT.resolve() not in out_dir.parents:
        raise RuntimeError("拆书目录越界")
    excerpts = []
    for path in sorted((out_dir / "selected").glob("*.txt"))[:4]:
        excerpts.append({"file": path.name, "text": read_limited(path, 1800)})
    if not excerpts:
        raise RuntimeError("拆书目录没有可用精选章节")
    metadata = {}
    if (out_dir / "source.json").exists():
        try:
            metadata = json.loads((out_dir / "source.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {}
    return {
        "packet": str(out_dir),
        "index": read_limited(out_dir / "00_拆书索引.md", 4000),
        "excerpts": excerpts,
        "identity_evidence": {
            "mirror_author": metadata.get("official_author") or metadata.get("author") or "未知",
            "mirror_chapter_count": metadata.get("mirror_chapter_count") or metadata.get("chapter_count"),
            "mirror_intro": str(metadata.get("mirror_intro") or "")[:500],
            "mirror_first_chapter_titles": (metadata.get("mirror_first_chapter_titles") or [])[:3],
            "verification_required": bool(metadata),
        },
    }


def packet_from_source(source, title):
    out_dir = RANKING_ROOT / "拆书分析" / ("action_" + safe_title(title))
    run_command(["python3", str(AI_ROOT / "scripts/prepare-novel-study.py"), str(source),
                 "--output", str(out_dir), "--front", "6", "--middle", "2", "--tail", "2"], 180)
    return packet_from_directory(out_dir)


def find_local_ranking(title):
    wanted = normalize_title(title)
    candidates = list((RANKING_ROOT / "番茄排行榜").glob("*.txt"))
    exact = [p for p in candidates if wanted and wanted in normalize_title(p.stem)]
    return exact[0] if exact else None


def market_cache_key(title):
    return normalize_title(title)


def parse_iso(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, timezone.utc)


def cache_store(title, author, status, packet_path=None, reason=None):
    stamp = now_iso()
    with db() as con:
        con.execute("""INSERT OR REPLACE INTO market_cache
                    (cache_key,title,author,status,packet_path,reason,verified_at,last_used_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (market_cache_key(title), title, author, status,
                     str(packet_path) if packet_path else None, reason, stamp, stamp))


def cache_lookup(title):
    key = market_cache_key(title)
    with db() as con:
        row = con.execute("SELECT * FROM market_cache WHERE cache_key=?", (key,)).fetchone()
    if not row:
        return None
    item = row_dict(row)
    age = datetime.now(timezone.utc) - parse_iso(item["verified_at"])
    if item["status"] == "success":
        path = Path(item.get("packet_path") or "")
        if age <= timedelta(days=MARKET_CACHE_DAYS) and path.is_dir():
            with db() as con:
                con.execute("UPDATE market_cache SET last_used_at=? WHERE cache_key=?", (now_iso(), key))
            return item
    elif item["status"] == "deterministic_failure" and age <= timedelta(hours=MARKET_FAILURE_HOURS):
        return item
    return None


def discover_packet(title):
    root = RANKING_ROOT / "拆书分析"
    if not root.exists():
        return None
    wanted = normalize_title(title)
    direct = [root / safe_title(title), root / ("action_" + safe_title(title))]
    candidates = direct + [path for path in root.iterdir() if path.is_dir() and path not in direct]
    for path in candidates:
        normalized = normalize_title(path.name.removeprefix("action_"))
        source = path / "source.json"
        if normalized != wanted or not source.exists() or not (path / "selected").is_dir():
            continue
        age = time.time() - source.stat().st_mtime
        if age <= MARKET_CACHE_DAYS * 86400:
            return path
    return None


def deterministic_failure(reason):
    reason = str(reason)
    # Search misses and source mismatches are often caused by temporary mirror
    # outages or an incomplete aggregated search. Retrying them is cheap after
    # the service has been restricted to the supported source, so only cache
    # genuinely stable input failures here.
    return "书名为空" in reason


def available_memory_mb():
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def choose_market_concurrency():
    memory = available_memory_mb()
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = 0.0
    # Fast-path mirror searches are lightweight. Aggregate SoNovel fallback
    # still fans out internally, so only use three workers with ample headroom.
    if memory >= 850 and load < 1.5:
        concurrency = 3
    elif memory >= 600 and load < 2.5:
        concurrency = 2
    else:
        concurrency = 1
    return {"concurrency": concurrency, "available_memory_mb": memory, "load_1m": round(load, 2)}


def market_study_job(payload, progress=None):
    audience = str(payload.get("audience") or "").strip()
    platform = str(payload.get("ranking_platform") or "").strip()
    attempted = [str(x).strip() for x in (payload.get("attempted_platforms") or []) if str(x).strip()]
    chains = {"男频": ["起点", "飞卢", "七猫", "番茄"], "女频": ["晋江", "七猫", "番茄"]}
    if audience not in chains:
        raise RuntimeError("audience必须为男频或女频")
    chain = chains[audience]
    expected_index = len(attempted)
    if attempted != chain[:expected_index] or expected_index >= len(chain) or platform != chain[expected_index]:
        expected = chain[expected_index] if attempted == chain[:expected_index] and expected_index < len(chain) else chain[0]
        raise RuntimeError(f"榜单来源顺序错误：{audience}当前必须使用{expected}，不得越级到{platform or '未指定平台'}")
    books = payload.get("ranking_books") or []
    if not 1 <= len(books) <= 15:
        raise RuntimeError("ranking_books数量必须为1到15")
    deduplicated, seen = [], set()
    for item in books:
        item_platform = str(item.get("source_platform") or platform).strip()
        if item_platform != platform:
            raise RuntimeError(f"榜单书目来源不一致：当前任务为{platform}，却收到{item_platform}")
        item["source_platform"] = platform
        key = market_cache_key(item.get("title") or "")
        if key and key not in seen:
            deduplicated.append(item)
            seen.add(key)
    books = deduplicated
    sample_limit = min(6, max(3, int(payload.get("sample_limit") or 6)))
    samples, skipped, remote_books = [], [], []
    started = time.monotonic()
    processed = 0
    resource = choose_market_concurrency()

    def report(phase, event=None):
        if not progress:
            return
        event = event or {}
        progress({
            "study_status": "running",
            "phase": phase,
            "processed": processed + int(event.get("processed") or 0),
            "total": len(books),
            "usable_samples": len(samples) + int(event.get("succeeded") or 0),
            "skipped_count": len(skipped) + int(event.get("skipped") or 0),
            "active_titles": event.get("active_titles") or [],
            "elapsed_seconds": round(time.monotonic() - started),
            **resource,
        })

    report("checking_cache")
    for item in books:
        if len(samples) >= sample_limit:
            break
        title = str(item.get("title") or "").strip()
        author = str(item.get("author") or "").strip()
        if not title:
            continue
        cached = cache_lookup(title)
        if not cached:
            discovered = discover_packet(title)
            if discovered:
                cache_store(title, author, "success", discovered)
                cached = cache_lookup(title)
        if cached and cached["status"] == "success":
            try:
                packet = packet_from_directory(cached["packet_path"])
                samples.append({"rank": item.get("rank"), "official_title": title,
                                "official_author": author, "mirror_file": Path(cached["packet_path"]).name,
                                "ranking_platform": platform, "cache_hit": True, **packet})
            except Exception:
                cached = None
        elif cached and cached["status"] == "deterministic_failure":
            skipped.append({"title": title, "reason": cached.get("reason") or "近期已确认不可拆取",
                            "cache_hit": True})
        if cached:
            processed += 1
            report("checking_cache")
            continue
        source = find_local_ranking(title)
        if source:
            try:
                packet = packet_from_source(source, title)
                cache_store(title, author, "success", packet["packet"])
                samples.append({"rank": item.get("rank"), "official_title": title,
                                "official_author": author, "mirror_file": source.name,
                                "ranking_platform": platform, "cache_hit": False, **packet})
            except Exception as exc:
                skipped.append({"title": title, "reason": str(exc)[-500:]})
            processed += 1
            report("preparing_local_samples")
        else:
            remote_books.append({"rank": item.get("rank"), "title": title, "author": author})

    if remote_books and len(samples) < sample_limit:
        input_path = None
        sonovel_script = AI_ROOT / "scripts/sonovel.sh"
        try:
            ROOT.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="sonovel-ranking-",
                                             dir=ROOT, encoding="utf-8", delete=False) as handle:
                json.dump(remote_books, handle, ensure_ascii=False)
                input_path = Path(handle.name)
            remaining = sample_limit - len(samples)
            output = run_streaming_command([
                str(sonovel_script), "packet-list", str(input_path),
                "--concurrency", str(resource["concurrency"]),
                "--success-limit", str(remaining),
                "--book-timeout-seconds", str(MARKET_BOOK_SECONDS),
                "--batch-timeout-seconds", str(MARKET_BATCH_SECONDS),
            ], MARKET_BATCH_SECONDS + 40, lambda event: report("downloading", event))
            paths = [Path(line.strip()) for line in output.splitlines() if line.strip().startswith("/")]
            queue_result = next((p for p in reversed(paths) if p.is_file()), None)
            if not queue_result:
                raise RuntimeError("SoNovel批量任务没有返回结果文件")
            for result in json.loads(queue_result.read_text(encoding="utf-8")):
                if len(samples) >= sample_limit:
                    break
                title = str(result.get("title") or "")
                if result.get("status") != "downloaded_needs_official_verification":
                    reason = str(result.get("reason") or "未找到可下载结果")[-500:]
                    if result.get("status") == "not_attempted":
                        skipped.append({"title": title, "reason": reason, "not_attempted": True})
                    else:
                        skipped.append({"title": title, "reason": reason})
                        if deterministic_failure(reason):
                            cache_store(title, str(result.get("author") or ""),
                                        "deterministic_failure", reason=reason)
                    continue
                packet_dir = Path(str(result.get("packet") or "").strip().splitlines()[-1])
                try:
                    packet = packet_from_directory(packet_dir)
                    cache_store(title, str(result.get("author") or ""), "success", packet_dir)
                    samples.append({"rank": result.get("rank"), "official_title": title,
                                    "official_author": str(result.get("author") or ""),
                                    "mirror_file": packet_dir.name, "ranking_platform": platform,
                                    "cache_hit": False, **packet})
                except Exception as exc:
                    skipped.append({"title": title, "reason": str(exc)[-500:]})
            processed += len([item for item in json.loads(queue_result.read_text(encoding="utf-8"))
                              if item.get("status") != "not_attempted"])
        except Exception as exc:
            reason = str(exc)[-500:]
            known = {item["title"] for item in skipped}
            skipped.extend({"title": item["title"], "reason": reason}
                           for item in remote_books if item["title"] not in known)
        finally:
            try:
                run_command([str(sonovel_script), "stop"], 30)
            except Exception:
                pass
            if input_path:
                input_path.unlink(missing_ok=True)

    ready = len(samples) >= 3
    return {
        "genre": payload.get("genre"),
        "audience": audience,
        "ranking_platform": platform,
        "attempted_platforms": attempted,
        "fallback_chain": chain,
        "study_status": "ready" if ready else "needs_more_books",
        "required_samples": 3,
        "usable_samples": len(samples),
        "samples": samples,
        "skipped": skipped,
        "performance": {**resource, "elapsed_seconds": round(time.monotonic() - started),
                        "batch_limit_seconds": MARKET_BATCH_SECONDS},
        "next_action": "生成并保存12个候选" if ready else (
            f"改用{chain[expected_index + 1]}官方榜单重新启动市场研究" if expected_index + 1 < len(chain)
            else "全部规定平台均失败，扩大最后平台榜单范围后重试，不得保存候选"),
        "identity_rule": "作者可为佚名、章节数可偏少；由GPT用简介或前几章标题确认，同一性不足则跳过。",
    }


def wait_port(port, seconds=30):
    import socket
    end = time.time() + seconds
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"浏览器端口{port}未启动")


def fanqie_session(account):
    cfg = ACCOUNT_MAP[account]
    cache = AI_ROOT / "codex/skills/fanqie-write-upload/scripts/fanqie-account-cache.sh"
    run_command(["sudo", "-n", str(cache), "switch-start", account, str(cfg["port"])], 60)
    wait_port(cfg["port"])
    identity = run_command([str(cache), "identify", str(cfg["port"])], 60).strip().splitlines()[-1]
    if identity != cfg["name"]:
        raise RuntimeError(f"账号核验失败：期望{cfg['name']}，实际{identity}")
    return cfg, cache


def finish_fanqie(cache, account):
    try:
        run_command(["sudo", "-n", str(cache), "save", account], 120)
    except Exception:
        pass


def platform_bind_job(payload):
    book = get_book(payload["book_id"])
    account = book["account"]
    cfg = ACCOUNT_MAP[account]
    runner = "/usr/local/sbin/novel-actions-fanqie"
    output = run_command(["sudo", "-n", runner, "bind", account, cfg["name"],
                          str(cfg["port"]), book["title"]], 180)
    found = json.loads(output.strip().splitlines()[-1])
    if not found.get("book_id"):
        raise RuntimeError("未找到同名番茄作品")
    with db() as con:
        con.execute("UPDATE books SET platform_book_id=?,updated_at=? WHERE id=?",
                    (found["book_id"], now_iso(), book["id"]))
    audit("platform_bound", book["id"], found)
    return found


def upload_drafts_job(payload):
    book = get_book(payload["book_id"])
    start, end = int(payload["from"]), int(payload["to"])
    if not book.get("platform_book_id"):
        raise RuntimeError("尚未绑定番茄作品")
    with db() as con:
        rows = con.execute("SELECT * FROM chapters WHERE book_id=? AND chapter_no BETWEEN ? AND ? ORDER BY chapter_no",
                           (book["id"], start, end)).fetchall()
    expected = end - start + 1
    if len(rows) != expected or any(not row["qa_passed"] for row in rows):
        raise RuntimeError("章节缺失或QA未通过")
    account = book["account"]
    cfg = ACCOUNT_MAP[account]
    output = run_command(["sudo", "-n", "/usr/local/sbin/novel-actions-fanqie", "upload",
                          account, cfg["name"], str(cfg["port"]), book["title"],
                          str(book["platform_book_id"]), str(start), str(end)],
                         max(300, expected * 300))
    result = json.loads(output.strip().splitlines()[-1])
    if int(result.get("verified") or 0) != expected:
        raise RuntimeError("草稿箱验收数量不符")
    with db() as con:
        con.execute("UPDATE chapters SET uploaded=1 WHERE book_id=? AND chapter_no BETWEEN ? AND ?",
                    (book["id"], start, end))
        batch = con.execute("SELECT * FROM writing_batches WHERE book_id=?", (book["id"],)).fetchone()
        if batch and start <= batch["from_chapter"] and end >= batch["from_chapter"] + batch["target_chapters"] - 1:
            con.execute("UPDATE writing_batches SET status='completed',upload_status='completed',updated_at=? WHERE book_id=?",
                        (now_iso(), book["id"]))
    audit("drafts_uploaded", book["id"], result)
    return result


def get_draft_status(book_id):
    book = get_book(book_id)
    with db() as con:
        chapters = con.execute("SELECT chapter_no,title,qa_passed,uploaded,updated_at FROM chapters WHERE book_id=? ORDER BY chapter_no",
                               (book_id,)).fetchall()
        verified = con.execute("SELECT at,action,details_json FROM audit WHERE book_id=? AND action IN ('drafts_uploaded','drafts_verified_manual_recovery') ORDER BY id DESC LIMIT 1",
                               (book_id,)).fetchone()
        latest_job = con.execute("SELECT id,status,error,created_at,updated_at FROM jobs WHERE type='upload_drafts' AND json_extract(payload_json,'$.book_id')=? ORDER BY created_at DESC LIMIT 1",
                                 (book_id,)).fetchone()
    verified_rows = []
    if verified:
        details = json.loads(verified["details_json"] or "{}")
        verified_rows = details.get("rows") or []
        if not verified_rows and details.get("from") and details.get("to"):
            verified_rows = [{"no": no} for no in range(int(details["from"]), int(details["to"]) + 1)]
    items = [row_dict(row) for row in chapters]
    uploaded_numbers = [row["chapter_no"] for row in items if row["uploaded"]]
    return {
        "book_id": book_id,
        "title": book["title"],
        "account": book["account"],
        "platform_book_id": book.get("platform_book_id"),
        "uploaded_chapters": uploaded_numbers,
        "all_local_chapters_uploaded": bool(items) and len(uploaded_numbers) == len(items),
        "chapters": items,
        "latest_platform_verification": ({"at": verified["at"], "action": verified["action"],
                                           "rows": verified_rows} if verified else None),
        "latest_upload_job": row_dict(latest_job),
        "authoritative_rule": "平台成功验收快照和uploaded标记代表当前已存在草稿；失败任务只代表该次尝试失败，不能据此否定已验收草稿。",
    }


def run_job(job_id):
    with db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row or row["status"] != "queued":
        return
    job_update(job_id, "running")
    payload = json.loads(row["payload_json"])
    try:
        if row["type"] == "market_study":
            result = market_study_job(payload, lambda value: job_update(job_id, "running", result=value))
        elif row["type"] == "platform_bind":
            result = platform_bind_job(payload)
        elif row["type"] == "upload_drafts":
            result = upload_drafts_job(payload)
        else:
            raise RuntimeError("未知任务类型")
        if job_snapshot(job_id)["status"] == "superseded":
            return
        job_update(job_id, "completed", result=result)
        if row["type"] == "upload_drafts":
            with db() as con:
                con.execute("UPDATE writing_batches SET upload_status='completed',status='completed',updated_at=? WHERE book_id=? AND upload_job_id=?",
                            (now_iso(), payload["book_id"], job_id))
    except Exception as exc:
        if job_snapshot(job_id)["status"] == "superseded":
            return
        job_update(job_id, "failed", error=str(exc)[-4000:])
        if row["type"] == "upload_drafts":
            with db() as con:
                con.execute("UPDATE writing_batches SET upload_status='failed',updated_at=? WHERE book_id=? AND upload_job_id=?",
                            (now_iso(), payload["book_id"], job_id))
        (LOG_DIR / f"{job_id}.log").write_text(traceback.format_exc(), encoding="utf-8")


def worker_loop():
    while True:
        run_job(JOB_QUEUE.get())
        JOB_QUEUE.task_done()


def load_defaults():
    files = [AI_ROOT / "memory/workflow-preferences.md", AI_ROOT / "memory/fanqie-book-creation-tags.md",
             AI_ROOT / "codex/skills/fanqie-novel-ideation/references/scoring-rubric.md"]
    return {"workflow": "12个候选→筛选3个→用户选1个→只写3章试读→用户批准后批量写→QA后上传草稿",
            "chapter_rules": {"minimum_cjk": 2500, "target_cjk": 3000, "batch_max": 4},
            "market_study_policy": {
                "batch_book_limit": 15,
                "target_samples": 6,
                "minimum_samples": 3,
                "stop_at_target": True,
                "attempt_full_batch_below_target": True,
                "continue_with_new_official_books_below_minimum": True,
                "action_wait_seconds": 35,
                "platform_fallback": {
                    "男频": ["起点", "飞卢", "七猫", "番茄"],
                    "女频": ["晋江", "七猫", "番茄"],
                },
            },
            "cover_policy": {
                "generate_after_account_confirmation": True,
                "prompt_must_include_title_and_author": True,
                "auto_generate_with_builtin_image_tool": False,
                "manual_generation_is_default": True,
                "show_saved_prompt_verbatim_to_user": True,
                "wait_for_user_uploaded_cover": True,
                "recommended_image_generator": "ChatGPT Images 2.0 in a separate new chat",
                "generated_cover_must_include_exact_title_and_author": True,
                "web_client_must_produce_exact_dimensions": True,
                "server_only_validates_and_saves": True,
                "final_format": "PNG",
                "final_width": 600,
                "final_height": 800,
                "relative_path": "封面/封面.png",
            },
            "resume_policy": {
                "create_project_is_idempotent_by_title_and_account": True,
                "reuse_existing_book_id_after_interruption": True,
                "never_ask_user_for_known_book_id": True,
            },
            "accounts": {k: v["name"] for k, v in ACCOUNT_MAP.items()},
            "references": [{"name": p.name, "content": read_limited(p, 14_000)} for p in files if p.exists()]}


def create_book(payload):
    ideation_id = str(payload.get("ideation_id") or "")
    title = safe_title(payload.get("title"))
    account = str(payload.get("account") or "")
    if account not in ACCOUNT_MAP:
        raise ApiError(400, "作者账号不在白名单")
    with db() as con:
        idea = con.execute("SELECT * FROM ideations WHERE id=?", (ideation_id,)).fetchone()
        if not idea:
            raise ApiError(409, "必须先完成12选3并选择一个方案")
        selected = selected_candidate_for_ideation(idea)
        validate_selected_working_title(payload, selected)
        existing = con.execute("SELECT * FROM books WHERE title=?", (title,)).fetchone()
        if existing:
            if existing["account"] != account:
                raise ApiError(409, "同名项目已存在但作者账号不一致", {
                    "title": title,
                    "existing_account": existing["account"],
                    "requested_account": account,
                })
            existing_path = Path(existing["path"]).resolve()
            if not existing_path.exists():
                raise ApiError(409, "已有项目记录的本地目录不存在，需人工检查", {
                    "book_id": existing["id"],
                    "path": str(existing_path),
                })
            if existing["ideation_id"] != ideation_id:
                current_idea = con.execute("SELECT * FROM ideations WHERE id=?",
                                           (existing["ideation_id"],)).fetchone()
                current_selected = selected_candidate_for_ideation(current_idea) if current_idea else {}
                blockers = rebind_blockers(row_dict(existing))
                raise ApiError(409, "同名项目绑定了不同选题，禁止静默复用", {
                    "code": "ideation_mismatch", "book_id": existing["id"],
                    "existing_ideation_id": existing["ideation_id"],
                    "requested_ideation_id": ideation_id,
                    "existing_selected_working_title": current_selected.get("working_title"),
                    "requested_selected_working_title": selected.get("working_title"),
                    "rebind_allowed": not blockers, "blockers": blockers,
                })
            restored = book_project_response(get_book(existing["id"]), resumed=True)
            audit("book_resumed", existing["id"], {"title": title, "account": account})
            return restored
    target = (TXT_ROOT / title).resolve()
    if target.exists():
        raise ApiError(409, "本地同名目录已存在")
    for rel in ["正文", "大纲", "设定/角色", "设定/世界观", "追踪", "分析", "封面"]:
        (target / rel).mkdir(parents=True, exist_ok=True)
    metadata = payload.get("metadata") or {}
    atomic_write(target / "作品信息_番茄上传.md", "# 作品信息\n\n" +
                 f"书名：{title}\n\n作者笔名：{ACCOUNT_MAP[account]['name']}\n\n番茄作品ID：待绑定\n\n" +
                 f"简介：\n\n{metadata.get('synopsis','')}\n\n创建状态：本地三章试读阶段。\n")
    atomic_write(target / "设定/作品圣经.md", "# 作品圣经\n\n" + json.dumps(selected, ensure_ascii=False, indent=2) + "\n")
    for key, rel in STATE_FILES.items():
        path = target / rel
        if key == "structured":
            atomic_write(path, json.dumps({"current_world": "", "characters": [], "worlds": [], "facts": []}, ensure_ascii=False, indent=2) + "\n")
        elif not path.exists():
            atomic_write(path, f"# {path.stem}\n\n")
    book_id = uuid.uuid4().hex
    stamp = now_iso()
    with db() as con:
        con.execute("INSERT INTO books(id,title,path,ideation_id,account,stage,revision,created_at,updated_at) VALUES(?,?,?,?,?,'trial_writing',1,?,?)",
                    (book_id, title, str(target), ideation_id, account, stamp, stamp))
    audit("book_created", book_id, {"title": title, "account": account})
    return book_project_response(get_book(book_id))


def chapter_file(directory, no, title):
    return directory / "正文" / f"第{no:03d}章_{safe_title(title)}.md"


def short_chapter_title(value):
    title = safe_title(value)
    title = re.sub(r"^(?:第\s*0*\d+\s*章[\s._-]*)+", "", title).strip()
    if not title:
        raise ApiError(400, "章节标题不能只有章号")
    return title


def save_chapters(book_id, payload):
    book = get_book(book_id)
    check_revision(book, payload.get("expected_revision"))
    items = payload.get("chapters") or []
    if not 1 <= len(items) <= MAX_CHAPTER_BATCH:
        raise ApiError(400, "每批必须保存1到4章")
    if book["stage"] not in {"trial_writing", "bulk_writing"}:
        raise ApiError(409, "当前阶段不允许写章")
    numbers = [int(x.get("chapter_no") or 0) for x in items]
    if len(set(numbers)) != len(numbers) or min(numbers) < 1:
        raise ApiError(400, "章节编号无效或重复")
    if book["stage"] == "trial_writing" and any(n > 3 for n in numbers):
        raise ApiError(409, "三章试读未批准，不能写第4章")
    directory = book_dir(book)
    prepared = []
    for item in items:
        no = int(item["chapter_no"])
        title = short_chapter_title(item.get("title"))
        body = str(item.get("body") or "").strip() + "\n"
        if len(body) > 20_000 or cjk_count(body) < 100:
            raise ApiError(400, f"第{no:03d}章正文长度无效")
        prepared.append((no, title, body, str(item.get("summary") or "")))
    with db() as con:
        for no, title, body, summary in prepared:
            old = con.execute("SELECT file_path FROM chapters WHERE book_id=? AND chapter_no=?", (book_id, no)).fetchone()
            path = chapter_file(directory, no, title)
            if old and Path(old["file_path"]) != path and Path(old["file_path"]).exists():
                Path(old["file_path"]).unlink()
            atomic_write(path, body)
            con.execute("INSERT OR REPLACE INTO chapters(book_id,chapter_no,title,file_path,body_chars,cjk_chars,summary,qa_json,qa_passed,uploaded,updated_at) VALUES(?,?,?,?,?,?,?,NULL,0,COALESCE((SELECT uploaded FROM chapters WHERE book_id=? AND chapter_no=?),0),?)",
                        (book_id, no, title, str(path), len(body.strip()), cjk_count(body), summary, book_id, no, now_iso()))
            con.execute("DELETE FROM chapter_fts WHERE book_id=? AND chapter_no=?", (book_id, no))
            con.execute("INSERT INTO chapter_fts VALUES(?,?,?,?,?)", (book_id, no, title, summary, body))
        bump_revision(con, book_id)
        count = con.execute("SELECT COUNT(*) n FROM chapters WHERE book_id=? AND chapter_no BETWEEN 1 AND 3", (book_id,)).fetchone()["n"]
        if book["stage"] == "trial_writing" and count == 3:
            con.execute("UPDATE books SET stage='awaiting_trial_approval' WHERE id=?", (book_id,))
    audit("chapters_saved", book_id, {"numbers": numbers})
    refresh_writing_batch(book_id)
    return get_book(book_id)


def update_state(book_id, payload):
    book = get_book(book_id)
    check_revision(book, payload.get("expected_revision"))
    state = payload.get("state") or {}
    directory = book_dir(book)
    for key, value in state.items():
        if key not in STATE_FILES:
            continue
        path = directory / STATE_FILES[key]
        if key == "structured":
            atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        else:
            atomic_write(path, str(value).strip() + "\n")
    with db() as con:
        bump_revision(con, book_id)
    audit("state_updated", book_id, {"keys": sorted(state)})
    return get_book(book_id)


def get_context(book_id, query=""):
    book = get_book(book_id)
    directory = book_dir(book)
    state_limits = {
        "context": 8000, "structured": 8000, "characters": 5000,
        "timeline": 5000, "foreshadowing": 5000, "chapter_index": 5000,
        "outline": 5000, "current_volume": 5000, "book_bible": 5000,
    }
    states = {key: read_limited(directory / rel, state_limits[key]) for key, rel in STATE_FILES.items()}
    with db() as con:
        latest = con.execute("SELECT * FROM chapters WHERE book_id=? ORDER BY chapter_no DESC LIMIT 3", (book_id,)).fetchall()
        related = []
        if query.strip():
            try:
                related = con.execute("SELECT chapter_no,title,snippet(chapter_fts,4,'','','…',20) body FROM chapter_fts WHERE book_id=? AND chapter_fts MATCH ? LIMIT 5", (book_id, query)).fetchall()
            except sqlite3.OperationalError:
                related = []
    chapters = []
    for row in reversed(latest):
        chapters.append({"chapter_no": row["chapter_no"], "title": row["title"],
                         "body": read_limited(Path(row["file_path"]), 6000)})
    return {"book": {k: book[k] for k in ("id", "title", "stage", "revision", "account", "platform_book_id")},
            "state": states, "latest_chapters": chapters, "related": [row_dict(x) for x in related],
            "instruction": "必须以服务器状态为准；发现冲突先报告，不得猜测。"}


def get_writing_batch(book_id):
    get_book(book_id)
    with db() as con:
        row = con.execute("SELECT * FROM writing_batches WHERE book_id=?", (book_id,)).fetchone()
    if not row:
        return {"book_id": book_id, "status": "not_configured",
                "instruction": "首次三章批准后，每次写正文前必须先询问数量和上传方式。"}
    return row_dict(row)


def configure_writing_batch(book_id, payload):
    book = get_book(book_id)
    if book["stage"] != "bulk_writing":
        raise ApiError(409, "首次三章尚未批准，不能配置后续写作批次")
    chapters = int(payload.get("target_chapters") or 0)
    words = int(payload.get("approximate_words") or 0)
    if bool(chapters) == bool(words):
        raise ApiError(400, "必须且只能指定章节数或大约字数其中一项")
    if words:
        if not 2500 <= words <= 300_000:
            raise ApiError(400, "大约字数必须为2500到300000")
        chapters = (words + 2999) // 3000
    elif not 1 <= chapters <= 100:
        raise ApiError(400, "章节数必须为1到100")
    mode = str(payload.get("upload_mode") or "")
    if mode not in {"auto", "review"}:
        raise ApiError(400, "upload_mode必须为auto或review")
    with db() as con:
        current = con.execute("SELECT * FROM writing_batches WHERE book_id=?", (book_id,)).fetchone()
        if current and current["status"] not in {"completed", "cancelled"}:
            raise ApiError(409, "已有未完成写作批次，请先完成后再创建新批次", row_dict(current))
        next_no = int(con.execute("SELECT COALESCE(MAX(chapter_no),0)+1 n FROM chapters WHERE book_id=?",
                                  (book_id,)).fetchone()["n"])
        stamp = now_iso()
        con.execute("INSERT OR REPLACE INTO writing_batches(book_id,from_chapter,target_chapters,approximate_words,upload_mode,status,completed_chapters,qa_status,upload_status,upload_job_id,created_at,updated_at) VALUES(?,?,?,?,?,'writing',0,'pending','pending',NULL,?,?)",
                    (book_id, next_no, chapters, words or chapters * 3000, mode, stamp, stamp))
    audit("writing_batch_configured", book_id, {"from": next_no, "chapters": chapters,
                                                 "approximate_words": words or chapters * 3000,
                                                 "upload_mode": mode})
    return get_writing_batch(book_id)


def refresh_writing_batch(book_id):
    with db() as con:
        batch = con.execute("SELECT * FROM writing_batches WHERE book_id=?", (book_id,)).fetchone()
        if not batch or batch["status"] in {"completed", "cancelled"}:
            return row_dict(batch)
        start = batch["from_chapter"]
        end = start + batch["target_chapters"] - 1
        rows = con.execute("SELECT chapter_no,qa_passed FROM chapters WHERE book_id=? AND chapter_no BETWEEN ? AND ?",
                           (book_id, start, end)).fetchall()
        completed = len(rows)
        all_ready = completed == batch["target_chapters"]
        qa_ready = all_ready and all(row["qa_passed"] for row in rows)
        status = "ready_for_upload" if qa_ready else ("qa_pending" if all_ready else "writing")
        qa_status = "passed" if qa_ready else ("pending" if not all_ready else "failed_or_pending")
        con.execute("UPDATE writing_batches SET completed_chapters=?,status=?,qa_status=?,updated_at=? WHERE book_id=?",
                    (completed, status, qa_status, now_iso(), book_id))
    return get_writing_batch(book_id)


def shingle_set(text, width=20):
    text = re.sub(r"\s+", "", text)
    return {text[i:i + width] for i in range(max(0, len(text) - width + 1))}


def run_qa(book_id, payload):
    book = get_book(book_id)
    review = payload.get("originality_review") or {}
    required_reviews = ("scene_causality_checked", "cross_work_swap_checked", "ai_pattern_reviewed")
    if any(review.get(key) is not True for key in required_reviews) or len(str(review.get("notes") or "").strip()) < 20:
        raise ApiError(400, "八项原创门禁失败：QA必须包含场景因果、跨书换皮和独立AI模板审查")
    start, end = int(payload.get("from") or 1), int(payload.get("to") or 10**9)
    with db() as con:
        rows = con.execute("SELECT * FROM chapters WHERE book_id=? AND chapter_no BETWEEN ? AND ? ORDER BY chapter_no", (book_id, start, end)).fetchall()
        all_rows = con.execute("SELECT * FROM chapters WHERE book_id=? ORDER BY chapter_no", (book_id,)).fetchall()
    bodies = {row["chapter_no"]: Path(row["file_path"]).read_text(encoding="utf-8") for row in all_rows}
    long_paras = {}
    for no, body in bodies.items():
        for para in re.split(r"\n\s*\n", body):
            compact = re.sub(r"\s+", "", para)
            if len(compact) >= 80:
                long_paras.setdefault(compact, []).append(no)
    duplicate_paras = {p: nos for p, nos in long_paras.items() if len(set(nos)) > 1}
    structured = {}
    structured_path = book_dir(book) / STATE_FILES["structured"]
    if structured_path.exists():
        try:
            structured = json.loads(structured_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            structured = {}
    results = []
    shingles = {no: shingle_set(body) for no, body in bodies.items()}
    for row in rows:
        no, title, body = row["chapter_no"], row["title"], bodies[row["chapter_no"]]
        errors, warnings = [], []
        if cjk_count(body) < 2500:
            errors.append("中文汉字少于2500")
        if title in body:
            errors.append("标题出现在正文")
        if re.search(rf"第\s*0*{no}\s*章", body):
            errors.append("章节编号出现在正文")
        if any(no in nos for nos in duplicate_paras.values()):
            errors.append("存在跨章重复长段落")
        for other, other_set in shingles.items():
            if other == no or not shingles[no] or not other_set:
                continue
            ratio = len(shingles[no] & other_set) / max(1, min(len(shingles[no]), len(other_set)))
            if ratio > 0.08:
                warnings.append(f"与第{other:03d}章相似度偏高:{ratio:.2%}")
        for char in structured.get("characters", []):
            name = str(char.get("name") or "")
            dead_after = char.get("dead_after_chapter")
            if name and dead_after and no > int(dead_after) and name in body and re.search(re.escape(name) + r".{0,80}[“\"]", body, re.S):
                warnings.append(f"已死亡角色{name}疑似再次对话")
        passed = not errors
        result = {"chapter_no": no, "passed": passed, "errors": errors, "warnings": warnings,
                  "cjk_chars": cjk_count(body), "body_chars": len(body.strip())}
        results.append(result)
    with db() as con:
        for result in results:
            con.execute("UPDATE chapters SET qa_json=?,qa_passed=? WHERE book_id=? AND chapter_no=?",
                        (json_text(result), 1 if result["passed"] else 0, book_id, result["chapter_no"]))
        if results and all(x["passed"] for x in results):
            con.execute("UPDATE books SET last_qa_revision=revision WHERE id=?", (book_id,))
    audit("qa_run", book_id, {"from": start, "to": end, "passed": all(x["passed"] for x in results)})
    batch = refresh_writing_batch(book_id)
    auto_job_id = None
    if batch and batch.get("status") == "ready_for_upload" and batch.get("upload_mode") == "auto":
        book = get_book(book_id)
        if not book.get("platform_book_id"):
            with db() as con:
                con.execute("UPDATE writing_batches SET upload_status='blocked_unbound',updated_at=? WHERE book_id=?",
                            (now_iso(), book_id))
        elif batch.get("upload_status") not in {"queued", "running", "completed"}:
            batch_end = batch["from_chapter"] + batch["target_chapters"] - 1
            auto_job_id, _ = enqueue_upload_job({"book_id": book_id,
                                                 "from": batch["from_chapter"], "to": batch_end})
            with db() as con:
                con.execute("UPDATE writing_batches SET upload_status='queued',upload_job_id=?,updated_at=? WHERE book_id=?",
                            (auto_job_id, now_iso(), book_id))
            batch = get_writing_batch(book_id)
    return {"passed": bool(results) and all(x["passed"] for x in results), "chapters": results,
            "writing_batch": batch, "auto_upload_job_id": auto_job_id,
            "semantic_check_required": ["人物动机", "感情递进", "隐性时间冲突", "标题内容匹配", "八项原创门禁"],
            "originality_review": review}


def approve_trial(book_id):
    book = get_book(book_id)
    if book["stage"] != "awaiting_trial_approval":
        raise ApiError(409, "当前不在三章审批阶段")
    with db() as con:
        rows = con.execute("SELECT qa_passed FROM chapters WHERE book_id=? AND chapter_no BETWEEN 1 AND 3", (book_id,)).fetchall()
        if len(rows) != 3 or any(not x["qa_passed"] for x in rows):
            raise ApiError(409, "前三章必须全部通过QA")
        con.execute("UPDATE books SET stage='bulk_writing',updated_at=? WHERE id=?", (now_iso(), book_id))
    audit("trial_approved", book_id)
    return get_book(book_id)


def save_assets(book_id, payload):
    book = get_book(book_id)
    refs = payload.get("openaiFileIdRefs") or []
    if len(refs) != 1:
        raise ApiError(400, "封面保存必须且只能提交1张当前对话生成的最终封面图片")
    cover_prompt = str(payload.get("cover_prompt") or "").strip()
    author_name = ACCOUNT_MAP.get(book["account"], {}).get("name") or ""
    if not cover_prompt:
        raise ApiError(400, "必须同时提交实际使用的封面生成提示词")
    if book["title"] not in cover_prompt or author_name not in cover_prompt:
        raise ApiError(400, "封面提示词必须完整包含书名和作者名", {
            "required_title": book["title"],
            "required_author": author_name,
        })
    stored_spec = get_cover_spec(book_id)
    if stored_spec["cover_status"] == "missing":
        raise ApiError(409, "必须先保存封面提示词，再生成和提交封面")
    if cover_prompt != stored_spec["cover_prompt"]:
        raise ApiError(409, "提交的提示词与服务器保存版本不一致，必须逐字使用已保存提示词")
    if payload.get("image_text_verified") is not True:
        raise ApiError(400, "提交前必须核对封面中的书名、作者名和题材画面")
    saved = []
    for index, ref in enumerate(refs, 1):
        if isinstance(ref, str):
            url = ref
            mime_type = ""
        elif isinstance(ref, dict):
            url = str(ref.get("download_link") or "")
            mime_type = str(ref.get("mime_type") or "").lower()
        else:
            raise ApiError(400, "素材引用格式无效")
        if not url.startswith("https://"):
            raise ApiError(400, "素材下载地址必须使用HTTPS")
        if mime_type and not mime_type.startswith("image/"):
            raise ApiError(400, "封面素材必须是图片", {"mime_type": mime_type})
        req = urllib.request.Request(url, headers={"User-Agent": "novel-actions/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                data = response.read(MAX_ASSET + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise ApiError(502, "封面图片下载失败，文件链接可能已过期，请用当前刚生成的图片立即重试", {
                "reason": str(exc)[:200],
            }) from exc
        if len(data) > MAX_ASSET:
            raise ApiError(413, "素材超过20MB")
        try:
            with Image.open(io.BytesIO(data)) as source:
                source.load()
                if source.width < 300 or source.height < 400:
                    raise ApiError(400, "封面图片分辨率过低", {
                        "received_width": source.width,
                        "received_height": source.height,
                    })
                if source.format != "PNG":
                    raise ApiError(400, "封面必须由网页版准备为PNG格式，服务器不会转换格式", {
                        "received_format": source.format,
                    })
                if source.size != (600, 800):
                    raise ApiError(400, "封面必须由网页版准备为600×800，服务器不会裁剪或缩放", {
                        "received_width": source.width,
                        "received_height": source.height,
                    })
                cover_bytes = data
        except (UnidentifiedImageError, OSError) as exc:
            raise ApiError(400, "无法识别封面图片内容") from exc
        target = book_dir(book) / "封面" / "封面.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".png.tmp")
        temporary.write_bytes(cover_bytes)
        os.replace(temporary, target)
        saved.append(str(target))
    audit("assets_saved", book_id, {"count": len(saved), "cover_size": "600x800"})
    return {"saved": saved, "cover_path": saved[0],
            "width": 600, "height": 800, "image_text_verified": True,
            "text_source": "chatgpt_images_2", "server_modified_image": False,
            "title": book["title"], "author": author_name,
            "prompt_path": str(book_dir(book) / "封面" / "封面生成提示词.md")}


def parse_json_body(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise ApiError(400, "Content-Length无效")
    if length > MAX_REQUEST:
        raise ApiError(413, "请求超过90,000字符限制")
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise ApiError(400, "JSON无效")


def response_bytes(value):
    raw = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    if len(raw) > MAX_RESPONSE:
        raise ApiError(500, "响应超过限制，请缩小查询范围")
    return raw


class Handler(BaseHTTPRequestHandler):
    server_version = "NovelActions/1.0"

    def log_message(self, fmt, *args):
        with (LOG_DIR / "access.log").open("a", encoding="utf-8") as f:
            f.write(f"{now_iso()} {self.client_address[0]} {fmt % args}\n")

    def send_json(self, value, status=200):
        raw = response_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def send_html(self, value, status=200):
        raw = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def authenticate(self, path):
        if path in PUBLIC_PATHS:
            return
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        supplied = [
            self.headers.get("Authorization", ""),
            self.headers.get("X-API-Key", ""),
            self.headers.get("Api-Key", ""),
        ]
        valid = any(
            value and (hmac.compare_digest(value, token) or hmac.compare_digest(value, "Bearer " + token))
            for value in supplied
        )
        if not valid:
            raise ApiError(401, "认证失败")

    def handle_api(self, method):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        self.authenticate(path)
        body = parse_json_body(self) if method in {"POST", "PUT"} else {}
        if method == "GET" and path == "/health":
            return {"ok": True, "service": "novel-actions", "time": now_iso()}
        if method == "GET" and path == "/openapi.json":
            return json.loads((SERVICE_ROOT / "openapi.json").read_text(encoding="utf-8"))
        if method == "GET" and path == "/v1/defaults":
            return load_defaults()
        if method == "POST" and path == "/v1/market-jobs":
            payload = dict(body)
            wait_seconds = payload.pop("wait_seconds", ACTION_WAIT_SECONDS)
            job_id = enqueue_job("market_study", payload)
            return wait_for_job(job_id, wait_seconds)
        m = re.fullmatch(r"/v1/jobs/([0-9a-f]+)", path)
        if method == "GET" and m:
            wait_seconds = (query.get("wait_seconds") or [str(ACTION_WAIT_SECONDS)])[0]
            return wait_for_job(m.group(1), wait_seconds)
        m = re.fullmatch(r"/v1/market-jobs/([0-9a-f]+)/samples/(\d+)", path)
        if method == "GET" and m:
            excerpt_offset = (query.get("excerpt_offset") or ["0"])[0]
            excerpt_limit = (query.get("excerpt_limit") or ["2"])[0]
            return market_sample_snapshot(m.group(1), int(m.group(2)),
                                          excerpt_offset, excerpt_limit)
        if method == "POST" and path == "/v1/ideations":
            genre, market_job_id, candidates = validate_ideation_payload(body)
            ideation_id, stamp = uuid.uuid4().hex, now_iso()
            with db() as con:
                con.execute("INSERT INTO ideations VALUES(?,?,'awaiting_selection',?,NULL,?,?,?)",
                            (ideation_id, genre, json_text(candidates), market_job_id, stamp, stamp))
            return {"ideation_id": ideation_id, "stage": "awaiting_selection", "count": 12}
        m = re.fullmatch(r"/v1/ideations/([0-9a-f]+)/select", path)
        if method == "POST" and m:
            number = int(body.get("candidate_no") or 0)
            if not 1 <= number <= 12:
                raise ApiError(400, "candidate_no必须为1到12")
            with db() as con:
                row = con.execute("SELECT * FROM ideations WHERE id=?", (m.group(1),)).fetchone()
                if not row or row["stage"] != "awaiting_selection":
                    raise ApiError(409, "选题记录不存在或已选择")
                con.execute("UPDATE ideations SET selected_no=?,stage='selected',updated_at=? WHERE id=?", (number, now_iso(), m.group(1)))
            return {"ideation_id": m.group(1), "selected_no": number, "stage": "selected"}
        if method == "POST" and path == "/v1/books":
            return create_book(body)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/ideation-rebind", path)
        if method == "POST" and m:
            return rebind_book_ideation(m.group(1), body)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/cover-spec", path)
        if method == "GET" and m:
            return get_cover_spec(m.group(1))
        if method == "PUT" and m:
            return save_cover_spec(m.group(1), body)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/context", path)
        if method == "GET" and m:
            return get_context(m.group(1), (query.get("query") or [""])[0])
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/writing-batch", path)
        if method == "GET" and m:
            return get_writing_batch(m.group(1))
        if method == "PUT" and m:
            return configure_writing_batch(m.group(1), body)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/chapters", path)
        if method == "POST" and m:
            return save_chapters(m.group(1), body)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/state", path)
        if method == "PUT" and m:
            return update_state(m.group(1), body)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/qa", path)
        if method == "POST" and m:
            return run_qa(m.group(1), body)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/trial-approval", path)
        if method == "POST" and m:
            return approve_trial(m.group(1))
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/platform-bind-jobs", path)
        if method == "POST" and m:
            book = get_book(m.group(1))
            if book["stage"] != "bulk_writing":
                raise ApiError(409, "三章试读未批准")
            return {"job_id": enqueue_job("platform_bind", {"book_id": m.group(1)}), "status": "queued"}
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/draft-upload-jobs", path)
        if method == "POST" and m:
            book = get_book(m.group(1))
            if book["stage"] != "bulk_writing":
                raise ApiError(409, "当前阶段禁止上传")
            start, end = int(body.get("from") or 0), int(body.get("to") or 0)
            if start < 1 or end < start or end - start > 99:
                raise ApiError(400, "上传章节范围无效")
            job_id, superseded = enqueue_upload_job({"book_id": m.group(1), "from": start, "to": end})
            return {"job_id": job_id, "status": "queued", "superseded_job_ids": superseded,
                    "deduplication": "同一本书只保留最新上传任务"}
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/draft-status", path)
        if method == "GET" and m:
            return get_draft_status(m.group(1))
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/assets", path)
        if method == "POST" and m:
            return save_assets(m.group(1), body)
        raise ApiError(404, "接口不存在")

    def dispatch(self, method):
        try:
            path = urlparse(self.path).path
            if method == "GET" and path == "/openapi.json":
                self.send_json(json.loads((SERVICE_ROOT / "openapi.json").read_text(encoding="utf-8")))
                return
            if method == "GET" and path == "/privacy":
                self.send_html("""<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><title>隐私说明</title><body><main><h1>小叮当长篇小说工作台隐私说明</h1><p>本服务仅处理私人小说资料，正文保存在用户自己的服务器。</p><p>服务不出售数据，认证密钥不写入访问日志。番茄发布不在服务能力范围内，最终发布由用户手动完成。</p></main></body></html>""")
                return
            self.send_json({"ok": True, "data": self.handle_api(method)})
        except ApiError as exc:
            self.send_json({"ok": False, "error": exc.message, "details": exc.details}, exc.status)
        except Exception as exc:
            incident = uuid.uuid4().hex[:12]
            (LOG_DIR / f"incident-{incident}.log").write_text(traceback.format_exc(), encoding="utf-8")
            self.send_json({"ok": False, "error": "服务器内部错误", "incident": incident}, 500)

    do_GET = lambda self: self.dispatch("GET")
    do_POST = lambda self: self.dispatch("POST")
    do_PUT = lambda self: self.dispatch("PUT")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET,POST,PUT,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()


def main():
    init_db()
    if not TOKEN_PATH.exists() or not TOKEN_PATH.read_text(encoding="utf-8").strip():
        raise SystemExit("Missing action.token")
    threading.Thread(target=worker_loop, daemon=True, name="novel-job-worker").start()
    with db() as con:
        for row in con.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at"):
            JOB_QUEUE.put(row["id"])
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"novel-actions listening on 127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
