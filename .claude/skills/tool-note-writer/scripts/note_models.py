"""筆記資料模型與基礎解析工具 (Note Models & Parser)。

定義各類型筆記的 frontmatter 規格、正規表示式、詞彙表讀取與通用解析函式。
"""

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SKILL_DIR = Path(__file__).resolve().parent.parent
VOCAB_PATH = SKILL_DIR / "references" / "vocabulary.md"
MDLINT_DIR = SKILL_DIR.parent / "markdown-linter" / "scripts"

COMMON_REQUIRED = ["type", "title", "status", "created", "updated", "tags"]
COMMON_OPTIONAL = ["review", "related", "aliases", "sources"]

NOTE_TYPES: Dict[str, Dict[str, Any]] = {
    "arch": {
        "label": "財商架構",
        "dir": "architecture",
        "required": COMMON_REQUIRED + ["domain", "version"],
        "optional": COMMON_OPTIONAL + ["tickers"],
        "status_vocab": "status",
        "default_status": "草稿",
        "sections": ["摘要", "規則", "理由", "適用範圍與例外", "變更紀錄"],
        "versioned": True,
    },
    "research": {
        "label": "標的研究",
        "dir": "research",
        "required": COMMON_REQUIRED + ["tickers"],
        "optional": COMMON_OPTIONAL,
        "status_vocab": "research_status",
        "default_status": "觀察",
        "sections": ["摘要", "論點", "依據", "風險與反方觀點", "追蹤指標", "更新紀錄"],
        "ticker_prefix": True,
        "dated_log": True,
    },
}

REQUIRED_FIELDS = COMMON_REQUIRED + ["domain", "version"]
LIST_FIELDS = {"tags", "tickers", "related", "aliases", "sources"}
DATE_FIELDS = ["created", "updated", "review"]

PLACEHOLDER = "（待填）"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_IN_NAME_RE = re.compile(r"(19|20)\d{2}-?\d{2}-?\d{2}")
BAD_NAME_CHARS = set('*"\\/<>:|?#^[] ')
TICKER_RE = re.compile(r"^\d{4,6}[A-Z]?$")
WIKILINK_RE = re.compile(r"^\[\[[^\[\]]+\]\]$")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
CHANGELOG_RE = re.compile(r"^###\s+v(\d+)（(\d{4}-\d{2}-\d{2})）\s*$")
DATED_LOG_RE = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\s*$")


def repo_root() -> Path:
    """獲取 Git Repository 頂層目錄路徑。"""
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, check=True)
        top = out.stdout.decode("utf-8").strip()
        if top:
            return Path(top)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def load_vocabulary(path: Path = VOCAB_PATH) -> Dict[str, List[str]]:
    """讀取受控詞彙表：`## 段落名` 下的 `- 詞：說明`。"""
    vocab: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(\w+)\s*$", line)
        if m:
            current = m.group(1)
            vocab[current] = []
            continue
        m = re.match(r"^-\s+([^：:\s]+)\s*[：:]", line)
        if m and current:
            vocab[current].append(m.group(1))
    return vocab


def _parse_value(raw: str) -> Any:
    """解析 frontmatter 單行值（支援清單字串與一般文字）。"""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"').strip("'") for item in re.split(r",(?![^\[]*\]\])", inner)]
    return raw.strip('"').strip("'")


def _format_value(value: Any) -> str:
    """格式化值為 frontmatter 寫法。"""
    if isinstance(value, list):
        items = [f'"{v}"' if v.startswith("[[") else v for v in value]
        return "[" + ", ".join(items) + "]"
    return str(value)


def parse_note(text: str) -> Tuple[Optional[Dict[str, Any]], List[str], List[str]]:
    """回傳 (frontmatter, body_lines, errors)；frontmatter 為 None 表示格式錯誤。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, lines, ["檔案開頭缺少 frontmatter（第一行必須是 ---）"]
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None, lines, ["frontmatter 缺少結尾的 ---"]
    meta: Dict[str, Any] = {}
    errors: List[str] = []
    for line in lines[1:end]:
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if not m:
            errors.append(f"frontmatter 這行不是單行 key: value 形式：{line!r}")
            continue
        key = m.group(1)
        if key in meta:
            errors.append(f"欄位 {key} 重複")
        meta[key] = _parse_value(m.group(2))
    return meta, lines[end + 1:], errors


def body_sections(body: List[str]) -> List[str]:
    """獲取本文中的所有二級標題清單。"""
    return [m.group(1) for line in body if (m := SECTION_RE.match(line))]
