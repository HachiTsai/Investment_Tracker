"""Fin-Commit 名冊與規則推斷模組（Registry & Inference）。

包含：
1. 類別（Categories）與 Type 名冊
2. 必填欄位與正規表達式
3. 執行者（Agent）識別
4. 路徑推斷類別、Scope 與 Type
5. Auto-Quick 防呆閘門規則
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

## ==============================================================================
## 🏷️ 類別名冊 (Categories Registry) — 規格書 §2
## ==============================================================================

CATEGORY_TRADE = "交易紀錄"
CATEGORY_PORTFOLIO = "持股分析"
CATEGORY_ARCH = "財商架構"
CATEGORY_RESEARCH = "投資研究"
CATEGORY_TREND = "趨勢覺察"
CATEGORY_IT = "IT"

## 同時是多類別混合時的優先序：交易 > 持股 > 架構 > 研究 > 趨勢 > IT
CATEGORIES_REGISTRY: List[str] = [
    CATEGORY_TRADE,
    CATEGORY_PORTFOLIO,
    CATEGORY_ARCH,
    CATEGORY_RESEARCH,
    CATEGORY_TREND,
    CATEGORY_IT,
]

## 路徑前綴 → 類別；依序比對，第一個命中者勝出（較具體的前綴放前面）
CATEGORY_PATH_RULES: List[Tuple[str, str]] = [
    ("portfolio/transactions/", CATEGORY_TRADE),
    ("portfolio/", CATEGORY_PORTFOLIO),
    ("reports/", CATEGORY_PORTFOLIO),
    ("architecture/", CATEGORY_ARCH),
    ("research/", CATEGORY_RESEARCH),
    ("journal/", CATEGORY_RESEARCH),
    ("trends/", CATEGORY_TREND),
]

DEFAULT_CATEGORY: str = CATEGORY_IT

## ==============================================================================
## 🧾 Type 名冊 — 規格書 §3.1
## ==============================================================================

TYPES: Dict[str, str] = {
    "buy": "買進",
    "sell": "賣出",
    "reinvest": "股息再投入",
    "rebal": "換股／再平衡",
    "div": "股利",
    "cash": "資金進出",
    "fee": "費用",
    "snap": "持股快照",
    "price": "行情更新",
    "goal": "目標調整",
    "patrol": "巡檢報告",
    "arch": "財商架構",
    "research": "研究",
    "trend": "趨勢覺察",
    "journal": "投資日誌",
    "fix": "修正",
    "tool": "工具",
    "docs": "文件",
    "chore": "雜項",
}

TRADE_TYPES: Tuple[str, ...] = ("buy", "sell", "reinvest", "rebal")

TRADE_SECTION = "交易明細"
DIVIDEND_SECTION = "股利明細"

## type → (必填區塊, 區塊內必填欄位)
REQUIRED_SECTION_FIELDS: Dict[str, Tuple[str, List[str]]] = {
    "buy": (TRADE_SECTION, ["日期", "數量", "價格", "金額", "手續費", "理由"]),
    "sell": (TRADE_SECTION, ["日期", "數量", "價格", "金額", "手續費", "損益", "理由"]),
    "reinvest": (TRADE_SECTION, ["日期", "數量", "價格", "金額", "手續費", "理由"]),
    "rebal": (TRADE_SECTION, ["日期", "賣出", "買入", "理由"]),
    "div": (DIVIDEND_SECTION, ["日期", "每股配息", "實收"]),
}

## 所有 commit 都應具備的區塊（缺少時僅警告）
RECOMMENDED_SECTIONS: Tuple[str, ...] = ("核心變更", "變更理由", "驗證", "Session-Sync")
IMPACT_SECTION = "目標影響"

MAX_SUMMARY = 50
AMOUNT_TOLERANCE = 1.0

HEADER_RE = re.compile(r"^(?P<type>[a-z]+)(?P<bang>!)?\((?P<scope>[^()\s]+)\): (?P<summary>.+)$")
SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
FIELD_RE = re.compile(r"^\s*[-*]\s*(\*\*)?(?P<key>[^:*：]+?)(\*\*)?\s*[:：]\s*(?P<value>.*)$")
NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
SKIP_RE = re.compile(r"^(Merge |Revert |fixup! |squash! )")

## ==============================================================================
## 🤖 執行者
## ==============================================================================

AGENT_REGISTRY: Dict[str, str] = {
    "kimi": "Kimi",
    "claude": "Claude",
    "antigravity": "Antigravity",
}
UNKNOWN_AGENT: str = "unknown"
UNKNOWN_AGENT_LABEL: str = "未標示"
ENV_FALSY_VALUES: Tuple[str, ...] = ("", "0", "false", "no", "off")

#: 署名固定不帶模型版本
COAUTHOR_LINE: str = "Co-Authored-By: Claude <noreply@anthropic.com>"
COAUTHOR_RE = re.compile(r"^Co-Authored-By:\s*Claude\b", re.M | re.I)

## L1 快速提交未帶入 狀態／下一步／阻塞 時的佔位語
L1_UNSPECIFIED: str = "—（L1 快速提交未帶入，請往前追溯最近一筆完整提交）"

## ==============================================================================
## 🛡️ Auto-Quick 防呆閘門 — 規格書 §6
## ==============================================================================

AUTO_QUICK_GUARDED_PREFIXES: Tuple[str, ...] = (".claude/skills/fin-commit/",)
AUTO_QUICK_GUARDED_FILES: Tuple[str, ...] = ("CLAUDE.md",)
AUTO_QUICK_FILE_SOFT_LIMIT = 10

MESSAGE_FILE = Path(".git/COMMIT_MSG_TEMP")
DIFF_PREVIEW_CHARS = 3000

TICKER_RE = re.compile(r"^(\d{4,6}[A-Z]?)_")


def _env_flag_is_true(name: str) -> bool:
    val = os.environ.get(name)
    return bool(val and val.strip().lower() not in ENV_FALSY_VALUES)


def normalize_agent(agent: Optional[str]) -> str:
    key = (agent or "").strip().lower()
    return key if key in AGENT_REGISTRY else UNKNOWN_AGENT


def detect_agent(cli_agent: Optional[str] = None) -> str:
    """決定當前執行者 key（kimi／claude／antigravity／unknown）。"""
    if cli_agent:
        return normalize_agent(cli_agent)
    env_agent = os.environ.get("AGENT_ID")
    if env_agent:
        return normalize_agent(env_agent)
    if _env_flag_is_true("CLAUDECODE"):
        return "claude"
    return UNKNOWN_AGENT


def get_agent_label(agent: Optional[str]) -> str:
    key = normalize_agent(agent)
    return AGENT_REGISTRY.get(key, UNKNOWN_AGENT_LABEL)


def infer_category(staged_files: List[str]) -> str:
    """依 staged 路徑判定類別；混合時取優先序最高者。"""
    found = set()
    for path in staged_files:
        for prefix, category in CATEGORY_PATH_RULES:
            if path.startswith(prefix):
                found.add(category)
                break
        else:
            found.add(CATEGORY_IT)
    for category in CATEGORIES_REGISTRY:
        if category in found:
            return category
    return DEFAULT_CATEGORY


def _scope_of(path: str) -> Optional[str]:
    parts = Path(path).parts
    name = Path(path).name
    if path == "CLAUDE.md":
        return "claude"
    if len(parts) >= 3 and parts[0] == ".claude" and parts[1] == "skills":
        return parts[2]
    if parts and parts[0] == "reports":
        return "fleet"
    if parts and parts[0] in ("research", "journal", "portfolio", "trends", "architecture"):
        m = TICKER_RE.match(name)
        if m:
            return m.group(1)
        return "portfolio" if parts[0] == "portfolio" else parts[0]
    if parts and parts[0] == "scripts":
        return "scripts"
    return None


def infer_scope(staged_files: List[str]) -> str:
    """推斷 scope：唯一且過半的候選勝出，否則 project。"""
    counts: Dict[str, int] = {}
    for raw in staged_files:
        scope = _scope_of(raw)
        if scope:
            counts[scope] = counts.get(scope, 0) + 1
    if not counts:
        return "project"
    max_count = max(counts.values())
    dominant = [s for s, c in counts.items() if c == max_count]
    if len(dominant) == 1 and max_count >= sum(counts.values()) * 0.5:
        return dominant[0]
    return "project"


def infer_commit_type(staged_files: List[str]) -> str:
    """Auto-Quick 用的 type 推斷（純路徑，不判斷交易行為）。"""
    paths = staged_files
    if paths and all(p.startswith("reports/") for p in paths):
        return "patrol"
    if paths and all(p.startswith("portfolio/snapshots/") for p in paths):
        return "snap"
    if paths and all(p.startswith("architecture/") for p in paths):
        return "arch"
    if paths and all(p.startswith("research/") for p in paths):
        return "research"
    if paths and all(p.startswith("trends/") for p in paths):
        return "trend"
    if paths and all(p.startswith("journal/") for p in paths):
        return "journal"
    if paths and all(p.endswith(".md") for p in paths):
        return "docs"
    if any(p.startswith("scripts/") or p.endswith(".py") for p in paths):
        return "tool"
    return "chore"


def check_auto_quick_guard(staged_files: List[str], category: str) -> List[str]:
    """回傳 --auto-quick 的阻擋原因；空清單代表允許。"""
    reasons: List[str] = []
    if category == CATEGORY_TRADE:
        reasons.append("類別為「交易紀錄」，交易需要明細與核對，禁止 auto-quick。")
    for f in staged_files:
        for prefix in AUTO_QUICK_GUARDED_PREFIXES:
            if f.startswith(prefix):
                reasons.append(f"暫存檔案包含保護路徑 {prefix}（{f}），禁止 auto-quick。")
                break
        if f in AUTO_QUICK_GUARDED_FILES:
            reasons.append(f"暫存檔案包含保護檔案 {f}，禁止 auto-quick。")
    return reasons
