"""筆記操作與 CLI 子命令實作模組 (Note Operations)。

負責新增筆記範本 (new)、全域檢查 (check)、依欄位/全文搜尋 (find) 與受控詞彙檢視 (vocab)。
"""

import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from note_models import (
    LIST_FIELDS,
    MDLINT_DIR,
    NOTE_TYPES,
    PLACEHOLDER,
    SECTION_RE,
    TICKER_RE,
    _format_value,
    load_vocabulary,
    parse_note,
    repo_root,
)
from note_validator import check_note, check_title, iter_notes


def render_note(
    ntype: str,
    title: str,
    domain: Optional[str],
    tags: List[str],
    tickers: List[str],
    status: str,
    today: str,
) -> str:
    """依照型別規格組裝新筆記的 Markdown 原始碼。"""
    spec = NOTE_TYPES[ntype]
    meta: Dict[str, Any] = {"type": ntype, "title": title}
    if "domain" in spec["required"]:
        meta["domain"] = domain
    meta["status"] = status
    if spec.get("versioned"):
        meta["version"] = 1
    meta.update({"created": today, "updated": today, "tags": tags})
    if tickers:
        meta["tickers"] = tickers
    fm = "\n".join(f"{k}: {_format_value(v)}" for k, v in meta.items())
    body = []
    for s in spec["sections"]:
        if s == "更新紀錄":
            body.append(f"## {s}\n\n### {today}\n\n- 建立{spec['label']}筆記。")
        elif s == "變更紀錄":
            body.append(f"## {s}\n\n### v1（{today}）\n\n- 變更：建立{spec['label']}筆記。\n- 原因：{PLACEHOLDER}")
        elif s == "規則":
            body.append(f"## {s}\n\n1. {PLACEHOLDER}")
        else:
            body.append(f"## {s}\n\n{PLACEHOLDER}")
    return f"---\n{fm}\n---\n\n" + "\n\n".join(body) + "\n"


def _split_csv(value: Optional[str]) -> List[str]:
    """將逗號分隔字串切分為字串列表（支援中文逗號）。"""
    return [v.strip() for v in (value or "").replace("，", ",").split(",") if v.strip()]


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


def cmd_new(args) -> int:
    """建立新筆記子命令。"""
    root = Path(args.root) if args.root else repo_root()
    vocab = load_vocabulary()
    spec = NOTE_TYPES[args.type]
    tags, tickers = _split_csv(args.tags), _split_csv(args.tickers)
    status = args.status or spec["default_status"]
    errors = check_title(args.title)
    if "domain" in spec["required"]:
        if args.domain not in vocab["domain"]:
            errors.append(f"domain {args.domain!r} 不在詞彙表：{', '.join(vocab['domain'])}")
    elif args.domain:
        errors.append(f"{args.type} 筆記不使用 domain")
    if status not in vocab[spec["status_vocab"]]:
        errors.append(f"status {status!r} 不在詞彙表：{', '.join(vocab[spec['status_vocab']])}")
    if "tickers" in spec["required"] and not tickers:
        errors.append(f"{args.type} 筆記至少需要一個代號（--tickers）")
    if spec.get("ticker_prefix") and tickers and not args.title.startswith(f"{tickers[0]}_"):
        errors.append(f"{args.type} 筆記名稱應為 <代號>_<主題>，例如 {tickers[0]}_股利追蹤")
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
    path.write_text(
        render_note(
            args.type,
            args.title,
            args.domain,
            tags,
            tickers,
            status,
            args.date or date.today().isoformat(),
        ),
        encoding="utf-8",
    )
    print(f"✅ 已建立 {path.relative_to(root).as_posix()}，請填寫「{PLACEHOLDER}」處")
    return 0


def cmd_check(args) -> int:
    """檢查筆記格式子命令。"""
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


def cmd_find(args) -> int:
    """搜尋筆記子命令。"""
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
        parts = [p.relative_to(root).as_posix(), meta.get("status")]
        if meta.get("domain"):
            parts.append(meta["domain"])
        if meta.get("version"):
            parts.append(f"v{meta['version']}")
        if meta.get("tickers"):
            parts.append(", ".join(meta["tickers"]))
        parts += [f"updated {meta.get('updated')}", f"tags {', '.join(meta.get('tags') or [])}"]
        print("- " + "｜".join(str(x) for x in parts))
        if summary:
            print(f"  {summary}")
    print(f"共 {len(hits)} 篇")
    return 0


def cmd_vocab(_args) -> int:
    """列出受控詞彙子命令。"""
    for key, words in load_vocabulary().items():
        print(f"{key}: {', '.join(words)}")
    return 0
