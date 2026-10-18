#!/usr/bin/env python3
"""投資組合全標的自動巡檢與每日簡報引擎（Portfolio Patrol Engine）。

用法：
  # 全艦隊例行巡檢（零隱私公開簡報）
  python3 .claude/skills/portfolio-patrol/scripts/patrol.py
  python3 .claude/skills/portfolio-patrol/scripts/patrol.py --tickers 00882
  python3 .claude/skills/portfolio-patrol/scripts/patrol.py --json
  python3 .claude/skills/portfolio-patrol/scripts/patrol.py --markdown
  python3 .claude/skills/portfolio-patrol/scripts/patrol.py --sync-doc <DOC_ID>
  python3 .claude/skills/portfolio-patrol/scripts/patrol.py --commit [--dry-run] [--no-push]

  # 單標的個人深潛試算與複利滾雪球時間線模擬
  python3 .claude/skills/portfolio-patrol/scripts/patrol.py --inspect [00882] [--shares 300000] [--dca 0] [--price 15.20]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 模組定位與根目錄判斷
REPO_ROOT = Path(__file__).resolve().parents[4]
if not (REPO_ROOT / "models").exists():
    for parent in Path(__file__).resolve().parents:
        if (parent / "models").exists() and (parent / ".claude").exists():
            REPO_ROOT = parent
            break

# 匯入各子模組
from patrol_cards import (
    check_watchdog,
    discover_tickers,
    load_cards,
    load_yaml_simple,
)
from patrol_committer import (
    build_patrol_commit_message,
    commit_patrol_report,
)
from patrol_evaluator import (
    _format_macro_feed,
    evaluate_ticker_posture,
    fetch_macro_telemetry,
    fetch_ticker_live_data,
    run_portfolio_patrol as _run_patrol,
)
from patrol_inspector import (
    format_inspect_ascii,
    inspect_ticker,
    simulate_snowball,
)
from patrol_reporter import (
    format_ascii_dashboard,
    format_markdown_briefing,
    sync_to_google_doc,
    update_briefing_file,
)


def run_portfolio_patrol(
    repo_root: Path = REPO_ROOT,
    filter_tickers: Optional[List[str]] = None,
    custom_models_dir: Optional[Path] = None,
    mock_macro: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """執行全艦隊巡檢核心主程序（Facade 包裝器，預設帶入 REPO_ROOT）。"""
    return _run_patrol(
        repo_root=repo_root,
        filter_tickers=filter_tickers,
        custom_models_dir=custom_models_dir,
        mock_macro=mock_macro,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", help="逗號分隔的標的代碼過濾（例如：00882）")
    parser.add_argument("--json", action="store_true", help="輸出結構化 JSON 格式")
    parser.add_argument("--markdown", action="store_true", help="輸出 Google Doc 標準 Markdown 區塊")
    parser.add_argument("--sync-doc", metavar="DOC_ID", help="同步寫入特定 Google Doc ID")
    parser.add_argument("--models-dir", help="指定模型根目錄（測試用）")
    parser.add_argument("--commit", action="store_true", help="原地更新 reports/portfolio_briefing.md 並自動 commit & push 觸發 Slack 通知")
    parser.add_argument("--dry-run", action="store_true", help="模擬 commit 訊息生成，不實際執行 git commit")
    parser.add_argument("--no-push", action="store_true", help="提交後不執行 git push")

    # 單標的深潛與個人持股試算參數
    parser.add_argument(
        "--inspect",
        nargs="?",
        const="00882",
        metavar="TICKER",
        help="單標的個人深潛運算與滾雪球時間線模擬（預設 00882）",
    )
    parser.add_argument("--shares", type=float, help="個人持股股數（預設由卡片讀取，例如 300000 股 / 300 張）")
    parser.add_argument("--price", type=float, help="手動指定/覆蓋標的市價（TWD）")
    parser.add_argument("--dca", type=float, default=0.0, help="每年預計額外定期定額投入本金（TWD）")

    args = parser.parse_args(argv)

    # 1. 單標的深度試算模式
    if args.inspect:
        custom_models_dir = Path(args.models_dir) if args.models_dir else None
        inspect_data = inspect_ticker(
            ticker=args.inspect,
            repo_root=REPO_ROOT,
            shares=args.shares,
            price_override=args.price,
            dca=args.dca,
            custom_models_dir=custom_models_dir,
        )
        if args.json:
            print(json.dumps(inspect_data, ensure_ascii=False, indent=2))
        else:
            print(format_inspect_ascii(inspect_data))
        return 0

    # 2. 全艦隊巡檢模式
    filter_tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    custom_models_dir = Path(args.models_dir) if args.models_dir else None

    report = run_portfolio_patrol(
        repo_root=REPO_ROOT,
        filter_tickers=filter_tickers,
        custom_models_dir=custom_models_dir,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    md_content = format_markdown_briefing(report)

    if args.sync_doc:
        sync_to_google_doc(args.sync_doc, md_content, repo_root=REPO_ROOT)

    if args.commit or args.dry_run:
        ok = commit_patrol_report(
            report,
            dry_run=args.dry_run,
            no_push=args.no_push,
            repo_root=REPO_ROOT,
        )
        return 0 if ok else 1

    if args.markdown:
        print(md_content)
    else:
        print(format_ascii_dashboard(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
