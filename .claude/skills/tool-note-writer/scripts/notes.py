#!/usr/bin/env python3
"""tool-note-writer：財商筆記的產生、格式檢查與搜尋（僅用標準函式庫）。

用法：
  notes.py new arch <title> --domain 目標 --tags 股利,複利 [--tickers 00882] [--status 草稿]
  notes.py new research <代號>_<主題> --tickers 00882 --tags 高股息 [--status 觀察]
  notes.py check [PATH ...]           檢查指定筆記；省略時檢查全部
  notes.py find [條件...]              依欄位或全文搜尋筆記
  notes.py vocab                      列出受控詞彙
  notes.py export-sheet --ticker 00882 [--exclude 筆記名]   匯出成 Sheet 分頁 JSON
"""

import argparse
import sys
from typing import List, Optional

# 匯入各子模組並 re-export 以保持測試與 API 100% 相容
from note_models import (
    BAD_NAME_CHARS,
    CHANGELOG_RE,
    COMMON_OPTIONAL,
    COMMON_REQUIRED,
    DATE_FIELDS,
    DATE_IN_NAME_RE,
    DATE_RE,
    DATED_LOG_RE,
    LIST_FIELDS,
    MDLINT_DIR,
    NOTE_TYPES,
    PLACEHOLDER,
    REQUIRED_FIELDS,
    SECTION_RE,
    SKILL_DIR,
    TICKER_RE,
    VOCAB_PATH,
    WIKILINK_RE,
    _format_value,
    _parse_value,
    body_sections,
    load_vocabulary,
    parse_note,
    repo_root,
)
from note_export import cmd_export_sheet
from note_operations import (
    _split_csv,
    cmd_check,
    cmd_find,
    cmd_new,
    cmd_vocab,
    render_note,
    run_mdlint,
    summary_of,
)
from note_validator import (
    check_note,
    check_title,
    iter_notes,
)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="財商筆記工具（tool-note-writer）")
    p.add_argument("--root", help="REPO 根目錄（預設為 git 頂層）")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="建立新筆記")
    n.add_argument("type", choices=NOTE_TYPES)
    n.add_argument("title", help="筆記名稱＝檔名，不含日期與空白")
    n.add_argument("--domain", help="arch 必填；research 不使用")
    n.add_argument("--tags", required=True, help="逗號分隔")
    n.add_argument("--tickers", help="逗號分隔")
    n.add_argument("--status", help="預設：arch 為草稿、research 為觀察")
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

    e = sub.add_parser("export-sheet", help="把某標的筆記匯出成 Sheet 分頁 JSON（過濾個人部位）")
    e.add_argument("--ticker", required=True)
    e.add_argument("--exclude", action="append", help="排除的筆記名（不含 .md），可重複")
    e.set_defaults(func=cmd_export_sheet)

    sub.add_parser("vocab", help="列出受控詞彙").set_defaults(func=cmd_vocab)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
