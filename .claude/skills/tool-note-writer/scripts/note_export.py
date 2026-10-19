"""筆記匯出成 Google Sheet 分頁 (Note Sheet Exporter)。

把 research/、trends/ 內某標的的筆記拆成固定分頁（每格一個值），輸出 JSON，
供排程用 Sheets update_values 寫入 Drive。公開邊界：過濾持股張數、成本、缺口、實收等個人部位。
"""

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from note_models import SECTION_RE, parse_note, repo_root

EXPORT_DIRS = ("research", "trends")

# 含這些字的句子視為個人部位資訊，不輸出
PRIVATE_RE = re.compile(r"張|缺口|成本|實收|持股 ?\d|持股快照|達標所需")

# (分頁名, 表頭第一格, 保留欄位；None 表示全留)
TABLE_TABS = [
    ("歷年配息", "年度", None),
    ("逐次配息", "除息日", None),
    ("每單位情境", "情境", ["情境", "每單位年配息"]),
    ("成分股中期息", "代號", None),
]

TEXT_SECTIONS = {
    "摘要": "摘要",
    "論點": "論點與風險",
    "風險與反方觀點": "論點與風險",
    "追蹤指標": "追蹤指標",
}

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def clean(text: str) -> str:
    """去掉 Markdown 粗體、反引號，連結只留網址（或文字）。"""
    text = LINK_RE.sub(lambda m: m.group(2) if m.group(1).upper() == "PDF" else m.group(1), text)
    return text.replace("**", "").replace("`", "").strip()


def split_row(line: str) -> List[str]:
    return [clean(c) for c in line.strip().strip("|").split("|")]


def is_separator(line: str) -> bool:
    return bool(re.match(r"^\|[\s:|\-]+\|$", line.strip()))


def public_sentences(text: str) -> str:
    """逐句過濾個人部位；整段都被濾掉則回傳空字串。"""
    parts = re.split(r"(?<=[。；])", text)
    kept = [p for p in parts if p.strip() and not PRIVATE_RE.search(p)]
    return "".join(kept).strip().rstrip("；")


def extract_tables(body: List[str]) -> List[List[List[str]]]:
    """回傳本文中所有表格，每張表為 [表頭, 資料列...]。"""
    tables: List[List[List[str]]] = []
    cur: List[List[str]] = []
    for line in body:
        if line.strip().startswith("|"):
            if not is_separator(line):
                cur.append(split_row(line))
        elif cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    return tables


def extract_bullets(body: List[str]) -> Dict[str, List[str]]:
    """回傳 {段落名: 條列文字}；巢狀條列併入上層，非條列段落以整段文字為一項。"""
    out: Dict[str, List[str]] = {}
    section: Optional[str] = None
    para: List[str] = []

    def flush() -> None:
        if section and para:
            out.setdefault(section, []).append(" ".join(para))
        para.clear()

    for line in body:
        m = SECTION_RE.match(line)
        if m:
            flush()
            section = m.group(1)
            continue
        if section is None or line.startswith("###") or line.strip().startswith("|"):
            if line.startswith("###"):
                flush()
            continue
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("- "):
            flush()
            para.append(clean(s[2:]))
        else:
            para.append(clean(s))
    flush()
    return out


def head_commit(root: Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                           capture_output=True, check=True)
        return r.stdout.decode().strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def note_files(root: Path, ticker: str, exclude: List[str]) -> List[Path]:
    paths = []
    for d in EXPORT_DIRS:
        for p in sorted((root / d).glob("*.md")) if (root / d).is_dir() else []:
            meta, _, _ = parse_note(p.read_text(encoding="utf-8"))
            if not meta or ticker not in (meta.get("tickers") or []):
                continue
            if p.stem in exclude:
                continue
            paths.append(p)
    return paths


def build_export(root: Path, ticker: str, exclude: List[str]) -> Dict[str, Any]:
    """組出所有分頁。第一分頁「來源說明」的 B2 固定為 HEAD commit。"""
    notes = note_files(root, ticker, exclude)
    tabs: Dict[str, List[List[Any]]] = {
        "來源說明": [["欄位", "值"],
                 ["HEAD commit", head_commit(root)],
                 ["同步日期", date.today().isoformat()],
                 ["說明", "自動同步自 REPO 筆記，請勿手動編輯；不含持股張數、成本、缺口、實收"]],
        "筆記清單": [["檔案", "title", "status", "created", "updated", "review", "tags"]],
        "歷年配息": [], "逐次配息": [], "每單位情境": [], "成分股中期息": [],
        "摘要論點風險": [["筆記", "段落", "內容"]],
        "追蹤指標": [["筆記", "指標"]],
    }
    for p in notes:
        meta, body, _ = parse_note(p.read_text(encoding="utf-8"))
        rel = p.relative_to(root).as_posix()
        tabs["來源說明"].append(["來源檔", rel])
        tabs["筆記清單"].append([rel, meta.get("title", ""), meta.get("status", ""), meta.get("created", ""),
                             meta.get("updated", ""), meta.get("review", ""), ",".join(meta.get("tags") or [])])
        for table in extract_tables(body):
            for tab, first, keep in TABLE_TABS:
                if table[0][0] != first:
                    continue
                idx = [table[0].index(c) for c in keep] if keep and all(c in table[0] for c in keep) else None
                if keep and idx is None:
                    continue
                rows = [[r[i] for i in idx] if idx else r for r in table]
                if not tabs[tab]:
                    tabs[tab].append(rows[0])
                tabs[tab] += [r for r in rows[1:] if not PRIVATE_RE.search(" ".join(r))]
        for section, items in extract_bullets(body).items():
            if section not in TEXT_SECTIONS:
                continue
            for item in items:
                text = public_sentences(item)
                if not text:
                    continue
                if section == "追蹤指標":
                    tabs["追蹤指標"].append([rel, text])
                else:
                    tabs["摘要論點風險"].append([rel, section, text])
    return {"head": tabs["來源說明"][1][1], "tabs": {k: v for k, v in tabs.items() if v}}


def cmd_export_sheet(args) -> int:
    """匯出筆記為 Sheet 分頁 JSON 子命令。"""
    root = Path(args.root) if args.root else repo_root()
    data = build_export(root, args.ticker, args.exclude or [])
    if not data["tabs"].get("筆記清單") or len(data["tabs"]["筆記清單"]) < 2:
        print(f"找不到 tickers 含 {args.ticker} 的筆記", file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=1))
    return 0
