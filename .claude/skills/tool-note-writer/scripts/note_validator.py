"""筆記規範檢查與校驗模組 (Note Validator)。

負責驗證檔名命名、必填欄位、受控詞彙、變更紀錄格式及段落結構完整性。
"""

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from note_models import (
    BAD_NAME_CHARS,
    CHANGELOG_RE,
    COMMON_OPTIONAL,
    DATE_FIELDS,
    DATE_IN_NAME_RE,
    DATE_RE,
    DATED_LOG_RE,
    LIST_FIELDS,
    NOTE_TYPES,
    PLACEHOLDER,
    REQUIRED_FIELDS,
    TICKER_RE,
    WIKILINK_RE,
    body_sections,
    parse_note,
    repo_root,
)


def check_title(title: str) -> List[str]:
    """檢查筆記名稱與檔名是否符合規範（不可含日期與特殊字元）。"""
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
    """回傳 (errors, warnings)。檢查單篇筆記的完整性與規範符合度。"""
    text = path.read_text(encoding="utf-8")
    meta, body, errors = parse_note(text)
    warnings: List[str] = []
    if meta is None:
        return errors, warnings

    ntype = meta.get("type")
    spec = NOTE_TYPES.get(ntype)
    if ntype and not spec:
        errors.append(f"未知的 type {ntype!r}，可用：{', '.join(NOTE_TYPES)}")
    required = spec["required"] if spec else REQUIRED_FIELDS
    allowed = required + (spec["optional"] if spec else COMMON_OPTIONAL + ["tickers"])

    for f in required:
        if f not in meta or meta[f] in ("", []):
            errors.append(f"缺少必填欄位 {f}")
    for f in meta:
        if f not in allowed:
            errors.append(f"未定義的欄位 {f}（{ntype or '此類型'} 可用：{', '.join(allowed)}）")
    for f in LIST_FIELDS & meta.keys():
        if not isinstance(meta[f], list):
            errors.append(f"{f} 必須是清單形式 [a, b]")

    title = meta.get("title", "")
    if isinstance(title, str):
        errors += check_title(title)
        if title and path.stem != title:
            errors.append(f"檔名 {path.stem!r} 與 title {title!r} 不一致")
        tickers = meta.get("tickers") if isinstance(meta.get("tickers"), list) else []
        if spec and spec.get("ticker_prefix") and tickers and not title.startswith(f"{tickers[0]}_"):
            errors.append(f"{ntype} 檔名應為 <代號>_<主題>，且代號為 tickers 第一個（{tickers[0]}）")

    if spec:
        rel_parent = path.resolve().parent
        expected = (root or repo_root()).resolve() / spec["dir"]
        if rel_parent != expected:
            errors.append(f"{ntype} 筆記應放在 {spec['dir']}/")

    status_vocab = spec["status_vocab"] if spec else "status"
    for field, vocab_key in (("domain", "domain"), ("status", status_vocab)):
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
        if spec.get("dated_log"):
            dates = [m.group(1) for line in body if (m := DATED_LOG_RE.match(line))]
            if not dates:
                errors.append("更新紀錄缺少 ### YYYY-MM-DD 小節")
            elif isinstance(meta.get("updated"), str) and max(dates) != meta["updated"]:
                errors.append(f"updated {meta['updated']} 與更新紀錄最新日期 {max(dates)} 不一致")

    if PLACEHOLDER in text:
        warnings.append(f"仍有 {text.count(PLACEHOLDER)} 處「{PLACEHOLDER}」尚未填寫")
    review = meta.get("review")
    if isinstance(review, str) and DATE_RE.match(review) and review <= date.today().isoformat():
        warnings.append(f"已到回顧日 {review}，請重新檢視這篇筆記")
    return errors, warnings


def iter_notes(root: Path) -> List[Path]:
    """遍歷 root 下所有筆記目錄中的 Markdown 檔案（排除 README 與 INDEX）。"""
    paths: List[Path] = []
    for spec in NOTE_TYPES.values():
        d = root / spec["dir"]
        if d.is_dir():
            paths += sorted(p for p in d.glob("*.md") if p.name not in ("README.md", "INDEX.md"))
    return paths
