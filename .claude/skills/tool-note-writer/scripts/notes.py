#!/usr/bin/env python3
"""tool-note-writer：財商筆記的產生、格式檢查與搜尋（僅用標準函式庫）。

用法：
  notes.py new arch <title> --domain 目標 --tags 股利,複利 [--tickers 00882] [--status 草稿]
  notes.py check [PATH ...]           檢查指定筆記；省略時檢查全部
  notes.py find [條件...]              依欄位或全文搜尋筆記
  notes.py vocab                      列出受控詞彙
"""

import argparse
import io
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

if sys.platform == "win32" and hasattr(sys.stdout, "buffer") and "pytest" not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parent.parent
VOCAB_PATH = SKILL_DIR / "references" / "vocabulary.md"
MDLINT_DIR = SKILL_DIR.parent / "markdown-linter" / "scripts"

## ==============================================================================
## 筆記類型名冊：新增類型時在此註冊，並新增 references/format-<type>.md
## ==============================================================================

NOTE_TYPES: Dict[str, Dict] = {
    "arch": {
        "label": "財商架構",
        "dir": "architecture",
        "sections": ["摘要", "規則", "理由", "適用範圍與例外", "變更紀錄"],
        "versioned": True,
    },
}

REQUIRED_FIELDS = ["type", "title", "domain", "status", "version", "created", "updated", "tags"]
OPTIONAL_FIELDS = ["review", "tickers", "related", "aliases", "sources"]
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

## ==============================================================================
## 基礎工具
## ==============================================================================


def repo_root() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, check=True)
        top = out.stdout.decode("utf-8").strip()
        if top:
            return Path(top)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def load_vocabulary(path: Path = VOCAB_PATH) -> Dict[str, List[str]]:
    """讀取詞彙表：`## 段落名` 下的 `- 詞：說明`。"""
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


def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"').strip("'") for item in re.split(r",(?![^\[]*\]\])", inner)]
    return raw.strip('"').strip("'")


def _format_value(value) -> str:
    if isinstance(value, list):
        items = [f'"{v}"' if v.startswith("[[") else v for v in value]
        return "[" + ", ".join(items) + "]"
    return str(value)


def parse_note(text: str) -> Tuple[Optional[Dict], List[str], List[str]]:
    """回傳 (frontmatter, body_lines, errors)；frontmatter 為 None 表示格式錯誤。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, lines, ["檔案開頭缺少 frontmatter（第一行必須是 ---）"]
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None, lines, ["frontmatter 缺少結尾的 ---"]
    meta: Dict = {}
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
    return [m.group(1) for line in body if (m := SECTION_RE.match(line))]

## ==============================================================================
## 檢查
## ==============================================================================


def check_title(title: str) -> List[str]:
    errors = []
    if not title:
        errors.append("title 不可為空")
    if DATE_IN_NAME_RE.search(title):
        errors.append(f"檔名／title 不可含日期：{title!r}（日期寫在 created／updated）")
    bad = sorted(set(title) & BAD_NAME_CHARS)
    if bad:
        errors.append(f"檔名／title 含不允許的字元 {''.join(bad)!r}（分隔請用 -）")
    return errors


def check_note(path: Path, vocab: Dict[str, List[str]], root: Optional[Path] = None) -> Tuple[List[str], List[str]]:
    """回傳 (errors, warnings)。"""
    text = path.read_text(encoding="utf-8")
    meta, body, errors = parse_note(text)
    warnings: List[str] = []
    if meta is None:
        return errors, warnings

    for f in REQUIRED_FIELDS:
        if f not in meta or meta[f] in ("", []):
            errors.append(f"缺少必填欄位 {f}")
    for f in meta:
        if f not in REQUIRED_FIELDS and f not in OPTIONAL_FIELDS:
            errors.append(f"未定義的欄位 {f}（可用：{', '.join(REQUIRED_FIELDS + OPTIONAL_FIELDS)}）")
    for f in LIST_FIELDS & meta.keys():
        if not isinstance(meta[f], list):
            errors.append(f"{f} 必須是清單形式 [a, b]")

    ntype = meta.get("type")
    spec = NOTE_TYPES.get(ntype)
    if ntype and not spec:
        errors.append(f"未知的 type {ntype!r}，可用：{', '.join(NOTE_TYPES)}")

    title = meta.get("title", "")
    if isinstance(title, str):
        errors += check_title(title)
        if title and path.stem != title:
            errors.append(f"檔名 {path.stem!r} 與 title {title!r} 不一致")

    if spec:
        rel_parent = path.resolve().parent
        expected = (root or repo_root()).resolve() / spec["dir"]
        if rel_parent != expected:
            errors.append(f"{ntype} 筆記應放在 {spec['dir']}/")

    for field, vocab_key in (("domain", "domain"), ("status", "status")):
        value = meta.get(field)
        if value and value not in vocab.get(vocab_key, []):
            errors.append(f"{field} {value!r} 不在詞彙表（可用：{', '.join(vocab.get(vocab_key, []))}）")
    for tag in meta.get("tags", []) if isinstance(meta.get("tags"), list) else []:
        if tag not in vocab.get("tags", []):
            errors.append(f"tag {tag!r} 不在詞彙表；確認無同義詞後再加入 references/vocabulary.md")

    for f in DATE_FIELDS:
        v = meta.get(f)
        if v and not (isinstance(v, str) and DATE_RE.match(v)):
            errors.append(f"{f} 日期格式應為 YYYY-MM-DD，實際：{v!r}")
    if all(isinstance(meta.get(f), str) and DATE_RE.match(meta[f]) for f in ("created", "updated")):
        if meta["updated"] < meta["created"]:
            errors.append("updated 早於 created")

    for t in meta.get("tickers", []) if isinstance(meta.get("tickers"), list) else []:
        if not TICKER_RE.match(t):
            errors.append(f"ticker {t!r} 格式錯誤（例：00882）")
    for r in meta.get("related", []) if isinstance(meta.get("related"), list) else []:
        if not WIKILINK_RE.match(r):
            errors.append(f"related 項目應為 \"[[筆記名]]\"，實際：{r!r}")

    version = meta.get("version")
    if version not in (None, ""):
        if not (isinstance(version, str) and version.isdigit() and int(version) >= 1):
            errors.append(f"version 應為正整數，實際：{version!r}")
            version = None

    if spec:
        sections = body_sections(body)
        missing = [s for s in spec["sections"] if s not in sections]
        if missing:
            errors.append(f"缺少段落：{', '.join('## ' + s for s in missing)}")
        else:
            order = [sections.index(s) for s in spec["sections"]]
            if order != sorted(order):
                errors.append(f"段落順序應為：{' → '.join(spec['sections'])}")
        if spec.get("versioned") and version:
            versions = [(int(m.group(1)), m.group(2)) for line in body if (m := CHANGELOG_RE.match(line))]
            if not versions:
                errors.append("變更紀錄缺少 ### v<版本>（YYYY-MM-DD） 小節")
            elif max(v for v, _ in versions) != int(version):
                errors.append(f"version {version} 與變更紀錄最新版本 v{max(v for v, _ in versions)} 不一致")

    if PLACEHOLDER in text:
        warnings.append(f"仍有 {text.count(PLACEHOLDER)} 處「{PLACEHOLDER}」尚未填寫")
    review = meta.get("review")
    if isinstance(review, str) and DATE_RE.match(review) and review <= date.today().isoformat():
        warnings.append(f"已到回顧日 {review}，請重新檢視這條規則")
    return errors, warnings


def iter_notes(root: Path) -> List[Path]:
    paths: List[Path] = []
    for spec in NOTE_TYPES.values():
        d = root / spec["dir"]
        if d.is_dir():
            paths += sorted(p for p in d.glob("*.md") if p.name not in ("README.md", "INDEX.md"))
    return paths

## ==============================================================================
## 指令
## ==============================================================================


def render_note(ntype: str, title: str, domain: str, tags: List[str], tickers: List[str],
                status: str, today: str) -> str:
    spec = NOTE_TYPES[ntype]
    meta = {
        "type": ntype, "title": title, "domain": domain, "status": status, "version": 1,
        "created": today, "updated": today, "tags": tags,
    }
    if tickers:
        meta["tickers"] = tickers
    fm = "\n".join(f"{k}: {_format_value(v)}" for k, v in meta.items())
    body = []
    for s in spec["sections"]:
        if s == "變更紀錄":
            body.append(f"## {s}\n\n### v1（{today}）\n\n- 變更：建立{spec['label']}筆記。\n- 原因：{PLACEHOLDER}")
        elif s == "規則":
            body.append(f"## {s}\n\n1. {PLACEHOLDER}")
        else:
            body.append(f"## {s}\n\n{PLACEHOLDER}")
    return f"---\n{fm}\n---\n\n" + "\n\n".join(body) + "\n"


def _split_csv(value: Optional[str]) -> List[str]:
    return [v.strip() for v in (value or "").replace("，", ",").split(",") if v.strip()]


def cmd_new(args) -> int:
    root = Path(args.root) if args.root else repo_root()
    vocab = load_vocabulary()
    tags, tickers = _split_csv(args.tags), _split_csv(args.tickers)
    errors = check_title(args.title)
    if args.domain not in vocab["domain"]:
        errors.append(f"domain {args.domain!r} 不在詞彙表：{', '.join(vocab['domain'])}")
    if args.status not in vocab["status"]:
        errors.append(f"status {args.status!r} 不在詞彙表：{', '.join(vocab['status'])}")
    if not tags:
        errors.append("至少需要一個 tag（--tags）")
    errors += [f"tag {t!r} 不在詞彙表" for t in tags if t not in vocab["tags"]]
    errors += [f"ticker {t!r} 格式錯誤" for t in tickers if not TICKER_RE.match(t)]
    path = root / NOTE_TYPES[args.type]["dir"] / f"{args.title}.md"
    if path.exists():
        errors.append(f"筆記已存在：{path.relative_to(root)}（修改既有筆記請直接編輯並更新變更紀錄）")
    if errors:
        for e in errors:
            print(f"❌ {e}", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_note(args.type, args.title, args.domain, tags, tickers, args.status,
                                args.date or date.today().isoformat()), encoding="utf-8")
    print(f"✅ 已建立 {path.relative_to(root).as_posix()}，請填寫「{PLACEHOLDER}」處")
    return 0


def cmd_check(args) -> int:
    root = Path(args.root) if args.root else repo_root()
    vocab = load_vocabulary()
    paths = [Path(p) for p in args.paths] if args.paths else iter_notes(root)
    if not paths:
        print("（沒有筆記可檢查）")
        return 0
    rc = 0
    for p in paths:
        errors, warnings = check_note(p, vocab, root)
        label = p.resolve().relative_to(root.resolve()).as_posix() if p.resolve().is_relative_to(root.resolve()) else str(p)
        print(f"{'❌' if errors else ('⚠️ ' if warnings else '✅')} {label}")
        for e in errors:
            print(f"   ❌ {e}")
        for w in warnings:
            print(f"   ⚠️  {w}")
        rc |= bool(errors)
    if not args.no_mdlint:
        rc |= run_mdlint(paths, root) != 0
    return 1 if rc else 0


def run_mdlint(paths: List[Path], root: Path) -> int:
    """呼叫 markdown-linter skill；筆記除了欄位格式，也必須沒有 Markdown 錯誤。"""
    sys.path.insert(0, str(MDLINT_DIR))
    try:
        import mdlint
    except ImportError:
        print("   ❌ 找不到 markdown-linter skill（.claude/skills/markdown-linter/）", file=sys.stderr)
        return 1
    return mdlint.lint([str(p) for p in paths], root=root)


def summary_of(body: List[str]) -> str:
    """取「## 摘要」段落第一行非空文字。"""
    in_summary = False
    for line in body:
        m = SECTION_RE.match(line)
        if m:
            in_summary = m.group(1) == "摘要"
            continue
        if in_summary and line.strip():
            return line.strip()
    return ""


def cmd_find(args) -> int:
    root = Path(args.root) if args.root else repo_root()
    today = date.today().isoformat()
    hits = []
    for p in iter_notes(root):
        text = p.read_text(encoding="utf-8")
        meta, body, _ = parse_note(text)
        if meta is None:
            continue
        lists = {k: meta.get(k) if isinstance(meta.get(k), list) else [] for k in LIST_FIELDS}
        if args.type and meta.get("type") != args.type:
            continue
        if args.domain and meta.get("domain") != args.domain:
            continue
        if args.status and meta.get("status") != args.status:
            continue
        if args.tag and not all(t in lists["tags"] for t in args.tag):
            continue
        if args.ticker and args.ticker not in lists["tickers"]:
            continue
        if args.due and not (isinstance(meta.get("review"), str) and meta["review"] <= today):
            continue
        if args.text and args.text.lower() not in text.lower():
            continue
        hits.append((p, meta, summary_of(body)))
    if not hits:
        print("（找不到符合條件的筆記）")
        return 0
    for p, meta, summary in hits:
        print(f"- {p.relative_to(root).as_posix()}｜{meta.get('status')}｜{meta.get('domain')}"
              f"｜v{meta.get('version')}｜updated {meta.get('updated')}｜tags {', '.join(meta.get('tags') or [])}")
        if summary:
            print(f"  {summary}")
    print(f"共 {len(hits)} 篇")
    return 0


def cmd_vocab(_args) -> int:
    for key, words in load_vocabulary().items():
        print(f"{key}: {', '.join(words)}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="財商筆記工具（tool-note-writer）")
    p.add_argument("--root", help="REPO 根目錄（預設為 git 頂層）")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="建立新筆記")
    n.add_argument("type", choices=NOTE_TYPES)
    n.add_argument("title", help="筆記名稱＝檔名，不含日期與空白")
    n.add_argument("--domain", required=True)
    n.add_argument("--tags", required=True, help="逗號分隔")
    n.add_argument("--tickers", help="逗號分隔")
    n.add_argument("--status", default="草稿")
    n.add_argument("--date", help="建立日，預設今天（YYYY-MM-DD）")
    n.set_defaults(func=cmd_new)

    c = sub.add_parser("check", help="檢查筆記格式")
    c.add_argument("paths", nargs="*")
    c.add_argument("--no-mdlint", action="store_true", help="略過 Markdown lint（僅限無 Node.js 時暫用）")
    c.set_defaults(func=cmd_check)

    f = sub.add_parser("find", help="搜尋筆記")
    f.add_argument("--type", choices=NOTE_TYPES)
    f.add_argument("--domain")
    f.add_argument("--status")
    f.add_argument("--tag", action="append", help="可重複，需全部符合")
    f.add_argument("--ticker")
    f.add_argument("--due", action="store_true", help="只列已到回顧日的筆記")
    f.add_argument("--text", help="全文關鍵字（不分大小寫）")
    f.set_defaults(func=cmd_find)

    sub.add_parser("vocab", help="列出受控詞彙").set_defaults(func=cmd_vocab)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
