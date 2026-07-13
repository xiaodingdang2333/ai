#!/usr/bin/env python3
import hashlib
import hmac
import io
import json
import difflib
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
PUBLIC_PATHS = {"/health", "/openapi.json", "/openapi-gpt.json", "/openapi-writer.json", "/privacy"}
WRITER_OPENAPI_OPERATIONS = {
    "findNovelProject",
    "getNovelWritingContext",
    "getNovelWritingResume",
    "createNovelWritingContract",
    "reviewNovelWritingSegment",
    "getNovelRevisionResume",
    "configureNovelRevision",
    "approveNovelRevision",
    "commitNovelChapterCheckpoint",
    "getNovelChapterDrafts",
    "runNovelQualityChecks",
}
GPT_OPENAPI_OMITTED_OPERATIONS = {
    "getNovelWorkflowDefaults",
    "importExistingNovelProject",
    "getNovelWritingBatch",
    "getNovelWritingContract",
    "getNovelRevisionBatch",
    "rebindNovelProjectIdeation",
}
NOVEL_WORKFLOW_ACTIONS = {
    "defaults", "market_start", "market_sample", "ideation_save", "ideation_select",
    "book_find", "book_import", "book_create", "book_rebind", "cover_get", "cover_save",
    "context_get", "drafts_get", "writing_get", "writing_configure", "writing_resume",
    "contract_create", "contract_get", "contract_review", "revision_configure",
    "revision_resume", "revision_get", "revision_approve", "checkpoint_commit",
    "trial_chapters_save", "state_update", "quality_check", "trial_approve",
    "writing_approve", "candidate_save", "candidate_critique", "candidate_revise",
    "candidate_verify",
}
WORKFLOW_TRANSITION_ACTIONS = {
    "trial_chapters_save", "state_update", "quality_check", "trial_approve", "writing_approve",
    "writing_configure", "contract_create", "contract_review", "revision_configure", "revision_approve",
    "candidate_save", "candidate_critique", "candidate_revise", "candidate_verify", "checkpoint_commit",
}
FANQIE_WORKFLOW_ACTIONS = {"bind", "upload", "status"}
QUALITY_PROFILE = {
    "minimum_cjk_chars": 2500,
    "target_cjk_chars": [2600, 3200],
    "maximum_short_paragraph_ratio": 0.60,
    "maximum_consecutive_short_paragraphs": 5,
    "maximum_dialogue_paragraph_ratio": 0.65,
    "maximum_ai_phrase_count": 7,
    "maximum_report_terms_per_1000_cjk": 8,
}
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


def load_openapi(gpt_import=False):
    spec = json.loads((SERVICE_ROOT / "openapi.json").read_text(encoding="utf-8"))
    if not gpt_import:
        return spec
    return load_unified_openapi(spec)


def load_unified_openapi(source=None):
    source = source or load_openapi()
    payload_schema = {
        "type": "object",
        "required": ["action", "payload"],
        "properties": {
            "action": {"type": "string", "enum": sorted(NOVEL_WORKFLOW_ACTIONS)},
            "book_id": {"type": "string"},
            "payload": {"type": "object", "additionalProperties": True,
                        "description": "直接提交JSON对象；按next_action.payload_schema填写，不要再次序列化为字符串。"},
            "payload_json": {"type": "string", "description": "仅供旧客户端兼容，新调用禁止使用。"},
        },
    }
    fanqie_schema = {
        "type": "object",
        "required": ["action", "book_id", "payload"],
        "properties": {
            "action": {"type": "string", "enum": sorted(FANQIE_WORKFLOW_ACTIONS)},
            "book_id": {"type": "string"},
            "payload": {"type": "object", "additionalProperties": True},
            "payload_json": {"type": "string", "description": "仅供旧客户端兼容，新调用禁止使用。"},
        },
    }
    asset_operation = source["paths"]["/v1/books/{book_id}/assets"]["post"]
    return {
        "openapi": source["openapi"],
        "info": {"title": "Novel", "version": "2"},
        "servers": source["servers"],
        "security": source["security"],
        "paths": {
            "/v1/actions/novel": {"post": {
                "operationId": "runNovelWorkflow",
                "x-openai-isConsequential": False,
                "requestBody": {"required": True, "content": {"application/json": {"schema": payload_schema}}},
                "responses": {"200": {"description": ""}},
            }},
            "/v1/actions/fanqie": {"post": {
                "operationId": "runFanqieWorkflow",
                "x-openai-isConsequential": False,
                "requestBody": {"required": True, "content": {"application/json": {"schema": fanqie_schema}}},
                "responses": {"200": {"description": ""}},
            }},
            "/v1/actions/job": {"post": {
                "operationId": "getNovelJob",
                "x-openai-isConsequential": False,
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "required": ["job_id"], "properties": {
                        "job_id": {"type": "string"},
                        "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 35},
                    }}}}},
                "responses": {"200": {"description": ""}},
            }},
            "/v1/books/{book_id}/assets": {"post": asset_operation},
        },
        "components": source.get("components", {}),
    }


def load_writer_openapi():
    source = load_openapi()

    def clean_schema(value):
        if isinstance(value, dict):
            return {
                key: clean_schema(item) for key, item in value.items()
                if key not in {"description", "summary", "x-openai-isConsequential"}
            }
        if isinstance(value, list):
            return [clean_schema(item) for item in value]
        return value

    paths = {}
    for path, path_item in source["paths"].items():
        kept = {}
        for method, operation in path_item.items():
            if not isinstance(operation, dict) or operation.get("operationId") not in WRITER_OPENAPI_OPERATIONS:
                continue
            compact = {
                "operationId": operation["operationId"],
                "responses": {"200": {"description": ""}},
            }
            if operation.get("parameters"):
                compact["parameters"] = clean_schema(operation["parameters"])
            if operation.get("requestBody"):
                compact["requestBody"] = clean_schema(operation["requestBody"])
            kept[method] = compact
        if kept:
            paths[path] = kept
    return {
        "openapi": source["openapi"],
        "info": {"title": "Writer", "version": "1"},
        "servers": source["servers"],
        "security": source["security"],
        "paths": paths,
        "components": source.get("components", {}),
    }


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
        CREATE TABLE IF NOT EXISTS chapter_drafts (
          book_id TEXT NOT NULL, chapter_no INTEGER NOT NULL, title TEXT NOT NULL,
          file_path TEXT NOT NULL, body_chars INTEGER NOT NULL, cjk_chars INTEGER NOT NULL,
          summary TEXT NOT NULL DEFAULT '', draft_revision INTEGER NOT NULL DEFAULT 1,
          qa_json TEXT, qa_passed INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'drafting', updated_at TEXT NOT NULL,
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
        CREATE TABLE IF NOT EXISTS chapter_checkpoints (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          book_id TEXT NOT NULL, chapter_no INTEGER NOT NULL,
          idempotency_key TEXT NOT NULL, title TEXT NOT NULL,
          body TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
          state_json TEXT NOT NULL, committed_revision INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(book_id, idempotency_key),
          FOREIGN KEY(book_id) REFERENCES books(id)
        );
        CREATE TABLE IF NOT EXISTS revision_batches (
          id TEXT PRIMARY KEY, book_id TEXT NOT NULL, target_json TEXT NOT NULL,
          mode TEXT NOT NULL, status TEXT NOT NULL,
          completed_chapters INTEGER NOT NULL DEFAULT 0,
          qa_status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(book_id) REFERENCES books(id)
        );
        CREATE TABLE IF NOT EXISTS writing_contracts (
          id TEXT PRIMARY KEY, book_id TEXT NOT NULL,
          segment_from INTEGER NOT NULL, segment_to INTEGER NOT NULL,
          status TEXT NOT NULL, contract_json TEXT NOT NULL,
          review_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          revision_batch_id TEXT,
          UNIQUE(book_id, segment_from, segment_to, revision_batch_id),
          FOREIGN KEY(book_id) REFERENCES books(id)
        );
        CREATE TABLE IF NOT EXISTS chapter_review_cycles (
          book_id TEXT NOT NULL, chapter_no INTEGER NOT NULL,
          revision_batch_id TEXT NOT NULL DEFAULT '', contract_id TEXT NOT NULL,
          candidate_revision INTEGER NOT NULL DEFAULT 1,
          title TEXT NOT NULL, body TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL, critique_json TEXT, changes_json TEXT,
          verification_json TEXT, review_round INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY(book_id, chapter_no, revision_batch_id),
          FOREIGN KEY(book_id) REFERENCES books(id)
        );
        """)
        batch_columns = {row[1] for row in con.execute("PRAGMA table_info(writing_batches)")}
        if "quality_mode" not in batch_columns:
            con.execute("ALTER TABLE writing_batches ADD COLUMN quality_mode TEXT NOT NULL DEFAULT 'legacy'")
        revision_columns = {row[1] for row in con.execute("PRAGMA table_info(revision_batches)")}
        if "quality_mode" not in revision_columns:
            con.execute("ALTER TABLE revision_batches ADD COLUMN quality_mode TEXT NOT NULL DEFAULT 'legacy'")
        contract_columns = {row[1] for row in con.execute("PRAGMA table_info(writing_contracts)")}
        if "revision_batch_id" not in contract_columns:
            con.execute("ALTER TABLE writing_contracts ADD COLUMN revision_batch_id TEXT")
        checkpoint_columns = {row[1] for row in con.execute("PRAGMA table_info(chapter_checkpoints)")}
        if "revision_batch_id" not in checkpoint_columns:
            con.execute("ALTER TABLE chapter_checkpoints ADD COLUMN revision_batch_id TEXT")
        if "contract_id" not in checkpoint_columns:
            con.execute("ALTER TABLE chapter_checkpoints ADD COLUMN contract_id TEXT")
        if "self_review_json" not in checkpoint_columns:
            con.execute("ALTER TABLE chapter_checkpoints ADD COLUMN self_review_json TEXT")
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
        draft_count = int(con.execute(
            "SELECT COUNT(*) n FROM chapter_drafts WHERE book_id=?", (book["id"],)
        ).fetchone()["n"])
    body_files = list((directory / "正文").glob("*.md")) if (directory / "正文").exists() else []
    if book["stage"] != "trial_writing":
        blockers.append(f"stage={book['stage']}")
    if book.get("platform_book_id"):
        blockers.append("已绑定番茄作品")
    if chapter_count or body_files:
        blockers.append(f"已有正文或章节记录:{max(chapter_count, len(body_files))}")
    if draft_count:
        blockers.append(f"已有临时稿:{draft_count}")
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


def normalize_book_query(text):
    value = normalize_title(text)
    for phrase in ("开头那本小说", "之前那本小说", "那本小说", "这本小说", "开头那本", "之前那本"):
        value = value.replace(phrase, "")
    return value


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
    with db() as con:
        batch = con.execute("SELECT * FROM writing_batches WHERE book_id=?", (book_id,)).fetchone()
        if batch:
            batch_end = batch["from_chapter"] + batch["target_chapters"] - 1
            upload_start, upload_end = int(payload["from"]), int(payload["to"])
            if upload_start <= batch_end and upload_end >= batch["from_chapter"]:
                con.execute("UPDATE writing_batches SET upload_status='queued',upload_job_id=?,updated_at=? WHERE book_id=?",
                            (job_id, now_iso(), book_id))
    audit("upload_jobs_superseded", book_id, {"superseded": superseded, "latest": job_id})
    return job_id, superseded


def job_update(job_id, status, result=None, error=None):
    with db() as con:
        con.execute("UPDATE jobs SET status=?, result_json=COALESCE(?,result_json), error=?, updated_at=? WHERE id=?",
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


def run_streaming_command(args, timeout, on_event=None, cwd=AI_ROOT, idle_timeout=None):
    process = subprocess.Popen(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True, bufsize=1)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    lines = []
    deadline = time.monotonic() + timeout
    idle_deadline = time.monotonic() + idle_timeout if idle_timeout else None
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline:
                os.killpg(process.pid, 15)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, 9)
                raise RuntimeError(f"命令超过{timeout}秒")
            if idle_deadline and time.monotonic() >= idle_deadline:
                os.killpg(process.pid, 15)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, 9)
                raise RuntimeError(f"命令连续{idle_timeout}秒没有进度，已停止防止永久卡死")
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
                if idle_timeout and (event is not None or on_event is None):
                    idle_deadline = time.monotonic() + idle_timeout
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


def upload_drafts_job(payload, progress_callback=None):
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
    verified_numbers = []

    def on_upload_event(event):
        if event.get("event") != "chapter_verified":
            return
        chapter_no = int(event.get("chapter_no") or 0)
        if not start <= chapter_no <= end:
            raise RuntimeError(f"上传器返回范围外章节：{chapter_no}")
        if chapter_no not in verified_numbers:
            verified_numbers.append(chapter_no)
        progress = {
            "phase": "uploading", "from": start, "to": end,
            "verified_chapters": sorted(verified_numbers),
            "verified_count": len(verified_numbers), "total": expected,
            "current_chapter": chapter_no,
            "instruction": "任务仍在运行，网页必须继续调用getNovelJob(wait_seconds=35)。",
        }
        with db() as con:
            con.execute("UPDATE chapters SET uploaded=1 WHERE book_id=? AND chapter_no=?",
                        (book["id"], chapter_no))
            con.execute("UPDATE writing_batches SET upload_status='running',updated_at=? WHERE book_id=?",
                        (now_iso(), book["id"]))
        audit("draft_chapter_verified", book["id"], {"job_progress": progress})
        if progress_callback:
            progress_callback(progress)

    output = run_streaming_command(
        ["sudo", "-n", "/usr/local/sbin/novel-actions-fanqie", "upload",
         account, cfg["name"], str(cfg["port"]), book["title"],
         str(book["platform_book_id"]), str(start), str(end)],
        max(300, expected * 270), on_event=on_upload_event, idle_timeout=240,
    )
    result = json.loads(output.strip().splitlines()[-1])
    if int(result.get("verified") or 0) != expected:
        raise RuntimeError("草稿箱验收数量不符")
    with db() as con:
        con.execute("UPDATE chapters SET uploaded=1 WHERE book_id=? AND chapter_no BETWEEN ? AND ?",
                    (book["id"], start, end))
        batch = con.execute("SELECT * FROM writing_batches WHERE book_id=?", (book["id"],)).fetchone()
        if batch:
            batch_end = batch["from_chapter"] + batch["target_chapters"] - 1
            remaining = con.execute(
                "SELECT COUNT(*) n FROM chapters WHERE book_id=? AND chapter_no BETWEEN ? AND ? AND uploaded=0",
                (book["id"], batch["from_chapter"], batch_end),
            ).fetchone()["n"]
            if remaining == 0:
                con.execute("UPDATE writing_batches SET status='completed',completed_chapters=target_chapters,"
                            "qa_status='passed',upload_status='completed',updated_at=? WHERE book_id=?",
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
            result = upload_drafts_job(payload, lambda value: job_update(job_id, "running", result=value))
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
    for rel in ["正文", "草稿暂存", "大纲", "设定/角色", "设定/世界观", "追踪", "分析", "封面"]:
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


def find_books(title_query, account=""):
    query = str(title_query or "").strip()
    normalized_query = normalize_book_query(query)
    if len(normalized_query) < 2:
        raise ApiError(400, "模糊查书至少需要2个有效字符")
    account = str(account or "").strip()
    if account and account not in ACCOUNT_MAP:
        by_name = [key for key, value in ACCOUNT_MAP.items() if value["name"] == account]
        if not by_name:
            raise ApiError(400, "作者账号或笔名不在白名单")
        account = by_name[0]
    with db() as con:
        rows = con.execute("SELECT * FROM books ORDER BY updated_at DESC").fetchall()
        batches = {row["book_id"]: row_dict(row) for row in con.execute(
            "SELECT * FROM writing_batches"
        )}
    registered_paths = {str(Path(row["path"]).resolve()) for row in rows}
    matches = []
    for row in rows:
        normalized_title = normalize_title(row["title"])
        ratio = difflib.SequenceMatcher(None, normalized_query, normalized_title).ratio()
        exact = normalized_query == normalized_title
        contains = normalized_query in normalized_title or normalized_title in normalized_query
        score = 1.0 if exact else max(ratio, 0.88 if contains else 0.0)
        if score < 0.45:
            continue
        batch = batches.get(row["id"])
        active = bool(batch and batch["status"] not in {"completed", "cancelled"})
        account_match = not account or row["account"] == account
        matches.append({
            "book_id": row["id"], "title": row["title"], "account": row["account"],
            "author": ACCOUNT_MAP[row["account"]]["name"], "stage": row["stage"],
            "revision": row["revision"], "platform_book_id": row["platform_book_id"],
            "updated_at": row["updated_at"], "match_score": round(score, 3),
            "exact": exact, "account_match": account_match, "active_writing_batch": active,
            "writing_progress": ({
                "from_chapter": batch["from_chapter"], "target_chapters": batch["target_chapters"],
                "completed_chapters": batch["completed_chapters"], "status": batch["status"],
                "upload_mode": batch["upload_mode"],
            } if batch else None),
        })
    for directory in TXT_ROOT.iterdir():
        if not directory.is_dir() or str(directory.resolve()) in registered_paths:
            continue
        formal_dir = directory / "正文"
        if not formal_dir.is_dir() or not any(formal_dir.glob("第*.md")):
            continue
        normalized_title = normalize_title(directory.name)
        ratio = difflib.SequenceMatcher(None, normalized_query, normalized_title).ratio()
        exact = normalized_query == normalized_title
        contains = normalized_query in normalized_title or normalized_title in normalized_query
        score = 1.0 if exact else max(ratio, 0.88 if contains else 0.0)
        if score < 0.45:
            continue
        info = read_limited(directory / "作品信息_番茄上传.md", 5000)
        detected = next(((key, cfg["name"]) for key, cfg in ACCOUNT_MAP.items() if cfg["name"] in info), ("", "未知"))
        account_match = not account or detected[0] == account
        matches.append({
            "book_id": None, "title": directory.name, "account": detected[0], "author": detected[1],
            "stage": "local_unregistered", "revision": None, "platform_book_id": None,
            "updated_at": datetime.fromtimestamp(directory.stat().st_mtime, timezone.utc).isoformat(),
            "match_score": round(score, 3), "exact": exact, "account_match": account_match,
            "active_writing_batch": False, "writing_progress": None,
            "registration_required": True,
        })
    matches.sort(key=lambda item: (
        item["account_match"], item["exact"], item["active_writing_batch"], item["match_score"], item["updated_at"]
    ), reverse=True)
    matches = matches[:10]
    resolved = False
    selected = None
    if matches:
        first = matches[0]
        second_score = matches[1]["match_score"] if len(matches) > 1 and matches[1]["account_match"] == first["account_match"] else 0
        resolved = bool(first["account_match"] and (
            first["exact"] or
            (len(matches) == 1 and first["match_score"] >= 0.55) or
            (first["match_score"] >= 0.72 and first["match_score"] - second_score >= 0.12)
        ))
        selected = first if resolved else None
    return {
        "query": query, "normalized_query": normalized_query, "resolved": resolved,
        "selected": selected, "matches": matches,
        "instruction": (("调用importExistingNovelProject注册selected.title，再使用返回的book_id继续。"
                         if selected and selected.get("registration_required") else
                         "直接使用selected.book_id继续，不得再询问用户book_id。") if resolved else
                        "存在多个可能项目时，只展示完整书名和作者让用户选择，不得询问book_id。"),
    }


def import_existing_book(payload):
    title = safe_title(payload.get("title"))
    directory = (TXT_ROOT / title).resolve()
    if TXT_ROOT.resolve() not in directory.parents or not directory.is_dir():
        raise ApiError(404, "本地小说目录不存在")
    with db() as con:
        existing = con.execute("SELECT * FROM books WHERE title=? OR path=?", (title, str(directory))).fetchone()
    if existing:
        return book_project_response(get_book(existing["id"]), resumed=True)
    info = read_limited(directory / "作品信息_番茄上传.md", 12_000)
    requested_account = str(payload.get("account") or "").strip()
    detected_accounts = [key for key, cfg in ACCOUNT_MAP.items() if cfg["name"] in info]
    account = requested_account or (detected_accounts[0] if len(detected_accounts) == 1 else "")
    if account not in ACCOUNT_MAP:
        raise ApiError(409, "无法从作品信息识别作者账号", {"allowed_accounts": ACCOUNT_MAP})
    if detected_accounts and account not in detected_accounts:
        raise ApiError(409, "指定账号与本地作品信息不一致")
    platform_match = re.search(r"番茄作品ID[：:]\s*(\d{10,})", info)
    platform_book_id = platform_match.group(1) if platform_match else None
    chapter_rows = []
    for path in sorted((directory / "正文").glob("第*.md")):
        match = re.match(r"第(\d+)章[_\s.-]*(.*?)\.md$", path.name)
        if not match:
            continue
        no = int(match.group(1))
        chapter_title = short_chapter_title(match.group(2))
        body = path.read_text(encoding="utf-8", errors="replace").strip()
        if len(body) < 2500 or cjk_count(body) < 100:
            raise ApiError(409, f"本地第{no:03d}章正文过短，不能自动登记")
        chapter_rows.append((no, chapter_title, path.resolve(), body))
    numbers = [row[0] for row in chapter_rows]
    if not numbers or numbers != list(range(1, max(numbers) + 1)):
        raise ApiError(409, "本地正式章节编号不连续，不能自动登记", {"chapters": numbers[:100]})
    for rel in ["草稿暂存", "大纲", "设定", "追踪", "封面"]:
        (directory / rel).mkdir(parents=True, exist_ok=True)
    chapter_index = directory / STATE_FILES["chapter_index"]
    if not chapter_index.exists():
        atomic_write(chapter_index, "# 章节索引\n\n" + "\n".join(
            f"- 第{no:03d}章 {chapter_title}" for no, chapter_title, _, _ in chapter_rows
        ) + "\n")
    timeline = directory / STATE_FILES["timeline"]
    if not timeline.exists():
        atomic_write(timeline, "# 时间线\n\n详细事件以现有正文和追踪/上下文.md为准。\n")
    structured = directory / STATE_FILES["structured"]
    if not structured.exists():
        atomic_write(structured, json.dumps({"imported": True, "last_chapter": max(numbers),
                                             "characters": [], "facts": []}, ensure_ascii=False, indent=2) + "\n")
    ideation_id = hashlib.sha256(("legacy:" + title).encode("utf-8")).hexdigest()
    book_id = uuid.uuid4().hex
    stamp = now_iso()
    legacy_candidate = [{"number": 1, "working_title": title, "legacy_import": True}]
    with db() as con:
        con.execute("INSERT OR IGNORE INTO ideations VALUES(?,?,'selected',?,1,NULL,?,?)",
                    (ideation_id, "历史本地项目", json_text(legacy_candidate), stamp, stamp))
        con.execute("""INSERT INTO books
                    (id,title,path,ideation_id,account,stage,revision,platform_book_id,last_qa_revision,created_at,updated_at)
                    VALUES(?,?,?,?,?,'bulk_writing',1,?,1,?,?)""",
                    (book_id, title, str(directory), ideation_id, account, platform_book_id, stamp, stamp))
        for no, chapter_title, path, body in chapter_rows:
            qa = {"passed": True, "legacy_import": True, "cjk_chars": cjk_count(body),
                  "body_chars": len(body),
                  "note": "历史项目按原有正文总字符标准登记；后续新章仍执行当前中文汉字门禁"}
            con.execute("""INSERT INTO chapters
                        (book_id,chapter_no,title,file_path,body_chars,cjk_chars,summary,qa_json,qa_passed,uploaded,updated_at)
                        VALUES(?,?,?,?,?,?,?, ?,1,0,?)""",
                        (book_id, no, chapter_title, str(path), len(body), cjk_count(body),
                         f"历史导入：第{no:03d}章 {chapter_title}", json_text(qa), stamp))
            con.execute("INSERT INTO chapter_fts VALUES(?,?,?,?,?)",
                        (book_id, no, chapter_title, f"第{no:03d}章 {chapter_title}", body))
    audit("existing_book_imported", book_id, {"title": title, "chapters": len(chapter_rows),
                                               "account": account, "platform_book_id": platform_book_id})
    result = book_project_response(get_book(book_id), resumed=True)
    result.update({"imported": True, "imported_chapters": len(chapter_rows), "next_chapter": max(numbers) + 1})
    return result


def chapter_file(directory, no, title):
    return directory / "正文" / f"第{no:03d}章_{safe_title(title)}.md"


def chapter_draft_file(directory, no, title):
    return directory / "草稿暂存" / f"第{no:03d}章_{safe_title(title)}.md"


def draft_state_path(directory):
    return directory / "草稿暂存" / "待确认状态.json"


def short_chapter_title(value):
    title = safe_title(value)
    title = re.sub(r"^(?:第\s*0*\d+\s*章[\s._-]*)+", "", title).strip()
    if not title:
        raise ApiError(400, "章节标题不能只有章号")
    return title


def promote_drafts(book_id, start, end, reset_uploaded=False):
    book = get_book(book_id)
    directory = book_dir(book)
    with db() as con:
        rows = con.execute(
            "SELECT * FROM chapter_drafts WHERE book_id=? AND chapter_no BETWEEN ? AND ? ORDER BY chapter_no",
            (book_id, start, end),
        ).fetchall()
    if len(rows) != end - start + 1 or any(not row["qa_passed"] for row in rows):
        raise ApiError(409, "临时稿缺失或QA未通过，不能正式保存")
    with db() as con:
        for row in rows:
            body = Path(row["file_path"]).read_text(encoding="utf-8")
            path = chapter_file(directory, row["chapter_no"], row["title"])
            old = con.execute("SELECT file_path FROM chapters WHERE book_id=? AND chapter_no=?",
                              (book_id, row["chapter_no"])).fetchone()
            if old and Path(old["file_path"]) != path and Path(old["file_path"]).exists():
                Path(old["file_path"]).unlink()
            atomic_write(path, body)
            uploaded_sql = "0" if reset_uploaded else "COALESCE((SELECT uploaded FROM chapters WHERE book_id=? AND chapter_no=?),0)"
            params = (book_id, row["chapter_no"], row["title"], str(path), row["body_chars"],
                      row["cjk_chars"], row["summary"], row["qa_json"])
            if not reset_uploaded:
                params += (book_id, row["chapter_no"])
            params += (now_iso(),)
            con.execute(f"""INSERT OR REPLACE INTO chapters
                        (book_id,chapter_no,title,file_path,body_chars,cjk_chars,summary,qa_json,qa_passed,uploaded,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,1,{uploaded_sql},?)""", params)
            con.execute("DELETE FROM chapter_fts WHERE book_id=? AND chapter_no=?", (book_id, row["chapter_no"]))
            con.execute("INSERT INTO chapter_fts VALUES(?,?,?,?,?)",
                        (book_id, row["chapter_no"], row["title"], row["summary"], body))
        con.execute("DELETE FROM chapter_drafts WHERE book_id=? AND chapter_no BETWEEN ? AND ?",
                    (book_id, start, end))
        bump_revision(con, book_id)
    state_path = draft_state_path(directory)
    if state_path.exists():
        try:
            staged_state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            staged_state = {}
        for key, value in staged_state.items():
            if key not in STATE_FILES:
                continue
            path = directory / STATE_FILES[key]
            if key == "structured":
                atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            else:
                atomic_write(path, str(value).strip() + "\n")
        state_path.unlink(missing_ok=True)
    for row in rows:
        Path(row["file_path"]).unlink(missing_ok=True)
    audit("chapter_drafts_promoted", book_id, {"from": start, "to": end})


def save_chapters(book_id, payload):
    book = get_book(book_id)
    check_revision(book, payload.get("expected_revision"))
    items = payload.get("chapters") or []
    if not 1 <= len(items) <= MAX_CHAPTER_BATCH:
        raise ApiError(400, "每批必须保存1到4章")
    if book["stage"] not in {"trial_writing", "trial_ready_for_review", "awaiting_trial_approval", "bulk_writing"}:
        raise ApiError(409, "当前阶段不允许写章")
    numbers = [int(x.get("chapter_no") or 0) for x in items]
    if len(set(numbers)) != len(numbers) or min(numbers) < 1:
        raise ApiError(400, "章节编号无效或重复")
    if book["stage"] in {"trial_writing", "trial_ready_for_review", "awaiting_trial_approval"} and any(n > 3 for n in numbers):
        raise ApiError(409, "三章试读未批准，不能写第4章")
    if book["stage"] == "bulk_writing":
        with db() as con:
            active_revision = con.execute(
                "SELECT id FROM revision_batches WHERE book_id=? AND status NOT IN ('completed','cancelled') LIMIT 1",
                (book_id,),
            ).fetchone()
            active_batch = con.execute("SELECT quality_mode,status FROM writing_batches WHERE book_id=?",
                                       (book_id,)).fetchone()
        if active_revision:
            raise ApiError(409, "旧批量保存接口禁止修改修订批次；请执行服务器next_action并使用候选稿审稿流程")
        if active_batch and active_batch["quality_mode"] == "strong" and active_batch["status"] not in {"completed", "cancelled"}:
            raise ApiError(409, "强制质量模式禁止绕过创作合同；请使用逐章原子检查点接口")
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
            old = con.execute("SELECT file_path,draft_revision FROM chapter_drafts WHERE book_id=? AND chapter_no=?", (book_id, no)).fetchone()
            path = chapter_draft_file(directory, no, title)
            if old and Path(old["file_path"]) != path and Path(old["file_path"]).exists():
                Path(old["file_path"]).unlink()
            atomic_write(path, body)
            draft_revision = int(old["draft_revision"] if old else 0) + 1
            con.execute("""INSERT OR REPLACE INTO chapter_drafts
                        (book_id,chapter_no,title,file_path,body_chars,cjk_chars,summary,draft_revision,qa_json,qa_passed,status,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,NULL,0,'drafting',?)""",
                        (book_id, no, title, str(path), len(body.strip()), cjk_count(body), summary,
                         draft_revision, now_iso()))
        bump_revision(con, book_id)
        if book["stage"] in {"trial_ready_for_review", "awaiting_trial_approval"}:
            con.execute("UPDATE books SET stage='trial_writing' WHERE id=?", (book_id,))
    audit("chapter_drafts_saved", book_id, {"numbers": numbers})
    refresh_writing_batch(book_id)
    return get_book(book_id)


def update_state(book_id, payload):
    book = get_book(book_id)
    check_revision(book, payload.get("expected_revision"))
    state = payload.get("state") or {}
    if not any(key in STATE_FILES for key in state):
        raise ApiError(400, "state_update没有可保存的追踪字段，不能用于提交审稿或推进revision")
    directory = book_dir(book)
    stage_state = book["stage"] in {"trial_writing", "trial_ready_for_review", "awaiting_trial_approval"}
    with db() as con:
        batch = con.execute("SELECT status FROM writing_batches WHERE book_id=?", (book_id,)).fetchone()
    stage_state = stage_state or bool(batch and batch["status"] not in {"completed", "cancelled"})
    if stage_state:
        path = draft_state_path(directory)
        existing = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
        existing.update({key: value for key, value in state.items() if key in STATE_FILES})
        atomic_write(path, json.dumps(existing, ensure_ascii=False, indent=2) + "\n")
    else:
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
    audit("draft_state_updated" if stage_state else "state_updated", book_id, {"keys": sorted(state)})
    return get_book(book_id)


CHECKPOINT_STATE_KEYS = {
    "context", "characters", "timeline", "foreshadowing", "chapter_index", "structured",
}

CONTRACT_PLAN_FIELDS = {
    "chapter_no", "title_intent", "protagonist_goal", "obstacle", "consequential_choice",
    "cost", "state_change", "emotional_payoff", "type_promise", "conflict_engine",
    "ending_hook", "structural_fingerprint",
}
SELF_REVIEW_FLAGS = {
    "protagonist_drives_plot", "genre_promise_delivered", "emotional_change_present",
    "no_repeated_loop", "ai_style_revised",
}
BATCH_REVIEW_FLAGS = {
    "protagonist_agency_passed", "genre_promise_passed", "emotional_arc_passed",
    "structure_diversity_passed", "title_variety_passed", "exposition_density_passed",
    "tracking_integrity_passed",
}


def contract_row_data(row):
    if not row:
        return None
    item = row_dict(row)
    item["contract"] = json.loads(item.pop("contract_json"))
    review_json = item.pop("review_json", None)
    item["review"] = json.loads(review_json) if review_json else None
    return item


def contract_summary(item):
    return {key: item.get(key) for key in (
        "id", "segment_from", "segment_to", "status", "revision_batch_id", "updated_at",
    )}


def get_writing_contract(book_id, contract_id):
    with db() as con:
        row = con.execute("SELECT * FROM writing_contracts WHERE id=? AND book_id=?",
                          (contract_id, book_id)).fetchone()
    if not row:
        raise ApiError(404, "批次创作合同不存在")
    return contract_row_data(row)


def contract_for_chapter(con, book_id, chapter_no):
    return con.execute(
        "SELECT * FROM writing_contracts WHERE book_id=? AND segment_from<=? AND segment_to>=? "
        "ORDER BY created_at DESC LIMIT 1", (book_id, chapter_no, chapter_no)
    ).fetchone()


def configure_writing_contract(book_id, payload):
    book = get_book(book_id)
    revision_batch_id = str(payload.get("revision_batch_id") or "").strip() or None
    batch = None
    revision_targets = None
    if revision_batch_id:
        with db() as con:
            revision = con.execute("SELECT * FROM revision_batches WHERE id=? AND book_id=?",
                                   (revision_batch_id, book_id)).fetchone()
        if not revision or revision["status"] in {"completed", "cancelled"}:
            raise ApiError(409, "当前没有可规划的修订批次")
        revision_targets = json.loads(revision["target_json"])
    else:
        batch = get_writing_batch(book_id)
        if not batch or batch.get("status") in {"not_configured", "completed", "cancelled"}:
            raise ApiError(409, "当前没有可规划的连续写作批次")
    start, end = int(payload.get("from") or 0), int(payload.get("to") or 0)
    allowed_start = min(revision_targets) if revision_targets else batch["from_chapter"]
    allowed_end = max(revision_targets) if revision_targets else batch["from_chapter"] + batch["target_chapters"] - 1
    if (start < allowed_start or end < start or end > allowed_end or end - start >= 4 or
            revision_targets is not None and any(no not in revision_targets for no in range(start, end + 1))):
        raise ApiError(400, "创作合同必须覆盖当前批次内连续1到4章")
    contract = payload.get("contract") or {}
    required = ("protagonist", "genre_promises", "segment_goal", "prohibited_loops",
                "prior_segment_comparison", "chapter_plans")
    missing = [key for key in required if not contract.get(key)]
    if missing:
        raise ApiError(400, "创作合同字段不完整", {"missing": missing})
    protagonist = str(contract["protagonist"]).strip()
    if not re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", protagonist):
        raise ApiError(400, "protagonist只能填写2到8字主角姓名，不得附加人物说明", {
            "example": "姜岁岁",
        })
    if not isinstance(contract["genre_promises"], list) or len(contract["genre_promises"]) < 3:
        raise ApiError(400, "至少声明3项作品类型承诺")
    if not isinstance(contract["prohibited_loops"], list) or len(contract["prohibited_loops"]) < 3:
        raise ApiError(400, "至少声明3项本段禁用重复结构")
    plans = contract["chapter_plans"]
    if not isinstance(plans, list) or [int(p.get("chapter_no") or 0) for p in plans] != list(range(start, end + 1)):
        raise ApiError(400, "chapter_plans必须按顺序完整覆盖合同章节")
    plan_errors = []
    fingerprints = []
    conflict_engines = []
    for plan in plans:
        absent = sorted(field for field in CONTRACT_PLAN_FIELDS if not plan.get(field))
        if absent:
            plan_errors.append({"chapter_no": plan.get("chapter_no"), "missing": absent})
        fingerprints.append(normalize_title(plan.get("structural_fingerprint")))
        conflict_engines.append(normalize_title(plan.get("conflict_engine")))
    if plan_errors:
        raise ApiError(400, "逐章创作计划不完整", {"chapter_errors": plan_errors})
    if len(set(fingerprints)) != len(fingerprints):
        raise ApiError(400, "同一创作合同存在重复结构指纹")
    if len(set(conflict_engines)) != len(conflict_engines):
        raise ApiError(400, "同一创作合同存在重复冲突引擎")
    if len(str(contract.get("prior_segment_comparison") or "").strip()) < 30:
        raise ApiError(400, "必须具体比较本段与最近章节的冲突引擎、人物选择和情绪回报")
    with db() as con:
        existing = con.execute("SELECT * FROM writing_contracts WHERE book_id=? AND segment_from=? AND segment_to=? "
                               "AND COALESCE(revision_batch_id,'')=COALESCE(?,'')",
                               (book_id, start, end, revision_batch_id)).fetchone()
        if existing:
            return contract_row_data(existing)
        previous = con.execute("SELECT contract_json FROM writing_contracts WHERE book_id=? "
                               "AND COALESCE(revision_batch_id,'')=COALESCE(?,'') "
                               "AND status NOT IN ('superseded','cancelled') ORDER BY segment_to DESC LIMIT 2",
                               (book_id, revision_batch_id)).fetchall()
        previous_fingerprints = {
            normalize_title(plan.get("structural_fingerprint"))
            for row in previous for plan in json.loads(row["contract_json"]).get("chapter_plans", [])
        }
        duplicated = sorted(set(fingerprints) & previous_fingerprints)
        if duplicated:
            raise ApiError(409, "结构指纹与最近创作合同重复，必须重做计划", {"fingerprints": duplicated})
        previous_engines = {
            normalize_title(plan.get("conflict_engine"))
            for row in previous for plan in json.loads(row["contract_json"]).get("chapter_plans", [])
        }
        duplicated_engines = sorted(set(conflict_engines) & previous_engines)
        if duplicated_engines:
            raise ApiError(409, "冲突引擎与最近创作合同重复，必须更换场景驱动力",
                           {"conflict_engines": duplicated_engines})
        contract_id, stamp = uuid.uuid4().hex, now_iso()
        con.execute("""INSERT INTO writing_contracts
                    (id,book_id,segment_from,segment_to,status,contract_json,review_json,created_at,updated_at,revision_batch_id)
                    VALUES(?,?,?,?,'planned',?,NULL,?,?,?)""",
                    (contract_id, book_id, start, end, json_text(contract), stamp, stamp, revision_batch_id))
    audit("writing_contract_created", book_id, {"contract_id": contract_id, "from": start, "to": end,
                                                  "revision_batch_id": revision_batch_id})
    return get_writing_contract(book_id, contract_id)


def validate_checkpoint_review(body, review):
    if not isinstance(review, dict):
        raise ApiError(400, "强制质量模式必须在payload_json顶层提交self_review对象", {
            "required_shape": {
                "self_review": {
                    "protagonist_drives_plot": True,
                    "genre_promise_delivered": True,
                    "emotional_change_present": True,
                    "no_repeated_loop": True,
                    "ai_style_revised": True,
                    "notes": "至少40字，说明初稿问题及已经修改的正文内容",
                    "evidence": {
                        "protagonist_action": "正文中逐字存在的至少6字摘录",
                        "emotional_change": "正文中逐字存在的至少6字摘录",
                        "type_promise": "正文中逐字存在的至少6字摘录",
                    },
                }
            }
        })
    missing_flags = sorted(flag for flag in SELF_REVIEW_FLAGS if review.get(flag) is not True)
    evidence = review.get("evidence") or {}
    evidence_fields = ("protagonist_action", "emotional_change", "type_promise")
    bad_evidence = []
    for field in evidence_fields:
        excerpt = str(evidence.get(field) or "").strip()
        if len(excerpt) < 6 or excerpt not in body:
            bad_evidence.append(field)
    if missing_flags or bad_evidence or len(str(review.get("notes") or "").strip()) < 40:
        raise ApiError(400, "逐章独立审稿证据不足", {
            "failed_flags": missing_flags, "invalid_evidence": bad_evidence,
            "notes_requirement": "至少40字，说明初稿问题及实际修订",
        })


REVIEW_CHECKS = {
    "causality_coherent", "character_motivation_coherent", "age_and_ability_plausible",
    "authority_and_duty_plausible", "time_and_space_consistent", "people_and_props_consistent",
    "emotional_change_earned", "genre_promise_delivered", "prose_not_expository",
}


def review_cycle_data(row):
    if not row:
        return None
    item = row_dict(row)
    for source, target in (("critique_json", "critique"), ("changes_json", "changes"),
                           ("verification_json", "verification")):
        raw = item.pop(source, None)
        item[target] = json.loads(raw) if raw else None
    return item


def review_cycle_summary(cycle):
    return {key: cycle.get(key) for key in (
        "chapter_no", "revision_batch_id", "contract_id", "candidate_revision", "title", "status",
        "review_round", "updated_at",
    )}


def review_next_action(cycle):
    status = cycle["status"]
    common = {"chapter_no": cycle["chapter_no"],
              "revision_batch_id": cycle.get("revision_batch_id") or ""}
    definitions = {
        "critique_required": {
            "type": "critique_chapter", "action": "candidate_critique",
            "payload_schema": {
                **common,
                "critique": {
                    "scene_model": {
                        "actors": [{"name": "角色名", "age_role": "年龄和身份", "location": "当前位置",
                                    "action": "本章关键行动", "knowledge": "当时已知信息"}],
                        "timeline": ["至少2个按先后排列的事件节点"],
                        "props": [{"item": "物件", "count": 1, "owner": "持有人",
                                   "transitions": "前后状态或流转"}],
                        "physical_and_social_constraints": "至少40字，说明年代、环境、年龄、职责权限和物理限制",
                    },
                    "issues": [{"id": "唯一ID", "severity": "low|medium|high", "category": "问题类别",
                                "evidence": "候选正文逐字摘录至少6字", "reasoning": "至少30字推理",
                                "proposed_fix": "至少20字修改方案"}],
                },
            },
        },
        "needs_revision": {
            "type": "revise_candidate", "action": "candidate_revise",
            "payload_schema": {**common, "body": "实际返修后的完整正文",
                               "changes": [{"issue_id": "审稿问题ID", "revision": "至少20字的实际修改说明"}]},
        },
        "verification_required": {
            "type": "verify_candidate", "action": "candidate_verify",
            "payload_schema": {**common, "verification": {
                "scene_model": "按critique阶段相同结构重新构建，不能复用结论",
                "checks": {key: {"passed": True, "evidence": "返修正文逐字摘录至少6字",
                                  "reasoning": "至少20字独立推理"} for key in sorted(REVIEW_CHECKS)},
                "residual_issues": [], "notes": "至少60字独立验收结论",
            }},
        },
        "verified": {
            "type": "commit_verified_chapter", "action": "checkpoint_commit",
            "payload_schema": {**common, "contract_id": cycle["contract_id"],
                               "chapter": "必须与review_cycle已验收标题、正文、摘要完全一致",
                               "expected_revision": "使用恢复快照book.revision",
                               "idempotency_key": "12至120位稳定标识",
                               "state_patch": {
                                   "context_update": "至少30字本章上下文更新",
                                   "characters_update": "至少10字人物状态变化",
                                   "timeline_entry": "至少10字本章时间与因果",
                                   "foreshadowing_update": "至少10字伏笔新增、推进或无变化说明",
                                   "chapter_index_entry": "至少6字本章索引摘要",
                                   "structured": {"characters_add": [], "facts_add": []},
                               },
                               "self_review": "正文证据自审对象"},
        },
        "blocked": {"type": "request_human_review", "action": None, "payload_schema": None},
    }
    return {**definitions[status], "chapter_no": cycle["chapter_no"], "review_cycle": cycle}


def executable_next_action(next_action, revision_batch_id=""):
    if "action" in next_action:
        return next_action
    action_type = next_action["type"]
    chapter_no = next_action.get("chapter_no")
    common_revision = {"revision_batch_id": revision_batch_id} if revision_batch_id else {}
    contract_template = {
        "protagonist": "填写2至8字主角姓名",
        "genre_promises": ["类型承诺1", "类型承诺2", "类型承诺3"],
        "segment_goal": "本段连续推进目标",
        "prohibited_loops": ["禁用重复结构1", "禁用重复结构2", "禁用重复结构3"],
        "prior_segment_comparison": "至少30字，具体比较最近章节的冲突引擎、人物选择和情绪回报",
        "chapter_plans": [{
            "chapter_no": no, "title_intent": f"第{no}章标题意图",
            "protagonist_goal": "主角本章主动目标", "obstacle": "现实阻力",
            "consequential_choice": "不可撤销选择", "cost": "真实代价",
            "state_change": "章末状态变化", "emotional_payoff": "情绪回报",
            "type_promise": "本章类型兑现", "conflict_engine": f"第{no}章独立冲突引擎",
            "ending_hook": "因果型章末钩子", "structural_fingerprint": f"第{no}章独立结构指纹",
        } for no in range(int(next_action.get("from") or 0), int(next_action.get("to") or -1) + 1)],
    }
    mappings = {
        "await_batch_configuration": ("writing_configure", {
            "target_chapters": "与approximate_words二选一", "approximate_words": "与target_chapters二选一",
            "upload_mode": "auto或review",
        }),
        "configure_revision": ("revision_configure", {
            "chapter_numbers": "与连续范围或all_chapters三选一", "from_chapter": "可选",
            "to_chapter": "可选", "all_chapters": False, "mode": "auto或review",
        }),
        "run_qa": ("quality_check", {
            "from": chapter_no, "to": chapter_no,
            "originality_review": {"scene_causality_checked": True, "cross_work_swap_checked": True,
                                   "ai_pattern_reviewed": True, "notes": "至少说明本章实际检查结论"},
        }),
        "plan_segment": ("contract_create", {
            "from": next_action.get("from"), "to": next_action.get("to"),
            "contract": contract_template,
        }),
        "plan_revision_segment": ("contract_create", {
            "from": next_action.get("from"), "to": next_action.get("to"),
            "revision_batch_id": revision_batch_id or next_action.get("revision_batch_id"),
            "contract": contract_template,
        }),
        "write_candidate": ("candidate_save", {
            "contract_id": next_action.get("contract_id"), **common_revision,
            "chapter": {"chapter_no": chapter_no, "title": "章节标题", "body": "完整候选正文", "summary": "章节摘要"},
        }),
        "rewrite_candidate": ("candidate_save", {
            "contract_id": next_action.get("contract_id"), **common_revision,
            "chapter": {"chapter_no": chapter_no, "title": "返修标题", "body": "完整返修候选正文", "summary": "返修摘要"},
        }),
        "revise_chapter": ("candidate_save", {
            "contract_id": next_action.get("contract_id") or "使用覆盖本章的当前合同ID", **common_revision,
            "chapter": {"chapter_no": chapter_no, "title": "实际返修标题", "body": "QA失败后实际修改的完整正文", "summary": "更新摘要"},
        }),
        "revise_segment": ("candidate_save", {
            "contract_id": next_action.get("contract_id"), **common_revision,
            "chapter": {"chapter_no": next_action.get("from"), "title": "段内首个待返修章标题",
                        "body": "根据合同审稿问题实际返修的完整正文", "summary": "更新摘要"},
        }),
        "review_segment": ("contract_review", {
            "contract_id": next_action.get("contract_id"),
            "review": {"protagonist_agency_passed": True, "genre_promise_passed": True,
                       "emotional_arc_passed": True, "structure_diversity_passed": True,
                       "title_variety_passed": True, "exposition_density_passed": True,
                       "tracking_integrity_passed": True,
                       "chapter_findings": "逐章结论数组", "cross_chapter_notes": "至少80字跨章审稿"},
        }),
        "poll_upload": ("getNovelJob", {"job_id": next_action.get("job_id"), "wait_seconds": 35}),
        "promote_revision": ("revision_approve", {"revision_batch_id": revision_batch_id}),
        "finalize_batch": ("writing_resume", {}),
    }
    terminal = {"completed", "await_user_review", "request_human_review"}
    if action_type in terminal:
        return {**next_action, "action": None, "payload_schema": None}
    if action_type not in mappings:
        raise ApiError(500, "服务器产生了未映射的next_action", {"type": action_type})
    action, schema = mappings[action_type]
    return {**next_action, "action": action, "payload_schema": schema}


def validate_scene_model(model):
    if not isinstance(model, dict):
        raise ApiError(400, "独立审稿必须提交scene_model", {
            "required_fields": ["actors", "timeline", "props", "physical_and_social_constraints"]})
    actors = model.get("actors") or []
    timeline = model.get("timeline") or []
    props = model.get("props") if "props" in model else model.get("objects")
    props = props or []
    if len(actors) < 2 or len(timeline) < 2 or not isinstance(props, list):
        raise ApiError(400, "scene_model必须包含至少2名角色、2个时序节点和物件列表", {
            "minimums": {"actors": 2, "timeline": 2}, "props_alias": "也接受objects"})
    actor_fields = ("name", "age_role", "location", "action", "knowledge")
    missing_fields = {
        f"actors[{index}]": list(actor_fields) if not isinstance(actor, dict) else
        [key for key in actor_fields if not str(actor.get(key) or "").strip()]
        for index, actor in enumerate(actors)
    }
    missing_fields = {path: fields for path, fields in missing_fields.items() if fields}
    if missing_fields:
        raise ApiError(400, "scene_model角色信息不完整", {"missing_fields": missing_fields,
                                                        "required_actor_fields": list(actor_fields)})
    if len(str(model.get("physical_and_social_constraints") or "").strip()) < 40:
        raise ApiError(400, "scene_model必须说明年代、环境、年龄、权限及物理限制")


def get_review_cycle(book_id, chapter_no, revision_batch_id=""):
    with db() as con:
        row = con.execute(
            "SELECT * FROM chapter_review_cycles WHERE book_id=? AND chapter_no=? AND revision_batch_id=?",
            (book_id, chapter_no, revision_batch_id or ""),
        ).fetchone()
    if not row:
        raise ApiError(404, "章节候选稿不存在，必须先保存初稿")
    return review_cycle_data(row)


def validate_candidate_scope(con, book_id, chapter_no, contract_id, revision_batch_id=""):
    contract = con.execute(
        "SELECT * FROM writing_contracts WHERE id=? AND book_id=? AND COALESCE(revision_batch_id,'')=?",
        (contract_id, book_id, revision_batch_id or ""),
    ).fetchone()
    if not contract or not contract["segment_from"] <= chapter_no <= contract["segment_to"]:
        raise ApiError(409, "候选稿必须绑定覆盖当前章的强质量合同")
    if revision_batch_id:
        batch = con.execute("SELECT * FROM revision_batches WHERE id=? AND book_id=?",
                            (revision_batch_id, book_id)).fetchone()
        if not batch or chapter_no not in json.loads(batch["target_json"]):
            raise ApiError(409, "章节不在当前修订批次")
    else:
        batch = con.execute("SELECT * FROM writing_batches WHERE book_id=?", (book_id,)).fetchone()
        if not batch or not batch["from_chapter"] <= chapter_no < batch["from_chapter"] + batch["target_chapters"]:
            raise ApiError(409, "章节不在当前写作批次")
    return contract


def save_review_candidate(book_id, payload):
    item = payload.get("chapter") or {}
    chapter_no = int(item.get("chapter_no") or 0)
    title = short_chapter_title(item.get("title"))
    body = str(item.get("body") or "").strip()
    summary = str(item.get("summary") or "").strip()
    contract_id = str(payload.get("contract_id") or "").strip()
    revision_batch_id = str(payload.get("revision_batch_id") or "").strip()
    if not 100 <= cjk_count(body) or len(body) > 20_000:
        raise ApiError(400, "候选稿正文长度无效")
    with db() as con:
        validate_candidate_scope(con, book_id, chapter_no, contract_id, revision_batch_id)
        old = con.execute("SELECT * FROM chapter_review_cycles WHERE book_id=? AND chapter_no=? AND revision_batch_id=?",
                          (book_id, chapter_no, revision_batch_id)).fetchone()
        if old and old["title"] == title and old["body"] == body and old["summary"] == summary:
            action_by_status = {
                "critique_required": "critique_chapter", "needs_revision": "revise_candidate",
                "verification_required": "verify_candidate", "verified": "commit_verified_chapter",
                "committed": "run_qa", "blocked": "request_human_review",
            }
            return {"candidate_saved": True, "idempotent_replay": True,
                    "review_cycle": review_cycle_data(old),
                    "next_action": action_by_status.get(old["status"], "critique_chapter")}
        candidate_revision = int(old["candidate_revision"] if old else 0) + 1
        stamp = now_iso()
        con.execute("""INSERT OR REPLACE INTO chapter_review_cycles
                    (book_id,chapter_no,revision_batch_id,contract_id,candidate_revision,title,body,summary,status,
                     critique_json,changes_json,verification_json,review_round,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,'critique_required',NULL,NULL,NULL,0,?,?)""",
                    (book_id, chapter_no, revision_batch_id, contract_id, candidate_revision, title, body, summary,
                     old["created_at"] if old else stamp, stamp))
    audit("chapter_candidate_saved", book_id, {"chapter_no": chapter_no, "candidate_revision": candidate_revision})
    return {"candidate_saved": True, "idempotent_replay": False,
            "review_cycle": get_review_cycle(book_id, chapter_no, revision_batch_id),
            "next_action": "critique_chapter"}


def critique_review_candidate(book_id, payload):
    chapter_no = int(payload.get("chapter_no") or 0)
    revision_batch_id = str(payload.get("revision_batch_id") or "").strip()
    critique = payload.get("critique") or {}
    cycle = get_review_cycle(book_id, chapter_no, revision_batch_id)
    if cycle["status"] != "critique_required":
        raise ApiError(409, "候选稿当前不在独立审稿阶段", {"status": cycle["status"]})
    validate_scene_model(critique.get("scene_model"))
    issues = critique.get("issues") or []
    if len(issues) < 2:
        raise ApiError(400, "独立审稿必须主动提出至少2个潜在问题")
    seen = set()
    substantive = False
    for issue in issues:
        issue_id = str(issue.get("id") or "").strip()
        severity = str(issue.get("severity") or "").strip()
        evidence = str(issue.get("evidence") or "").strip()
        if (not issue_id or issue_id in seen or severity not in {"low", "medium", "high"} or
                len(evidence) < 6 or evidence not in cycle["body"] or
                len(str(issue.get("reasoning") or "").strip()) < 30 or
                len(str(issue.get("proposed_fix") or "").strip()) < 20):
            raise ApiError(400, "独立审稿问题缺少有效ID、正文证据、推理或修改方案")
        seen.add(issue_id)
        substantive = substantive or severity in {"medium", "high"}
    if not substantive:
        raise ApiError(400, "独立审稿至少要识别1个需要实际返修的中高风险问题")
    with db() as con:
        con.execute("UPDATE chapter_review_cycles SET status='needs_revision',critique_json=?,updated_at=? "
                    "WHERE book_id=? AND chapter_no=? AND revision_batch_id=?",
                    (json_text(critique), now_iso(), book_id, chapter_no, revision_batch_id))
    audit("chapter_candidate_critiqued", book_id, {"chapter_no": chapter_no, "issues": len(issues)})
    return {"critique_saved": True, "review_cycle": get_review_cycle(book_id, chapter_no, revision_batch_id),
            "next_action": "revise_candidate"}


def revise_review_candidate(book_id, payload):
    chapter_no = int(payload.get("chapter_no") or 0)
    revision_batch_id = str(payload.get("revision_batch_id") or "").strip()
    cycle = get_review_cycle(book_id, chapter_no, revision_batch_id)
    if cycle["status"] != "needs_revision":
        raise ApiError(409, "候选稿当前不在返修阶段", {"status": cycle["status"]})
    body = str(payload.get("body") or "").strip()
    if body == cycle["body"] or cjk_count(body) < 100 or len(body) > 20_000:
        raise ApiError(400, "返修必须实际修改正文")
    changes = payload.get("changes") or []
    required_ids = {str(issue["id"]) for issue in cycle["critique"]["issues"]
                    if issue.get("severity") in {"medium", "high"}}
    changed_ids = {str(item.get("issue_id") or "") for item in changes if isinstance(item, dict)}
    if not required_ids <= changed_ids or any(len(str(item.get("revision") or "").strip()) < 20 for item in changes):
        raise ApiError(400, "返修说明必须覆盖全部中高风险问题并说明实际正文修改")
    review_round = int(cycle["review_round"]) + 1
    if review_round > 3:
        raise ApiError(409, "返修已超过3轮，必须停止并交人工处理")
    with db() as con:
        con.execute("UPDATE chapter_review_cycles SET body=?,status='verification_required',changes_json=?,"
                    "verification_json=NULL,review_round=?,candidate_revision=candidate_revision+1,updated_at=? "
                    "WHERE book_id=? AND chapter_no=? AND revision_batch_id=?",
                    (body, json_text(changes), review_round, now_iso(), book_id, chapter_no, revision_batch_id))
    audit("chapter_candidate_revised", book_id, {"chapter_no": chapter_no, "round": review_round})
    return {"revision_saved": True, "review_cycle": get_review_cycle(book_id, chapter_no, revision_batch_id),
            "next_action": "verify_candidate"}


def verify_review_candidate(book_id, payload):
    chapter_no = int(payload.get("chapter_no") or 0)
    revision_batch_id = str(payload.get("revision_batch_id") or "").strip()
    verification = payload.get("verification") or {}
    cycle = get_review_cycle(book_id, chapter_no, revision_batch_id)
    if cycle["status"] != "verification_required":
        raise ApiError(409, "候选稿当前不在独立验收阶段", {"status": cycle["status"]})
    validate_scene_model(verification.get("scene_model"))
    checks = verification.get("checks") or {}
    failed_checks = []
    invalid_findings = []
    for key in sorted(REVIEW_CHECKS):
        finding = checks.get(key)
        if not isinstance(finding, dict):
            invalid_findings.append(key)
            continue
        evidence = str(finding.get("evidence") or "").strip()
        reasoning = str(finding.get("reasoning") or "").strip()
        if len(evidence) < 6 or evidence not in cycle["body"] or len(reasoning) < 20:
            invalid_findings.append(key)
        if finding.get("passed") is not True:
            failed_checks.append(key)
    if invalid_findings:
        raise ApiError(400, "独立验收必须为每项判断提交返修正文中的证据和推理", {
            "invalid_checks": invalid_findings,
            "required_shape": {"passed": True, "evidence": "正文逐字摘录至少6字", "reasoning": "至少20字推理"},
        })
    residual = verification.get("residual_issues") or []
    unresolved = [item for item in residual if str(item.get("severity") or "") in {"medium", "high"}]
    passed = not failed_checks and not unresolved and len(str(verification.get("notes") or "").strip()) >= 60
    if passed:
        status, next_action = "verified", "commit_verified_chapter"
    elif int(cycle["review_round"]) >= 3:
        status, next_action = "blocked", "request_human_review"
    else:
        status, next_action = "needs_revision", "revise_candidate"
    stored = {**verification, "server_failed_checks": failed_checks, "passed": passed}
    with db() as con:
        con.execute("UPDATE chapter_review_cycles SET status=?,verification_json=?,updated_at=? "
                    "WHERE book_id=? AND chapter_no=? AND revision_batch_id=?",
                    (status, json_text(stored), now_iso(), book_id, chapter_no, revision_batch_id))
    audit("chapter_candidate_verified", book_id, {"chapter_no": chapter_no, "passed": passed, "status": status})
    return {"passed": passed, "review_cycle": get_review_cycle(book_id, chapter_no, revision_batch_id),
            "next_action": next_action}


def validate_tracking_state(con, book_id, chapter_no, state, revision=False):
    for key in ("context", "characters", "timeline", "foreshadowing", "chapter_index"):
        if not isinstance(state.get(key), str):
            raise ApiError(400, f"追踪状态{key}必须提交完整Markdown文本")
    if len(state["context"].strip()) < 100 or len(state["characters"].strip()) < 50:
        raise ApiError(400, "上下文或人物追踪过短，禁止用单行摘要覆盖完整状态")
    if len(state["timeline"].strip()) < 30 or len(state["foreshadowing"].strip()) < 30:
        raise ApiError(400, "时间线或伏笔追踪过短")
    structured = state.get("structured")
    formal_max = int(con.execute("SELECT COALESCE(MAX(chapter_no),0) FROM chapters WHERE book_id=?",
                                 (book_id,)).fetchone()[0])
    expected_last = formal_max if revision else chapter_no
    if not isinstance(structured, dict) or int(structured.get("last_chapter") or 0) != expected_last:
        raise ApiError(400, "结构化状态last_chapter与项目当前末章不一致", {"expected": expected_last})
    if not isinstance(structured.get("characters"), list) or not isinstance(structured.get("facts"), list):
        raise ApiError(400, "结构化状态必须保留characters和facts数组")
    expected_numbers = [row[0] for row in con.execute(
        "SELECT chapter_no FROM chapters WHERE book_id=? AND chapter_no<=? ORDER BY chapter_no",
        (book_id, expected_last),
    )]
    if chapter_no not in expected_numbers:
        expected_numbers.append(chapter_no)
    missing_index = [no for no in expected_numbers if f"第{no:03d}章" not in state["chapter_index"]]
    if missing_index:
        raise ApiError(400, "章节索引不完整，禁止缩减历史索引", {"missing_chapters": missing_index[:30]})
    if f"第{chapter_no:03d}章" not in state["timeline"]:
        raise ApiError(400, "时间线必须追加当前章节标记", {"chapter_no": chapter_no})


def upsert_tracking_section(text, chapter_no, value):
    start = f"<!-- checkpoint:{chapter_no:03d}:start -->"
    end = f"<!-- checkpoint:{chapter_no:03d}:end -->"
    section = f"{start}\n{value.strip()}\n{end}"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if pattern.search(text):
        return pattern.sub(section, text).strip() + "\n"
    return text.rstrip() + "\n\n" + section + "\n"


def load_complete_tracking_state(book):
    directory = book_dir(book)
    state = {}
    for key in CHECKPOINT_STATE_KEYS:
        path = directory / STATE_FILES[key]
        if key == "structured":
            try:
                state[key] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            except json.JSONDecodeError:
                state[key] = {}
        else:
            state[key] = path.read_text(encoding="utf-8") if path.exists() else f"# {key}\n"
    staged_path = draft_state_path(directory)
    if staged_path.exists():
        try:
            staged = json.loads(staged_path.read_text(encoding="utf-8"))
            for key in CHECKPOINT_STATE_KEYS:
                if key in staged:
                    state[key] = staged[key]
        except json.JSONDecodeError:
            pass
    return state


def resolve_checkpoint_state(con, book, chapter_no, payload, revision=False):
    full_state = payload.get("state")
    patch = payload.get("state_patch")
    if bool(full_state) == bool(patch):
        raise ApiError(400, "检查点必须且只能提交state_patch或兼容版完整state其中之一")
    if full_state:
        missing = sorted(CHECKPOINT_STATE_KEYS - set(full_state))
        if missing:
            raise ApiError(400, "逐章检查点缺少完整追踪状态", {"missing": missing})
        return full_state
    if not isinstance(patch, dict):
        raise ApiError(400, "state_patch必须是对象")
    requirements = {
        "context_update": 30, "characters_update": 10, "timeline_entry": 10,
        "foreshadowing_update": 10, "chapter_index_entry": 6,
    }
    invalid = [key for key, minimum in requirements.items()
               if len(str(patch.get(key) or "").strip()) < minimum]
    structured_patch = patch.get("structured") or {}
    if invalid or not isinstance(structured_patch, dict):
        raise ApiError(400, "state_patch缺少本章追踪增量", {
            "invalid_fields": invalid, "minimum_lengths": requirements,
        })
    state = load_complete_tracking_state(book)
    formal_rows = con.execute(
        "SELECT chapter_no,title,summary FROM chapters WHERE book_id=? ORDER BY chapter_no", (book["id"],)
    ).fetchall()
    missing_history = [row for row in formal_rows if f"第{row['chapter_no']:03d}章" not in state["chapter_index"]]
    if missing_history:
        recovered = ["## 服务器恢复的历史索引"]
        recovered.extend(
            f"- 第{row['chapter_no']:03d}章：{row['title']}；{str(row['summary'] or '').strip()[:120]}"
            for row in missing_history
        )
        state["chapter_index"] = state["chapter_index"].rstrip() + "\n\n" + "\n".join(recovered) + "\n"
    label = f"第{chapter_no:03d}章"
    state["context"] = upsert_tracking_section(state["context"], chapter_no,
                                                f"## {label}上下文更新\n\n{patch['context_update']}")
    state["characters"] = upsert_tracking_section(state["characters"], chapter_no,
                                                   f"## {label}人物状态\n\n{patch['characters_update']}")
    state["timeline"] = upsert_tracking_section(state["timeline"], chapter_no,
                                                 f"- {label}：{patch['timeline_entry']}")
    state["foreshadowing"] = upsert_tracking_section(state["foreshadowing"], chapter_no,
                                                      f"## {label}伏笔\n\n{patch['foreshadowing_update']}")
    state["chapter_index"] = upsert_tracking_section(state["chapter_index"], chapter_no,
                                                      f"- {label}：{patch['chapter_index_entry']}")
    structured = state["structured"] if isinstance(state["structured"], dict) else {}
    existing_characters = structured.get("characters") if isinstance(structured.get("characters"), list) else []
    existing_facts = structured.get("facts") if isinstance(structured.get("facts"), list) else []
    for key, existing in (("characters_add", existing_characters), ("facts_add", existing_facts)):
        additions = structured_patch.get(key) or []
        if not isinstance(additions, list):
            raise ApiError(400, f"state_patch.structured.{key}必须是数组")
        for item in additions:
            if item not in existing:
                existing.append(item)
    formal_max = int(con.execute("SELECT COALESCE(MAX(chapter_no),0) FROM chapters WHERE book_id=?",
                                 (book["id"],)).fetchone()[0])
    structured["last_chapter"] = formal_max if revision else chapter_no
    structured["characters"] = existing_characters
    structured["facts"] = existing_facts
    state["structured"] = structured
    return state


def refresh_writing_contract(book_id, contract_id):
    contract = get_writing_contract(book_id, contract_id)
    if contract["status"] in {"completed", "needs_revision"}:
        return contract
    with db() as con:
        rows = con.execute(
            "SELECT chapter_no,qa_passed FROM chapter_drafts WHERE book_id=? AND chapter_no BETWEEN ? AND ?",
            (book_id, contract["segment_from"], contract["segment_to"]),
        ).fetchall()
        ready = len(rows) == contract["segment_to"] - contract["segment_from"] + 1 and all(row["qa_passed"] for row in rows)
        status = "ready_for_review" if ready else "drafting"
        con.execute("UPDATE writing_contracts SET status=?,updated_at=? WHERE id=?",
                    (status, now_iso(), contract_id))
    return get_writing_contract(book_id, contract_id)


def review_writing_contract(book_id, contract_id, payload):
    contract = get_writing_contract(book_id, contract_id)
    if contract["status"] not in {"ready_for_review", "needs_revision"}:
        raise ApiError(409, "合同章节尚未全部通过逐章QA")
    review = payload.get("review") or {}
    issues = []
    issues.extend(sorted(flag for flag in BATCH_REVIEW_FLAGS if review.get(flag) is not True))
    findings = review.get("chapter_findings") or []
    expected = list(range(contract["segment_from"], contract["segment_to"] + 1))
    if [int(item.get("chapter_no") or 0) for item in findings] != expected:
        issues.append("chapter_findings未完整覆盖合同章节")
    elif any(len(str(item.get("finding") or "").strip()) < 30 for item in findings):
        issues.append("每章审稿结论必须至少30字并指出选择、代价和情绪变化")
    if len(str(review.get("cross_chapter_notes") or "").strip()) < 80:
        issues.append("cross_chapter_notes少于80字")
    protagonist = contract["contract"]["protagonist"]
    with db() as con:
        rows = con.execute("SELECT * FROM chapter_drafts WHERE book_id=? AND chapter_no BETWEEN ? AND ? ORDER BY chapter_no",
                           (book_id, contract["segment_from"], contract["segment_to"])).fetchall()
    bodies = [Path(row["file_path"]).read_text(encoding="utf-8") for row in rows]
    titles = [normalize_title(row["title"]) for row in rows]
    if len(set(titles)) != len(titles):
        issues.append("合同内章节标题重复")
    low_agency = [row["chapter_no"] for row, body in zip(rows, bodies) if body.count(protagonist) < 3]
    if low_agency:
        issues.append(f"主角出现次数过低:{low_agency}")
    cjk_total = sum(cjk_count(body) for body in bodies)
    explanatory = sum(body.count(term) for body in bodies for term in ("不是", "不能", "不等于"))
    if cjk_total and explanatory * 1000 / cjk_total > 6:
        issues.append(f"解释性否定句密度过高:{explanatory * 1000 / cjk_total:.1f}/千字")
    status = "needs_revision" if issues else "completed"
    stored_review = {**review, "server_issues": issues, "passed": not issues}
    with db() as con:
        con.execute("UPDATE writing_contracts SET status=?,review_json=?,updated_at=? WHERE id=?",
                    (status, json_text(stored_review), now_iso(), contract_id))
    audit("writing_contract_reviewed", book_id, {"contract_id": contract_id, "passed": not issues, "issues": issues})
    result = get_writing_contract(book_id, contract_id)
    result["passed"] = not issues
    result["next_action"] = "continue" if not issues else "revise_segment"
    return result


def materialize_latest_checkpoint(book_id):
    """Restore a missing draft file from its durable checkpoint after an interrupted commit."""
    book = get_book(book_id)
    directory = book_dir(book)
    with db() as con:
        drafts = con.execute(
            "SELECT * FROM chapter_drafts WHERE book_id=? ORDER BY chapter_no", (book_id,)
        ).fetchall()
        latest = con.execute(
            "SELECT * FROM chapter_checkpoints WHERE book_id=? ORDER BY id DESC LIMIT 1", (book_id,)
        ).fetchone()
        checkpoint_by_chapter = {}
        for row in drafts:
            checkpoint = con.execute(
                "SELECT * FROM chapter_checkpoints WHERE book_id=? AND chapter_no=? ORDER BY id DESC LIMIT 1",
                (book_id, row["chapter_no"]),
            ).fetchone()
            if checkpoint:
                checkpoint_by_chapter[row["chapter_no"]] = checkpoint
    for row in drafts:
        checkpoint = checkpoint_by_chapter.get(row["chapter_no"])
        if checkpoint and not Path(row["file_path"]).exists():
            atomic_write(Path(row["file_path"]), checkpoint["body"].rstrip() + "\n")
    if latest and drafts and not draft_state_path(directory).exists():
        atomic_write(draft_state_path(directory), json.dumps(
            json.loads(latest["state_json"]), ensure_ascii=False, indent=2
        ) + "\n")


def writing_resume_snapshot(book_id):
    with db() as con:
        active_revision = con.execute(
            "SELECT id FROM revision_batches WHERE book_id=? AND status NOT IN ('completed','cancelled') "
            "ORDER BY created_at DESC LIMIT 1", (book_id,),
        ).fetchone()
    if active_revision:
        return revision_resume_snapshot(book_id, active_revision["id"])
    materialize_latest_checkpoint(book_id)
    book = get_book(book_id)
    batch = get_writing_batch(book_id)
    with db() as con:
        formal = {row["chapter_no"]: row_dict(row) for row in con.execute(
            "SELECT chapter_no,title,cjk_chars,qa_passed,uploaded FROM chapters WHERE book_id=? ORDER BY chapter_no",
            (book_id,),
        )}
        drafts = {row["chapter_no"]: row_dict(row) for row in con.execute(
            "SELECT chapter_no,title,cjk_chars,draft_revision,qa_passed,status,qa_json FROM chapter_drafts WHERE book_id=? ORDER BY chapter_no",
            (book_id,),
        )}
        latest_checkpoint = con.execute(
            "SELECT chapter_no,committed_revision,created_at FROM chapter_checkpoints WHERE book_id=? ORDER BY id DESC LIMIT 1",
            (book_id,),
        ).fetchone()
        contracts = [contract_row_data(row) for row in con.execute(
            "SELECT * FROM writing_contracts WHERE book_id=? AND status NOT IN ('superseded','cancelled') "
            "ORDER BY segment_from", (book_id,)
        ).fetchall()]
        review_cycles = {row["chapter_no"]: review_cycle_data(row) for row in con.execute(
            "SELECT * FROM chapter_review_cycles WHERE book_id=? AND revision_batch_id='' ORDER BY chapter_no",
            (book_id,),
        ).fetchall()}
    next_action = {"type": "await_batch_configuration"}
    progress = None
    if batch and batch.get("status") != "not_configured":
        start = int(batch["from_chapter"])
        end = start + int(batch["target_chapters"]) - 1
        target = list(range(start, end + 1))
        progress = {
            "from": start, "to": end, "target_chapters": len(target),
            "formal": sum(no in formal for no in target),
            "drafted": sum(no in drafts for no in target),
            "qa_passed": sum(bool(drafts.get(no, {}).get("qa_passed")) or
                             bool(formal.get(no, {}).get("qa_passed")) for no in target),
        }
        failed = [no for no in target if no in drafts and drafts[no]["status"] == "qa_failed"]
        pending = [no for no in target if no in drafts and not drafts[no]["qa_passed"]]
        missing = [no for no in target if no not in drafts and no not in formal]
        target_contracts = [item for item in contracts if item["segment_from"] >= start and item["segment_to"] <= end]
        contract_needs_revision = next((item for item in target_contracts if item["status"] == "needs_revision"), None)
        contract_needs_review = next((item for item in target_contracts if item["status"] == "ready_for_review"), None)
        active_cycle = next((review_cycles.get(no) for no in target
                             if review_cycles.get(no) and review_cycles[no]["status"] not in {"committed"}), None)
        earliest_blocker = min(failed + pending) if failed or pending else None
        if earliest_blocker is not None and (not active_cycle or earliest_blocker < active_cycle["chapter_no"]):
            if earliest_blocker in failed:
                next_action = {"type": "revise_chapter", "chapter_no": earliest_blocker}
            else:
                next_action = {"type": "run_qa", "chapter_no": earliest_blocker}
        elif active_cycle:
            next_action = review_next_action(active_cycle)
        elif failed:
            next_action = {"type": "revise_chapter", "chapter_no": failed[0]}
        elif pending:
            next_action = {"type": "run_qa", "chapter_no": pending[0]}
        elif batch.get("quality_mode") == "strong" and contract_needs_revision:
            next_action = {"type": "revise_segment", "contract_id": contract_needs_revision["id"],
                           "from": contract_needs_revision["segment_from"], "to": contract_needs_revision["segment_to"],
                           "issues": (contract_needs_revision.get("review") or {}).get("server_issues", [])}
        elif batch.get("quality_mode") == "strong" and contract_needs_review:
            next_action = {"type": "review_segment", "contract_id": contract_needs_review["id"],
                           "from": contract_needs_review["segment_from"], "to": contract_needs_review["segment_to"]}
        elif missing:
            chapter_no = missing[0]
            contract = next((item for item in target_contracts
                             if item["segment_from"] <= chapter_no <= item["segment_to"]), None)
            incomplete_prior = next((item for item in target_contracts
                                     if item["segment_to"] < chapter_no and item["status"] != "completed"), None)
            if batch.get("quality_mode") == "strong" and incomplete_prior:
                next_action = {"type": "review_segment", "contract_id": incomplete_prior["id"],
                               "from": incomplete_prior["segment_from"], "to": incomplete_prior["segment_to"]}
            elif batch.get("quality_mode") == "strong" and not contract:
                segment_end = min(chapter_no + 3, end)
                next_action = {"type": "plan_segment", "from": chapter_no, "to": segment_end,
                               "requirements": "先建立逐章创作合同；每章主角主动选择、类型兑现、情绪变化和结构指纹必须不同。"}
            else:
                next_action = {"type": "write_candidate", "chapter_no": chapter_no,
                               "contract_id": contract["id"] if contract else None,
                               "chapter_plan": next((plan for plan in contract["contract"]["chapter_plans"]
                                                     if int(plan["chapter_no"]) == chapter_no), None) if contract else None}
        elif batch.get("upload_job_id") and batch.get("upload_status") in {"queued", "running"}:
            next_action = {"type": "poll_upload", "job_id": batch["upload_job_id"]}
        elif batch.get("upload_mode") == "review" and batch.get("status") == "ready_for_upload":
            next_action = {"type": "await_user_review"}
        elif batch.get("upload_status") == "completed":
            next_action = {"type": "completed"}
        else:
            next_action = {"type": "finalize_batch"}
    next_action = executable_next_action(next_action)
    active_contract_id = next_action.get("contract_id") if next_action["type"] in {"review_segment", "revise_segment"} else None
    return {
        "book": {k: book[k] for k in ("id", "title", "stage", "revision", "account", "platform_book_id")},
        "writing_batch": batch,
        "writing_contracts": [contract_summary(item) for item in target_contracts]
        if batch and batch.get("status") != "not_configured" else [],
        "active_contract": next((item for item in target_contracts if item["id"] == active_contract_id), None),
        "review_cycles": [review_cycle_summary(item) for item in review_cycles.values()],
        "progress": progress,
        "drafts": list(drafts.values()),
        "latest_checkpoint": row_dict(latest_checkpoint),
        "next_action": next_action,
        "continue_required": next_action["type"] not in {"completed", "await_user_review", "await_batch_configuration"},
        "instruction": "只执行next_action；服务器是唯一事实来源，不得用聊天缓存覆盖较新revision。",
    }


def configure_revision_batch(book_id, payload):
    get_book(book_id)
    mode = str(payload.get("mode") or "review")
    if mode not in {"auto", "review"}:
        raise ApiError(400, "mode必须为auto或review")
    selectors = sum(bool(payload.get(key)) for key in ("all_chapters", "chapter_numbers", "from_chapter"))
    if selectors != 1:
        raise ApiError(400, "必须且只能选择整本、章节列表或连续章节范围之一")
    with db() as con:
        formal_numbers = [row[0] for row in con.execute(
            "SELECT chapter_no FROM chapters WHERE book_id=? ORDER BY chapter_no", (book_id,)
        )]
        active = con.execute(
            "SELECT * FROM revision_batches WHERE book_id=? AND status NOT IN ('completed','cancelled') ORDER BY created_at DESC LIMIT 1",
            (book_id,),
        ).fetchone()
        if active:
            return revision_resume_snapshot(book_id, active["id"])
        writing = con.execute("SELECT * FROM writing_batches WHERE book_id=?", (book_id,)).fetchone()
        if writing and writing["status"] not in {"completed", "cancelled", "promoted"}:
            raise ApiError(409, "当前续写批次尚未完成，不能同时修订旧章节", row_dict(writing))
        if con.execute("SELECT 1 FROM chapter_drafts WHERE book_id=? LIMIT 1", (book_id,)).fetchone():
            raise ApiError(409, "当前还有待QA临时稿，必须先完成或处理后再修订旧章节")
    if payload.get("all_chapters"):
        targets = formal_numbers
    elif payload.get("chapter_numbers"):
        targets = sorted(set(int(no) for no in payload["chapter_numbers"]))
    else:
        start = int(payload.get("from_chapter") or 0)
        end = int(payload.get("to_chapter") or 0)
        if start < 1 or end < start:
            raise ApiError(400, "修订章节范围无效")
        targets = list(range(start, end + 1))
    if not targets or len(targets) > 500:
        raise ApiError(400, "修订范围必须包含1到500章")
    missing = [no for no in targets if no not in formal_numbers]
    if missing:
        raise ApiError(409, "部分章节尚未正式保存，不能修订", {"missing": missing[:30]})
    revision_id, stamp = uuid.uuid4().hex, now_iso()
    with db() as con:
        con.execute("""INSERT INTO revision_batches
                    (id,book_id,target_json,mode,status,completed_chapters,qa_status,created_at,updated_at,quality_mode)
                    VALUES(?,?,?,?,'revising',0,'pending',?,?,'strong')""",
                    (revision_id, book_id, json_text(targets), mode, stamp, stamp))
    audit("revision_batch_configured", book_id, {"revision_batch_id": revision_id, "targets": targets, "mode": mode})
    return revision_resume_snapshot(book_id, revision_id)


def refresh_revision_batch(book_id, revision_batch_id):
    with db() as con:
        batch = con.execute("SELECT * FROM revision_batches WHERE id=? AND book_id=?",
                            (revision_batch_id, book_id)).fetchone()
        if not batch:
            raise ApiError(404, "修订批次不存在")
        targets = json.loads(batch["target_json"])
        completed = 0
        qa_passed = 0
        for no in targets:
            checkpoint = con.execute(
                "SELECT 1 FROM chapter_checkpoints WHERE book_id=? AND chapter_no=? AND revision_batch_id=? LIMIT 1",
                (book_id, no, revision_batch_id),
            ).fetchone()
            draft = con.execute("SELECT qa_passed FROM chapter_drafts WHERE book_id=? AND chapter_no=?",
                                (book_id, no)).fetchone()
            if checkpoint:
                completed += 1
                if draft and draft["qa_passed"]:
                    qa_passed += 1
        chapter_ready = completed == len(targets) and qa_passed == len(targets)
        contracts_ready = True
        if batch["quality_mode"] == "strong":
            contracts = con.execute("SELECT segment_from,segment_to,status FROM writing_contracts "
                                    "WHERE book_id=? AND revision_batch_id=? "
                                    "AND status NOT IN ('superseded','cancelled') ORDER BY segment_from",
                                    (book_id, revision_batch_id)).fetchall()
            covered = [no for contract in contracts for no in range(contract["segment_from"], contract["segment_to"] + 1)]
            contracts_ready = covered == targets and all(contract["status"] == "completed" for contract in contracts)
        ready = chapter_ready and contracts_ready
        status = ("ready_for_review" if ready and batch["mode"] == "review" else
                  "ready_to_promote" if ready else
                  "quality_review_pending" if chapter_ready and not contracts_ready else "revising")
        qa_status = "passed" if ready else ("quality_review_pending" if chapter_ready else "partial" if completed else "pending")
        con.execute("UPDATE revision_batches SET completed_chapters=?,status=?,qa_status=?,updated_at=? WHERE id=?",
                    (completed, status, qa_status, now_iso(), revision_batch_id))
    return row_dict(batch) if batch["status"] == "completed" else revision_resume_snapshot(book_id, revision_batch_id)


def revision_resume_snapshot(book_id, revision_batch_id=""):
    materialize_latest_checkpoint(book_id)
    with db() as con:
        if revision_batch_id:
            batch = con.execute("SELECT * FROM revision_batches WHERE id=? AND book_id=?",
                                (revision_batch_id, book_id)).fetchone()
        else:
            batch = con.execute(
                "SELECT * FROM revision_batches WHERE book_id=? AND status NOT IN ('completed','cancelled') ORDER BY created_at DESC LIMIT 1",
                (book_id,),
            ).fetchone()
        if not batch:
            return {"book_id": book_id, "status": "not_configured",
                    "next_action": executable_next_action({"type": "configure_revision"})}
        targets = json.loads(batch["target_json"])
        contracts = [contract_row_data(row) for row in con.execute(
            "SELECT * FROM writing_contracts WHERE book_id=? AND revision_batch_id=? "
            "AND status NOT IN ('superseded','cancelled') ORDER BY segment_from",
            (book_id, batch["id"]),
        ).fetchall()]
        review_cycles = {row["chapter_no"]: review_cycle_data(row) for row in con.execute(
            "SELECT * FROM chapter_review_cycles WHERE book_id=? AND revision_batch_id=? ORDER BY chapter_no",
            (book_id, batch["id"]),
        ).fetchall()}
        progress = []
        for no in targets:
            checkpoint = con.execute(
                "SELECT 1 FROM chapter_checkpoints WHERE book_id=? AND chapter_no=? AND revision_batch_id=? LIMIT 1",
                (book_id, no, batch["id"]),
            ).fetchone()
            draft = con.execute("SELECT * FROM chapter_drafts WHERE book_id=? AND chapter_no=?", (book_id, no)).fetchone()
            progress.append({"chapter_no": no, "checkpointed": bool(checkpoint),
                             "qa_passed": bool(draft and draft["qa_passed"]),
                             "status": draft["status"] if draft else "not_revised"})
        failed = [x for x in progress if x["status"] == "qa_failed"]
        pending = [x for x in progress if x["checkpointed"] and not x["qa_passed"]]
        missing = [x for x in progress if not x["checkpointed"]]
        contract_needs_revision = next((item for item in contracts if item["status"] == "needs_revision"), None)
        contract_needs_review = next((item for item in contracts if item["status"] == "ready_for_review"), None)
        active_cycle = next((review_cycles.get(no) for no in targets
                             if review_cycles.get(no) and review_cycles[no]["status"] not in {"committed"}), None)
        blockers = failed + pending
        earliest_blocker = min(blockers, key=lambda item: item["chapter_no"]) if blockers else None
        if earliest_blocker and (not active_cycle or earliest_blocker["chapter_no"] < active_cycle["chapter_no"]):
            if earliest_blocker in failed:
                next_action = {"type": "revise_chapter", "chapter_no": earliest_blocker["chapter_no"]}
            else:
                next_action = {"type": "run_qa", "chapter_no": earliest_blocker["chapter_no"]}
        elif active_cycle:
            next_action = review_next_action(active_cycle)
        elif failed:
            next_action = {"type": "revise_chapter", "chapter_no": failed[0]["chapter_no"]}
        elif pending:
            next_action = {"type": "run_qa", "chapter_no": pending[0]["chapter_no"]}
        elif batch["quality_mode"] == "strong" and contract_needs_revision:
            next_action = {"type": "revise_segment", "contract_id": contract_needs_revision["id"],
                           "from": contract_needs_revision["segment_from"], "to": contract_needs_revision["segment_to"],
                           "issues": (contract_needs_revision.get("review") or {}).get("server_issues", [])}
        elif batch["quality_mode"] == "strong" and contract_needs_review:
            next_action = {"type": "review_segment", "contract_id": contract_needs_review["id"],
                           "from": contract_needs_review["segment_from"], "to": contract_needs_review["segment_to"]}
        elif missing:
            chapter_no = missing[0]["chapter_no"]
            contract = next((item for item in contracts if item["segment_from"] <= chapter_no <= item["segment_to"]), None)
            incomplete_prior = next((item for item in contracts
                                     if item["segment_to"] < chapter_no and item["status"] != "completed"), None)
            if batch["quality_mode"] == "strong" and incomplete_prior:
                next_action = {"type": "review_segment", "contract_id": incomplete_prior["id"],
                               "from": incomplete_prior["segment_from"], "to": incomplete_prior["segment_to"]}
            elif batch["quality_mode"] == "strong" and not contract:
                target_index = targets.index(chapter_no)
                segment_targets = targets[target_index:target_index + 4]
                next_action = {"type": "plan_revision_segment", "from": segment_targets[0], "to": segment_targets[-1],
                               "revision_batch_id": batch["id"]}
            else:
                next_action = {"type": "rewrite_candidate", "chapter_no": chapter_no,
                               "contract_id": contract["id"] if contract else None,
                               "chapter_plan": next((plan for plan in contract["contract"]["chapter_plans"]
                                                     if int(plan["chapter_no"]) == chapter_no), None) if contract else None}
        elif batch["status"] == "ready_for_review":
            next_action = {"type": "await_user_review"}
        elif batch["status"] == "ready_to_promote":
            next_action = {"type": "promote_revision"}
        else:
            next_action = {"type": "completed"}
        chapter_no = next_action.get("chapter_no")
        source = None
        if chapter_no and next_action["type"] not in {
                "critique_chapter", "revise_candidate", "verify_candidate", "commit_verified_chapter"}:
            row = con.execute("SELECT * FROM chapter_drafts WHERE book_id=? AND chapter_no=?",
                              (book_id, chapter_no)).fetchone()
            if not row:
                row = con.execute("SELECT * FROM chapters WHERE book_id=? AND chapter_no=?",
                                  (book_id, chapter_no)).fetchone()
            if row:
                source = {"chapter_no": chapter_no, "title": row["title"], "summary": row["summary"],
                          "body": read_limited(Path(row["file_path"]), 20_000)}
        planning_sources = []
        if next_action["type"] == "plan_revision_segment":
            for planned_no in range(next_action["from"], next_action["to"] + 1):
                row = con.execute("SELECT * FROM chapters WHERE book_id=? AND chapter_no=?",
                                  (book_id, planned_no)).fetchone()
                planning_sources.append({"chapter_no": planned_no, "title": row["title"],
                                         "summary": row["summary"], "cjk_chars": row["cjk_chars"],
                                         "body_retrieval": {"action": "context_get",
                                                            "payload": {"chapter_no": planned_no,
                                                                        "offset": 0, "limit": 4000}}})
    next_action = executable_next_action(next_action, batch["id"])
    active_contract_id = next_action.get("contract_id") if next_action["type"] in {"review_segment", "revise_segment"} else None
    return {
        "book": {k: get_book(book_id)[k] for k in ("id", "title", "stage", "revision", "account")},
        "revision_batch": {**row_dict(batch), "targets": targets}, "progress": progress,
        "writing_contracts": [contract_summary(item) for item in contracts],
        "active_contract": next((item for item in contracts if item["id"] == active_contract_id), None),
        "source_chapter": source, "planning_sources": planning_sources,
        "review_cycles": [review_cycle_summary(item) for item in review_cycles.values()],
        "next_action": next_action,
        "continue_required": next_action["type"] not in {"completed", "await_user_review"},
        "instruction": "逐章修订并使用revision_batch_id提交原子检查点；未全部QA通过前不得覆盖正式正文。",
    }


def promote_revision_batch(book_id, revision_batch_id, require_review=False):
    snapshot = revision_resume_snapshot(book_id, revision_batch_id)
    batch = snapshot.get("revision_batch") or {}
    allowed = "ready_for_review" if require_review else "ready_to_promote"
    if batch.get("status") != allowed:
        raise ApiError(409, "修订批次尚未全部通过QA或模式不匹配", {"status": batch.get("status")})
    targets = batch["targets"]
    ranges = []
    start = end = targets[0]
    for no in targets[1:]:
        if no == end + 1:
            end = no
        else:
            ranges.append((start, end))
            start = end = no
    ranges.append((start, end))
    for start, end in ranges:
        promote_drafts(book_id, start, end, reset_uploaded=True)
    with db() as con:
        con.execute("UPDATE revision_batches SET status='completed',qa_status='passed',updated_at=? WHERE id=?",
                    (now_iso(), revision_batch_id))
    audit("revision_batch_promoted", book_id, {"revision_batch_id": revision_batch_id, "targets": targets})
    return revision_resume_snapshot(book_id, revision_batch_id)


def require_verified_candidate(con, book_id, chapter_no, revision_batch_id, contract_id, title, body, summary):
    row = con.execute(
        "SELECT * FROM chapter_review_cycles WHERE book_id=? AND chapter_no=? AND revision_batch_id=?",
        (book_id, chapter_no, revision_batch_id or ""),
    ).fetchone()
    if not row or row["status"] != "verified":
        raise ApiError(409, "强质量模式必须先完成候选稿独立审稿、返修和验收", {
            "next_action": "candidate_save" if not row else row["status"],
            "review_cycle": review_cycle_data(row),
        })
    if (row["contract_id"] != contract_id or row["title"] != title or row["body"].strip() != body.strip()
            or row["summary"] != summary):
        raise ApiError(409, "检查点正文必须与已通过独立验收的候选版本完全一致")
    return row


def save_chapter_checkpoint(book_id, payload):
    book = get_book(book_id)
    expected = int(payload.get("expected_revision") or 0)
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{12,120}", idempotency_key):
        raise ApiError(400, "idempotency_key必须为12到120位稳定标识")
    item = payload.get("chapter") or {}
    no = int(item.get("chapter_no") or 0)
    title = short_chapter_title(item.get("title"))
    body = str(item.get("body") or "").strip() + "\n"
    summary = str(item.get("summary") or "").strip()
    revision_batch_id = str(payload.get("revision_batch_id") or "").strip() or None
    contract_id = str(payload.get("contract_id") or "").strip() or None
    self_review = payload.get("self_review") or None
    chapter_plan = None
    verified_candidate = None
    state = None
    if len(body) > 20_000 or cjk_count(body) < 100:
        raise ApiError(400, f"第{no:03d}章正文长度无效")
    if book["stage"] not in {"trial_writing", "trial_ready_for_review", "awaiting_trial_approval", "bulk_writing"}:
        raise ApiError(409, "当前阶段不允许写章")
    stamp = now_iso()
    directory = book_dir(book)
    with db() as con:
        state = resolve_checkpoint_state(con, book, no, payload, revision=bool(revision_batch_id))
        duplicate = con.execute(
            "SELECT chapter_no,title,body,summary,state_json,committed_revision,revision_batch_id,contract_id,self_review_json FROM chapter_checkpoints "
            "WHERE book_id=? AND idempotency_key=?",
            (book_id, idempotency_key),
        ).fetchone()
        if duplicate:
            if (duplicate["chapter_no"] != no or duplicate["title"] != title or
                    duplicate["body"] != body or duplicate["summary"] != summary or
                    duplicate["state_json"] != json_text(state) or
                    duplicate["revision_batch_id"] != revision_batch_id or
                    duplicate["contract_id"] != contract_id or
                    (duplicate["self_review_json"] or None) != (json_text(self_review) if self_review else None)):
                raise ApiError(409, "idempotency_key已用于不同内容，必须重新读取恢复快照并使用新key")
            return {"checkpoint_committed": True, "idempotent_replay": True,
                    "committed_revision": duplicate["committed_revision"],
                    "resume": writing_resume_snapshot(book_id)}
        current = con.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if not current or int(current["revision"]) != expected:
            raise ApiError(409, "项目版本已变化，必须重新读取恢复快照", {
                "expected_revision": expected,
                "current_revision": int(current["revision"]) if current else None,
            })
        if revision_batch_id:
            revision_batch = con.execute(
                "SELECT * FROM revision_batches WHERE id=? AND book_id=?",
                (revision_batch_id, book_id),
            ).fetchone()
            if not revision_batch or revision_batch["status"] not in {"revising", "qa_pending"}:
                raise ApiError(409, "修订批次不存在或当前不可修改")
            targets = json.loads(revision_batch["target_json"])
            if no not in targets:
                raise ApiError(409, "章节不在当前修订范围", {"targets": targets[:20]})
            if not con.execute("SELECT 1 FROM chapters WHERE book_id=? AND chapter_no=?", (book_id, no)).fetchone():
                raise ApiError(409, "只能修订已经正式保存的章节", {"chapter_no": no})
            if revision_batch["quality_mode"] == "strong":
                contract_row = con.execute("SELECT * FROM writing_contracts WHERE id=? AND book_id=? AND revision_batch_id=?",
                                           (contract_id, book_id, revision_batch_id)).fetchone() if contract_id else None
                if not contract_row or not contract_row["segment_from"] <= no <= contract_row["segment_to"]:
                    raise ApiError(409, "强制修订模式必须先建立覆盖当前章的创作合同")
                contract_data = json.loads(contract_row["contract_json"])
                chapter_plan = next((plan for plan in contract_data["chapter_plans"]
                                     if int(plan["chapter_no"]) == no), None)
                if not chapter_plan:
                    raise ApiError(409, "修订创作合同缺少当前章节计划")
                validate_checkpoint_review(body, self_review)
                validate_tracking_state(con, book_id, no, state, revision=True)
                verified_candidate = require_verified_candidate(
                    con, book_id, no, revision_batch_id, contract_id, title, body, summary)
            for prior in targets[:targets.index(no)]:
                checkpoint = con.execute(
                    "SELECT 1 FROM chapter_checkpoints WHERE book_id=? AND chapter_no=? AND revision_batch_id=? LIMIT 1",
                    (book_id, prior, revision_batch_id),
                ).fetchone()
                draft = con.execute(
                    "SELECT qa_passed FROM chapter_drafts WHERE book_id=? AND chapter_no=?", (book_id, prior)
                ).fetchone()
                if not checkpoint or not draft or not draft["qa_passed"]:
                    raise ApiError(409, "前序修订章节尚未通过QA", {"blocking_chapter": prior})
        elif current["stage"] in {"trial_writing", "trial_ready_for_review", "awaiting_trial_approval"}:
            if not 1 <= no <= 3:
                raise ApiError(409, "三章试读未批准，不能写第4章")
        else:
            batch = con.execute("SELECT * FROM writing_batches WHERE book_id=?", (book_id,)).fetchone()
            if not batch or batch["status"] in {"completed", "cancelled"}:
                raise ApiError(409, "没有可恢复的写作批次")
            start, end = batch["from_chapter"], batch["from_chapter"] + batch["target_chapters"] - 1
            if not start <= no <= end:
                raise ApiError(409, "章节不在当前写作批次范围内", {"from": start, "to": end})
            if batch["quality_mode"] == "strong":
                contract_row = con.execute("SELECT * FROM writing_contracts WHERE id=? AND book_id=?",
                                           (contract_id, book_id)).fetchone() if contract_id else None
                if not contract_row or not contract_row["segment_from"] <= no <= contract_row["segment_to"]:
                    raise ApiError(409, "强制质量模式必须先建立覆盖当前章的创作合同")
                contract_data = json.loads(contract_row["contract_json"])
                chapter_plan = next((plan for plan in contract_data["chapter_plans"]
                                     if int(plan["chapter_no"]) == no), None)
                if not chapter_plan:
                    raise ApiError(409, "创作合同缺少当前章节计划")
                validate_checkpoint_review(body, self_review)
                validate_tracking_state(con, book_id, no, state)
                verified_candidate = require_verified_candidate(
                    con, book_id, no, "", contract_id, title, body, summary)
            blockers = con.execute(
                "SELECT chapter_no,status FROM chapter_drafts WHERE book_id=? AND chapter_no BETWEEN ? AND ? "
                "AND chapter_no<>? AND qa_passed=0 ORDER BY chapter_no",
                (book_id, start, no - 1, no),
            ).fetchall()
            if blockers:
                raise ApiError(409, "前序章节尚未通过QA，禁止继续写后续章节", {
                    "blocking_chapter": blockers[0]["chapter_no"], "status": blockers[0]["status"],
                })
            existing = con.execute(
                "SELECT chapter_no FROM chapter_drafts WHERE book_id=? AND chapter_no=?", (book_id, no)
            ).fetchone()
            if not existing:
                first_missing = next((candidate for candidate in range(start, end + 1) if not con.execute(
                    "SELECT 1 FROM chapters WHERE book_id=? AND chapter_no=? UNION SELECT 1 FROM chapter_drafts WHERE book_id=? AND chapter_no=?",
                    (book_id, candidate, book_id, candidate),
                ).fetchone()), None)
                if first_missing != no:
                    raise ApiError(409, "必须按连续章节顺序写作", {"next_chapter": first_missing})
        old = con.execute(
            "SELECT file_path,draft_revision FROM chapter_drafts WHERE book_id=? AND chapter_no=?", (book_id, no)
        ).fetchone()
        path = chapter_draft_file(directory, no, title)
        draft_revision = int(old["draft_revision"] if old else 0) + 1
        committed_revision = expected + 1
        con.execute("""INSERT INTO chapter_checkpoints
                    (book_id,chapter_no,idempotency_key,title,body,summary,state_json,committed_revision,created_at,
                     revision_batch_id,contract_id,self_review_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (book_id, no, idempotency_key, title, body, summary, json_text(state),
                     committed_revision, stamp, revision_batch_id, contract_id,
                     json_text(self_review) if self_review else None))
        con.execute("""INSERT OR REPLACE INTO chapter_drafts
                    (book_id,chapter_no,title,file_path,body_chars,cjk_chars,summary,draft_revision,qa_json,qa_passed,status,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,NULL,0,'drafting',?)""",
                    (book_id, no, title, str(path), len(body.strip()), cjk_count(body), summary,
                     draft_revision, stamp))
        con.execute("UPDATE books SET revision=?,updated_at=? WHERE id=?", (committed_revision, stamp, book_id))
        if current["stage"] in {"trial_ready_for_review", "awaiting_trial_approval"}:
            con.execute("UPDATE books SET stage='trial_writing' WHERE id=?", (book_id,))
        if contract_id:
            con.execute("UPDATE writing_contracts SET status='drafting',review_json=NULL,updated_at=? WHERE id=?",
                        (stamp, contract_id))
        if verified_candidate:
            con.execute("UPDATE chapter_review_cycles SET status='committed',updated_at=? "
                        "WHERE book_id=? AND chapter_no=? AND revision_batch_id=?",
                        (stamp, book_id, no, revision_batch_id or ""))
    if old and Path(old["file_path"]) != path:
        Path(old["file_path"]).unlink(missing_ok=True)
    atomic_write(path, body)
    atomic_write(draft_state_path(directory), json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    if chapter_plan:
        outline = (
            f"# 第{no:03d}章细纲：{title}\n\n"
            f"- 主角目标：{chapter_plan['protagonist_goal']}\n"
            f"- 阻力：{chapter_plan['obstacle']}\n"
            f"- 关键选择：{chapter_plan['consequential_choice']}\n"
            f"- 代价：{chapter_plan['cost']}\n"
            f"- 状态变化：{chapter_plan['state_change']}\n"
            f"- 情绪回报：{chapter_plan['emotional_payoff']}\n"
            f"- 类型兑现：{chapter_plan['type_promise']}\n"
            f"- 冲突引擎：{chapter_plan['conflict_engine']}\n"
            f"- 章末钩子：{chapter_plan['ending_hook']}\n"
            f"- 结构指纹：{chapter_plan['structural_fingerprint']}\n"
            f"- 正文摘要：{summary}\n"
        )
        atomic_write(directory / "大纲" / f"细纲_第{no:03d}章.md", outline)
    audit("chapter_checkpoint_committed", book_id, {
        "chapter_no": no, "idempotency_key": idempotency_key, "revision": committed_revision,
        "revision_batch_id": revision_batch_id, "contract_id": contract_id,
    })
    if revision_batch_id:
        refresh_revision_batch(book_id, revision_batch_id)
    else:
        refresh_writing_batch(book_id)
    return {"checkpoint_committed": True, "idempotent_replay": False,
            "committed_revision": committed_revision, "resume": writing_resume_snapshot(book_id)}


def get_context(book_id, query="", section="", offset=0, limit=4000, chapter_no=0):
    materialize_latest_checkpoint(book_id)
    book = get_book(book_id)
    directory = book_dir(book)
    staged = {}
    staged_state_path = draft_state_path(directory)
    if staged_state_path.exists():
        try:
            staged = json.loads(staged_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            staged = {}
    if chapter_no:
        with db() as con:
            row = con.execute("SELECT chapter_no,title,summary,file_path FROM chapter_drafts WHERE book_id=? AND chapter_no=?",
                              (book_id, chapter_no)).fetchone()
            source = "draft"
            if not row:
                row = con.execute("SELECT chapter_no,title,summary,file_path FROM chapters WHERE book_id=? AND chapter_no=?",
                                  (book_id, chapter_no)).fetchone()
                source = "formal"
        if not row:
            raise ApiError(404, "章节不存在", {"chapter_no": chapter_no})
        value = Path(row["file_path"]).read_text(encoding="utf-8")
        offset = max(0, int(offset or 0))
        limit = min(5000, max(500, int(limit or 4000)))
        chunk = value[offset:offset + limit]
        return {"book_id": book_id, "chapter_no": chapter_no, "title": row["title"],
                "summary": row["summary"], "source": source, "offset": offset, "limit": limit,
                "total_chars": len(value), "content": chunk,
                "next_offset": offset + len(chunk) if offset + len(chunk) < len(value) else None,
                "has_more": offset + len(chunk) < len(value)}
    if section:
        if section not in STATE_FILES:
            raise ApiError(400, "未知追踪分区", {"allowed_sections": sorted(STATE_FILES)})
        value = staged.get(section)
        if value is None:
            value = read_limited(directory / STATE_FILES[section], 200_000)
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        offset = max(0, int(offset or 0))
        limit = min(5000, max(500, int(limit or 4000)))
        chunk = value[offset:offset + limit]
        return {"book_id": book_id, "section": section, "offset": offset, "limit": limit,
                "total_chars": len(value), "content": chunk,
                "next_offset": offset + len(chunk) if offset + len(chunk) < len(value) else None,
                "has_more": offset + len(chunk) < len(value)}
    state_limits = {
        "context": 2500, "structured": 2500, "characters": 1800,
        "timeline": 1800, "foreshadowing": 1800, "chapter_index": 2500,
        "outline": 2500, "current_volume": 3000, "book_bible": 2500,
    }
    states = {key: read_limited(directory / rel, state_limits[key]) for key, rel in STATE_FILES.items()}
    for key, value in staged.items():
        if key in STATE_FILES:
            if key == "structured" and isinstance(value, dict):
                states[key] = value
            else:
                rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
                states[key] = rendered[:state_limits[key]]
    state_manifest = {}
    for key, rel in STATE_FILES.items():
        value = staged.get(key)
        if value is None:
            path = directory / rel
            total = len(path.read_text(encoding="utf-8")) if path.exists() else 0
        else:
            total = len(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        state_manifest[key] = {"total_chars": total, "preview_truncated": total > state_limits[key]}
    with db() as con:
        latest = con.execute("SELECT * FROM chapters WHERE book_id=? ORDER BY chapter_no DESC LIMIT 3", (book_id,)).fetchall()
        drafts = con.execute("SELECT * FROM chapter_drafts WHERE book_id=? ORDER BY chapter_no", (book_id,)).fetchall()
        related = []
        if query.strip():
            try:
                related = con.execute("SELECT chapter_no,title,snippet(chapter_fts,4,'','','…',20) body FROM chapter_fts WHERE book_id=? AND chapter_fts MATCH ? LIMIT 5", (book_id, query)).fetchall()
            except sqlite3.OperationalError:
                related = []
    chapters = []
    for row in reversed(latest):
        chapters.append({"chapter_no": row["chapter_no"], "title": row["title"],
                         "body": read_limited(Path(row["file_path"]), 2500)})
    return {"book": {k: book[k] for k in ("id", "title", "stage", "revision", "account", "platform_book_id")},
            "state": states, "state_manifest": state_manifest, "latest_chapters": chapters,
            "active_drafts": [{"chapter_no": x["chapter_no"], "title": x["title"],
                               "draft_revision": x["draft_revision"], "qa_passed": bool(x["qa_passed"]),
                               "status": x["status"], "summary": x["summary"]} for x in drafts],
            "related": [row_dict(x) for x in related],
            "instruction": "默认响应为轻量预览；需要完整追踪时用context_get提交section、offset、limit分页读取。"}


def get_chapter_drafts(book_id, start=1, end=10**9):
    book = get_book(book_id)
    with db() as con:
        rows = con.execute("SELECT * FROM chapter_drafts WHERE book_id=? AND chapter_no BETWEEN ? AND ? ORDER BY chapter_no",
                           (book_id, start, end)).fetchall()
    return {
        "book_id": book_id, "stage": book["stage"], "revision": book["revision"],
        "drafts": [{**row_dict(row), "qa_passed": bool(row["qa_passed"]),
                    "qa_json": json.loads(row["qa_json"]) if row["qa_json"] else None,
                    "body": read_limited(Path(row["file_path"]), 20_000)} for row in rows],
    }


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
        con.execute("INSERT OR REPLACE INTO writing_batches(book_id,from_chapter,target_chapters,approximate_words,upload_mode,status,completed_chapters,qa_status,upload_status,upload_job_id,created_at,updated_at,quality_mode) VALUES(?,?,?,?,?,'writing',0,'pending','pending',NULL,?,?,'strong')",
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
        rows = con.execute("SELECT chapter_no,qa_passed FROM chapter_drafts WHERE book_id=? AND chapter_no BETWEEN ? AND ?",
                           (book_id, start, end)).fetchall()
        completed = len(rows)
        all_ready = completed == batch["target_chapters"]
        chapter_qa_ready = all_ready and all(row["qa_passed"] for row in rows)
        contracts_ready = True
        if batch["quality_mode"] == "strong":
            contracts = con.execute(
                "SELECT segment_from,segment_to,status FROM writing_contracts WHERE book_id=? "
                "AND segment_from>=? AND segment_to<=? ORDER BY segment_from",
                (book_id, start, end),
            ).fetchall()
            covered = [no for contract in contracts for no in range(contract["segment_from"], contract["segment_to"] + 1)]
            contracts_ready = covered == list(range(start, end + 1)) and all(contract["status"] == "completed" for contract in contracts)
        qa_ready = chapter_qa_ready and contracts_ready
        status = ("ready_for_upload" if qa_ready else
                  "quality_review_pending" if chapter_qa_ready and not contracts_ready else
                  "qa_pending" if all_ready else "writing")
        qa_status = ("passed" if qa_ready else "quality_review_pending" if chapter_qa_ready and not contracts_ready else
                     "pending" if not all_ready else "failed_or_pending")
        con.execute("UPDATE writing_batches SET completed_chapters=?,status=?,qa_status=?,updated_at=? WHERE book_id=?",
                    (completed, status, qa_status, now_iso(), book_id))
    return get_writing_batch(book_id)


def finalize_auto_writing_batch(book_id):
    batch = refresh_writing_batch(book_id)
    if not batch or batch.get("upload_mode") != "auto" or batch.get("status") != "ready_for_upload":
        return batch
    end = batch["from_chapter"] + batch["target_chapters"] - 1
    promote_drafts(book_id, batch["from_chapter"], end)
    with db() as con:
        con.execute("UPDATE writing_batches SET status='promoted',updated_at=? WHERE book_id=?",
                    (now_iso(), book_id))
    book = get_book(book_id)
    if not book.get("platform_book_id"):
        with db() as con:
            con.execute("UPDATE writing_batches SET upload_status='blocked_unbound',updated_at=? WHERE book_id=?",
                        (now_iso(), book_id))
    elif batch.get("upload_status") not in {"queued", "running", "completed"}:
        job_id, _ = enqueue_upload_job({"book_id": book_id, "from": batch["from_chapter"], "to": end})
        with db() as con:
            con.execute("UPDATE writing_batches SET upload_status='queued',upload_job_id=?,updated_at=? WHERE book_id=?",
                        (job_id, now_iso(), book_id))
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
        rows = con.execute("SELECT * FROM chapter_drafts WHERE book_id=? AND chapter_no BETWEEN ? AND ? ORDER BY chapter_no", (book_id, start, end)).fetchall()
        all_rows = con.execute("SELECT * FROM chapter_drafts WHERE book_id=? ORDER BY chapter_no", (book_id,)).fetchall()
        other_rows = con.execute("SELECT book_id,chapter_no,file_path FROM chapters WHERE book_id<>?", (book_id,)).fetchall()
        contract_rows = con.execute(
            "SELECT cp.chapter_no,wc.contract_json FROM chapter_checkpoints cp "
            "JOIN writing_contracts wc ON wc.id=cp.contract_id "
            "WHERE cp.book_id=? AND cp.chapter_no BETWEEN ? AND ? ORDER BY cp.id",
            (book_id, start, end),
        ).fetchall()
    contracts_by_chapter = {row["chapter_no"]: json.loads(row["contract_json"]) for row in contract_rows}
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
    other_shingles = [(row["book_id"], row["chapter_no"], shingle_set(read_limited(Path(row["file_path"]), 20_000)))
                      for row in other_rows if Path(row["file_path"]).exists()]
    ai_phrases = ("仿佛", "一丝", "一抹", "缓缓", "轻轻", "淡淡", "眼中闪过", "嘴角勾起", "这一刻")
    report_terms = ("规则", "字段", "记录表", "验证", "流程", "登记", "复核", "结论")
    for row in rows:
        no, title, body = row["chapter_no"], row["title"], bodies[row["chapter_no"]]
        errors, warnings = [], []
        if cjk_count(body) < 2500:
            errors.append("中文汉字少于2500")
        if title in body:
            errors.append("标题出现在正文")
        if re.search(rf"第\s*0*{no}\s*章", body):
            errors.append("章节编号出现在正文")
        if re.search(r"(?:补记|续写补充|以下是正文)", body):
            errors.append("正文含补记或生成过程文字")
        paragraphs = [re.sub(r"\s+", "", p) for p in re.split(r"\n\s*\n", body) if re.sub(r"\s+", "", p)]
        short_ratio = sum(len(p) < 35 for p in paragraphs) / max(1, len(paragraphs))
        consecutive_short = 0
        max_consecutive_short = 0
        for paragraph in paragraphs:
            consecutive_short = consecutive_short + 1 if len(paragraph) < 35 else 0
            max_consecutive_short = max(max_consecutive_short, consecutive_short)
        dialogue_ratio = sum(bool(re.match(r"^[“\"『]", p)) for p in paragraphs) / max(1, len(paragraphs))
        if short_ratio > QUALITY_PROFILE["maximum_short_paragraph_ratio"]:
            errors.append(f"短段落比例过高:{short_ratio:.1%}")
        if max_consecutive_short > 5:
            errors.append(f"连续短段落过多:{max_consecutive_short}")
        if dialogue_ratio > 0.65:
            errors.append(f"对话段落比例过高:{dialogue_ratio:.1%}")
        phrase_count = sum(body.count(phrase) for phrase in ai_phrases)
        if phrase_count > QUALITY_PROFILE["maximum_ai_phrase_count"]:
            errors.append(f"AI模板词密度过高:{phrase_count}")
        report_count = sum(body.count(term) for term in report_terms)
        report_density = report_count * 1000 / max(1, cjk_count(body))
        if report_density > QUALITY_PROFILE["maximum_report_terms_per_1000_cjk"]:
            errors.append(f"报告体术语密度过高:{report_density:.1f}/千字")
        contract = contracts_by_chapter.get(no)
        if contract:
            protagonist = str(contract.get("protagonist") or "")
            if protagonist and body.count(protagonist) < 3:
                errors.append(f"主角能动性证据不足:{protagonist}仅出现{body.count(protagonist)}次")
        if any(no in nos for nos in duplicate_paras.values()):
            errors.append("存在跨章重复长段落")
        for other, other_set in shingles.items():
            if other == no or not shingles[no] or not other_set:
                continue
            ratio = len(shingles[no] & other_set) / max(1, min(len(shingles[no]), len(other_set)))
            if ratio > 0.08:
                warnings.append(f"与第{other:03d}章相似度偏高:{ratio:.2%}")
        for other_book, other_no, other_set in other_shingles:
            if not shingles[no] or not other_set:
                continue
            ratio = len(shingles[no] & other_set) / max(1, min(len(shingles[no]), len(other_set)))
            if ratio > 0.12:
                errors.append(f"与其他本地小说正文相似度过高:{other_book[:8]}/第{other_no:03d}章/{ratio:.2%}")
                break
        for char in structured.get("characters", []):
            if not isinstance(char, dict):
                continue
            name = str(char.get("name") or "")
            dead_after = char.get("dead_after_chapter")
            if name and dead_after and no > int(dead_after) and name in body and re.search(re.escape(name) + r".{0,80}[“\"]", body, re.S):
                warnings.append(f"已死亡角色{name}疑似再次对话")
        passed = not errors
        result = {"chapter_no": no, "passed": passed, "errors": errors, "warnings": warnings,
                  "cjk_chars": cjk_count(body), "body_chars": len(body.strip()),
                  "short_paragraph_ratio": round(short_ratio, 4),
                  "dialogue_paragraph_ratio": round(dialogue_ratio, 4),
                  "ai_phrase_count": phrase_count, "report_term_density": round(report_density, 2)}
        results.append(result)
    with db() as con:
        for result in results:
            con.execute("UPDATE chapter_drafts SET qa_json=?,qa_passed=?,status=?,updated_at=? WHERE book_id=? AND chapter_no=?",
                        (json_text(result), 1 if result["passed"] else 0,
                         "qa_passed" if result["passed"] else "qa_failed", now_iso(), book_id, result["chapter_no"]))
        if results and all(x["passed"] for x in results):
            con.execute("UPDATE books SET last_qa_revision=revision WHERE id=?", (book_id,))
        if start == 1 and end == 3:
            trial_count = con.execute("SELECT COUNT(*) n FROM chapter_drafts WHERE book_id=? AND chapter_no BETWEEN 1 AND 3 AND qa_passed=1",
                                      (book_id,)).fetchone()["n"]
            con.execute("UPDATE books SET stage=? WHERE id=?",
                        ("trial_ready_for_review" if trial_count == 3 else "trial_writing", book_id))
    audit("qa_run", book_id, {"from": start, "to": end, "passed": all(x["passed"] for x in results)})
    with db() as con:
        contract_ids = [row[0] for row in con.execute(
            "SELECT DISTINCT contract_id FROM chapter_checkpoints WHERE book_id=? AND chapter_no BETWEEN ? AND ? "
            "AND contract_id IS NOT NULL", (book_id, start, end)
        )]
    for current_contract_id in contract_ids:
        refresh_writing_contract(book_id, current_contract_id)
    with db() as con:
        revision = con.execute(
            "SELECT id FROM revision_batches WHERE book_id=? AND status NOT IN ('completed','cancelled') ORDER BY created_at DESC LIMIT 1",
            (book_id,),
        ).fetchone()
    batch = get_writing_batch(book_id) if revision else refresh_writing_batch(book_id)
    auto_job_id = None
    if not revision and batch and batch.get("status") == "ready_for_upload" and batch.get("upload_mode") == "auto":
        batch_end = batch["from_chapter"] + batch["target_chapters"] - 1
        promote_drafts(book_id, batch["from_chapter"], batch_end)
        with db() as con:
            con.execute("UPDATE writing_batches SET status='promoted',updated_at=? WHERE book_id=?",
                        (now_iso(), book_id))
        book = get_book(book_id)
        if not book.get("platform_book_id"):
            with db() as con:
                con.execute("UPDATE writing_batches SET upload_status='blocked_unbound',updated_at=? WHERE book_id=?",
                            (now_iso(), book_id))
        elif batch.get("upload_status") not in {"queued", "running", "completed"}:
            auto_job_id, _ = enqueue_upload_job({"book_id": book_id,
                                                 "from": batch["from_chapter"], "to": batch_end})
            with db() as con:
                con.execute("UPDATE writing_batches SET upload_status='queued',upload_job_id=?,updated_at=? WHERE book_id=?",
                            (auto_job_id, now_iso(), book_id))
            batch = get_writing_batch(book_id)
    revision_result = None
    if revision:
        revision_result = refresh_revision_batch(book_id, revision["id"])
        revision_status = (revision_result.get("revision_batch") or {}).get("status")
        if revision_status == "ready_to_promote":
            revision_result = promote_revision_batch(book_id, revision["id"], require_review=False)
    return {"passed": bool(results) and all(x["passed"] for x in results), "chapters": results,
            "writing_batch": batch, "auto_upload_job_id": auto_job_id,
            "revision_batch": revision_result,
            "semantic_check_required": ["人物动机", "感情递进", "隐性时间冲突", "标题内容匹配", "八项原创门禁"],
            "originality_review": review, "quality_profile": QUALITY_PROFILE}


def approve_trial(book_id):
    book = get_book(book_id)
    if book["stage"] != "trial_ready_for_review":
        raise ApiError(409, "当前不在三章审批阶段")
    promote_drafts(book_id, 1, 3)
    with db() as con:
        con.execute("UPDATE books SET stage='bulk_writing',updated_at=? WHERE id=?", (now_iso(), book_id))
    audit("trial_approved", book_id)
    return get_book(book_id)


def approve_writing_batch(book_id):
    batch = get_writing_batch(book_id)
    if not batch or batch.get("upload_mode") != "review" or batch.get("status") != "ready_for_upload":
        raise ApiError(409, "当前没有等待人工确认的写作批次")
    end = batch["from_chapter"] + batch["target_chapters"] - 1
    promote_drafts(book_id, batch["from_chapter"], end)
    with db() as con:
        con.execute("UPDATE writing_batches SET status='promoted',updated_at=? WHERE book_id=?",
                    (now_iso(), book_id))
    audit("writing_batch_approved", book_id, {"from": batch["from_chapter"], "to": end})
    return {"book": get_book(book_id), "writing_batch": get_writing_batch(book_id)}


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


def parse_action_payload(body):
    if "payload" in body:
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ApiError(400, "payload必须是JSON对象，禁止序列化为字符串")
        return payload
    raw = body.get("payload_json", "{}")
    if isinstance(raw, dict):
        payload = raw
    elif isinstance(raw, str) and len(raw) <= 88_000:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiError(400, "payload_json必须是有效JSON对象字符串", {
                "line": exc.lineno, "column": exc.colno,
            }) from exc
    else:
        raise ApiError(400, "payload_json必须是长度不超过88000字符的JSON对象字符串")
    if not isinstance(payload, dict):
        raise ApiError(400, "payload_json解析后必须是JSON对象")
    return payload


def required_book_id(body):
    book_id = str(body.get("book_id") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", book_id):
        raise ApiError(400, "该动作必须提交有效book_id")
    return book_id


def finish_contract_review(book_id, contract_id, payload):
    result = review_writing_contract(book_id, contract_id, payload)
    if result.get("revision_batch_id"):
        snapshot = refresh_revision_batch(book_id, result["revision_batch_id"])
        batch = snapshot.get("revision_batch") if isinstance(snapshot, dict) else None
        if batch and batch.get("mode") == "auto" and batch.get("status") == "ready_to_promote":
            promote_revision_batch(book_id, result["revision_batch_id"])
    else:
        finalize_auto_writing_batch(book_id)
    return result


def canonicalize_workflow_action_response(body, result):
    action = str(body.get("action") or "").strip()
    if action not in WORKFLOW_TRANSITION_ACTIONS or not isinstance(result, dict):
        return result
    book_id = required_book_id(body)
    payload = parse_action_payload(body)
    revision_batch_id = str(payload.get("revision_batch_id") or result.get("revision_batch_id") or "").strip()
    cycle = result.get("review_cycle") or {}
    revision_batch_id = revision_batch_id or str(cycle.get("revision_batch_id") or "").strip()
    if not revision_batch_id:
        with db() as con:
            active = con.execute(
                "SELECT id FROM revision_batches WHERE book_id=? AND status NOT IN ('completed','cancelled') "
                "ORDER BY created_at DESC LIMIT 1", (book_id,),
            ).fetchone()
        revision_batch_id = active["id"] if active else ""
    if revision_batch_id:
        snapshot = revision_resume_snapshot(book_id, revision_batch_id)
    else:
        snapshot = writing_resume_snapshot(book_id)
    legacy_next_action = result.get("next_action")
    canonical = dict(result)
    if legacy_next_action is not None and not isinstance(legacy_next_action, dict):
        canonical["operation_next_action"] = legacy_next_action
    canonical["next_action"] = snapshot["next_action"]
    canonical["workflow_state"] = {
        "book": snapshot.get("book"),
        "revision_batch": snapshot.get("revision_batch"),
        "writing_batch": snapshot.get("writing_batch"),
        "progress": snapshot.get("progress"),
        "continue_required": snapshot.get("continue_required"),
    }
    return canonical


def run_novel_workflow_action(body):
    action = str(body.get("action") or "").strip()
    if action not in NOVEL_WORKFLOW_ACTIONS:
        raise ApiError(400, "未知小说动作", {"allowed_actions": sorted(NOVEL_WORKFLOW_ACTIONS)})
    payload = parse_action_payload(body)
    book_id = str(body.get("book_id") or "").strip()

    if action == "defaults":
        return {**load_defaults(), "quality_profile": QUALITY_PROFILE}
    if action == "market_start":
        wait_seconds = payload.pop("wait_seconds", ACTION_WAIT_SECONDS)
        return wait_for_job(enqueue_job("market_study", payload), wait_seconds)
    if action == "market_sample":
        return market_sample_snapshot(str(payload.get("job_id") or ""), int(payload.get("sample_index") or 0),
                                      int(payload.get("excerpt_offset") or 0), int(payload.get("excerpt_limit") or 2))
    if action == "ideation_save":
        genre, market_job_id, candidates = validate_ideation_payload(payload)
        ideation_id, stamp = uuid.uuid4().hex, now_iso()
        with db() as con:
            con.execute("INSERT INTO ideations VALUES(?,?,'awaiting_selection',?,NULL,?,?,?)",
                        (ideation_id, genre, json_text(candidates), market_job_id, stamp, stamp))
        return {"ideation_id": ideation_id, "stage": "awaiting_selection", "count": 12}
    if action == "ideation_select":
        ideation_id = str(payload.get("ideation_id") or "")
        number = int(payload.get("candidate_no") or 0)
        if not re.fullmatch(r"[0-9a-f]{32}", ideation_id) or not 1 <= number <= 12:
            raise ApiError(400, "ideation_id或candidate_no无效")
        with db() as con:
            row = con.execute("SELECT * FROM ideations WHERE id=?", (ideation_id,)).fetchone()
            if not row or row["stage"] != "awaiting_selection":
                raise ApiError(409, "选题记录不存在或已选择")
            con.execute("UPDATE ideations SET selected_no=?,stage='selected',updated_at=? WHERE id=?",
                        (number, now_iso(), ideation_id))
        return {"ideation_id": ideation_id, "selected_no": number, "stage": "selected"}
    if action == "book_find":
        return find_books(str(payload.get("title") or ""), str(payload.get("account") or ""))
    if action == "book_import":
        return import_existing_book(payload)
    if action == "book_create":
        return create_book(payload)

    book_id = required_book_id(body)
    if action == "book_rebind":
        return rebind_book_ideation(book_id, payload)
    if action == "cover_get":
        return get_cover_spec(book_id)
    if action == "cover_save":
        return save_cover_spec(book_id, payload)
    if action == "context_get":
        return get_context(book_id, str(payload.get("query") or ""), str(payload.get("section") or ""),
                           int(payload.get("offset") or 0), int(payload.get("limit") or 4000),
                           int(payload.get("chapter_no") or 0))
    if action == "drafts_get":
        return get_chapter_drafts(book_id, int(payload.get("from") or 1), int(payload.get("to") or 10**9))
    if action == "writing_get":
        return get_writing_batch(book_id)
    if action == "writing_configure":
        return configure_writing_batch(book_id, payload)
    if action == "writing_resume":
        return writing_resume_snapshot(book_id)
    if action == "contract_create":
        return configure_writing_contract(book_id, payload)
    if action == "contract_get":
        return get_writing_contract(book_id, str(payload.get("contract_id") or ""))
    if action == "contract_review":
        return finish_contract_review(book_id, str(payload.get("contract_id") or ""), payload)
    if action == "revision_configure":
        return configure_revision_batch(book_id, payload)
    if action == "revision_resume":
        return revision_resume_snapshot(book_id)
    if action == "revision_get":
        return revision_resume_snapshot(book_id, str(payload.get("revision_batch_id") or ""))
    if action == "revision_approve":
        return promote_revision_batch(book_id, str(payload.get("revision_batch_id") or ""), require_review=True)
    if action == "checkpoint_commit":
        return save_chapter_checkpoint(book_id, payload)
    if action == "candidate_save":
        return save_review_candidate(book_id, payload)
    if action == "candidate_critique":
        return critique_review_candidate(book_id, payload)
    if action == "candidate_revise":
        return revise_review_candidate(book_id, payload)
    if action == "candidate_verify":
        return verify_review_candidate(book_id, payload)
    if action == "trial_chapters_save":
        return save_chapters(book_id, payload)
    if action == "state_update":
        return update_state(book_id, payload)
    if action == "quality_check":
        return run_qa(book_id, payload)
    if action == "trial_approve":
        return approve_trial(book_id)
    if action == "writing_approve":
        return approve_writing_batch(book_id)
    raise ApiError(500, "小说动作尚未实现", {"action": action})


def run_fanqie_workflow_action(body):
    action = str(body.get("action") or "").strip()
    if action not in FANQIE_WORKFLOW_ACTIONS:
        raise ApiError(400, "未知番茄动作", {"allowed_actions": sorted(FANQIE_WORKFLOW_ACTIONS)})
    payload = parse_action_payload(body)
    book_id = required_book_id(body)
    book = get_book(book_id)
    if action == "status":
        return get_draft_status(book_id)
    if book["stage"] != "bulk_writing":
        raise ApiError(409, "三章试读未批准，当前阶段禁止番茄操作")
    if action == "bind":
        return {"job_id": enqueue_job("platform_bind", {"book_id": book_id}), "status": "queued"}
    start, end = int(payload.get("from") or 0), int(payload.get("to") or 0)
    if start < 1 or end < start or end - start > 99:
        raise ApiError(400, "上传章节范围无效")
    job_id, superseded = enqueue_upload_job({"book_id": book_id, "from": start, "to": end})
    return {"job_id": job_id, "status": "queued", "superseded_job_ids": superseded,
            "deduplication": "同一本书只保留最新上传任务"}


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

    def send_compact_json(self, value, status=200):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
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
            return load_openapi()
        if method == "GET" and path == "/openapi-gpt.json":
            return load_openapi(gpt_import=True)
        if method == "GET" and path == "/openapi-writer.json":
            return load_writer_openapi()
        if method == "POST" and path == "/v1/actions/novel":
            return canonicalize_workflow_action_response(body, run_novel_workflow_action(body))
        if method == "POST" and path == "/v1/actions/fanqie":
            return run_fanqie_workflow_action(body)
        if method == "POST" and path == "/v1/actions/job":
            return wait_for_job(str(body.get("job_id") or ""), int(body.get("wait_seconds") or ACTION_WAIT_SECONDS))
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
        if method == "GET" and path == "/v1/books":
            return find_books((query.get("title") or [""])[0], (query.get("account") or [""])[0])
        if method == "POST" and path == "/v1/books/import-existing":
            return import_existing_book(body)
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
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/chapter-drafts", path)
        if method == "GET" and m:
            start = int((query.get("from") or ["1"])[0])
            end = int((query.get("to") or [str(10**9)])[0])
            return get_chapter_drafts(m.group(1), start, end)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/writing-batch", path)
        if method == "GET" and m:
            return get_writing_batch(m.group(1))
        if method == "PUT" and m:
            return configure_writing_batch(m.group(1), body)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/writing-resume", path)
        if method == "GET" and m:
            return writing_resume_snapshot(m.group(1))
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/writing-contracts", path)
        if method == "POST" and m:
            return configure_writing_contract(m.group(1), body)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/writing-contracts/([0-9a-f]+)", path)
        if method == "GET" and m:
            return get_writing_contract(m.group(1), m.group(2))
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/writing-contracts/([0-9a-f]+)/review", path)
        if method == "POST" and m:
            return finish_contract_review(m.group(1), m.group(2), body)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/revision-batches", path)
        if method == "POST" and m:
            return configure_revision_batch(m.group(1), body)
        if method == "GET" and m:
            return revision_resume_snapshot(m.group(1))
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/revision-batches/([0-9a-f]+)", path)
        if method == "GET" and m:
            return revision_resume_snapshot(m.group(1), m.group(2))
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/revision-batches/([0-9a-f]+)/approval", path)
        if method == "POST" and m:
            return promote_revision_batch(m.group(1), m.group(2), require_review=True)
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/chapter-checkpoints", path)
        if method == "POST" and m:
            return save_chapter_checkpoint(m.group(1), body)
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
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/writing-batch-approval", path)
        if method == "POST" and m:
            return approve_writing_batch(m.group(1))
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
                self.send_json(load_openapi())
                return
            if method == "GET" and path == "/openapi-gpt.json":
                self.send_compact_json(load_openapi(gpt_import=True))
                return
            if method == "GET" and path == "/openapi-writer.json":
                self.send_compact_json(load_writer_openapi())
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
