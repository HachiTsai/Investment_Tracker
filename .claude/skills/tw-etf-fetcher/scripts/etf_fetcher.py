#!/usr/bin/env python3
"""台股 ETF 資料管線與成分股穿透分析引擎 (TW ETF Fetcher Facade)。

用法：
  # 1. 查詢全市場 ETF
  python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py list
  python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py list --filter 高息 --limit 20
  python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py list --json

  # 2. 抓取成分股持股明細
  python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py holdings 00878
  python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py holdings 00878 00919 --json

  # 3. 投資組合穿透分析 (Look-through)
  python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py lookthrough --portfolio "00878:10,00919:5"

  # 4. 一鍵建立 DCS 建模卡片
  python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py scaffold-model 00878
"""

import argparse
import json
import sys
from pathlib import Path

# 將當前腳本目錄加入 sys.path 確保模組載入正常
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

REPO_ROOT = SCRIPT_DIR.parents[3]

from etf_holdings_scraper import clean_ticker, fetch_etf_holdings, format_holdings_ascii  # noqa: E402
from etf_list_scraper import fetch_twse_etf_list, filter_etfs, format_etf_list_ascii  # noqa: E402
from etf_lookthrough import calculate_lookthrough, format_lookthrough_ascii  # noqa: E402
from etf_model_scaffolder import scaffold_etf_model  # noqa: E402


def cmd_list(args) -> int:
    """處理 list 子命令。"""
    try:
        etfs = fetch_twse_etf_list()
    except Exception as e:
        print(f"❌ 抓取全市場 ETF 失敗：{e}", file=sys.stderr)
        return 1

    filtered = filter_etfs(etfs, keyword=args.filter, limit=args.limit)

    if args.json:
        print(json.dumps(filtered, ensure_ascii=False, indent=2))
    else:
        print(format_etf_list_ascii(filtered, keyword=args.filter))
    return 0


def cmd_holdings(args) -> int:
    """處理 holdings 子命令。"""
    results = {}
    for ticker in args.tickers:
        code = clean_ticker(ticker)
        try:
            h_data = fetch_etf_holdings(code)
            results[code] = h_data
            if not args.json:
                print(format_holdings_ascii(h_data, limit=args.limit))
                print()
        except Exception as e:
            print(f"❌ 解析 {code} 成分股失敗：{e}", file=sys.stderr)

    if args.json:
        print(json.dumps(results if len(args.tickers) > 1 else list(results.values())[0], ensure_ascii=False, indent=2))

    return 0


def cmd_lookthrough(args) -> int:
    """處理 lookthrough 穿透分析子命令。"""
    # 解析 --portfolio "00878:10,00919:5"
    portfolio_sheets = {}
    for item in args.portfolio.split(","):
        if not item.strip():
            continue
        parts = item.strip().split(":")
        if len(parts) != 2:
            print(f"❌ 格式錯誤：'{item}'，請使用 'ETF代號:張數'（例如 '00878:10'）", file=sys.stderr)
            return 1
        code = clean_ticker(parts[0])
        try:
            sheets = float(parts[1])
            portfolio_sheets[code] = sheets
        except ValueError:
            print(f"❌ 張數數值錯誤：'{parts[1]}'", file=sys.stderr)
            return 1

    holdings_map = {}
    for code in portfolio_sheets:
        h = fetch_etf_holdings(code)
        holdings_map[code] = h

    res = calculate_lookthrough(portfolio_sheets, holdings_map)

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(format_lookthrough_ascii(res, limit=args.limit or 15))

    return 0


def cmd_scaffold(args) -> int:
    """處理 scaffold-model 子命令。"""
    code = clean_ticker(args.ticker)
    print(f"🔍 正在獲取 {code} 官方資料與成分股明細...")

    # 1. 抓取基本資料
    etf_info = None
    try:
        etfs = fetch_twse_etf_list()
        matches = [e for e in etfs if e["ticker"] == code]
        if matches:
            etf_info = matches[0]
    except Exception:
        pass

    # 2. 抓取成分股
    holdings = fetch_etf_holdings(code)
    if not holdings.get("constituents"):
        print(f"⚠️ 未能解析到 {code} 的成分股名單，仍建立空卡片範本。", file=sys.stderr)

    models_dir = Path(args.models_dir) if args.models_dir else None
    target_dir = scaffold_etf_model(
        ticker=code,
        repo_root=REPO_ROOT,
        holdings_data=holdings,
        etf_info=etf_info,
        custom_models_dir=models_dir,
    )

    print(f"✅ 成功為 {code} 建立 DCS 建模卡片：")
    print(f"   📂 目錄：{target_dir}")
    print("   📄 生成卡片：ticker.yml, constituents.jsonl, loop_dividend_500k.yml, interlock_yield_trap.yml")
    print("   🚀 提示：該標的已自動納入 portfolio-patrol 巡檢範圍！")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="查詢全市場 ETF 清單")
    p_list.add_argument("--filter", help="依代號、名稱、類型篩選（例如：高息、美債）")
    p_list.add_argument("--limit", type=int, help="最多顯示幾筆")
    p_list.add_argument("--json", action="store_true", help="以 JSON 格式輸出")
    p_list.set_defaults(func=cmd_list)

    # holdings
    p_holdings = subparsers.add_parser("holdings", help="查詢指定 ETF 的完整成分股與持股權重")
    p_holdings.add_argument("tickers", nargs="+", help="ETF 代號（例如 00878 00919）")
    p_holdings.add_argument("--limit", type=int, help="最多顯示前幾大成分股")
    p_holdings.add_argument("--json", action="store_true", help="以 JSON 格式輸出")
    p_holdings.set_defaults(func=cmd_holdings)

    # lookthrough
    p_lookthrough = subparsers.add_parser("lookthrough", help="投資組合穿透實質持股分析")
    p_lookthrough.add_argument(
        "--portfolio",
        required=True,
        help="持股組合字串，格式為 '代號:張數,代號:張數'（例如 '00878:10,00919:5'）",
    )
    p_lookthrough.add_argument("--limit", type=int, default=15, help="最多顯示前幾大穿透個股")
    p_lookthrough.add_argument("--json", action="store_true", help="以 JSON 格式輸出")
    p_lookthrough.set_defaults(func=cmd_lookthrough)

    # scaffold-model
    p_scaffold = subparsers.add_parser("scaffold-model", help="為指定 ETF 自動建立 DCS 建模卡片")
    p_scaffold.add_argument("ticker", help="目標 ETF 代號（例如 00878）")
    p_scaffold.add_argument("--models-dir", help="指定 models 目錄（測試用）")
    p_scaffold.set_defaults(func=cmd_scaffold)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
