#!/usr/bin/env python3
import hashlib
import hmac
import json
import mimetypes
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import traceback
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
FANQIE_LOCK = threading.Lock()


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


def enqueue_job(kind, payload):
    job_id = uuid.uuid4().hex
    stamp = now_iso()
    with db() as con:
        con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
                    (job_id, kind, "queued", json_text(payload), None, None, stamp, stamp))
    JOB_QUEUE.put(job_id)
    return job_id


def job_update(job_id, status, result=None, error=None):
    with db() as con:
        con.execute("UPDATE jobs SET status=?, result_json=?, error=?, updated_at=? WHERE id=?",
                    (status, json_text(result) if result is not None else None, error, now_iso(), job_id))


def run_command(args, timeout=300, cwd=AI_ROOT):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "命令失败")[-3000:])
    return result.stdout


def packet_from_source(source, title):
    out_dir = RANKING_ROOT / "拆书分析" / ("action_" + safe_title(title))
    run_command(["python3", str(AI_ROOT / "scripts/prepare-novel-study.py"), str(source),
                 "--output", str(out_dir), "--front", "6", "--middle", "2", "--tail", "2"], 180)
    excerpts = []
    for path in sorted((out_dir / "selected").glob("*.txt"))[:4]:
        excerpts.append({"file": path.name, "text": read_limited(path, 1800)})
    return {"packet": str(out_dir), "index": read_limited(out_dir / "00_拆书索引.md", 4000), "excerpts": excerpts}


def find_local_ranking(title):
    wanted = normalize_title(title)
    candidates = list((RANKING_ROOT / "番茄排行榜").glob("*.txt"))
    exact = [p for p in candidates if wanted and wanted in normalize_title(p.stem)]
    return exact[0] if exact else None


def market_study_job(payload):
    books = payload.get("ranking_books") or []
    if not 1 <= len(books) <= 15:
        raise RuntimeError("ranking_books数量必须为1到15")
    sample_limit = min(6, max(3, int(payload.get("sample_limit") or 6)))
    samples, skipped = [], []
    for item in books:
        if len(samples) >= sample_limit:
            break
        title = str(item.get("title") or "").strip()
        author = str(item.get("author") or "").strip()
        if not title:
            continue
        source = find_local_ranking(title)
        if not source:
            try:
                output = run_command([str(AI_ROOT / "scripts/sonovel.sh"), "packet", title, author], 420)
                paths = [Path(line.strip()) for line in output.splitlines() if line.strip().startswith("/")]
                packet = next((p for p in reversed(paths) if p.exists()), None)
                if packet and (packet / "source.json").exists():
                    source_data = json.loads((packet / "source.json").read_text(encoding="utf-8"))
                    source_path = Path(source_data.get("source", ""))
                    source = source_path if source_path.exists() else None
                if not source:
                    source = find_local_ranking(title)
            except Exception as exc:
                skipped.append({"title": title, "reason": str(exc)[-500:]})
                continue
        try:
            packet = packet_from_source(source, title)
            samples.append({"rank": item.get("rank"), "official_title": title,
                            "official_author": author, "mirror_file": source.name, **packet})
        except Exception as exc:
            skipped.append({"title": title, "reason": str(exc)[-500:]})
    return {"genre": payload.get("genre"), "samples": samples, "skipped": skipped,
            "identity_rule": "作者可为佚名、章节数可偏少；由GPT用简介或前几章标题确认，同一性不足则跳过。"}


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
    run_command([str(cache), "switch-start", account, str(cfg["port"])], 60)
    wait_port(cfg["port"])
    identity = run_command([str(cache), "identify", str(cfg["port"])], 60).strip().splitlines()[-1]
    if identity != cfg["name"]:
        raise RuntimeError(f"账号核验失败：期望{cfg['name']}，实际{identity}")
    return cfg, cache


def finish_fanqie(cache, account):
    try:
        run_command([str(cache), "save", account], 120)
    except Exception:
        pass


def platform_bind_job(payload):
    book = get_book(payload["book_id"])
    account = book["account"]
    with FANQIE_LOCK:
        cfg, cache = fanqie_session(account)
        try:
            output = run_command(["node", str(SERVICE_ROOT / "fanqie-find-book.js"),
                                  "--port", str(cfg["port"]), "--title", book["title"]], 90)
            found = json.loads(output.strip().splitlines()[-1])
            if not found.get("book_id"):
                raise RuntimeError("未找到同名番茄作品")
            with db() as con:
                con.execute("UPDATE books SET platform_book_id=?,updated_at=? WHERE id=?",
                            (found["book_id"], now_iso(), book["id"]))
            audit("platform_bound", book["id"], found)
            return found
        finally:
            finish_fanqie(cache, account)


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
    with FANQIE_LOCK:
        cfg, cache = fanqie_session(account)
        try:
            uploader = AI_ROOT / "codex/skills/fanqie-upload/scripts/fanqie-upload.js"
            output = run_command(["node", str(uploader), "drafts", "--root", str(TXT_ROOT),
                                  "--book", book["title"], "--book-id", book["platform_book_id"],
                                  "--port", str(cfg["port"]), "--from", str(start), "--to", str(end)], 1200)
            raw = run_command(["node", str(SERVICE_ROOT / "fanqie-list-drafts.js"), "--port", str(cfg["port"]),
                               "--book-id", book["platform_book_id"], "--book", book["title"]], 120)
            listing = json.loads(raw.strip().splitlines()[-1])
            by_no = {int(x["no"]): x for x in listing.get("rows", [])}
            bad = [n for n in range(start, end + 1) if n not in by_no or int(by_no[n].get("words") or 0) <= 0]
            if bad:
                raise RuntimeError(f"草稿箱验收失败：{bad}")
            with db() as con:
                con.execute("UPDATE chapters SET uploaded=1 WHERE book_id=? AND chapter_no BETWEEN ? AND ?",
                            (book["id"], start, end))
            result = {"from": start, "to": end, "verified": expected,
                      "account": ACCOUNT_MAP[account]["name"], "output": output[-2500:]}
            audit("drafts_uploaded", book["id"], result)
            return result
        finally:
            finish_fanqie(cache, account)


def run_job(job_id):
    with db() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row or row["status"] != "queued":
        return
    job_update(job_id, "running")
    payload = json.loads(row["payload_json"])
    try:
        if row["type"] == "market_study":
            result = market_study_job(payload)
        elif row["type"] == "platform_bind":
            result = platform_bind_job(payload)
        elif row["type"] == "upload_drafts":
            result = upload_drafts_job(payload)
        else:
            raise RuntimeError("未知任务类型")
        job_update(job_id, "completed", result=result)
    except Exception as exc:
        job_update(job_id, "failed", error=str(exc)[-4000:])
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
        if not idea or idea["stage"] != "selected":
            raise ApiError(409, "必须先完成12选3并选择一个方案")
        if con.execute("SELECT 1 FROM books WHERE title=?", (title,)).fetchone():
            raise ApiError(409, "书名已存在")
    target = (TXT_ROOT / title).resolve()
    if target.exists():
        raise ApiError(409, "本地同名目录已存在")
    for rel in ["正文", "大纲", "设定/角色", "设定/世界观", "追踪", "分析", "封面"]:
        (target / rel).mkdir(parents=True, exist_ok=True)
    selected = json.loads(idea["candidates_json"])[int(idea["selected_no"]) - 1]
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
    return get_book(book_id)


def chapter_file(directory, no, title):
    return directory / "正文" / f"第{no:03d}章_{safe_title(title)}.md"


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
        title = safe_title(item.get("title"))
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


def shingle_set(text, width=20):
    text = re.sub(r"\s+", "", text)
    return {text[i:i + width] for i in range(max(0, len(text) - width + 1))}


def run_qa(book_id, payload):
    book = get_book(book_id)
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
    return {"passed": bool(results) and all(x["passed"] for x in results), "chapters": results,
            "semantic_check_required": ["人物动机", "感情递进", "隐性时间冲突", "标题内容匹配"]}


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
    if not 1 <= len(refs) <= 10:
        raise ApiError(400, "文件数量必须为1到10")
    saved = []
    for index, ref in enumerate(refs, 1):
        if isinstance(ref, str):
            url = ref
            url_name = Path(urlparse(url).path).name
            name = safe_title(url_name or f"asset-{index}.bin")
        elif isinstance(ref, dict):
            url = str(ref.get("download_link") or "")
            name = safe_title(ref.get("name") or f"asset-{index}.bin")
        else:
            raise ApiError(400, "素材引用格式无效")
        if not url.startswith("https://"):
            raise ApiError(400, "素材下载地址必须使用HTTPS")
        suffix = Path(name).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".md", ".txt"}:
            raise ApiError(400, "不支持的素材格式")
        req = urllib.request.Request(url, headers={"User-Agent": "novel-actions/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            data = response.read(MAX_ASSET + 1)
        if len(data) > MAX_ASSET:
            raise ApiError(413, "素材超过20MB")
        target = book_dir(book) / "封面" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        saved.append(str(target))
    audit("assets_saved", book_id, {"count": len(saved)})
    return {"saved": saved}


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
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + TOKEN_PATH.read_text(encoding="utf-8").strip()
        if not hmac.compare_digest(supplied, expected):
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
            return {"job_id": enqueue_job("market_study", body), "status": "queued"}
        m = re.fullmatch(r"/v1/jobs/([0-9a-f]+)", path)
        if method == "GET" and m:
            with db() as con:
                row = con.execute("SELECT * FROM jobs WHERE id=?", (m.group(1),)).fetchone()
            if not row:
                raise ApiError(404, "任务不存在")
            item = row_dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
            return item
        if method == "POST" and path == "/v1/ideations":
            candidates = body.get("candidates") or []
            if len(candidates) != 12:
                raise ApiError(400, "必须提交且只能提交12个候选")
            ideation_id, stamp = uuid.uuid4().hex, now_iso()
            with db() as con:
                con.execute("INSERT INTO ideations VALUES(?,?,'awaiting_selection',?,NULL,?,?,?)",
                            (ideation_id, str(body.get("genre") or ""), json_text(candidates), body.get("market_job_id"), stamp, stamp))
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
        m = re.fullmatch(r"/v1/books/([0-9a-f]+)/context", path)
        if method == "GET" and m:
            return get_context(m.group(1), (query.get("query") or [""])[0])
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
            return {"job_id": enqueue_job("upload_drafts", {"book_id": m.group(1), "from": start, "to": end}), "status": "queued"}
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
