import cgi
import csv
import ipaddress
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import parse, request

ROOT = Path(__file__).resolve().parent
AI_ROOT = Path("/home/admin/ai").resolve()
UPLOADS = ROOT / "uploads"
RENMINWANG_STATE = Path("/home/admin/ai/trade/runs/renminwang_paper_monitor/state.json")
RENMINWANG_TOKEN = ROOT / "renminwang.token"
TRADE_FEEDBACK_LOG = ROOT / "trade-feedback.jsonl"
CMB_GOLD_CONFIG = Path("/home/admin/ai/monitors/cmb-gold-monitor/config.json")
CMB_GOLD_STATE = Path("/home/admin/ai/monitors/cmb-gold-monitor/state.json")
FUND_DCA_CONFIG = Path("/home/admin/ai/trade/runs/fund_dca_monitor/config.json")
FUND_DCA_STATE = Path("/home/admin/ai/trade/runs/fund_dca_monitor/state.json")
NDXTMC_QDII_STATE = Path("/home/admin/ai/trade/runs/ndxtmc_qdii_monitor/state.json")
FINANCE_MEMORY = Path("/root/ai/memory/stock-finance.md")
PORTFOLIO_SNAPSHOT = Path("/home/admin/ai/trade/portfolio/2026-06-13-current-valuation.md")
TRADE_BACKTEST_DIR = Path("/home/admin/ai/trade/runs/dip_rebound_a_share")
TRADE_FILTERED_SUMMARY = TRADE_BACKTEST_DIR / "results" / "filtered" / "filtered_summary.csv"
TRADE_FILTERED_META = TRADE_BACKTEST_DIR / "results" / "filtered" / "run_meta.json"
TRADE_FILTERED_LOG = TRADE_BACKTEST_DIR / "logs" / "filtered_backtest.log"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
TEXT_FILE_SUFFIXES = {
    ".md", ".markdown", ".txt", ".log", ".conf", ".ini", ".yaml", ".yml",
    ".csv", ".html", ".htm", ".css", ".js", ".py", ".sh", ".json", ".xml",
}
CLOCK_GENERATOR = Path("/home/admin/ai/output/videos/cartoon-clock-6-to-7/make_clock_video.py")
CLOCK_STATUS = ROOT / "videos" / "clock_generation_status.json"
CLOCK_PUBLIC = ROOT / "videos"
CLOCK_LOCK = threading.Lock()
FINANCE_QUOTE_CACHE = ROOT / "finance-quote-cache.json"
FINANCE_QUOTE_CACHE_LOCK = threading.Lock()
FINANCE_REFRESH_CODES = ("009052", "022430", "017091", "017093", "019118", "603000", "gold")
NOVEL_GIT_REPO = Path("/home/admin/chatgpt-novel-production-system")
NOVEL_DASHBOARD_RECENT_SAMPLE_LIMIT = 3
SONOVEL_SCRIPT = AI_ROOT / "scripts" / "sonovel.sh"
SONOVEL_DOWNLOAD_SOURCE = AI_ROOT / "tools" / "so-novel" / "downloads"
SONOVEL_ARCHIVE_DIR = AI_ROOT / "txt" / "download"
SONOVEL_WEB_STATE = ROOT / "sonovel-web-state.json"
SONOVEL_SEARCH_CACHE_TTL_SECONDS = 10 * 60
SONOVEL_SEARCH_CACHE_LIMIT = 12
SONOVEL_RECENT_DOWNLOAD_LIMIT = 12
SONOVEL_SEARCH_MIN_INTERVAL_SECONDS = 2
SONOVEL_DOWNLOAD_MIN_INTERVAL_SECONDS = 10
SONOVEL_PROGRESS_CACHE_SECONDS = 1.0
SONOVEL_JOURNAL_LINE_LIMIT = 140
SONOVEL_PUBLIC_LOG_LINE_LIMIT = 18
SONOVEL_WEB_STATE_LOCK = threading.RLock()
SONOVEL_WEB_STATE_DATA = {"active": None, "recent": []}
SONOVEL_SEARCH_CACHE = {}
SONOVEL_REQUEST_TIMES = {}
SONOVEL_PROGRESS_CACHE_LOCK = threading.Lock()
SONOVEL_PROGRESS_CACHE = {"job_id": "", "checked_at": 0.0, "progress": None}

SCHEDULED_TASKS = [
    {
        "id": "renminwang-stock",
        "name": "人民网股票监控",
        "category": "股票",
        "runner": "cron",
        "marker": "# renminwang ntfy monitor",
        "default_schedule": "* 9-15 * * 1-5",
        "command": "/home/admin/ai/trade/runs/renminwang_paper_monitor/run_monitor.sh",
        "config_path": None,
        "description": "盘中检查人民网 603000.SH 的减仓、清仓、反抽卖出等策略提醒。",
    },
    {
        "id": "ndxtmc-qdii",
        "name": "纳指科技 QDII 监控",
        "category": "基金",
        "runner": "cron",
        "marker": "# ndxtmc qdii morning monitor",
        "default_schedule": "30 6 * * 2-6",
        "command": "/home/admin/ai/trade/runs/ndxtmc_qdii_monitor/run_monitor.sh",
        "config_path": None,
        "description": "美股收盘后检查纳指科技 QDII 是否触发赎回/减仓提醒。",
    },
    {
        "id": "fund-dca",
        "name": "基金定投提醒",
        "category": "基金",
        "runner": "cron",
        "marker": "# fund dca salary-cycle reminder",
        "default_schedule": "30 14 10-26 * 1-5",
        "command": "/home/admin/ai/trade/runs/fund_dca_monitor/run_monitor.sh",
        "config_path": "/home/admin/ai/trade/runs/fund_dca_monitor/config.json",
        "description": "工资到账后分两笔提醒定投 022430，并根据估值涨跌判断是否延后。",
    },
    {
        "id": "fanqie-kuaiqian",
        "name": "番茄《快穿：他们要我还债，我偏要讨债》人工发布协作",
        "category": "小说",
        "runner": "cron",
        "marker": "# fanqie kuaiqian daily publish",
        "default_schedule": "30 0 * * *",
        "command": "/home/admin/ai/scripts/fanqie-kuaiqian-daily-publish.sh",
        "config_path": None,
        "manual_only": True,
        "description": "自动发布已停用。AI 只负责写作、质检、上传并核验草稿，最终发布由你手动完成。",
    },
    {
        "id": "fanqie-liusui",
        "name": "番茄《重生六岁，我带空间抢回军区大院》人工发布协作",
        "category": "小说",
        "runner": "cron",
        "marker": "# fanqie liusui daily publish",
        "default_schedule": "40 0 * * *",
        "command": "/home/admin/ai/scripts/fanqie-liusui-daily-publish.sh",
        "config_path": None,
        "manual_only": True,
        "description": "自动发布已停用。AI 只负责写作、质检、上传并核验草稿，最终发布由你手动完成。",
    },
    {
        "id": "fanqie-pianxin",
        "name": "番茄《快穿：她一出现，全世界都偏心了》人工发布协作",
        "category": "小说",
        "runner": "cron",
        "marker": "# fanqie pianxin daily publish",
        "default_schedule": "50 0 * * *",
        "command": "/home/admin/ai/scripts/fanqie-pianxin-daily-publish.sh",
        "config_path": None,
        "manual_only": True,
        "description": "自动发布已停用。AI 只负责写作、质检、上传并核验草稿，最终发布由你手动完成。",
    },
    {
        "id": "cmb-gold",
        "name": "招行黄金监控",
        "category": "黄金",
        "runner": "systemd",
        "unit": "cmb-gold-monitor.timer",
        "service": "cmb-gold-monitor.service",
        "config_path": "/home/admin/ai/monitors/cmb-gold-monitor/config.json",
        "description": "定时刷新招行黄金/上金所价格，根据买入、止损、婚用目标等规则推送提醒。",
    },
    {
        "id": "flight-ckg-urc",
        "name": "重庆-乌鲁木齐机票监控",
        "category": "出行",
        "runner": "systemd",
        "unit": "flight-price-ckg-urc-monitor.timer",
        "service": "flight-price-ckg-urc-monitor.service",
        "config_path": "/home/admin/ai/monitors/flight-price-ckg-urc-20260815/config.json",
        "description": "定时检查指定川航往返航班价格，价格变化达到阈值时提醒。",
    },
]

PARAM_EXPLANATIONS = {
    "cash_balance": "当前记录的零钱宝余额。工资转入或定投反馈会更新它，定投金额会受它约束。",
    "cash_floor": "零钱宝最低保留金额。低于这个值时暂停定投，避免把流动资金用光。",
    "cash_reduce_threshold": "现金接近底线的警戒值。低于/接近时会暂停或降档定投。",
    "cash_full_threshold": "现金充足阈值。高于它才按完整定投计划执行。",
    "monthly_base_amount": "每月计划投入基金的总金额，目前拆成两笔执行。",
    "defer_if_022430_up_pct": "022430 当天估值涨幅达到这个百分比时，本笔延后，避免追高。",
    "execute_if_022430_down_pct": "022430 当天估值跌到这个百分比以下时，本笔正常执行，视作回调买入。",
    "target_weight": "该基金在定投金额中的分配权重。022430=1 表示本笔全部投 022430；009052=0 表示不再定投红利。",
    "cost": "本地记录的持仓成本。提交定投反馈后会增加；App 最新成本优先级更高。",
    "value": "本地记录的持仓市值。提交定投反馈后会临时增加；App 最新市值优先级更高。",
    "profit": "本地记录的浮动收益。App 最新收益优先级更高。",
    "salary_day": "工资到账日。定投提醒会从这个日期之后开始寻找执行窗口。",
    "tranches": "定投分批计划。每个分批有窗口、金额和 id。",
    "id": "内部编号，用来区分不同分批或数据源。一般不需要改。",
    "label": "页面和通知里显示的名称，只影响可读性，不影响计算逻辑。",
    "start_day": "本笔定投窗口开始日期。脚本只会在这个日期之后寻找交易日提醒。",
    "end_day": "本笔定投窗口结束日期。超过这个日期仍未执行，本月该笔不会再提醒。",
    "amount": "本笔计划金额。对基金定投来说是本次建议投入金额；对反馈来说是实际操作金额。",
    "reminder_hour": "提醒小时，24小时制。",
    "reminder_minute": "提醒分钟。",
    "buy_add_price": "黄金正常小额加仓提醒价。估算买入价低于它时才考虑加仓。",
    "buy_wait_freefall_price": "黄金急跌观察价。低于它时不急着买，先等价格稳定。",
    "sell_risk_price": "黄金风险卖出参考价。结合婚用核心仓规则使用，不是机械清仓价。",
    "sell_breakeven_price": "黄金成本价。卖出价回到成本附近时才考虑非核心仓处理。",
    "sell_take_profit_price": "黄金止盈参考价。超过 50g 的投资仓才更适用。",
    "risk_daily_drop_abs": "黄金单日下跌风险阈值。跌幅超过它会提高提醒优先级。",
    "deep_drop_abs": "黄金深跌阈值。用于识别急跌环境，避免盲目接飞刀。",
    "grams": "当前黄金克数。来自招行 App 或操作反馈。",
    "cost_price_per_g": "黄金每克平均成本。来自招行 App 或操作反馈。",
    "core_physical_target_grams": "婚用实物黄金目标克数。目标内仓位不为小波动卖出。",
    "alert_cooldown_minutes": "黄金同类提醒冷却时间，避免短时间重复推送。",
    "vibetrading_proximity_yuan": "接近关键买卖价多少元时触发 Vibe-Trading 复核。",
    "strategy_summary_times": "黄金策略定时总结发送时间列表。",
    "baseline_price": "机票监控的基准价格。低于或高于它达到阈值时提醒。",
    "min_notify_delta": "机票价格变化提醒阈值，单位元。",
    "cash_asset": "现金账户的显示名称，目前用于代表零钱宝。",
    "feedback_base_url": "反馈网页的基础地址，推送里的操作反馈链接会用它生成。",
    "feedback_token_path": "反馈链接校验令牌所在文件路径。一般不要改，改错会导致反馈提交失败。",
    "name": "任务、基金、航班或数据源的正式名称。",
    "display_name": "页面和通知里使用的短名称，只影响显示。",
    "asset": "资产或账户名称，只影响显示和日志识别。",
    "core_physical_target_use": "说明为什么设置婚用黄金目标，帮助策略判断哪些黄金不应轻易卖出。",
    "initial_app_buy_price": "最初记录策略时的招行 App 买入价，只作为历史参考。",
    "initial_app_sell_price": "最初记录策略时的招行 App 卖出价，只作为历史参考。",
    "initial_api_au9999_price": "最初记录策略时的 AU9999 行情，只作为历史参考。",
    "app_buy_offset_from_au9999": "招行买入价通常比 AU9999 行情高出的估算差值，用于估算 App 买入价。",
    "sell_spread_per_g": "招行买入价和卖出价之间的估算价差，用于估算卖出可得金额。",
    "source_url": "行情数据接口地址。改错会导致监控无法拉取价格。",
    "primary_gold_no": "主要参考的黄金行情品种代码，当前是 AU9999。",
    "secondary_gold_no": "辅助参考的黄金行情品种代码，用于交叉验证。",
    "recheck_delay_seconds": "触发提醒前等待几秒再复查一次，减少瞬时异常报价误报。",
    "monitor_price_basis": "说明机票价格监控用的价格来源和口径，避免和 App 最终支付价混淆。",
    "currency": "价格使用的币种。",
    "route": "监控的往返航线。",
    "passengers": "查询机票时使用的乘客条件。",
    "date": "航班日期。",
    "weekday": "航班日期对应的星期。",
    "flight_no": "指定要监控的航班号。",
    "airline": "指定要监控的航空公司。",
    "depart_airport": "出发机场和航站楼。",
    "depart_time": "计划出发时间。",
    "arrive_airport": "到达机场和航站楼。",
    "arrive_time": "计划到达时间。",
    "source_screenshot": "创建机票监控时参考的截图路径。",
    "mobile_verify_steps": "手机 App 里人工核对价格的步骤。",
    "outbound_url": "去程航班查询链接。",
    "return_url": "返程航班查询链接。",
    "type": "数据源类型。一般不需要改。",
    "url": "数据源链接。改错会导致监控无法查询。",
}

PARAM_LABELS = {
    "salary_day": "工资到账日",
    "tranches": "定投分批计划",
    "id": "分批编号",
    "label": "分批名称",
    "start_day": "开始日期",
    "end_day": "结束日期",
    "amount": "金额",
    "reminder_hour": "提醒小时",
    "reminder_minute": "提醒分钟",
    "cash_asset": "现金账户名称",
    "cash_balance": "零钱宝余额",
    "cash_floor": "零钱宝最低保留金额",
    "cash_reduce_threshold": "现金暂停定投阈值",
    "cash_full_threshold": "完整定投现金阈值",
    "monthly_base_amount": "每月计划定投总额",
    "defer_if_022430_up_pct": "022430 涨幅延后阈值",
    "execute_if_022430_down_pct": "022430 回调执行阈值",
    "feedback_base_url": "反馈网页地址",
    "feedback_token_path": "反馈令牌文件路径",
    "funds": "基金配置",
    "name": "名称",
    "display_name": "显示名称",
    "value": "当前记录市值",
    "profit": "当前记录收益",
    "cost": "当前记录成本",
    "target_weight": "定投分配权重",
    "asset": "资产名称",
    "grams": "黄金克数",
    "core_physical_target_grams": "婚用黄金目标克数",
    "core_physical_target_use": "婚用黄金目标说明",
    "cost_price_per_g": "黄金每克平均成本",
    "initial_app_buy_price": "初始招行买入价",
    "initial_app_sell_price": "初始招行卖出价",
    "initial_api_au9999_price": "初始 AU9999 报价",
    "app_buy_offset_from_au9999": "招行买入价相对 AU9999 加价",
    "sell_spread_per_g": "买卖价差",
    "source_url": "行情数据接口",
    "primary_gold_no": "主黄金品种代码",
    "secondary_gold_no": "辅助黄金品种代码",
    "alert_cooldown_minutes": "提醒冷却时间",
    "recheck_delay_seconds": "二次确认等待秒数",
    "vibetrading_proximity_yuan": "Vibe-Trading 复核接近距离",
    "strategy_summary_times": "策略总结时间",
    "thresholds": "策略阈值",
    "buy_add_price": "正常加仓提醒价",
    "buy_wait_freefall_price": "急跌等待观察价",
    "sell_risk_price": "风险卖出参考价",
    "sell_breakeven_price": "回本参考价",
    "sell_take_profit_price": "止盈参考价",
    "risk_daily_drop_abs": "单日下跌风险阈值",
    "deep_drop_abs": "深跌阈值",
    "baseline_price": "基准价格",
    "min_notify_delta": "价格变化提醒阈值",
    "monitor_price_basis": "监控价格口径",
    "currency": "币种",
    "route": "航线",
    "passengers": "乘客",
    "outbound": "去程",
    "return": "返程",
    "date": "日期",
    "weekday": "星期",
    "flight_no": "航班号",
    "airline": "航司",
    "depart_airport": "出发机场",
    "depart_time": "出发时间",
    "arrive_airport": "到达机场",
    "arrive_time": "到达时间",
    "sources": "数据来源",
    "source_screenshot": "参考截图",
    "mobile_verify_steps": "手机核价步骤",
    "outbound_url": "去程查询链接",
    "return_url": "返程查询链接",
    "type": "类型",
    "url": "链接",
}


def safe_name(name):
    name = Path(name or "upload.bin").name
    name = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", name).strip("._")
    return name or "upload.bin"


def upload_rows():
    UPLOADS.mkdir(exist_ok=True)
    rows = []
    for item in sorted(UPLOADS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not item.is_file():
            continue
        stat = item.stat()
        rows.append({
            "name": item.name,
            "url": f"uploads/{item.name}",
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        })
    return rows[:100]


def clear_uploads():
    UPLOADS.mkdir(exist_ok=True)
    deleted = 0
    errors = []
    for item in UPLOADS.iterdir():
        if not item.is_file():
            continue
        try:
            item.unlink()
            deleted += 1
        except OSError as exc:
            errors.append(f"{item.name}: {exc}")
    return {"deleted": deleted, "errors": errors}


def read_json_body(handler, max_bytes=1024 * 1024):
    content_length = int(handler.headers.get("Content-Length") or 0)
    if content_length <= 0:
        return {}
    if content_length > max_bytes:
        raise ValueError("Request body too large")
    return json.loads(handler.rfile.read(content_length).decode("utf-8"))


def write_json(handler, payload, status=HTTPStatus.OK):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def sonovel_now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def load_sonovel_web_state():
    try:
        payload = json.loads(SONOVEL_WEB_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {}
    active = payload.get("active") if isinstance(payload.get("active"), dict) else None
    recent = payload.get("recent") if isinstance(payload.get("recent"), list) else []
    recent = [item for item in recent if isinstance(item, dict)][:SONOVEL_RECENT_DOWNLOAD_LIMIT]
    changed = False
    if active and active.get("status") == "running":
        active["status"] = "interrupted"
        active["message"] = "8090 服务重启，未确认原下载是否完成。请重新搜索或检查服务器归档目录。"
        active["finished_at"] = sonovel_now()
        recent.insert(0, active)
        active = None
        changed = True
    return {"active": active, "recent": recent[:SONOVEL_RECENT_DOWNLOAD_LIMIT], "changed": changed}


def persist_sonovel_web_state():
    payload = {
        "active": SONOVEL_WEB_STATE_DATA.get("active"),
        "recent": SONOVEL_WEB_STATE_DATA.get("recent", [])[:SONOVEL_RECENT_DOWNLOAD_LIMIT],
        "updated_at": sonovel_now(),
    }
    SONOVEL_WEB_STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SONOVEL_WEB_STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SONOVEL_WEB_STATE)


SONOVEL_WEB_STATE_DATA = load_sonovel_web_state()
if SONOVEL_WEB_STATE_DATA.pop("changed", False):
    persist_sonovel_web_state()


def sonovel_public_job(job):
    if not isinstance(job, dict):
        return None
    fields = (
        "job_id", "title", "author", "format", "status", "message", "started_at",
        "finished_at", "archive_path", "archive_size", "download_url", "error",
    )
    public = {field: job[field] for field in fields if field in job}
    if "progress" in job:
        public["progress"] = sonovel_public_progress(job.get("progress"))
    return public


def cleanup_sonovel_search_cache():
    now = time.time()
    stale = [key for key, value in SONOVEL_SEARCH_CACHE.items() if value.get("expires_at", 0) <= now]
    for key in stale:
        SONOVEL_SEARCH_CACHE.pop(key, None)
    while len(SONOVEL_SEARCH_CACHE) > SONOVEL_SEARCH_CACHE_LIMIT:
        oldest = min(SONOVEL_SEARCH_CACHE, key=lambda key: SONOVEL_SEARCH_CACHE[key].get("created_at", 0))
        SONOVEL_SEARCH_CACHE.pop(oldest, None)


def guard_sonovel_rate(remote_ip, action, minimum_interval):
    key = (str(remote_ip or "unknown"), action)
    now = time.monotonic()
    previous = SONOVEL_REQUEST_TIMES.get(key, 0.0)
    remaining = minimum_interval - (now - previous)
    if remaining > 0:
        raise ValueError(f"操作过于频繁，请 {remaining:.0f} 秒后再试")
    SONOVEL_REQUEST_TIMES[key] = now


def run_sonovel_command(arguments, timeout_seconds):
    result = subprocess.run(
        [str(SONOVEL_SCRIPT), *arguments],
        cwd=str(AI_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "SoNovel command failed").strip()
        raise RuntimeError(detail[-1200:])
    return (result.stdout or "").strip()


def sonovel_clean_log_line(value):
    # Journal entries can contain terminal color controls. They make the browser
    # log pane unreadable, so retain only plain text and a bounded line length.
    line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value or "")).strip()
    return line[:360]


def sonovel_live_progress(job):
    """Return a small, cached progress snapshot derived from SoNovel's own logs."""
    job_id = str(job.get("job_id") or "")
    now = time.monotonic()
    with SONOVEL_PROGRESS_CACHE_LOCK:
        cached = SONOVEL_PROGRESS_CACHE.get("progress")
        if (
            job_id
            and SONOVEL_PROGRESS_CACHE.get("job_id") == job_id
            and isinstance(cached, dict)
            and now - float(SONOVEL_PROGRESS_CACHE.get("checked_at") or 0) < SONOVEL_PROGRESS_CACHE_SECONDS
        ):
            return dict(cached)

    started_epoch = float(job.get("started_epoch") or time.time() - 120)
    try:
        result = subprocess.run(
            [
                "/usr/bin/journalctl",
                "-u",
                "sonovel.service",
                "--since",
                f"@{max(0, int(started_epoch) - 1)}",
                "--no-pager",
                "--output=cat",
                "-n",
                str(SONOVEL_JOURNAL_LINE_LIMIT),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        lines = [
            cleaned
            for raw in (result.stdout or "").splitlines()
            if (cleaned := sonovel_clean_log_line(raw))
            and ("SoNovel" in cleaned or "[INFO]" in cleaned or "[ERROR]" in cleaned or "<==" in cleaned)
        ]
    except (OSError, subprocess.SubprocessError):
        lines = []

    previous = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    seen_chapters = set(previous.get("seen_chapters") or [])
    total = int(previous.get("total") or 0)
    phase = str(previous.get("phase") or "正在启动")
    current_chapter = str(previous.get("current_chapter") or "")

    for line in lines:
        total_match = re.search(r"共计\s*(\d+)\s*章", line)
        if total_match:
            total = max(total, int(total_match.group(1)))
            phase = "正在准备正文"
        if "正在解析章节目录" in line:
            phase = "正在读取目录"
        if "开始下载" in line:
            phase = "正在抓取正文"
        chapter_match = re.search(r"正在下载[:：]\s*【(.+?)】", line)
        if not chapter_match:
            chapter_match = re.search(r"正在下载[:：]\s*(.+?)(?:\s+间隔|$)", line)
        if chapter_match:
            current_chapter = chapter_match.group(1).strip()[:180]
            chapter_no = re.search(r"第\s*0*(\d+)\s*章", current_chapter)
            if chapter_no:
                seen_chapters.add(int(chapter_no.group(1)))
            phase = "正在抓取正文"
        if "章节下载完毕" in line or "正在生成 " in line:
            phase = "正在生成文件"
        if "完成！" in line:
            phase = "正在整理归档"

    scheduled = len(seen_chapters)
    if total:
        scheduled = min(scheduled, total)
    percent = round(scheduled * 100 / total) if total else None
    progress = {
        "phase": phase,
        "total": total or None,
        "scheduled": scheduled or None,
        "percent": percent,
        "current_chapter": current_chapter,
        "logs": lines[-SONOVEL_PUBLIC_LOG_LINE_LIMIT:],
        "updated_at": sonovel_now(),
        # This remains internal and lets later journal tails retain an accurate
        # count without returning a growing chapter list to the browser.
        "seen_chapters": sorted(seen_chapters)[-1000:],
    }
    with SONOVEL_PROGRESS_CACHE_LOCK:
        SONOVEL_PROGRESS_CACHE.update({"job_id": job_id, "checked_at": now, "progress": progress})
    return progress


def sonovel_public_progress(progress):
    if not isinstance(progress, dict):
        return None
    fields = ("phase", "total", "scheduled", "percent", "current_chapter", "logs", "updated_at")
    return {field: progress[field] for field in fields if field in progress}


def is_public_sonovel_url(value):
    parsed = parse.urlparse(str(value or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def sonovel_search(query, remote_ip):
    query = str(query or "").strip()
    if not query:
        raise ValueError("请输入书名或作者")
    if len(query) > 120:
        raise ValueError("搜索内容不能超过 120 个字符")
    with SONOVEL_WEB_STATE_LOCK:
        guard_sonovel_rate(remote_ip, "search", SONOVEL_SEARCH_MIN_INTERVAL_SECONDS)

    raw = run_sonovel_command(["search", query], timeout_seconds=55)
    try:
        items = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError("SoNovel 搜索结果格式异常") from exc
    if not isinstance(items, list):
        raise RuntimeError("SoNovel 未返回可用搜索结果")

    selected = []
    public = []
    for item in items[:50]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("bookName") or "").strip()
        author = str(item.get("author") or "").strip()
        url = str(item.get("url") or "").strip()
        source_id = item.get("sourceId")
        if not title or source_id is None or not is_public_sonovel_url(url):
            continue
        selected.append({
            "bookName": title[:180],
            "author": author[:120],
            "sourceId": str(source_id),
            "url": url,
            "latestChapter": str(item.get("latestChapter") or "")[:180],
        })
        public.append({
            "result_index": len(selected) - 1,
            "title": title[:180],
            "author": author[:120],
            "source_id": str(source_id),
            "latest_chapter": str(item.get("latestChapter") or "")[:180],
        })

    search_id = uuid.uuid4().hex
    with SONOVEL_WEB_STATE_LOCK:
        cleanup_sonovel_search_cache()
        SONOVEL_SEARCH_CACHE[search_id] = {
            "created_at": time.time(),
            "expires_at": time.time() + SONOVEL_SEARCH_CACHE_TTL_SECONDS,
            "results": selected,
        }
    return {"search_id": search_id, "query": query, "results": public}


def archive_sonovel_download(source):
    source_root = SONOVEL_DOWNLOAD_SOURCE.resolve()
    source = source.resolve()
    if source.parent != source_root or not source.is_file():
        raise RuntimeError("SoNovel 返回的文件不在受控下载目录中")
    SONOVEL_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    filename = safe_name(source.name)
    target = SONOVEL_ARCHIVE_DIR / filename
    if target.exists():
        stem, suffix = target.stem, target.suffix
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target = SONOVEL_ARCHIVE_DIR / f"{stem}_{stamp}{suffix}"
        serial = 2
        while target.exists():
            target = SONOVEL_ARCHIVE_DIR / f"{stem}_{stamp}_{serial}{suffix}"
            serial += 1
    shutil.copy2(source, target)
    return target


def complete_sonovel_job(job_id, status, **updates):
    with SONOVEL_WEB_STATE_LOCK:
        active = SONOVEL_WEB_STATE_DATA.get("active")
        if not isinstance(active, dict) or active.get("job_id") != job_id:
            return
        completed = dict(active)
        completed.update(updates)
        completed["status"] = status
        completed["finished_at"] = sonovel_now()
        SONOVEL_WEB_STATE_DATA["active"] = None
        SONOVEL_WEB_STATE_DATA["recent"] = [completed] + SONOVEL_WEB_STATE_DATA.get("recent", [])
        SONOVEL_WEB_STATE_DATA["recent"] = SONOVEL_WEB_STATE_DATA["recent"][:SONOVEL_RECENT_DOWNLOAD_LIMIT]
        persist_sonovel_web_state()


def run_sonovel_download_job(job_id, selected, output_format):
    try:
        raw = run_sonovel_command(
            [
                "download-url",
                selected["bookName"],
                selected.get("author", ""),
                selected["sourceId"],
                selected["url"],
                output_format,
            ],
            timeout_seconds=12 * 60,
        )
        payload = json.loads(raw)
        file_info = payload.get("file") if isinstance(payload, dict) else None
        filename = str(file_info.get("name") or "") if isinstance(file_info, dict) else ""
        if not filename or Path(filename).name != filename:
            raise RuntimeError("SoNovel 未返回有效下载文件名")
        archive = archive_sonovel_download(SONOVEL_DOWNLOAD_SOURCE / filename)
        relative_archive = ai_relative(archive)
        complete_sonovel_job(
            job_id,
            "completed",
            message="已保存到服务器归档，并可下载到当前设备。",
            archive_path=relative_archive,
            archive_size=archive.stat().st_size,
            download_url="/api/ai-download?" + parse.urlencode({"path": relative_archive}),
        )
    except subprocess.TimeoutExpired:
        complete_sonovel_job(job_id, "failed", error="下载超过 12 分钟，已停止本次任务。")
    except Exception as exc:
        complete_sonovel_job(job_id, "failed", error=str(exc)[-1200:])


def start_sonovel_download(search_id, result_index, output_format, remote_ip):
    output_format = str(output_format or "txt").strip().lower()
    if output_format not in {"txt", "epub", "html", "pdf"}:
        raise ValueError("仅支持 TXT、EPUB、HTML 或 PDF")
    try:
        result_index = int(result_index)
    except (TypeError, ValueError) as exc:
        raise ValueError("下载结果编号无效，请重新搜索") from exc

    with SONOVEL_WEB_STATE_LOCK:
        guard_sonovel_rate(remote_ip, "download", SONOVEL_DOWNLOAD_MIN_INTERVAL_SECONDS)
        cleanup_sonovel_search_cache()
        search = SONOVEL_SEARCH_CACHE.get(str(search_id or ""))
        if not search:
            raise ValueError("搜索结果已过期，请重新搜索后再下载")
        results = search.get("results") if isinstance(search.get("results"), list) else []
        if result_index < 0 or result_index >= len(results):
            raise ValueError("下载结果不存在，请重新搜索")
        active = SONOVEL_WEB_STATE_DATA.get("active")
        if isinstance(active, dict) and active.get("status") == "running":
            raise RuntimeError(f"已有下载任务正在运行：{active.get('title') or '未命名作品'}")
        selected = dict(results[result_index])
        job = {
            "job_id": uuid.uuid4().hex,
            "title": selected["bookName"],
            "author": selected.get("author", ""),
            "format": output_format,
            "status": "running",
            "message": "正在启动 SoNovel 并下载，完成后会同时归档到服务器和下载到当前设备。",
            "started_at": sonovel_now(),
            "started_epoch": time.time(),
            "progress": {"phase": "正在启动", "logs": [], "updated_at": sonovel_now(), "seen_chapters": []},
        }
        SONOVEL_WEB_STATE_DATA["active"] = job
        persist_sonovel_web_state()

    thread = threading.Thread(
        target=run_sonovel_download_job,
        args=(job["job_id"], selected, output_format),
        daemon=True,
        name=f"sonovel-download-{job['job_id'][:8]}",
    )
    thread.start()
    return sonovel_public_job(job)


def sonovel_web_status():
    with SONOVEL_WEB_STATE_LOCK:
        active = SONOVEL_WEB_STATE_DATA.get("active")
        active_snapshot = dict(active) if isinstance(active, dict) and active.get("status") == "running" else None
    if active_snapshot:
        progress = sonovel_live_progress(active_snapshot)
        with SONOVEL_WEB_STATE_LOCK:
            active = SONOVEL_WEB_STATE_DATA.get("active")
            if isinstance(active, dict) and active.get("job_id") == active_snapshot.get("job_id") and active.get("status") == "running":
                active["progress"] = progress
                total = progress.get("total")
                scheduled = progress.get("scheduled")
                current = progress.get("current_chapter")
                phase = progress.get("phase") or "正在下载"
                if total and scheduled:
                    active["message"] = f"{phase}：已发起 {scheduled}/{total} 章{f'，当前 {current}' if current else ''}"
                elif current:
                    active["message"] = f"{phase}：当前 {current}"
                else:
                    active["message"] = phase
    with SONOVEL_WEB_STATE_LOCK:
        archive_count = 0
        if SONOVEL_ARCHIVE_DIR.exists():
            archive_count = sum(
                1 for item in SONOVEL_ARCHIVE_DIR.iterdir()
                if item.is_file() and not item.name.startswith(".")
            )
        return {
            "active": sonovel_public_job(SONOVEL_WEB_STATE_DATA.get("active")),
            "recent": [sonovel_public_job(item) for item in SONOVEL_WEB_STATE_DATA.get("recent", [])],
            "archive_path": ai_relative(SONOVEL_ARCHIVE_DIR),
            "archive_count": archive_count,
            "updated_at": sonovel_now(),
        }


def query_params(path):
    query = ""
    if "?" in path:
        query = path.split("?", 1)[1]
    return {key: values[-1] for key, values in parse.parse_qs(query).items()}


def resolve_ai_path(value=""):
    rel = str(value or "").lstrip("/")
    target = (AI_ROOT / rel).resolve()
    if target != AI_ROOT and AI_ROOT not in target.parents:
        raise ValueError("Path escapes AI root")
    return target


def ai_relative(path):
    if path == AI_ROOT:
        return ""
    return str(path.relative_to(AI_ROOT))


def ai_file_rows(rel_path=""):
    folder = resolve_ai_path(rel_path)
    if not folder.exists() or not folder.is_dir():
        raise ValueError("Directory not found")
    rows = []
    for item in folder.iterdir():
        try:
            stat = item.stat()
        except OSError:
            continue
        is_dir = item.is_dir()
        suffix = item.suffix.lower()
        rows.append(
            {
                "name": item.name,
                "path": ai_relative(item),
                "type": "dir" if is_dir else "file",
                "is_md": item.is_file() and suffix == ".md",
                "is_text": item.is_file() and suffix in TEXT_FILE_SUFFIXES,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            }
        )
    rows.sort(key=lambda row: (row["type"] != "dir", row["name"].lower()))
    parent = None
    if folder != AI_ROOT:
        parent = ai_relative(folder.parent)
    return {"root": str(AI_ROOT), "path": ai_relative(folder), "parent": parent, "entries": rows}


def read_ai_text(rel_path):
    target = resolve_ai_path(rel_path)
    if not target.exists() or not target.is_file():
        raise ValueError("File not found")
    if target.suffix.lower() not in TEXT_FILE_SUFFIXES:
        raise ValueError("This file type cannot be copied as text")
    if target.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("File is larger than 5MB")
    return target.read_text(encoding="utf-8")


INLINE_PREVIEW_TYPES = {
    "image/",
    "video/",
    "audio/",
    "text/",
}

INLINE_PREVIEW_MIMES = {
    "application/pdf",
    "application/json",
    "application/xml",
    "application/javascript",
}


def ai_preview_mime(target):
    guessed, _encoding = mimetypes.guess_type(str(target))
    mime = guessed or "application/octet-stream"
    suffix = target.suffix.lower()
    if suffix in TEXT_FILE_SUFFIXES:
        return "text/plain; charset=utf-8"
    return mime


def is_inline_previewable(mime):
    base = mime.split(";", 1)[0]
    return base in INLINE_PREVIEW_MIMES or any(base.startswith(prefix) for prefix in INLINE_PREVIEW_TYPES)


def read_clock_status():
    if not CLOCK_STATUS.exists():
        return {
            "running": False,
            "ok": True,
            "progress": 100,
            "phase": "暂无生成任务",
            "params": {
                "start": "06:00",
                "end": "07:00",
                "speed": 240,
                "style": "cartoon",
                "duration_seconds": 15,
            },
        }
    try:
        return json.loads(CLOCK_STATUS.read_text(encoding="utf-8"))
    except Exception:
        return {"running": False, "ok": False, "progress": 100, "phase": "状态文件读取失败"}


def read_trade_backtest_status():
    running = False
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid=,cmd="],
            text=True,
            capture_output=True,
            timeout=2,
        )
        running = proc.returncode == 0 and any(
            "filtered_backtest.py" in line and "ps -eo" not in line and "rg " not in line
            for line in proc.stdout.splitlines()
        )
    except Exception:
        running = False

    log_tail = ""
    if TRADE_FILTERED_LOG.exists():
        try:
            lines = TRADE_FILTERED_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()
            log_tail = "\n".join(lines[-20:])
        except Exception:
            log_tail = "日志读取失败"

    meta = {}
    if TRADE_FILTERED_META.exists():
        try:
            meta = json.loads(TRADE_FILTERED_META.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    rows = []
    if TRADE_FILTERED_SUMMARY.exists():
        try:
            with TRADE_FILTERED_SUMMARY.open("r", encoding="utf-8", newline="") as f:
                all_rows = list(csv.DictReader(f))
            def as_float(row, key):
                try:
                    return float(row.get(key) or 0)
                except ValueError:
                    return 0.0
            preferred = [
                row for row in all_rows
                if row.get("exit_rule") == "next_close"
                and int(float(row.get("trades") or 0)) >= 300
            ]
            rows = sorted(preferred or all_rows, key=lambda r: as_float(r, "avg_return"), reverse=True)[:40]
        except Exception as exc:
            log_tail = f"{log_tail}\n结果读取失败：{exc}".strip()

    return {
        "running": running,
        "has_result": TRADE_FILTERED_SUMMARY.exists(),
        "summary_path": str(TRADE_FILTERED_SUMMARY),
        "meta": meta,
        "rows": rows,
        "log_tail": log_tail,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def load_json_file(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_read_error": str(exc)}


def rel_to_novel_repo(path):
    try:
        return str(path.relative_to(NOVEL_GIT_REPO))
    except ValueError:
        return str(path)


def novel_git_jobs():
    jobs = []
    repo = NOVEL_GIT_REPO
    sample_pending = repo / "sample-requests" / "pending"
    sample_results = repo / "sample-results"
    seen = set()
    if sample_pending.exists():
        for request_path in sorted(sample_pending.glob("*.json")):
            request = load_json_file(request_path)
            request_id = str(request.get("request_id") or request_path.stem)
            status_path = sample_results / request_id / "status.json"
            status = load_json_file(status_path) if status_path.exists() else {}
            payload = status if status and "_read_error" not in status else request
            progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
            books = payload.get("books") if isinstance(payload.get("books"), list) else request.get("books", [])
            jobs.append({
                "type": "sample",
                "request_id": request_id,
                "status": payload.get("status") or request.get("status") or "unknown",
                "genre": request.get("genre"),
                "target_platform": request.get("target_platform"),
                "updated_at": payload.get("updated_at") or request.get("updated_at") or request.get("created_at"),
                "request_path": rel_to_novel_repo(request_path),
                "status_path": rel_to_novel_repo(status_path) if status_path.exists() else None,
                "effective_sample_count": payload.get("effective_sample_count", 0),
                "target_effective_sample_count": payload.get("target_effective_sample_count") or request.get("min_effective_samples"),
                "attempted_count": payload.get("attempted_count"),
                "total_candidate_count": payload.get("total_candidate_count") or len(request.get("books") or []),
                "current_index": progress.get("current_index"),
                "current_book": progress.get("current_book"),
                "progress_stage": progress.get("stage"),
                "progress_message": progress.get("message"),
                "books": books,
            })
            seen.add(request_id)
    if sample_results.exists():
        for status_path in sorted(sample_results.glob("*/status.json")):
            request_id = status_path.parent.name
            if request_id in seen:
                continue
            status = load_json_file(status_path)
            progress = status.get("progress") if isinstance(status.get("progress"), dict) else {}
            jobs.append({
                "type": "sample",
                "request_id": request_id,
                "status": status.get("status") or "unknown",
                "updated_at": status.get("updated_at"),
                "status_path": rel_to_novel_repo(status_path),
                "effective_sample_count": status.get("effective_sample_count", 0),
                "target_effective_sample_count": status.get("target_effective_sample_count"),
                "attempted_count": status.get("attempted_count"),
                "total_candidate_count": status.get("total_candidate_count"),
                "current_index": progress.get("current_index"),
                "current_book": progress.get("current_book"),
                "progress_stage": progress.get("stage"),
                "progress_message": progress.get("message"),
                "books": status.get("books") if isinstance(status.get("books"), list) else [],
            })

    # The dashboard is an operational view, not an archive.  Keep only the
    # three most recently updated sample jobs; historical Git status files
    # remain untouched for audit and later research.
    sample_jobs = [job for job in jobs if job.get("type") == "sample"]
    recent_sample_jobs = sorted(
        sample_jobs,
        key=lambda job: str(job.get("updated_at") or ""),
        reverse=True,
    )[:NOVEL_DASHBOARD_RECENT_SAMPLE_LIMIT]
    jobs = [job for job in jobs if job.get("type") != "sample"] + recent_sample_jobs

    write_pending = repo / "server-write-requests" / "pending"
    write_results = repo / "server-write-results"
    if write_pending.exists():
        for request_path in sorted(write_pending.glob("*.json")):
            request = load_json_file(request_path)
            request_id = str(request.get("request_id") or request_path.stem)
            status_path = write_results / request_id / "status.json"
            status = load_json_file(status_path) if status_path.exists() else {}
            payload = status if status and "_read_error" not in status else request
            jobs.append({
                "type": "server_write",
                "request_id": request_id,
                "status": payload.get("status") or request.get("status") or "unknown",
                "updated_at": payload.get("updated_at") or request.get("updated_at") or request.get("created_at"),
                "request_path": rel_to_novel_repo(request_path),
                "status_path": rel_to_novel_repo(status_path) if status_path.exists() else None,
                "project_path": request.get("project_path") or payload.get("project_path"),
                "chapter_range": payload.get("chapter_range") or payload.get("planned_range"),
                "quality_passed": payload.get("quality_passed"),
            })

    novels = repo / "novels"
    if novels.exists():
        for project_file in sorted(novels.glob("*/00_PROJECT.json")):
            project = load_json_file(project_file)
            if project.get("auto_upload_to_drafts") is not True:
                continue
            upload_status = project.get("upload_status")
            if upload_status in {"not_ready", None}:
                continue
            jobs.append({
                "type": "upload",
                "request_id": str(project.get("book_id") or project_file.parent.name),
                "status": upload_status,
                "updated_at": (project.get("last_upload") or {}).get("uploaded_at") or project.get("updated_at"),
                "project_path": rel_to_novel_repo(project_file.parent),
                "book_title": project.get("book_title"),
                "fanqie_account": project.get("fanqie_account"),
                "upload_range": project.get("upload_range"),
                "ready_evidence": project.get("ready_evidence"),
            })

    status_order = {
        "running": 0,
        "pending": 1,
        "ready_for_draft_upload": 2,
        "partially_completed": 3,
        "failed": 4,
        "manual_material_required": 5,
        "completed": 6,
        "uploaded_to_drafts": 7,
    }
    other_jobs = [job for job in jobs if job.get("type") != "sample"]
    other_jobs.sort(
        key=lambda row: (status_order.get(row.get("status"), 9), str(row.get("updated_at") or "")),
        reverse=False,
    )
    jobs = recent_sample_jobs + other_jobs
    return {
        "repo": str(repo),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "jobs": jobs,
        "summary": {
            "total": len(jobs),
            "running": sum(1 for job in jobs if job.get("status") == "running"),
            "pending": sum(1 for job in jobs if job.get("status") == "pending"),
            "failed": sum(1 for job in jobs if job.get("status") in {"failed", "manual_material_required"}),
        },
    }


def novel_jobs_page():
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>小说任务进度</title>
  <style>
    body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f7f7f4;color:#1f2933}
    header{padding:18px 22px;border-bottom:1px solid #ddd;background:#fff;position:sticky;top:0}
    h1{font-size:20px;margin:0 0 4px}
    main{padding:18px;max-width:1180px;margin:auto}
    .meta{color:#607080;font-size:13px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
    .card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:14px}
    .row{display:flex;gap:8px;align-items:center;justify-content:space-between}
    .badge{font-size:12px;padding:2px 8px;border-radius:999px;background:#e8edf2}
    .running{background:#dff3ff}.failed{background:#ffe1df}.completed{background:#e1f7e8}.pending{background:#fff3ca}
    .small{font-size:12px;color:#607080;word-break:break-all}
    .books{margin-top:10px;border-top:1px solid #eee;padding-top:8px;max-height:220px;overflow:auto}
    .book{font-size:13px;padding:5px 0;border-bottom:1px solid #f1f1f1}
    button{border:1px solid #c7d0d9;background:#fff;border-radius:6px;padding:7px 10px}
  </style>
</head>
<body>
  <header>
    <div class="row"><div><h1>小说任务进度</h1><div id="meta" class="meta">加载中</div></div><button onclick="loadJobs()">刷新</button></div>
  </header>
  <main><div id="jobs" class="grid"></div></main>
  <script>
    function esc(v){return String(v ?? '').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]))}
    function badgeClass(s){return ['running','failed','completed','pending'].includes(s)?s:''}
    function bookLine(b){
      const status = b.acquisition_status || b.quality_status || '';
      const reason = b.failure_reason || b.skip_reason || '';
      return `<div class="book"><b>${esc(b.title)}</b> — ${esc(b.author)} <span class="small">${esc(status)}</span>${reason?`<div class="small">${esc(reason)}</div>`:''}</div>`
    }
    async function loadJobs(){
      const res = await fetch('/api/novel-git-jobs',{cache:'no-store'});
      const data = await res.json();
      document.getElementById('meta').textContent = `${data.updated_at} · 共 ${data.summary.total} 个任务 · running ${data.summary.running} · pending ${data.summary.pending} · failed ${data.summary.failed}`;
      const jobs = document.getElementById('jobs');
      jobs.innerHTML = '';
      for (const job of data.jobs){
        const current = job.current_book ? `${job.current_index || ''} ${job.current_book.title || ''} ${job.current_book.author || ''}` : '';
        const target = job.target_effective_sample_count ? `${job.effective_sample_count || 0}/${job.target_effective_sample_count}` : '';
        const books = Array.isArray(job.books) ? job.books.map(bookLine).join('') : '';
        const range = job.upload_range || job.chapter_range || {};
        jobs.insertAdjacentHTML('beforeend', `
          <section class="card">
            <div class="row"><b>${esc(job.type)} · ${esc(job.request_id)}</b><span class="badge ${badgeClass(job.status)}">${esc(job.status)}</span></div>
            <div class="small">更新：${esc(job.updated_at)}</div>
            ${job.genre?`<div>题材：${esc(job.genre)} · ${esc(job.target_platform)}</div>`:''}
            ${job.book_title?`<div>书名：${esc(job.book_title)}</div>`:''}
            ${target?`<div>有效样本：${esc(target)} · 候选 ${esc(job.total_candidate_count || '')} · 已试 ${esc(job.attempted_count || '')}</div>`:''}
            ${current?`<div>当前：${esc(current)}</div>`:''}
            ${job.progress_message?`<div class="small">${esc(job.progress_stage)}：${esc(job.progress_message)}</div>`:''}
            ${(range.from_chapter || range.to_chapter)?`<div>章节：${esc(range.from_chapter)} - ${esc(range.to_chapter)}</div>`:''}
            ${job.status_path?`<div class="small">状态：${esc(job.status_path)}</div>`:''}
            ${books?`<div class="books">${books}</div>`:''}
          </section>`);
      }
    }
    loadJobs();
    setInterval(loadJobs, 5000);
  </script>
</body>
</html>"""


def finance_http_get(url, encoding="utf-8", timeout=5):
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://fundf10.eastmoney.com/",
        },
    )
    with request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, "ignore")


def finance_fund_estimate(code):
    # This public estimate endpoint is materially faster and more reliable over
    # HTTP on this host; it carries no account, credential, or trading data.
    text = finance_http_get(f"http://fundgz.1234567.com.cn/js/{code}.js?rt={int(time.time() * 1000)}")
    payload = text.split("(", 1)[1].rsplit(")", 1)[0]
    return json.loads(payload)


def finance_fund_nav_rows(code, page_size=30):
    query = parse.urlencode({"fundCode": code, "pageIndex": 1, "pageSize": page_size})
    url = f"http://api.fund.eastmoney.com/f10/lsjz?{query}"
    text = finance_http_get(url)
    payload = json.loads(text)
    return payload.get("Data", {}).get("LSJZList", []) or []


def finance_latest_fund_nav(code):
    rows = finance_fund_nav_rows(code, page_size=3)
    row = next((item for item in rows if item.get("FSRQ") and item.get("DWJZ")), None)
    if not row:
        raise ValueError(f"{code} latest confirmed NAV not found")
    return {
        "date": str(row["FSRQ"]),
        "nav": float(row["DWJZ"]),
        "cumulative_nav": float(row["LJJZ"]) if row.get("LJJZ") not in {None, ""} else None,
        "change_pct": float(row["JZZZL"]) if row.get("JZZZL") not in {None, ""} else None,
    }


def finance_nav_on_or_before(code, date_text):
    rows = finance_fund_nav_rows(code)
    candidates = [row for row in rows if str(row.get("FSRQ", "")) <= date_text and row.get("DWJZ")]
    if not candidates:
        return None
    row = max(candidates, key=lambda item: str(item.get("FSRQ", "")))
    return {"date": row.get("FSRQ"), "nav": float(row.get("DWJZ"))}


def estimate_fund_position(code, base_value, cost, base_date, estimate):
    base_value = float(base_value or 0)
    cost = float(cost or 0)
    current_nav = None
    if estimate.get("gsz") not in {None, ""}:
        current_nav = float(estimate["gsz"])
    elif estimate.get("dwjz") not in {None, ""}:
        current_nav = float(estimate["dwjz"])
    if not current_nav:
        return {
            "value": round(base_value, 2),
            "cost": round(cost, 2),
            "profit": round(base_value - cost, 2),
            "source_note": f"未取到最新估值，沿用 {base_date} 本地基准",
            "estimated": False,
        }

    base_nav = None
    base_nav_date = base_date
    try:
        nav_info = finance_nav_on_or_before(code, base_date)
        if nav_info:
            base_nav = nav_info["nav"]
            base_nav_date = nav_info["date"]
    except Exception:
        base_nav = None

    if not base_nav:
        change_pct = float(estimate.get("gszzl") or 0)
        value = base_value * (1 + change_pct / 100)
        source_note = f"未取到 {base_date} 基准净值，按最新涨跌幅临时估算"
    else:
        value = base_value / base_nav * current_nav
        source_note = f"按 {base_nav_date} App基准净值 {base_nav:.4f} 和最新估值 {current_nav:.4f} 折算"

    return {
        "value": round(value, 2),
        "cost": round(cost, 2),
        "profit": round(value - cost, 2),
        "source_note": source_note,
        "estimated": True,
    }


def finance_tencent_quote(symbol):
    text = finance_http_get(f"https://qt.gtimg.cn/q={symbol}", "gbk")
    raw = text.split('="', 1)[1].rsplit('"', 1)[0].split("~")
    return {
        "name": raw[1],
        "price": float(raw[3]),
        "prev_close": float(raw[4]),
        "change_pct": float(raw[32]),
        "time": raw[30],
    }


def finance_gold_snapshot():
    config = load_json_file(CMB_GOLD_CONFIG)
    payload = json.loads(finance_http_get(config["source_url"]))
    rows = payload.get("body", {}).get("data", [])
    primary = next((row for row in rows if row.get("goldNo") == config.get("primary_gold_no")), None)
    if not primary:
        raise ValueError("AU9999 quote not found")
    au_price = float(str(primary.get("curPrice", 0)).replace(",", ""))
    app_buy = au_price + float(config.get("app_buy_offset_from_au9999", 0))
    app_sell = app_buy - float(config.get("sell_spread_per_g", 0))
    grams = float(config.get("grams", 0))
    cost = float(config.get("cost_price_per_g", 0))
    return {
        "price": round(app_sell, 2),
        "app_buy": round(app_buy, 2),
        "app_sell": round(app_sell, 2),
        "grams": grams,
        "cost": round(grams * cost, 2),
        "value": round(grams * app_sell, 2),
        "profit": round((app_sell - cost) * grams, 2),
        "change_pct": None,
        "time": f"{payload.get('body', {}).get('time', '')} {primary.get('time', '')}".strip(),
    }


def load_finance_quote_cache():
    with FINANCE_QUOTE_CACHE_LOCK:
        if not FINANCE_QUOTE_CACHE.exists():
            return {}
        try:
            data = load_json_file(FINANCE_QUOTE_CACHE)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}


def save_finance_quote(code, quote):
    with FINANCE_QUOTE_CACHE_LOCK:
        try:
            data = load_json_file(FINANCE_QUOTE_CACHE) if FINANCE_QUOTE_CACHE.exists() else {}
        except (OSError, ValueError, json.JSONDecodeError):
            data = {}
        data[code] = quote
        temp_path = FINANCE_QUOTE_CACHE.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, FINANCE_QUOTE_CACHE)


def local_finance_quote_fallbacks():
    fallbacks = {}
    try:
        state = load_renminwang_state()
        quote = state.get("last_quote") or {}
        if quote.get("price") is not None:
            prev_close = float(quote.get("prev_close") or 0)
            price = float(quote["price"])
            fallbacks["603000"] = {
                "code": "603000",
                "price": price,
                "change_pct": round((price / prev_close - 1) * 100, 2) if prev_close else None,
                "time": f"{quote.get('date', '')} {quote.get('time', '')}".strip(),
                "refreshed_at": state.get("last_checked_at", ""),
                "source": "股票监控最近行情",
                "cached": True,
            }
    except Exception:
        pass
    try:
        state = load_json_file(CMB_GOLD_STATE)
        snapshot = state.get("last_snapshot") or {}
        if snapshot.get("estimated_app_sell_price") is not None:
            fallbacks["gold"] = {
                "code": "gold",
                "price": float(snapshot["estimated_app_sell_price"]),
                "change_pct": None,
                "time": snapshot.get("api_time") or snapshot.get("checked_at", ""),
                "refreshed_at": state.get("last_success_at", ""),
                "source": "黄金监控最近行情",
                "cached": True,
            }
    except Exception:
        pass
    return fallbacks


def refresh_finance_quote(code):
    if code not in FINANCE_REFRESH_CODES:
        raise ValueError("不支持刷新这个资产")
    if code in {"009052", "022430", "017091", "017093", "019118"}:
        nav = finance_latest_fund_nav(code)
        quote = {
            "code": code,
            "price": nav["nav"],
            "change_pct": nav["change_pct"],
            "time": nav["date"],
            "refreshed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "天天基金最新确认净值",
            "quote_kind": "confirmed_nav",
            "cumulative_nav": nav["cumulative_nav"],
            "cached": False,
        }
    elif code == "603000":
        raw = finance_tencent_quote("sh603000")
        quote = {
            "code": code,
            "price": raw["price"],
            "change_pct": raw["change_pct"],
            "time": raw["time"],
            "refreshed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "腾讯行情",
            "cached": False,
        }
    else:
        raw = finance_gold_snapshot()
        quote = {
            "code": code,
            "price": raw["price"],
            "change_pct": raw["change_pct"],
            "time": raw["time"],
            "refreshed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "招行/上金所行情",
            "cached": False,
        }
    save_finance_quote(code, quote)
    return quote


def finance_portfolio_totals(rows):
    total = round(sum(float(row.get("value") or 0) for row in rows), 2)
    profit = round(sum(float(row.get("profit") or 0) for row in rows if row.get("profit") is not None), 2)
    by_category = {}
    for row in rows:
        by_category[row["category"]] = round(by_category.get(row["category"], 0) + float(row.get("value") or 0), 2)
    return total, profit, by_category


def read_finance_portfolio():
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    config = load_json_file(FUND_DCA_CONFIG) if FUND_DCA_CONFIG.exists() else {}
    cache = {**local_finance_quote_fallbacks(), **load_finance_quote_cache()}
    rows = []
    notes = []

    def add(row):
        row.setdefault("profit", None)
        row.setdefault("change_pct", None)
        row.setdefault("price", None)
        row.setdefault("quantity", None)
        row.setdefault("price_unit", "")
        row.setdefault("quantity_unit", "")
        row.setdefault("source", "")
        row.setdefault("refreshable", False)
        rows.append(row)

    cash = float(config.get("cash_balance", 0))
    add({"code": "cash", "name": "零钱宝", "category": "现金", "value": round(cash, 2), "source": "本地反馈/配置", "editable_fields": []})
    add({"code": "fixed-income", "name": "固收理财", "category": "固收", "value": 50000.0, "profit": None, "source": "本地记录，到期 2026-07-27", "editable_fields": []})

    fund_cfg = config.get("funds", {})
    for code in ("009052", "022430"):
        fund = fund_cfg.get(code, {})
        quote = cache.get(code, {})
        if quote.get("quote_kind") != "confirmed_nav":
            quote = {}
        account_updated_at = fund.get("account_updated_at") or "本地记录"
        price = quote.get("price")
        shares = float(fund.get("shares") or 0)
        value = round(shares * float(price), 2) if shares and price else round(float(fund.get("value", 0)), 2)
        cost = round(float(fund.get("cost", 0)), 2)
        add(
            {
                "code": code,
                "name": f"{code} {fund.get('display_name', fund.get('name', '')).replace(code, '').strip()}".strip(),
                "category": "基金",
                "value": value,
                "cost": cost,
                "profit": round(value - cost, 2),
                "daily_profit": round(float(fund.get("daily_profit", 0)), 2) if fund.get("daily_profit") is not None else None,
                "change_pct": quote.get("change_pct"),
                "price": price,
                "quantity": shares,
                "quantity_verified": bool(fund.get("shares_verified")),
                "price_unit": "元/份",
                "quantity_unit": "份",
                "time": quote.get("time", ""),
                "quote_updated_at": quote.get("refreshed_at", ""),
                "source": f"{shares:.4f}份 × {quote.get('time', '待刷新')}确认净值；份额更新于 {account_updated_at}",
                "estimated": False,
                "refreshable": True,
                "editable_fields": ["quantity", "profit", "daily_profit"],
            }
        )

    qdii_cfg = config.get("qdii_funds") or {}
    qdii_defaults = {
        "017091": {"display_name": "017091 景顺纳指科技A", "value": 35549.32, "profit": 6249.32, "cost": 29300.0, "shares": 12763.650725, "daily_profit": -208.32, "holding_return": "21.33%", "account_updated_at": "2026-06-26"},
        "017093": {"display_name": "017093 景顺纳指科技C", "value": 14437.84, "profit": 2437.84, "cost": 12000.0, "shares": 5262.946087, "daily_profit": -84.84, "account_updated_at": "2026-06-26"},
        "019118": {"display_name": "019118 景顺纳指科技E", "value": 11611.52, "profit": 2011.52, "cost": 9600.0, "shares": 4196.732688, "daily_profit": -68.07, "account_updated_at": "2026-06-26"},
    }
    for code in ("017091", "017093", "019118"):
        fund = {**qdii_defaults.get(code, {}), **qdii_cfg.get(code, {})}
        quote = cache.get(code, {})
        if quote.get("quote_kind") != "confirmed_nav":
            quote = {}
        price = quote.get("price")
        shares = float(fund.get("shares") or 0)
        value = round(shares * float(price), 2) if shares and price else round(float(fund.get("value", 0)), 2)
        cost = round(float(fund.get("cost", 0)), 2)
        holding_return_note = f"，持有收益率 {fund.get('holding_return')}" if fund.get("holding_return") else ""
        account_updated_at = fund.get("account_updated_at") or "本地记录"
        add(
            {
                "code": code,
                "name": str(fund.get("display_name") or f"{code} {fund.get('name', '')}").strip(),
                "category": "纳指QDII",
                "value": value,
                "cost": cost,
                "profit": round(value - cost, 2),
                "daily_profit": round(float(fund.get("daily_profit", 0)), 2) if fund.get("daily_profit") is not None else None,
                "change_pct": quote.get("change_pct"),
                "price": price,
                "quantity": shares,
                "quantity_verified": bool(fund.get("shares_verified")),
                "price_unit": "元/份",
                "quantity_unit": "份",
                "time": quote.get("time", ""),
                "quote_updated_at": quote.get("refreshed_at", ""),
                "source": f"{shares:.4f}份 × {quote.get('time', '待刷新')}确认净值；份额更新于 {account_updated_at}{holding_return_note}；QDII净值通常滞后",
                "estimated": False,
                "refreshable": True,
                "editable_fields": ["quantity", "profit", "daily_profit"],
            }
        )
    if NDXTMC_QDII_STATE.exists():
        qdii_state = load_json_file(NDXTMC_QDII_STATE)
        skip_reason = (qdii_state.get("last_snapshot") or {}).get("skip_reason")
        if skip_reason:
            notes.append(f"纳指 QDII 指数监控最近一次跳过：{skip_reason}")

    try:
        state = load_renminwang_state()
        quote = cache.get("603000", {})
        shares = int(state.get("position", 0))
        price = float(quote.get("price") or 0)
        value = round(shares * price, 2)
        cost = round(shares * float(state.get("cost", 0)), 2)
        add(
            {
                "code": "603000",
                "name": "603000 人民网",
                "category": "股票",
                "value": value,
                "cost": cost,
                "profit": round(value - cost, 2),
                "change_pct": quote.get("change_pct"),
                "price": price or None,
                "quantity": shares,
                "price_unit": "元/股",
                "quantity_unit": "股",
                "time": quote.get("time", ""),
                "quote_updated_at": quote.get("refreshed_at", ""),
                "source": f"{quote.get('source', '等待股票行情')} + 本地持仓",
                "refreshable": True,
                "editable_fields": ["value", "profit"],
            }
        )
    except Exception as exc:
        add({"code": "603000", "name": "603000 人民网", "category": "股票", "value": 0, "source": f"读取失败：{exc}", "refreshable": True})

    try:
        gold_config = load_json_file(CMB_GOLD_CONFIG)
        quote = cache.get("gold", {})
        price = float(quote.get("price") or 0)
        grams = float(gold_config.get("grams", 0))
        cost = round(grams * float(gold_config.get("cost_price_per_g", 0)), 2)
        value = round(grams * price, 2)
        add(
            {
                "code": "gold",
                "name": "招行黄金",
                "category": "黄金",
                "value": value,
                "cost": cost,
                "profit": round(value - cost, 2),
                "change_pct": quote.get("change_pct"),
                "price": price or None,
                "quantity": grams,
                "price_unit": "元/克",
                "quantity_unit": "克",
                "time": quote.get("time", ""),
                "quote_updated_at": quote.get("refreshed_at", ""),
                "source": f"{quote.get('source', '等待黄金行情')}，{grams}g",
                "refreshable": True,
                "editable_fields": [],
            }
        )
    except Exception as exc:
        add({"code": "gold", "name": "招行黄金", "category": "黄金", "value": 0, "source": f"读取失败：{exc}", "refreshable": True})

    total, profit, by_category = finance_portfolio_totals(rows)
    return {
        "generated_at": generated_at,
        "total": total,
        "known_profit": profit,
        "by_category": by_category,
        "holdings": rows,
        "refresh_codes": list(FINANCE_REFRESH_CODES),
        "notes": notes,
    }


def refresh_finance_holding(code):
    quote = refresh_finance_quote(code)
    portfolio = read_finance_portfolio()
    holding = next((row for row in portfolio["holdings"] if row.get("code") == code), None)
    if not holding:
        raise ValueError("持仓不存在")
    return {"quote": quote, "holding": holding, "refreshed_at": quote["refreshed_at"]}


def valid_time_text(value):
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", text):
        raise ValueError("时间格式应为 HH:MM")
    hour, minute = [int(part) for part in text.split(":")]
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("时间超出范围")
    return f"{hour:02d}:{minute:02d}"


def start_clock_generation(body):
    with CLOCK_LOCK:
        status = read_clock_status()
        if status.get("running"):
            raise ValueError("已有生成任务正在运行")

        start = valid_time_text(body.get("start") or "06:00")
        end = valid_time_text(body.get("end") or "07:00")
        speed = float(body.get("speed") or 240)
        if speed <= 0 or speed > 3600:
            raise ValueError("速度倍数必须在 0 到 3600 之间")
        style = str(body.get("style") or "cartoon")
        if style not in {"cartoon", "classic", "minimal"}:
            raise ValueError("未知钟表样式")

        CLOCK_PUBLIC.mkdir(exist_ok=True)
        CLOCK_STATUS.write_text(
            json.dumps(
                {
                    "running": True,
                    "ok": True,
                    "progress": 1,
                    "phase": "任务已提交",
                    "params": {"start": start, "end": end, "speed": speed, "style": style},
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        def worker():
            try:
                subprocess.run(
                    [
                        sys.executable,
                        str(CLOCK_GENERATOR),
                        "--start",
                        start,
                        "--end",
                        end,
                        "--speed",
                        str(speed),
                        "--style",
                        style,
                        "--public-dir",
                        str(CLOCK_PUBLIC),
                        "--status",
                        str(CLOCK_STATUS),
                    ],
                    cwd=str(CLOCK_GENERATOR.parent),
                    check=True,
                )
            except Exception as exc:
                CLOCK_STATUS.write_text(
                    json.dumps(
                        {
                            "running": False,
                            "ok": False,
                            "progress": 100,
                            "phase": f"生成失败：{exc}",
                            "params": {"start": start, "end": end, "speed": speed, "style": style},
                            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

        threading.Thread(target=worker, daemon=True).start()
        return read_clock_status()


def task_by_id(task_id):
    for task in SCHEDULED_TASKS:
        if task["id"] == task_id:
            return task
    raise ValueError("Unknown task")


def run_cmd(args, check=False):
    result = subprocess.run(args, text=True, capture_output=True, timeout=10)
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    return result


def current_crontab_lines():
    result = subprocess.run(["crontab", "-l"], text=True, capture_output=True, timeout=5)
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def install_crontab_lines(lines):
    data = "\n".join(lines).rstrip() + "\n"
    proc = subprocess.run(["crontab", "-"], input=data, text=True, capture_output=True, timeout=5)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "crontab update failed").strip())


def cron_status(task):
    lines = current_crontab_lines()
    marker = task["marker"]
    for line in lines:
        stripped = line.strip()
        active = not stripped.startswith("#")
        body = stripped[1:].strip() if stripped.startswith("#") else stripped
        if marker in body and task["command"] in body:
            left = body.split(task["command"], 1)[0].strip()
            return {"enabled": active, "schedule": left}
    return {"enabled": False, "schedule": task.get("default_schedule", "")}


def set_cron_task(task, enabled, schedule):
    lines = current_crontab_lines()
    marker = task["marker"]
    command = task["command"]
    new_line = f"{schedule.strip()} {command} {marker}"
    updated = []
    found = False
    for line in lines:
        body = line.strip()[1:].strip() if line.strip().startswith("#") else line.strip()
        if marker in body and command in body:
            found = True
            updated.append(new_line if enabled else f"# {new_line}")
        else:
            updated.append(line)
    if not found:
        updated.append(new_line if enabled else f"# {new_line}")
    install_crontab_lines(updated)


def systemd_timer_status(task):
    unit = task["unit"]
    enabled = run_cmd(["systemctl", "is-enabled", "--quiet", unit]).returncode == 0
    active = run_cmd(["systemctl", "is-active", "--quiet", unit]).returncode == 0
    timer_path = Path("/etc/systemd/system") / unit
    schedule = ""
    if timer_path.exists():
        text = timer_path.read_text(encoding="utf-8")
        match = re.search(r"^OnUnitActiveSec=(.+)$", text, re.MULTILINE)
        if match:
            schedule = match.group(1).strip()
    return {"enabled": enabled and active, "schedule": schedule}


def set_systemd_timer(task, enabled, schedule=None):
    unit = task["unit"]
    timer_path = Path("/etc/systemd/system") / unit
    if schedule and timer_path.exists():
        text = timer_path.read_text(encoding="utf-8")
        if re.search(r"^OnUnitActiveSec=.+$", text, re.MULTILINE):
            text = re.sub(r"^OnUnitActiveSec=.+$", f"OnUnitActiveSec={schedule.strip()}", text, flags=re.MULTILINE)
            timer_path.write_text(text, encoding="utf-8")
            run_cmd(["systemctl", "daemon-reload"], check=True)
    run_cmd(["systemctl", "enable" if enabled else "disable", unit], check=True)
    run_cmd(["systemctl", "start" if enabled else "stop", unit], check=True)


def parameter_explanation(path, key):
    joined = ".".join(str(part) for part in path)
    if joined in PARAM_EXPLANATIONS:
        return PARAM_EXPLANATIONS[joined]
    if key in PARAM_EXPLANATIONS:
        return PARAM_EXPLANATIONS[key]
    for known, text in PARAM_EXPLANATIONS.items():
        if joined.endswith("." + known):
            return text
    return "该参数会写回任务配置文件，改动后会影响这个定时任务的运行。不了解含义时建议先不要改。"


def parameter_label(path):
    labels = []
    for index, part in enumerate(path):
        if isinstance(part, int):
            prev = path[index - 1] if index else ""
            if prev == "tranches":
                labels.append(f"第 {part + 1} 笔")
            elif prev == "strategy_summary_times":
                labels.append(f"第 {part + 1} 个时间")
            elif prev == "sources":
                labels.append(f"来源 {part + 1}")
            else:
                labels.append(f"第 {part + 1} 项")
            continue
        text = str(part)
        if re.fullmatch(r"\d{6}", text):
            labels.append(f"{text} 基金")
        else:
            labels.append(PARAM_LABELS.get(text, text))
    return " > ".join(labels)


def parameter_unit(path, key):
    joined = ".".join(str(part) for part in path)
    if key in {"cash_balance", "cash_floor", "cash_reduce_threshold", "cash_full_threshold", "monthly_base_amount", "amount", "value", "profit", "cost", "baseline_price", "min_notify_delta"}:
        return "元"
    if key in {"defer_if_022430_up_pct", "execute_if_022430_down_pct", "target_weight"}:
        return "%"
    if key in {"grams", "core_physical_target_grams"}:
        return "克"
    if key.endswith("_price") or key in {"cost_price_per_g", "app_buy_offset_from_au9999", "sell_spread_per_g"}:
        return "元/克"
    if key.endswith("_minutes"):
        return "分钟"
    if key.endswith("_seconds"):
        return "秒"
    if joined.endswith("reminder_hour"):
        return "点"
    if joined.endswith("reminder_minute"):
        return "分"
    return ""


def human_cron_field(value, kind):
    if value == "*":
        return {"minute": "每分钟", "hour": "每小时", "day": "每天", "month": "每月", "weekday": "每天"}[kind]
    names = {
        "weekday": {"1": "周一", "2": "周二", "3": "周三", "4": "周四", "5": "周五", "6": "周六", "0": "周日", "7": "周日"}
    }
    if "-" in value and "/" not in value:
        start, end = value.split("-", 1)
        if kind == "weekday":
            return f"{names['weekday'].get(start, start)}到{names['weekday'].get(end, end)}"
        if kind == "day":
            return f"{start}号到{end}号"
        if kind == "hour":
            return f"{start}点到{end}点"
    if "," in value:
        parts = value.split(",")
        if kind == "weekday":
            return "、".join(names["weekday"].get(part, part) for part in parts)
        return "、".join(parts)
    if kind == "weekday":
        return names["weekday"].get(value, value)
    if kind == "minute":
        return f"{int(value):02d}分" if value.isdigit() else value
    if kind == "hour":
        return f"{int(value):02d}点" if value.isdigit() else value
    if kind == "day":
        return f"{value}号"
    if kind == "month":
        return f"{value}月"
    return value


def human_duration(value):
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([a-zA-Z]+)", text)
    if not match:
        return text
    number, unit = match.groups()
    unit_map = {
        "s": "秒",
        "sec": "秒",
        "secs": "秒",
        "second": "秒",
        "seconds": "秒",
        "m": "分钟",
        "min": "分钟",
        "mins": "分钟",
        "minute": "分钟",
        "minutes": "分钟",
        "h": "小时",
        "hr": "小时",
        "hour": "小时",
        "hours": "小时",
        "d": "天",
        "day": "天",
        "days": "天",
    }
    return f"{number} {unit_map.get(unit.lower(), unit)}"


def describe_schedule(runner, schedule):
    schedule = str(schedule or "").strip()
    if runner == "systemd":
        return f"每隔 {human_duration(schedule)}运行一次" if schedule else "使用 systemd timer 当前设置"
    fields = schedule.split()
    if len(fields) != 5:
        return "Cron 表达式格式不完整，应为：分 时 日 月 周"
    minute, hour, day, month, weekday = fields
    if minute.startswith("*/"):
        return f"每 {minute[2:]} 分钟运行一次"
    if minute == "*" and hour != "*":
        time_text = f"{human_cron_field(hour, 'hour')}之间每分钟"
    else:
        time_text = f"{human_cron_field(hour, 'hour')} {human_cron_field(minute, 'minute')}"
    day_text = human_cron_field(day, "day")
    month_text = human_cron_field(month, "month")
    weekday_text = human_cron_field(weekday, "weekday")
    pieces = [time_text]
    if day != "*":
        pieces.append(day_text)
    if weekday != "*":
        pieces.append(weekday_text)
    if month != "*":
        pieces.append(month_text)
    if day == "*" and weekday == "*":
        pieces.append("每天")
    return "，".join(pieces) + "运行"


def flatten_params(value, path=None):
    path = path or []
    rows = []
    if isinstance(value, dict):
        for key, child in value.items():
            rows.extend(flatten_params(child, path + [key]))
        return rows
    if isinstance(value, list):
        for idx, child in enumerate(value):
            rows.extend(flatten_params(child, path + [idx]))
        return rows
    key = str(path[-1]) if path else ""
    if isinstance(value, bool):
        kind = "bool"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        kind = "number"
    else:
        kind = "text"
    return [
        {
            "path": path,
            "key": ".".join(str(part) for part in path),
            "label": parameter_label(path),
            "value": value,
            "type": kind,
            "unit": parameter_unit(path, key),
            "explanation": parameter_explanation(path, key),
        }
    ]


def set_nested_value(root, path, raw_value):
    target = root
    for part in path[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    last = path[-1]
    old = target[int(last)] if isinstance(target, list) else target[last]
    if isinstance(old, bool):
        value = bool(raw_value)
    elif isinstance(old, int) and not isinstance(old, bool):
        value = int(float(raw_value))
    elif isinstance(old, float):
        value = float(raw_value)
    else:
        value = str(raw_value)
    if isinstance(target, list):
        target[int(last)] = value
    else:
        target[last] = value


def load_task_config(task):
    path = task.get("config_path")
    if not path:
        return None, []
    target = Path(path)
    if not target.exists():
        return None, []
    data = json.loads(target.read_text(encoding="utf-8"))
    return data, flatten_params(data)


def task_status_payload(task):
    status = cron_status(task) if task["runner"] == "cron" else systemd_timer_status(task)
    _config, params = load_task_config(task)
    return {
        "id": task["id"],
        "name": task["name"],
        "category": task["category"],
        "runner": task["runner"],
        "enabled": status["enabled"],
        "schedule": status["schedule"],
        "schedule_human": describe_schedule(task["runner"], status["schedule"]),
        "description": task.get("description", ""),
        "command": task.get("command") or task.get("unit"),
        "config_path": task.get("config_path"),
        "manual_only": bool(task.get("manual_only")),
        "params": params,
    }


def read_scheduled_tasks():
    return {"tasks": [task_status_payload(task) for task in SCHEDULED_TASKS]}


def save_scheduled_task(body):
    task = task_by_id(str(body.get("id") or ""))
    enabled = bool(body.get("enabled"))
    schedule = str(body.get("schedule") or "").strip()

    if task.get("manual_only"):
        if enabled:
            raise ValueError("该小说已改为人工发布，不能启用自动发布")
        set_cron_task(task, False, schedule or task.get("default_schedule", ""))
        return task_status_payload(task)

    path = task.get("config_path")
    if path and isinstance(body.get("params"), list):
        target = Path(path)
        config = json.loads(target.read_text(encoding="utf-8"))
        for item in body["params"]:
            param_path = item.get("path")
            if isinstance(param_path, list) and param_path:
                set_nested_value(config, param_path, item.get("value"))
        target.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    if task["runner"] == "cron":
        set_cron_task(task, enabled, schedule or task.get("default_schedule", ""))
    else:
        set_systemd_timer(task, enabled, schedule)
    return task_status_payload(task)


def run_scheduled_task_now(body):
    task = task_by_id(str(body.get("id") or ""))
    if task.get("manual_only"):
        raise ValueError("该小说已改为人工发布，自动发布入口已停用")
    timeout_seconds = 900 if str(task.get("id", "")).startswith("fanqie-") else 120
    try:
        if task["runner"] == "cron":
            command = task["command"]
            result = subprocess.run([command], text=True, capture_output=True, timeout=timeout_seconds)
        else:
            result = subprocess.run(["systemctl", "start", task["service"]], text=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": 124,
            "stdout": (exc.stdout or "")[-4000:],
            "stderr": ((exc.stderr or "") + f"\n任务超过 {timeout_seconds} 秒未完成，已超时。")[-4000:],
        }
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def configured_token():
    return RENMINWANG_TOKEN.read_text(encoding="utf-8").strip()


def request_token(path, body=None):
    query = ""
    if "?" in path:
        query = path.split("?", 1)[1]
    params = {}
    for pair in query.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        params[key] = value
    return (body or {}).get("token") or params.get("token", "")


def require_renminwang_token(handler, body=None):
    if request_token(handler.path, body) != configured_token():
        write_json(handler, {"ok": False, "error": "Bad token"}, HTTPStatus.FORBIDDEN)
        return False
    return True


def load_renminwang_state():
    return json.loads(RENMINWANG_STATE.read_text(encoding="utf-8"))


def save_renminwang_state(state):
    RENMINWANG_STATE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_json_file(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_file(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_renminwang_trade(body):
    state = load_renminwang_state()
    action = str(body.get("action") or "hold")
    shares = int(body.get("shares") or 0)
    price = float(body.get("price") or 0)
    if action in {"sell", "buy"}:
        if shares <= 0:
            raise ValueError("股数必须大于 0")
        if shares % 100 != 0:
            raise ValueError("股数必须是 100 的整数倍")
        if price <= 0:
            raise ValueError("成交价格必须大于 0")
    if action == "sell":
        if shares > int(state.get("position", 0)):
            raise ValueError("卖出股数不能超过当前记录持仓")
        state["position"] = int(state.get("position", 0)) - shares
        state["cash"] = round(float(state.get("cash", 0.0)) + shares * price, 2)
    elif action == "buy":
        state["position"] = int(state.get("position", 0)) + shares
        state["cash"] = round(float(state.get("cash", 0.0)) - shares * price, 2)
    elif action != "hold":
        raise ValueError("未知操作")

    record = {
        "type": "USER_TRADE_FEEDBACK",
        "action": action,
        "shares": shares,
        "price": price,
        "note": str(body.get("note") or ""),
        "alert_key": str(body.get("alert_key") or ""),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "position_after": int(state.get("position", 0)),
        "cash_after": float(state.get("cash", 0.0)),
    }
    state.setdefault("manual_actions", []).append(record)
    state.setdefault("actions", []).append(record)
    save_renminwang_state(state)
    return state, record


def apply_cmb_gold_trade(body):
    config = load_json_file(CMB_GOLD_CONFIG)
    state = load_json_file(CMB_GOLD_STATE)
    action = str(body.get("action") or "hold")
    grams = float(body.get("amount") or 0)
    price = float(body.get("price") or 0)
    current_grams = float(config.get("grams") or 0)
    current_cost = float(config.get("cost_price_per_g") or 0)

    if action in {"sell", "buy"}:
        if grams <= 0:
            raise ValueError("克数必须大于 0")
        if price <= 0:
            raise ValueError("成交价必须大于 0")
    if action == "sell":
        if grams > current_grams:
            raise ValueError("卖出克数不能超过当前记录持仓")
        config["grams"] = round(current_grams - grams, 4)
        config["cost_price_per_g"] = round(current_cost, 4)
    elif action == "buy":
        new_grams = current_grams + grams
        new_cost = ((current_grams * current_cost) + (grams * price)) / new_grams
        config["grams"] = round(new_grams, 4)
        config["cost_price_per_g"] = round(new_cost, 4)
    elif action != "hold":
        raise ValueError("未知操作")

    record = {
        "type": "USER_TRADE_FEEDBACK",
        "source": "cmb_gold_monitor",
        "action": action,
        "grams": grams,
        "price": price,
        "note": str(body.get("note") or ""),
        "alert_key": str(body.get("alert_key") or ""),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "grams_before": current_grams,
        "cost_price_per_g_before": current_cost,
        "grams_after": float(config.get("grams") or current_grams),
        "cost_price_per_g_after": float(config.get("cost_price_per_g") or current_cost),
    }
    state.setdefault("manual_actions", []).append(record)
    for alert in state.get("sent_alerts", []):
        if alert.get("alert_key") == record["alert_key"]:
            alert["feedback_status"] = "submitted"
            alert["feedback"] = record
    save_json_file(CMB_GOLD_CONFIG, config)
    save_json_file(CMB_GOLD_STATE, state)
    return config, state, record


def append_finance_memory(line):
    if not FINANCE_MEMORY.exists():
        return
    with FINANCE_MEMORY.open("a", encoding="utf-8") as file:
        file.write("\n" + line.rstrip() + "\n")


def update_portfolio_cash_line(cash_balance):
    if not PORTFOLIO_SNAPSHOT.exists():
        return
    text = PORTFOLIO_SNAPSHOT.read_text(encoding="utf-8")
    text = re.sub(
        r"- Cash-like Lingqianbao balance: .*",
        f"- Cash-like Lingqianbao balance: {cash_balance:.2f} CNY from latest feedback/config record. User app values remain authoritative when provided.",
        text,
    )
    text = re.sub(
        r"- Cash-like Lingqianbao: .*",
        f"- Cash-like Lingqianbao: {cash_balance:.2f} CNY.",
        text,
    )
    PORTFOLIO_SNAPSHOT.write_text(text, encoding="utf-8")


def load_fund_dca_config():
    if not FUND_DCA_CONFIG.exists():
        raise ValueError("fund DCA config not found")
    return load_json_file(FUND_DCA_CONFIG)


def save_fund_dca_config(config):
    save_json_file(FUND_DCA_CONFIG, config)


def load_fund_dca_state():
    if FUND_DCA_STATE.exists():
        return load_json_file(FUND_DCA_STATE)
    return {}


def save_fund_dca_state(state):
    save_json_file(FUND_DCA_STATE, state)


def _editable_number(body):
    raw = body.get("value")
    if raw in {None, ""}:
        raise ValueError("请输入数字")
    value = float(raw)
    if not (value == value) or value in {float("inf"), float("-inf")}:
        raise ValueError("请输入有效数字")
    return round(value, 6)


def _current_holding_value(record, price):
    shares = float(record.get("shares") or 0)
    if shares and price:
        return round(shares * price, 2)
    return round(float(record.get("value") or 0), 2)


def apply_finance_holding_update(body):
    code = str(body.get("code") or "").strip()
    field = str(body.get("field") or "").strip()
    value = _editable_number(body)
    price = float(body.get("price") or 0)
    if field not in {"value", "quantity", "profit", "daily_profit"}:
        raise ValueError("不支持编辑这个字段")

    now_text = time.strftime("%Y-%m-%d")

    if code == "603000":
        if field not in {"value", "profit"}:
            raise ValueError("人民网仅支持编辑市值或收益")
        state = load_renminwang_state()
        quote = finance_tencent_quote("sh603000")
        quote_price = float(quote.get("price") or price or 0)
        shares = int(state.get("position") or 0)
        if field == "value":
            if quote_price <= 0:
                raise ValueError("缺少当前价格，无法反推股数")
            shares = max(0, int(round(value / quote_price)))
            state["position"] = shares
        current_value = round(shares * quote_price, 2)
        if field == "profit":
            if shares <= 0:
                raise ValueError("没有持仓股数，无法反推成本")
            state["cost"] = round((current_value - value) / shares, 6)
        save_renminwang_state(state)
        record = {"type": "MANUAL_HOLDING_EDIT", "code": code, "field": field, "value": value, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with TRADE_FEEDBACK_LOG.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return read_finance_portfolio()

    config = load_fund_dca_config()
    if code in (config.get("funds") or {}):
        group = config.setdefault("funds", {})
    elif code in (config.get("qdii_funds") or {}):
        group = config.setdefault("qdii_funds", {})
    else:
        raise ValueError("这条持仓暂不支持编辑")

    item = group.setdefault(code, {})
    if field == "quantity":
        if value < 0:
            raise ValueError("基金份额不能为负数")
        item["shares"] = round(value, 8)
        item["shares_verified"] = True
        item["shares_basis"] = f"{now_text} 网页手动录入份额"
        if price > 0:
            item["value"] = round(value * price, 2)
            item["profit"] = round(item["value"] - float(item.get("cost") or 0), 2)
    elif field == "value":
        if price <= 0:
            raise ValueError("缺少当前价格，无法反推份额")
        item["shares"] = round(value / price, 8)
        item["value"] = round(value, 2)
        item["profit"] = round(value - float(item.get("cost") or 0), 2)
    elif field == "profit":
        current_value = _current_holding_value(item, price)
        item["profit"] = round(value, 2)
        item["cost"] = round(current_value - value, 2)
    elif field == "daily_profit":
        item["daily_profit"] = round(value, 2)
    item["account_updated_at"] = now_text
    save_fund_dca_config(config)

    record = {
        "type": "MANUAL_HOLDING_EDIT",
        "code": code,
        "field": field,
        "value": value,
        "price": price,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with TRADE_FEEDBACK_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
    return read_finance_portfolio()


def apply_cash_update(body):
    config = load_fund_dca_config()
    state = load_fund_dca_state()
    mode = str(body.get("cash_action") or body.get("mode") or "set_balance")
    amount = float(body.get("amount") or 0)
    if mode not in {"set_balance", "deposit"}:
        raise ValueError("未知零钱宝更新方式")
    if amount < 0:
        raise ValueError("金额不能为负数")

    before = round(float(config.get("cash_balance", 0.0)), 2)
    if mode == "set_balance":
        after = round(amount, 2)
    else:
        if amount <= 0:
            raise ValueError("转入金额必须大于 0")
        after = round(before + amount, 2)

    config["cash_balance"] = after
    record = {
        "type": "CASH_BALANCE_FEEDBACK",
        "source": "fund_dca_monitor",
        "cash_action": mode,
        "amount": round(amount, 2),
        "note": str(body.get("note") or ""),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cash_before": before,
        "cash_after": after,
    }
    state.setdefault("cash_updates", []).append(record)
    save_fund_dca_config(config)
    save_fund_dca_state(state)
    update_portfolio_cash_line(after)
    append_finance_memory(
        f"- {record['created_at']}: User updated Lingqianbao via feedback: "
        f"mode={mode}, amount={amount:.2f}, balance_after={after:.2f} CNY. "
        "Use this feedback value over prior cash estimates."
    )
    return config, state, record


def apply_fund_dca_feedback(body):
    config = load_fund_dca_config()
    state = load_fund_dca_state()
    action = str(body.get("action") or "buy")
    if action == "hold":
        record = {
            "type": "FUND_DCA_FEEDBACK",
            "source": "fund_dca_monitor",
            "action": "hold",
            "note": str(body.get("note") or ""),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "cash_after": round(float(config.get("cash_balance", 0.0)), 2),
            "amounts": {},
        }
        state.setdefault("dca_feedback", []).append(record)
        save_fund_dca_state(state)
        return config, state, record
    if action != "buy":
        raise ValueError("基金定投反馈只支持买入或未操作")

    funds = config.get("funds", {})
    amounts = {}
    for code in funds:
        value = float(body.get(f"amount_{code}") or 0)
        if value < 0:
            raise ValueError(f"{code} 金额不能为负数")
        if value > 0:
            amounts[code] = round(value, 2)
    if not amounts:
        fallback_amount = float(body.get("amount") or 0)
        asset = str(body.get("asset") or "")
        if fallback_amount > 0 and asset in funds:
            amounts[asset] = round(fallback_amount, 2)
    total = round(sum(amounts.values()), 2)
    if total <= 0:
        raise ValueError("定投金额必须大于 0")

    cash_before = round(float(config.get("cash_balance", 0.0)), 2)
    if total > cash_before:
        raise ValueError("定投金额不能超过当前记录的零钱宝余额")

    for code, amount in amounts.items():
        fund = funds[code]
        fund["cost"] = round(float(fund.get("cost", 0.0)) + amount, 2)
        fund["value"] = round(float(fund.get("value", 0.0)) + amount, 2)
        fund["profit"] = round(float(fund.get("value", 0.0)) - float(fund.get("cost", 0.0)), 2)

    cash_after = round(cash_before - total, 2)
    config["cash_balance"] = cash_after
    record = {
        "type": "FUND_DCA_FEEDBACK",
        "source": "fund_dca_monitor",
        "action": "buy",
        "amounts": amounts,
        "total": total,
        "note": str(body.get("note") or ""),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cash_before": cash_before,
        "cash_after": cash_after,
        "funds_after": funds,
    }
    state.setdefault("dca_feedback", []).append(record)
    save_fund_dca_config(config)
    save_fund_dca_state(state)
    update_portfolio_cash_line(cash_after)
    append_finance_memory(
        f"- {record['created_at']}: User submitted fund DCA feedback: "
        f"amounts={amounts}, total={total:.2f} CNY, assumed source=Lingqianbao, "
        f"Lingqianbao balance_after={cash_after:.2f} CNY. Fund cost/value records in "
        "`fund_dca_monitor/config.json` were increased by the submitted amounts; future app values override these temporary estimates."
    )
    return config, state, record


def save_trade_feedback(body):
    source = str(body.get("source") or "")
    feedback_type = str(body.get("feedback_type") or "")
    if source == "fund_dca_monitor" and feedback_type == "cash_update":
        _config, _state, cash_record = apply_cash_update(body)
        record = {
            "created_at": cash_record["created_at"],
            "source": source,
            "feedback_type": feedback_type,
            "asset": "零钱宝",
            **cash_record,
        }
        with TRADE_FEEDBACK_LOG.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
    if source == "fund_dca_monitor" and feedback_type == "fund_dca":
        _config, _state, dca_record = apply_fund_dca_feedback(body)
        record = {
            "created_at": dca_record["created_at"],
            "source": source,
            "feedback_type": feedback_type,
            "asset": "009052/022430",
            **dca_record,
        }
        with TRADE_FEEDBACK_LOG.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    action = str(body.get("action") or "hold")
    if action not in {"sell", "buy", "hold"}:
        raise ValueError("未知操作")
    record = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source,
        "alert_key": str(body.get("alert_key") or ""),
        "asset": str(body.get("asset") or ""),
        "action": action,
        "amount": float(body.get("amount") or 0),
        "price": float(body.get("price") or 0),
        "note": str(body.get("note") or ""),
    }
    if source == "cmb_gold_monitor":
        _config, _state, gold_record = apply_cmb_gold_trade(body)
        record.update(
            {
                "asset": record["asset"] or "招行黄金",
                "grams_after": gold_record["grams_after"],
                "cost_price_per_g_after": gold_record["cost_price_per_g_after"],
                "position_record": gold_record,
            }
        )
    with TRADE_FEEDBACK_LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/novel-jobs":
            data = novel_jobs_page().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/uploads.json":
            write_json(self, upload_rows())
            return
        if path == "/api/novel-git-jobs":
            try:
                write_json(self, {"ok": True, **novel_git_jobs()})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/sonovel/search":
            try:
                params = query_params(self.path)
                write_json(self, {"ok": True, **sonovel_search(params.get("q", ""), self.client_address[0])})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/sonovel/status":
            try:
                write_json(self, {"ok": True, **sonovel_web_status()})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/ai-files":
            try:
                params = query_params(self.path)
                write_json(self, {"ok": True, **ai_file_rows(params.get("path", ""))})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/ai-file-content":
            try:
                params = query_params(self.path)
                rel_path = params.get("path", "")
                write_json(self, {"ok": True, "path": rel_path, "content": read_ai_text(rel_path)})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/ai-download":
            try:
                params = query_params(self.path)
                target = resolve_ai_path(params.get("path", ""))
                if not target.exists() or not target.is_file():
                    raise ValueError("File not found")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename*=UTF-8\'\'{parse.quote(target.name)}')
                self.send_header("Content-Length", str(target.stat().st_size))
                self.end_headers()
                with target.open("rb") as f:
                    shutil.copyfileobj(f, self.wfile)
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/ai-preview":
            try:
                params = query_params(self.path)
                target = resolve_ai_path(params.get("path", ""))
                if not target.exists() or not target.is_file():
                    raise ValueError("File not found")
                mime = ai_preview_mime(target)
                if not is_inline_previewable(mime):
                    raise ValueError("This file type cannot be previewed in browser")
                size = target.stat().st_size
                range_header = self.headers.get("Range")
                if range_header:
                    match = re.match(r"bytes=(\d*)-(\d*)", range_header)
                    if not match:
                        raise ValueError("Invalid Range header")
                    start_text, end_text = match.groups()
                    start = int(start_text) if start_text else 0
                    end = int(end_text) if end_text else size - 1
                    start = max(0, min(start, size - 1))
                    end = max(start, min(end, size - 1))
                    length = end - start + 1
                    self.send_response(HTTPStatus.PARTIAL_CONTENT)
                    self.send_header("Content-Type", mime)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Content-Length", str(length))
                    self.send_header("Content-Disposition", f'inline; filename*=UTF-8\'\'{parse.quote(target.name)}')
                    self.end_headers()
                    with target.open("rb") as f:
                        f.seek(start)
                        remaining = length
                        while remaining > 0:
                            chunk = f.read(min(64 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Disposition", f'inline; filename*=UTF-8\'\'{parse.quote(target.name)}')
                self.send_header("Content-Length", str(size))
                self.end_headers()
                with target.open("rb") as f:
                    shutil.copyfileobj(f, self.wfile)
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/clock/progress":
            write_json(self, {"ok": True, "status": read_clock_status()})
            return
        if path == "/api/trade/backtest":
            write_json(self, {"ok": True, "status": read_trade_backtest_status()})
            return
        if path == "/api/finance/portfolio":
            try:
                write_json(self, {"ok": True, "portfolio": read_finance_portfolio()})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/finance/quote":
            try:
                params = query_params(self.path)
                result = refresh_finance_holding(str(params.get("code") or "").strip())
                write_json(self, {"ok": True, **result})
            except ValueError as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            return
        if path == "/api/renminwang/state":
            if not require_renminwang_token(self):
                return
            write_json(self, {"ok": True, "state": load_renminwang_state()})
            return
        if path == "/api/scheduled-tasks":
            try:
                write_json(self, {"ok": True, **read_scheduled_tasks()})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        super().do_GET()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS, PATCH")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/sonovel/download":
            try:
                body = read_json_body(self)
                if body.get("authorized") is not True:
                    raise ValueError("请先确认你对该文本具有合法访问或处理授权")
                job = start_sonovel_download(
                    body.get("search_id"),
                    body.get("result_index"),
                    body.get("format"),
                    self.client_address[0],
                )
                write_json(self, {"ok": True, "job": job}, HTTPStatus.ACCEPTED)
            except RuntimeError as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.CONFLICT)
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/renminwang/action":
            try:
                body = read_json_body(self)
                if not require_renminwang_token(self, body):
                    return
                state, record = apply_renminwang_trade(body)
                write_json(self, {"ok": True, "state": state, "record": record})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/trade-feedback":
            try:
                body = read_json_body(self)
                if not require_renminwang_token(self, body):
                    return
                record = save_trade_feedback(body)
                write_json(self, {"ok": True, "record": record})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/finance/holding-update":
            try:
                body = read_json_body(self)
                portfolio = apply_finance_holding_update(body)
                write_json(self, {"ok": True, "portfolio": portfolio})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/scheduled-tasks/save":
            try:
                body = read_json_body(self)
                task = save_scheduled_task(body)
                write_json(self, {"ok": True, "task": task})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/scheduled-tasks/run":
            try:
                body = read_json_body(self)
                result = run_scheduled_task_now(body)
                write_json(self, {"ok": result["returncode"] == 0, "result": result})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/ai-upload":
            try:
                content_length = int(self.headers.get("Content-Length") or 0)
                if content_length <= 0:
                    write_json(self, {"ok": False, "error": "No upload body"}, HTTPStatus.BAD_REQUEST)
                    return
                if content_length > MAX_UPLOAD_BYTES:
                    write_json(self, {"ok": False, "error": "Upload too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                    return
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                        "CONTENT_LENGTH": str(content_length),
                    },
                    keep_blank_values=True,
                )
                dir_path = str(form.getfirst("dir", "") or "")
                target_dir = resolve_ai_path(dir_path)
                if not target_dir.is_dir():
                    raise ValueError("Target directory not found")
                fields = form["files"] if "files" in form else []
                if not isinstance(fields, list):
                    fields = [fields]
                saved = []
                for field in fields:
                    if not getattr(field, "filename", None):
                        continue
                    original = safe_name(field.filename)
                    target = target_dir / original
                    counter = 1
                    while target.exists():
                        stem, ext = os.path.splitext(original)
                        target = target_dir / f"{stem}_{counter}{ext}"
                        counter += 1
                    with target.open("wb") as out:
                        shutil.copyfileobj(field.file, out)
                    saved.append({"name": target.name, "path": ai_relative(target), "size": target.stat().st_size})
                write_json(self, {"ok": True, "saved": saved})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/ai-zip":
            try:
                body = read_json_body(self)
                paths = body.get("paths") or []
                if not paths:
                    raise ValueError("No paths provided")
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for rel in paths:
                        target = resolve_ai_path(rel)
                        if target.is_file():
                            zf.write(target, target.name)
                        elif target.is_dir():
                            for root, _dirs, files in os.walk(target):
                                for fname in files:
                                    fp = Path(root) / fname
                                    arcname = str(fp.relative_to(target))
                                    zf.write(fp, f"{target.name}/{arcname}")
                buf.seek(0)
                data = buf.getvalue()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", "attachment; filename=ai_files.zip")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/clock/generate":
            try:
                body = read_json_body(self)
                status = start_clock_generation(body)
                write_json(self, {"ok": True, "status": status})
            except Exception as exc:
                write_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if path == "/api/uploads/clear":
            result = clear_uploads()
            write_json(self, {"ok": not result["errors"], **result})
            return

        if path != "/upload":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0:
            self.send_error(HTTPStatus.BAD_REQUEST, "No upload body")
            return
        if content_length > MAX_UPLOAD_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload too large")
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(content_length),
            },
            keep_blank_values=True,
        )

        fields = form["files"] if "files" in form else []
        if not isinstance(fields, list):
            fields = [fields]

        UPLOADS.mkdir(exist_ok=True)
        saved = []
        for field in fields:
            if not getattr(field, "filename", None):
                continue
            original = safe_name(field.filename)
            target = UPLOADS / f"{time.strftime('%Y%m%d-%H%M%S')}-{original}"
            counter = 1
            while target.exists():
                target = UPLOADS / f"{time.strftime('%Y%m%d-%H%M%S')}-{counter}-{original}"
                counter += 1
            with target.open("wb") as out:
                shutil.copyfileobj(field.file, out)
            saved.append({
                "name": target.name,
                "url": f"uploads/{target.name}",
                "size": target.stat().st_size,
            })

        write_json(self, {"ok": True, "saved": saved})

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8090), Handler)
    print("QR login server listening on http://0.0.0.0:8090/", flush=True)
    server.serve_forever()
