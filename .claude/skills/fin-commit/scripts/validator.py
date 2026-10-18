"""Fin-Commit 訊息格式驗證與補強模組（Validator）。

包含：
1. 區塊與欄位解析（parse_sections）
2. 標題長度與數值計算核對（validate_message）
3. 錯誤與警告通報（report）
4. Co-Author 協作者署名補強（ensure_coauthor_line）
"""

import re
import sys
from typing import Dict, List, Optional, Tuple

from registry import (
    AMOUNT_TOLERANCE,
    COAUTHOR_LINE,
    COAUTHOR_RE,
    DATE_RE,
    FIELD_RE,
    HEADER_RE,
    IMPACT_SECTION,
    MAX_SUMMARY,
    NUMBER_RE,
    RECOMMENDED_SECTIONS,
    REQUIRED_SECTION_FIELDS,
    SECTION_RE,
    SKIP_RE,
    TRADE_TYPES,
    TYPES,
)


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


def ensure_coauthor_line(msg: str) -> str:
    """訊息尾端補上 Co-Authored-By；已有者不重複（大小寫不敏感）。"""
    if COAUTHOR_RE.search(msg):
        return msg
    newline = "\r\n" if "\r\n" in msg else "\n"
    return msg.rstrip(newline) + newline * 2 + COAUTHOR_LINE + newline
