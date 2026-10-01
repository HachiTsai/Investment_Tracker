# ==========================================
## 💰 Fin-Commit Workflow
## 職責：自動化 Git 暫存、變更驗證與提交指令生成，確保 Commit Message 符合規格書 SSOT
## 參考 delivery-commit-workflow/committer.py 改寫為財商版：
##   單一詳細模板；類別／type／scope 依 staged 路徑自動判定，不逐次詢問使用者；
##   交易紀錄是其中一種 commit，只多了必填的「交易明細」區塊。
## --auto-quick 為獨立的純機械式精簡提交（交易紀錄禁用）。
# ==========================================

import argparse
import io
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

## ==============================================================================
## Encoding Guard: Force UTF-8 for stdout/stderr on Windows to prevent cp950 errors
## ==============================================================================

if sys.platform == "win32" and hasattr(sys.stdout, "buffer") and "pytest" not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parent.parent
SPEC_PATH = SKILL_DIR / "references" / "spec-git-commit-protocol.md"
MDLINT_DIR = SKILL_DIR.parent / "markdown-linter" / "scripts"

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
    CATEGORY_TRADE, CATEGORY_PORTFOLIO, CATEGORY_ARCH, CATEGORY_RESEARCH, CATEGORY_TREND, CATEGORY_IT,
]

## 路徑前綴 → 類別；依序比對，第一個命中者勝出（較具體的前綴放前面）
CATEGORY_PATH_RULES: List[Tuple[str, str]] = [
    ("portfolio/transactions/", CATEGORY_TRADE),
    ("portfolio/", CATEGORY_PORTFOLIO),
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
## 🤖 執行者與裝置
## ==============================================================================

AGENT_REGISTRY: Dict[str, str] = {
    "kimi": "Kimi",
    "claude": "Claude",
    "antigravity": "Antigravity",
}
UNKNOWN_AGENT: str = "unknown"
UNKNOWN_AGENT_LABEL: str = "未標示"
ENV_FALSY_VALUES: Tuple[str, ...] = ("", "0", "false", "no", "off")

DEVICE_FIELD: str = "執行裝置"
DEVICE_ENV_VAR: str = "AGENT_DEVICE"
PLATFORM_LABELS: Dict[str, str] = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}
VERIFICATION_HEADING: str = "## 驗證"
DEVICE_LINE_RE = re.compile(rf"^\s*[-*]\s*(\*\*)?{DEVICE_FIELD}(\*\*)?\s*[:：]")

#: 署名固定不帶模型版本——換模型不必改模板（沿用 delivery-commit-workflow 裁定）
COAUTHOR_LINE: str = "Co-Authored-By: Claude <noreply@anthropic.com>"
COAUTHOR_RE = re.compile(r"^Co-Authored-By:\s*Claude\b", re.M | re.I)

## L1 快速提交未帶入 狀態／下一步／阻塞 時的佔位語（可 grep，提示往前追溯）
L1_UNSPECIFIED: str = "—（L1 快速提交未帶入，請往前追溯最近一筆完整提交）"

## ==============================================================================
## 🛡️ Auto-Quick 防呆閘門 — 規格書 §6
## ==============================================================================

AUTO_QUICK_GUARDED_PREFIXES: Tuple[str, ...] = (".claude/skills/fin-commit/",)
AUTO_QUICK_GUARDED_FILES: Tuple[str, ...] = ("CLAUDE.md",)
AUTO_QUICK_FILE_SOFT_LIMIT = 10

MESSAGE_FILE = Path(".git/COMMIT_MSG_TEMP")
DIFF_PREVIEW_CHARS = 3000

## ==============================================================================
## 🛠️ 偵測工具
## ==============================================================================


def _env_flag_is_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() not in ENV_FALSY_VALUES


def normalize_agent(agent: Optional[str]) -> str:
    key = (agent or "").strip().lower()
    return key if key in AGENT_REGISTRY else UNKNOWN_AGENT


def detect_agent(cli_agent: Optional[str] = None) -> str:
    """執行者偵測：CLI --agent → 環境變數 AGENT_ID → CLAUDECODE → 未標示（不猜）。"""
    if cli_agent:
        return normalize_agent(cli_agent)
    env_agent = os.environ.get("AGENT_ID", "").strip()
    if env_agent:
        return normalize_agent(env_agent)
    if _env_flag_is_true("CLAUDECODE"):
        return "claude"
    return UNKNOWN_AGENT


def get_agent_label(agent: Optional[str]) -> str:
    key = normalize_agent(agent)
    return UNKNOWN_AGENT_LABEL if key == UNKNOWN_AGENT else AGENT_REGISTRY[key]


def detect_device(platform: Optional[str] = None) -> str:
    """環境變數 AGENT_DEVICE 優先，否則標作業系統（不標 hostname，避免機器名外流）。"""
    env_device = os.environ.get(DEVICE_ENV_VAR, "").strip()
    if env_device:
        return env_device
    plat = sys.platform if platform is None else platform
    return PLATFORM_LABELS.get(plat, plat)


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def infer_category(staged_files: List[str]) -> str:
    """依 staged 路徑判定類別；混合時取優先序最高者。"""
    found = set()
    for raw in staged_files:
        path = _normalize_path(raw)
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


TICKER_RE = re.compile(r"^(\d{4,6}[A-Z]?)_")  # 檔名慣例 <代號>_<主題>；日期檔用 - 不會誤判


def _scope_of(path: str) -> Optional[str]:
    path = _normalize_path(path)
    parts = Path(path).parts
    name = Path(path).name
    if path == "CLAUDE.md":
        return "claude"
    if len(parts) >= 3 and parts[0] == ".claude" and parts[1] == "skills":
        return parts[2]
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
    paths = [_normalize_path(p) for p in staged_files]
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
        reasons.append(f"類別為「{CATEGORY_TRADE}」——交易需要明細與數字核對，不可機械生成")
    for raw in staged_files:
        path = _normalize_path(raw)
        if path in AUTO_QUICK_GUARDED_FILES:
            reasons.append(f"{raw}（Agent 執行規範 SSOT）")
        elif any(path.startswith(p) for p in AUTO_QUICK_GUARDED_PREFIXES):
            reasons.append(f"{raw}（commit 規範本體）")
    return reasons

## ==============================================================================
## 🔍 訊息檢查 — 規格書 §5
## ==============================================================================


def first_number(text: str) -> Optional[float]:
    m = NUMBER_RE.search(text or "")
    return float(m.group().replace(",", "")) if m else None


def parse_sections(lines: List[str]) -> Dict[str, Dict[str, str]]:
    """把 body 依 `## 標題` 切段，回傳 {標題首詞: {欄位: 值}}。

    標題取第一個詞（去掉「（選用…）」等括號說明），讓模板註解不影響比對。
    """
    sections: Dict[str, Dict[str, str]] = {}
    current: Optional[str] = None
    for line in lines:
        m = SECTION_RE.match(line)
        if m:
            current = re.split(r"[\s（(]", m.group("title"), maxsplit=1)[0]
            sections.setdefault(current, {})
            continue
        if current is None:
            continue
        fm = FIELD_RE.match(line)
        if fm:
            key = fm.group("key").strip()
            sections[current].setdefault(key, fm.group("value").strip())
    return sections


def validate_message(text: str) -> Tuple[List[str], List[str]]:
    """回傳 (errors, warnings)。errors 非空即擋下提交。"""
    lines = [l.rstrip("\r") for l in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return ["commit message 是空的"], []

    header = lines[0]
    if SKIP_RE.match(header):
        return [], []

    m = HEADER_RE.match(header)
    if not m:
        return [f"標題格式應為 <type>(<scope>): <摘要>，實際：{header!r}"], []

    errors: List[str] = []
    warnings: List[str] = []
    ctype, summary = m.group("type"), m.group("summary")

    if ctype not in TYPES:
        errors.append(f"未知的 type {ctype!r}，可用：{', '.join(TYPES)}")
    if len(summary) > MAX_SUMMARY:
        errors.append(f"摘要 {len(summary)} 字，超過 {MAX_SUMMARY} 字")
    if summary.endswith(("。", ".")):
        errors.append("摘要結尾不要加句號")
    if len(lines) > 1 and lines[1].strip():
        errors.append("標題與 body 之間要空一行")

    sections = parse_sections(lines[1:])

    if ctype in REQUIRED_SECTION_FIELDS:
        section, fields = REQUIRED_SECTION_FIELDS[ctype]
        if section not in sections:
            errors.append(f"{ctype} 缺少「## {section}」區塊")
        else:
            missing = [f for f in fields if not sections[section].get(f)]
            if missing:
                errors.append(f"「{section}」缺少欄位：{', '.join(missing)}")

    for name, fields in sections.items():
        if all(fields.get(k) for k in ("數量", "價格", "金額")):
            qty, price, amount = (first_number(fields[k]) for k in ("數量", "價格", "金額"))
            if None in (qty, price, amount):
                errors.append(f"「{name}」數量／價格／金額 無法解析為數字")
            elif abs(qty * price - amount) > AMOUNT_TOLERANCE:
                errors.append(
                    f"「{name}」金額不符：{qty:,.0f} × {price} = {qty * price:,.0f}，寫的是 {amount:,.0f}"
                )
        date_value = fields.get("日期")
        if date_value and not DATE_RE.match(date_value):
            errors.append(f"「{name}」日期格式應為 YYYY-MM-DD，實際：{date_value!r}")

    missing_sections = [s for s in RECOMMENDED_SECTIONS if s not in sections]
    if missing_sections:
        warnings.append(f"缺少建議區塊：{', '.join(missing_sections)}")
    if ctype in TRADE_TYPES and IMPACT_SECTION not in sections:
        warnings.append(f"{ctype} 會改變股利推估，建議加「## {IMPACT_SECTION}」")

    return errors, warnings


def report(errors: List[str], warnings: List[str]) -> bool:
    for w in warnings:
        print(f"   ⚠️  [Check] {w}", file=sys.stderr)
    for e in errors:
        print(f"   ❌ [Check] {e}", file=sys.stderr)
    return not errors

## ==============================================================================
## ✍️ 訊息補強
## ==============================================================================


def ensure_device_line(msg: str, device: str) -> str:
    """於「驗證」區塊標題下補上執行裝置；已明寫或無該區塊者原樣返回。"""
    newline = "\r\n" if "\r\n" in msg else "\n"
    lines = msg.split(newline)
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == VERIFICATION_HEADING)
    except StopIteration:
        return msg
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    if any(DEVICE_LINE_RE.match(line) for line in lines[start + 1:end]):
        return msg
    device_line = f"- **{DEVICE_FIELD}**: {device}"
    if start + 1 < len(lines) and not lines[start + 1].strip():
        lines.insert(start + 2, device_line)
    else:
        lines[start + 1:start + 1] = ["", device_line]
    return newline.join(lines)


def ensure_coauthor_line(msg: str) -> str:
    """訊息尾端補上 Co-Authored-By；已有者不重複（大小寫不敏感）。"""
    if COAUTHOR_RE.search(msg):
        return msg
    newline = "\r\n" if "\r\n" in msg else "\n"
    return msg.rstrip(newline) + newline * 2 + COAUTHOR_LINE + newline

## ==============================================================================
## 📦 Git 操作
## ==============================================================================


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], capture_output=True, check=check)


def get_staged_file_list() -> List[str]:
    """已暫存檔案清單；強制 core.quotePath=false，避免中文路徑被跳脫。"""
    try:
        out = git("diff", "--staged", "--name-only").stdout.decode("utf-8", errors="replace")
        return [line.strip() for line in out.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        return []


def get_git_diff() -> str:
    try:
        return git("diff", "--staged").stdout.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError:
        return ""


def get_git_stats() -> str:
    try:
        return git("diff", "--staged", "--stat").stdout.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError:
        return "N/A"


def run_git_add(paths: Optional[List[str]] = None, exclude: Optional[List[str]] = None) -> bool:
    """paths：清空暫存後只 add 指定路徑；exclude：git add . 後排除；皆無：git add .。"""
    try:
        if paths:
            print("   🧹 [Git] 清空暫存區後只暫存指定路徑...")
            subprocess.run(["git", "reset", "-q", "HEAD"], check=False)
            print(f"   📦 [Git] git add -- {' '.join(paths)}")
            subprocess.run(["git", "add", "--", *paths], check=True)
            return True
        print("   📦 [Git] git add .")
        subprocess.run(["git", "add", "."], check=True)
        if exclude:
            print(f"   🚫 [Git] 排除：{' '.join(exclude)}")
            subprocess.run(["git", "reset", "-q", "HEAD", "--", *exclude], check=False)
        return True
    except subprocess.CalledProcessError as e:
        print(f"   ❌ [Git] 暫存失敗：{e}", file=sys.stderr)
        return False


def install_hook() -> int:
    """安裝 commit-msg hook：任何 git commit 都經過 validate_message。"""
    hooks_dir = Path(git("rev-parse", "--git-path", "hooks").stdout.decode().strip())
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "commit-msg"
    hook.write_text(f'#!/bin/sh\nexec python3 "{Path(__file__).resolve()}" --check "$1"\n', encoding="utf-8")
    hook.chmod(0o755)
    print(f"   ✅ [Hook] 已安裝 commit-msg hook：{hook}")
    return 0

## ==============================================================================
## 🚀 提交
## ==============================================================================


def lint_staged_markdown(staged_files: List[str]) -> int:
    """暫存區內的 .md 必須通過 markdown-linter；回傳 0 表示通過或無 .md。"""
    md_files = [f for f in staged_files if f.lower().endswith(".md")]
    if not md_files:
        return 0
    sys.path.insert(0, str(MDLINT_DIR))
    try:
        import mdlint
    except ImportError:
        print("   ❌ [MDLint] 找不到 markdown-linter skill（.claude/skills/markdown-linter/）", file=sys.stderr)
        return 1
    print(f"   🔍 [MDLint] 檢查暫存區 {len(md_files)} 個 Markdown 檔案...")
    return mdlint.lint(md_files)


def finalize_commit(message_file: Path, no_push: bool = False, dry_run: bool = False,
                    skip_mdlint: bool = False) -> int:
    """Markdown lint、補上執行裝置與 Co-Author、檢查格式，通過後 commit（並 push）。"""
    if not skip_mdlint and lint_staged_markdown(get_staged_file_list()) != 0:
        print("❌ [Finalize] 暫存區的 Markdown 未通過 lint，未提交。可先執行 mdlint.py --fix。", file=sys.stderr)
        return 1
    if not message_file.exists():
        print(f"❌ [Finalize] 找不到訊息檔：{message_file}", file=sys.stderr)
        return 1
    msg = message_file.read_text(encoding="utf-8")
    if not msg.strip():
        print("❌ [Finalize] Commit message 是空的。", file=sys.stderr)
        return 1

    original = msg
    device = detect_device()
    msg = ensure_device_line(msg, device)
    if msg != original:
        print(f"   🖥️ [Device] 「驗證」區塊補上 {DEVICE_FIELD}：{device}")
    signed = ensure_coauthor_line(msg)
    if signed != msg:
        print("   ✍️ [Co-Author] 訊息尾端補上 Co-Authored-By")
        msg = signed

    errors, warnings = validate_message(msg)
    if not report(errors, warnings):
        print("❌ [Finalize] 訊息不符規格書，未提交。請修正後重跑。", file=sys.stderr)
        return 1

    if dry_run:
        print("   🧪 [Dry Run] 將以下列訊息提交：")
        print("-" * 60)
        print(msg)
        print("-" * 60)
        if not no_push:
            print("   🧪 [Dry Run] 提交後將 push。")
        return 0

    if msg != original:
        message_file.write_text(msg, encoding="utf-8")

    print(f"   📦 [Git] git commit -F {message_file}")
    if subprocess.run(["git", "commit", "-F", str(message_file)]).returncode != 0:
        print("❌ [Git] commit 失敗。", file=sys.stderr)
        return 1
    if no_push:
        print("   ✅ [Commit] 完成（--no-push，未推送）。")
        return 0
    print("   🚀 [Git] git push")
    if subprocess.run(["git", "push"]).returncode != 0:
        print("❌ [Git] push 失敗。", file=sys.stderr)
        return 1
    print("   ✅ [Commit & Push] 完成。")
    return 0


def build_quick_commit_message(
    staged_files: List[str],
    category: str,
    agent: Optional[str] = None,
    status: Optional[str] = None,
    next_step: Optional[str] = None,
    blocker: Optional[str] = None,
) -> str:
    """L1 快速提交訊息：純由路徑生成，Session-Sync 未帶入的欄位填佔位語。"""
    if not staged_files:
        raise ValueError("沒有已暫存的檔案，無法產生快速提交訊息。")
    ctype = infer_commit_type(staged_files)
    scope = infer_scope(staged_files)
    total = len(staged_files)
    summary = f"更新 {staged_files[0]}" if total == 1 else f"更新 {total} 個檔案"
    if len(summary) > MAX_SUMMARY:
        summary = f"更新 {Path(staged_files[0]).name}"
    bullets = "\n".join(f"- `{p}`" for p in staged_files[:AUTO_QUICK_FILE_SOFT_LIMIT])
    if total > AUTO_QUICK_FILE_SOFT_LIMIT:
        bullets += f"\n- …另有 {total - AUTO_QUICK_FILE_SOFT_LIMIT} 個檔案"
    return f"""{ctype}({scope}): {summary}

## 核心變更

{bullets}

## 變更理由

- L1 快速提交（純機械生成）

## 驗證

- 無需驗證—L1 快速提交

## Session-Sync

- **執行者**: {get_agent_label(agent)}
- **類別**: {category}
- **狀態**: {(status or '').strip() or L1_UNSPECIFIED}
- **下一步**: {(next_step or '').strip() or L1_UNSPECIFIED}
- **阻塞**: {(blocker or '').strip() or L1_UNSPECIFIED}
"""


def build_agent_directive(category: str, agent_label: str, device: str, stats: str, diff: str, spec: str) -> str:
    """草擬指令：交給 Agent 依 diff 與規格書直接寫出訊息並提交。"""
    script = Path(__file__).resolve()
    try:
        script = script.relative_to(Path.cwd())
    except ValueError:
        pass
    return f"""
==============================================================================
🔴 AGENT 強制執行指令 (MANDATORY DIRECTIVE) 🔴
==============================================================================
你現在被 `fin-commit` 技能接管。請依下方 [Git 變更] 與 [規格書]，草擬 Commit Message 並直接完成提交。
類別、type、訊息內容一律不詢問使用者；只有缺少的**數字**（價格、股數、金額）必須詢問，不得推測。

## SOP

1. **[理解]** 閱讀 stats 與 diff，判斷這次是哪一種投資行為或維運變更。
2. **[拆分]** 若混了多種行為（例：股利入帳＋再投入），用 `--stage-list` 拆成多個 commit。
3. **[合規]** 依規格書 §3 選 type／scope；交易類必填「交易明細」，div 必填「股利明細」。
4. **[類別]** 已自動判定為 **{category}**；需要覆蓋時重跑並帶 `--category`。
5. **[核對]** 數量 × 價格 = 金額；數字以 Investment_Tracker_Core 為準（唯讀，嚴禁修改）。
6. **[草擬]** 依規格書 §4 唯一模板寫出最終訊息（不提供多個選項），選用區塊依內容決定。
7. **[提交]** 寫入 `{MESSAGE_FILE.as_posix()}`，執行：
   `python3 {script.as_posix()} --no-stage --message-file {MESSAGE_FILE.as_posix()}`
   （會補執行裝置與 Co-Author、檢查格式；不通過即不提交）。

## Session-Sync 預填值

- **執行者**: {agent_label}
- **類別**: {category}
- **執行裝置**: {device}（提交時自動補進「驗證」區塊）

---
📂 [Git 變更統計 (Stats)]
{stats}
---
📄 [Git 變更內容 (Diff, max {DIFF_PREVIEW_CHARS} chars)]
{diff[:DIFF_PREVIEW_CHARS] if diff else "None"}
---
📜 [SSOT 規格書 ({SPEC_PATH.name})]
{spec}
==============================================================================
"""

## ==============================================================================
## 🚀 Main
## ==============================================================================


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fin-Commit Workflow（財商工程 commit 流程）")
    p.add_argument("--category", choices=CATEGORIES_REGISTRY, help="覆蓋自動判定的類別")
    p.add_argument("--message-file", type=Path, help="已寫好的訊息檔，檢查後直接提交")
    p.add_argument("--exclude", nargs="+", help="git add . 後排除的路徑")
    p.add_argument("--stage-list", nargs="+", help="只暫存指定路徑（與 --exclude 互斥）")
    p.add_argument("--no-stage", action="store_true", help="不自動 git add，使用現有暫存區")
    p.add_argument("--no-push", action="store_true", help="commit 後不 push")
    p.add_argument("--dry-run", action="store_true", help="只顯示訊息，不提交")
    p.add_argument("--auto-quick", action="store_true", help="L1 機械式快速提交（交易紀錄禁用）")
    p.add_argument("--allow-guarded", action="store_true", help="解除 --auto-quick 防呆閘門")
    p.add_argument("--agent", type=lambda s: s.strip().lower(), choices=sorted(AGENT_REGISTRY), help="指定執行者")
    p.add_argument("--status", help="L1 的 Session-Sync 狀態")
    p.add_argument("--next", dest="next_step", help="L1 的 Session-Sync 下一步")
    p.add_argument("--blocker", help="L1 的 Session-Sync 阻塞")
    p.add_argument("--skip-mdlint", action="store_true", help="略過暫存區 Markdown lint（僅限無 Node.js 時暫用，CI 仍會檢查）")
    p.add_argument("--check", type=Path, metavar="FILE", help="只檢查訊息檔格式（commit-msg hook 用）")
    p.add_argument("--install-hook", action="store_true", help="安裝 commit-msg hook")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.check:
        errors, warnings = validate_message(args.check.read_text(encoding="utf-8"))
        return 0 if report(errors, warnings) else 1
    if args.install_hook:
        return install_hook()
    if args.auto_quick and args.message_file:
        print("   ❌ --auto-quick 與 --message-file 不可併用。", file=sys.stderr)
        return 1
    if args.stage_list and args.exclude:
        print("   ❌ --stage-list 與 --exclude 不可併用。", file=sys.stderr)
        return 1

    print("🚀 [Fin-Commit] Initializing...")
    agent_id = detect_agent(args.agent)
    if agent_id == UNKNOWN_AGENT:
        print(f"   ⚠️  [Agent] 無法判定執行者，將標示「{UNKNOWN_AGENT_LABEL}」；可加 --agent 或設定 AGENT_ID。")
    else:
        print(f"   🤖 [Agent] 執行者：{get_agent_label(agent_id)}")

    if args.no_stage:
        print("   📦 [Git] 略過自動暫存（--no-stage）。")
    elif not run_git_add(paths=args.stage_list, exclude=args.exclude):
        return 1

    staged_files = get_staged_file_list()
    if not staged_files:
        print("   ⚠️ [Git] 沒有已暫存的變更，請先 git add。")
        return 0
    print(f"   📋 [Git] Staged files ({len(staged_files)}):")
    for f in staged_files[:15]:
        print(f"      - {f}")
    if len(staged_files) > 15:
        print(f"      ... and {len(staged_files) - 15} more")

    category = args.category or infer_category(staged_files)
    how = "--category 指定" if args.category else "依 staged 路徑自動判定"
    print(f"   🏷️  [Category] 類別：{category}（{how}）")

    if args.message_file:
        return finalize_commit(args.message_file, no_push=args.no_push, dry_run=args.dry_run,
                               skip_mdlint=args.skip_mdlint)

    if args.auto_quick:
        reasons = check_auto_quick_guard(staged_files, category)
        if reasons and not args.allow_guarded:
            print("   🛑 [Auto-Quick] 已阻擋，請改走完整模板：", file=sys.stderr)
            for r in reasons:
                print(f"      - {r}", file=sys.stderr)
            print("   ➜ 確認屬純格式修正時，可加 --allow-guarded 解除。", file=sys.stderr)
            return 1
        if len(staged_files) > AUTO_QUICK_FILE_SOFT_LIMIT:
            print(f"   ⚠️ [Auto-Quick] 暫存 {len(staged_files)} 檔，超過建議上限 {AUTO_QUICK_FILE_SOFT_LIMIT}。")
        message = build_quick_commit_message(
            staged_files, category, agent=agent_id,
            status=args.status, next_step=args.next_step, blocker=args.blocker,
        )
        MESSAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        MESSAGE_FILE.write_text(message, encoding="utf-8")
        return finalize_commit(MESSAGE_FILE, no_push=args.no_push, dry_run=args.dry_run,
                               skip_mdlint=args.skip_mdlint)

    if not SPEC_PATH.exists():
        print(f"   ❌ [Contract] 找不到規格書：{SPEC_PATH}", file=sys.stderr)
        return 1
    print(build_agent_directive(
        category=category,
        agent_label=get_agent_label(agent_id),
        device=detect_device(),
        stats=get_git_stats(),
        diff=get_git_diff(),
        spec=SPEC_PATH.read_text(encoding="utf-8"),
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
