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

  # 5. 同步成分股至 Google Sheets
  python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py sync-sheets
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

# 將當前腳本目錄加入 sys.path 確保模組載入正常
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

REPO_ROOT = SCRIPT_DIR.parents[3]

from etf_holdings_scraper import clean_ticker, fetch_etf_holdings, format_holdings_ascii  # noqa: E402
from etf_list_scraper import fetch_twse_etf_list, filter_etfs, format_etf_list_ascii  # noqa: E402
from etf_lookthrough import calculate_lookthrough, format_lookthrough_ascii  # noqa: E402
import etf_market  # noqa: E402
from etf_model_scaffolder import scaffold_etf_model  # noqa: E402
from etf_sheets_sync import DEFAULT_SHEET_ID, run_sync_pipeline  # noqa: E402


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

    tier = getattr(args, "tier", "pool")
    models_dir = Path(args.models_dir) if args.models_dir else None
    target_dir = scaffold_etf_model(
        ticker=code,
        repo_root=REPO_ROOT,
        holdings_data=holdings,
        etf_info=etf_info,
        custom_models_dir=models_dir,
        tier=tier,
    )

    print(f"✅ 成功為 {code} 建立標的建模卡片：")
    print(f"   📂 目錄：{target_dir}")
    print("   📄 生成卡片：ticker.yml, constituents.jsonl, loop_dividend_500k.yml, interlock_yield_trap.yml")
    if tier == "core":
        print("   🚀 提示：該標的已納入「核心團隊」，將參與 portfolio-patrol 與每日戰報巡檢！")
    else:
        print("   📦 提示：該標的已納入「資料池」（預設不參與每日巡檢）。若欲納入核心團隊，請執行：")
        print(f"      python3 .claude/skills/tw-etf-fetcher/scripts/etf_fetcher.py set-tier {code} core")
    return 0


def cmd_set_tier(args) -> int:
    """處理 set-tier 子命令：調整標的分級 (core: 核心團隊 / pool: 資料池)。"""
    code = clean_ticker(args.ticker)
    new_tier = args.tier.lower()
    if new_tier not in ("core", "pool"):
        print(f"❌ 無效的分級 '{args.tier}'，僅支援 'core'（核心團隊）或 'pool'（資料池）。", file=sys.stderr)
        return 1

    models_dir = Path(args.models_dir) if getattr(args, "models_dir", None) else (REPO_ROOT / "models")
    ticker_file = models_dir / code / "cards" / "ticker.yml"
    if not ticker_file.exists():
        print(f"❌ 找不到標的卡片：{ticker_file}", file=sys.stderr)
        return 1

    content = ticker_file.read_text(encoding="utf-8")
    lines = content.splitlines()
    has_tier = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("tier:"):
            new_lines.append(f"tier: {new_tier}")
            has_tier = True
        else:
            new_lines.append(line)

    if not has_tier:
        idx_to_insert = len(new_lines)
        for i, line in enumerate(new_lines):
            if line.strip().startswith("full_name:") or line.strip().startswith("title:"):
                idx_to_insert = i + 1
                break
        new_lines.insert(idx_to_insert, f"tier: {new_tier}")

    ticker_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    label = "核心團隊（將參與每日巡檢與戰報）" if new_tier == "core" else "資料池（僅供穿透分析，不參與每日巡檢）"
    print(f"✅ 已成功將 {code} 的分級調整為：{new_tier}（{label}）")
    return 0


def check_gate(
    etf_count: int,
    constituents_count: int,
    min_etfs: int = etf_market.Gate().min_summary_rows,
    min_constituents: int = etf_market.Gate().min_constituent_rows,
) -> Tuple[bool, List[str]]:
    """排程健康門檻檢核（全市場）：ETF_Summary 列數與 ETF_Constituents 列數的下限，門檻值來自 etf_market.Gate。"""
    reasons = etf_market.gate_reasons([
        ("ETF_Summary 列數不足", etf_count, min_etfs, "min"),
        ("ETF_Constituents 列數不足", constituents_count, min_constituents, "min"),
    ])
    return len(reasons) == 0, reasons


def cmd_sync_sheets(args) -> int:
    """處理 sync-sheets 子命令。"""
    print("🚀 啟動全市場 ETF 成分股與摘要 Google Sheets 雲端同步...")
    models_dir = Path(args.models_dir) if args.models_dir else REPO_ROOT / "models"
    output_dir = Path(args.output_dir) if args.output_dir else REPO_ROOT / "reports"
    include_pool = not getattr(args, "no_pool", False)
    delay = getattr(args, "delay", 0.1)

    def _prog(code, idx, total):
        if idx == total:
            print(f"   [{idx}/{total}] 正在聚合全市場資料池成分股：{code}... 完成！\n   ⚡ 正在計算穿透加權 ROE 與評分矩陣...", flush=True)
        else:
            print(f"   [{idx}/{total}] 正在聚合全市場資料池成分股：{code}...", end="\r", flush=True)

    res = run_sync_pipeline(
        models_dir=models_dir,
        output_dir=output_dir,
        sheet_id=args.sheet_id,
        export_only=args.export_only,
        dry_run=args.dry_run,
        include_market_pool=include_pool,
        delay=delay,
        progress_callback=_prog if include_pool else None,
    )
    if include_pool:
        print()
    if res["status"] == "success":
        print(f"✅ 成功處理 {res['etf_count']} 檔 ETF，共 {res['constituents_count']} 筆底層成分股紀錄。")
        print(f"   📁 摘要 CSV：{res['summary_csv']}")
        print(f"   📁 成分股 CSV：{res['constituents_csv']}")
        if res.get("synced"):
            print(f"   ☁️ 雲端同步成功：試算表 ID [{res['sheet_id']}]")
        else:
            print(f"   ℹ️ {res.get('message', '')}")
        if getattr(args, "gate", False):
            min_e = getattr(args, "min_etfs", None)
            min_c = getattr(args, "min_constituents", None)
            gate_args = {}
            if min_e is not None:
                gate_args["min_etfs"] = min_e
            elif getattr(args, "no_pool", False):
                gate_args["min_etfs"] = 40
            if min_c is not None:
                gate_args["min_constituents"] = min_c
            elif getattr(args, "no_pool", False):
                gate_args["min_constituents"] = 5000
            ok, reasons = check_gate(res.get("etf_count", 0), res.get("constituents_count", 0), **gate_args)
            if not ok:
                print(f"❌ [Gate Failed] {'; '.join(reasons)}", file=sys.stderr)
                return 1
        return 0
    else:
        print(f"❌ 同步失敗：{res.get('message', '未知錯誤')}", file=sys.stderr)
        return 1


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
    p_scaffold = subparsers.add_parser("scaffold-model", help="為指定 ETF 自動建立標的建模卡片")
    p_scaffold.add_argument("ticker", help="目標 ETF 代號（例如 00878）")
    p_scaffold.add_argument(
        "--tier",
        choices=["core", "pool"],
        default="pool",
        help="標的分級（core: 核心團隊 / pool: 資料池，預設 pool）",
    )
    p_scaffold.add_argument("--models-dir", help="指定 models 目錄（測試用）")
    p_scaffold.set_defaults(func=cmd_scaffold)

    # set-tier
    p_settier = subparsers.add_parser("set-tier", help="調整標的分級（core: 核心團隊 / pool: 資料池）")
    p_settier.add_argument("ticker", help="目標標的代號（例如 00878）")
    p_settier.add_argument("tier", choices=["core", "pool"], help="目標分級（core: 核心團隊 / pool: 資料池）")
    p_settier.add_argument("--models-dir", help="指定 models 目錄（測試用）")
    p_settier.set_defaults(func=cmd_set_tier)

    # sync-sheets
    p_sync = subparsers.add_parser("sync-sheets", help="將全市場 ETF 成分股與摘要同步至 Google Sheets")
    p_sync.add_argument("--sheet-id", default=DEFAULT_SHEET_ID, help="目標 Google Sheet ID")
    p_sync.add_argument("--models-dir", help="指定 models 目錄（預設 REPO/models）")
    p_sync.add_argument("--output-dir", help="指定 CSV 輸出目錄（預設 REPO/reports）")
    p_sync.add_argument("--export-only", action="store_true", help="僅產出本機 CSV，不上傳雲端")
    p_sync.add_argument("--dry-run", action="store_true", help="模擬執行，不變更雲端試算表")
    p_sync.add_argument("--no-pool", action="store_true", help="僅同步 models/ 核心卡片，不包含全市場資料池")
    p_sync.add_argument("--delay", type=float, default=0.1, help="爬取全市場資料池時的延遲秒數（預設 0.1 秒）")
    p_sync.add_argument("--min-etfs", type=int, help="自訂 Gate 門檻最低 ETF 檔數")
    p_sync.add_argument("--min-constituents", type=int, help="自訂 Gate 門檻最低成分股筆數")
    p_sync.add_argument("--gate", action="store_true", help="啟用排程健康檢查門檻判定（全市場：ETF_Summary >= 200 且 ETF_Constituents >= 10000）")
    p_sync.set_defaults(func=cmd_sync_sheets)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
