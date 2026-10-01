#!/usr/bin/env python3
"""fin-commit：財商 commit 規範的產生、檢查與 hook 安裝工具（僅用標準函式庫）。

用法：
  fin_commit.py types                         列出所有 commit type
  fin_commit.py check [FILE|-]                檢查 commit message（預設讀 stdin）
  fin_commit.py log [N]                       檢查最近 N 個 commit（預設 20）
  fin_commit.py commit --type buy --scope 00882 --summary "..." [欄位...] [--dry-run]
  fin_commit.py install-hook                  安裝 commit-msg hook，提交時自動檢查
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

TYPES = {
    # 交易行為
    "buy": "買進",
    "sell": "賣出",
    "reinvest": "股息再投入",
    "rebal": "換股 / 再平衡",
    # 現金流與收益
    "div": "股利",
    "cash": "資金進出",
    "fee": "費用",
    # 狀態與分析
    "snap": "持股快照",
    "price": "行情更新",
    "goal": "目標調整",
    "research": "研究",
    "journal": "投資日誌",
    # 維運
    "fix": "資料修正",
    "tool": "工具",
    "docs": "文件",
    "chore": "雜項",
}

TRADE_FIELDS = ["日期", "數量", "價格", "金額", "手續費", "理由"]
REQUIRED_FIELDS = {
    "buy": TRADE_FIELDS,
    "sell": TRADE_FIELDS + ["損益"],
    "reinvest": TRADE_FIELDS,
    "rebal": ["日期", "賣出", "買入", "理由"],
    "div": ["日期", "每股配息", "實收"],
}
# 會改變年股利推估的 type，缺「目標影響」時給警告
IMPACT_TYPES = {"buy", "sell", "reinvest", "rebal"}

# commit 選項名稱 -> body 欄位名稱（依輸出順序）
FIELD_OPTIONS = [
    ("date", "日期"),
    ("qty", "數量"),
    ("price", "價格"),
    ("amount", "金額"),
    ("fee", "手續費"),
    ("pnl", "損益"),
    ("sold", "賣出"),
    ("bought", "買入"),
    ("dps", "每股配息"),
    ("received", "實收"),
    ("ytd", "年度累計"),
    ("reason", "理由"),
]

HEADER_RE = re.compile(r"^(?P<type>[a-z]+)(?P<bang>!)?\((?P<scope>[^()\s]+)\): (?P<summary>.+)$")
FIELD_RE = re.compile(r"^(?P<key>[^:：\s]+)[:：]\s*(?P<value>.+)$")
SKIP_RE = re.compile(r"^(Merge |Revert |fixup! |squash! )")
MAX_SUMMARY = 50


def first_number(text):
    """取出字串中第一個數字（支援千分位與正負號）。"""
    m = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", text)
    return float(m.group().replace(",", "")) if m else None


def parse_fields(body_lines):
    fields = {}
    for line in body_lines:
        m = FIELD_RE.match(line.strip())
        if m and m.group("key") not in fields:
            fields[m.group("key")] = m.group("value").strip()
    return fields


def check_message(text):
    """回傳 (errors, warnings)。"""
    lines = [l.rstrip() for l in text.splitlines() if not l.startswith("#")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return ["commit message 是空的"], []

    header = lines[0]
    if SKIP_RE.match(header):
        return [], []

    errors, warnings = [], []
    m = HEADER_RE.match(header)
    if not m:
        return [f"標題格式應為 <type>(<scope>): <摘要>，實際：{header!r}"], []

    ctype, summary = m.group("type"), m.group("summary")
    if ctype not in TYPES:
        errors.append(f"未知的 type {ctype!r}，可用：{', '.join(TYPES)}")
    if len(summary) > MAX_SUMMARY:
        errors.append(f"摘要 {len(summary)} 字，超過 {MAX_SUMMARY} 字")
    if summary.endswith(("。", ".")):
        errors.append("摘要結尾不要加句號")
    if len(lines) > 1 and lines[1].strip():
        errors.append("標題與 body 之間要空一行")

    fields = parse_fields(lines[1:])
    missing = [f for f in REQUIRED_FIELDS.get(ctype, []) if f not in fields]
    if missing:
        errors.append(f"{ctype} 缺少 body 欄位：{', '.join(missing)}")

    if all(k in fields for k in ("數量", "價格", "金額")):
        qty, price, amount = (first_number(fields[k]) for k in ("數量", "價格", "金額"))
        if None in (qty, price, amount):
            errors.append("數量／價格／金額 無法解析為數字")
        elif abs(qty * price - amount) > 1:
            errors.append(f"金額不符：{qty:,.0f} × {price} = {qty * price:,.0f}，body 寫 {amount:,.0f}")

    if "日期" in fields and not re.match(r"^\d{4}-\d{2}-\d{2}", fields["日期"]):
        errors.append(f"日期格式應為 YYYY-MM-DD，實際：{fields['日期']!r}")

    if ctype in IMPACT_TYPES and "目標影響" not in fields:
        warnings.append(f"{ctype} 會改變股利推估，建議在 footer 加「目標影響: ...」")

    return errors, warnings


def report(errors, warnings, label=None):
    prefix = f"[{label}] " if label else ""
    for w in warnings:
        print(f"{prefix}⚠️  {w}", file=sys.stderr)
    for e in errors:
        print(f"{prefix}❌ {e}", file=sys.stderr)
    return 1 if errors else 0


def cmd_types(_args):
    for t, desc in TYPES.items():
        req = REQUIRED_FIELDS.get(t)
        extra = f"  必填：{', '.join(req)}" if req else ""
        print(f"{t:<9} {desc}{extra}")
    return 0


def cmd_check(args):
    text = sys.stdin.read() if args.file in (None, "-") else Path(args.file).read_text(encoding="utf-8")
    errors, warnings = check_message(text)
    rc = report(errors, warnings)
    if rc == 0 and not args.quiet:
        print("✅ commit message 符合 fin-commit 規範", file=sys.stderr)
    return rc


def cmd_log(args):
    out = subprocess.run(
        ["git", "log", f"-{args.n}", "--format=%h%x00%B%x01"],
        check=True, capture_output=True, text=True,
    ).stdout
    rc = 0
    for entry in filter(str.strip, out.split("\x01")):
        sha, _, msg = entry.strip().partition("\x00")
        errors, warnings = check_message(msg)
        header = msg.strip().splitlines()[0]
        status = "❌" if errors else ("⚠️ " if warnings else "✅")
        print(f"{status} {sha} {header}")
        rc |= report(errors, warnings, sha)
    return rc


def build_message(args):
    header = f"{args.type}{'!' if args.breaking else ''}({args.scope}): {args.summary}"
    body = [f"{label}: {getattr(args, opt)}" for opt, label in FIELD_OPTIONS if getattr(args, opt)]
    body += args.note or []
    footer = []
    if args.impact:
        footer.append(f"目標影響: {args.impact}")
    if args.source:
        footer.append(f"來源: {args.source}")
    footer += args.trailer or []
    return "\n\n".join(part for part in (header, "\n".join(body), "\n".join(footer)) if part) + "\n"


def cmd_commit(args):
    msg = build_message(args)
    errors, warnings = check_message(msg)
    print(msg)
    if report(errors, warnings):
        return 1
    if args.dry_run:
        print("（dry-run，未提交）", file=sys.stderr)
        return 0
    return subprocess.run(["git", "commit", "-F", "-"], input=msg, text=True).returncode


def cmd_install_hook(_args):
    git_dir = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"], check=True, capture_output=True, text=True
    ).stdout.strip()
    hook = Path(git_dir) / "commit-msg"
    script = Path(__file__).resolve()
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f'#!/bin/sh\nexec python3 "{script}" check --quiet "$1"\n', encoding="utf-8")
    hook.chmod(0o755)
    print(f"已安裝 commit-msg hook：{hook}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="財商 commit 規範工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("types", help="列出 commit type").set_defaults(func=cmd_types)

    c = sub.add_parser("check", help="檢查 commit message")
    c.add_argument("file", nargs="?", help="message 檔案，省略或 - 代表 stdin")
    c.add_argument("--quiet", action="store_true", help="通過時不輸出")
    c.set_defaults(func=cmd_check)

    lg = sub.add_parser("log", help="檢查最近的 commit")
    lg.add_argument("n", nargs="?", type=int, default=20)
    lg.set_defaults(func=cmd_log)

    m = sub.add_parser("commit", help="產生 message 並提交已 staged 的變更")
    m.add_argument("--type", required=True, choices=TYPES)
    m.add_argument("--scope", required=True, help="代號（00882）或主題（portfolio）")
    m.add_argument("--summary", required=True)
    m.add_argument("--breaking", action="store_true", help="重大策略轉向，標題加 !")
    for opt, label in FIELD_OPTIONS:
        m.add_argument(f"--{opt}", help=label)
    m.add_argument("--note", action="append", help="額外 body 行，可重複")
    m.add_argument("--impact", help="目標影響")
    m.add_argument("--source", help="資料來源，如 Core/Transactions Tx_ID xxx")
    m.add_argument("--trailer", action="append", help="結尾 trailer，如 Co-Authored-By，可重複")
    m.add_argument("--dry-run", action="store_true", help="只印出 message，不提交")
    m.set_defaults(func=cmd_commit)

    sub.add_parser("install-hook", help="安裝 commit-msg hook").set_defaults(func=cmd_install_hook)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
