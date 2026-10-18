#!/usr/bin/env python3
"""基本面財務指標與評分引擎入口 CLI (Fundamental Analyzer Facade)。

用法：
  # 1. 查詢單一個股財報指標與四象限評分
  python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py stock 2330.TW
  python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py stock NVDA --json

  # 2. 查詢單一 ETF 穿透聚合基本面與評分
  python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py etf 00878 --top 10

  # 3. 掃描全投資組合標的之加權基本面矩陣
  python3 .claude/skills/fundamental-analyzer/scripts/analyzer_cli.py portfolio
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]

from fundamental_calculator import calculate_stock_fundamentals  # noqa: E402
from lookthrough_fundamentals import aggregate_etf_fundamentals  # noqa: E402


def format_stock_ascii(res: dict) -> str:
    """格式化個股財報體檢 ASCII 儀表板。"""
    scores = res.get("scores", {})
    lines = [
        "=" * 68,
        f"📊 個股財務體檢與多維評分報告：【{res.get('symbol')}】",
        "=" * 68,
        f"  💎 綜合財務分 (netScore)  : {scores.get('netScore', 0):>5} / 100",
        f"  🛡️ 股利持續分 (divScore)  : {scores.get('divScore', 0):>5} / 100",
        f"  🎯 估值邊際分 (valScore)  : {scores.get('valScore', 0):>5} / 100",
        f"  ⚖️ 摩擦阻力分 (fricScore) : {scores.get('fricScore', 0):>5} / 100",
        "-" * 68,
        "【核心財務指標明細】：",
        f"  • 股東權益報酬率 (ROE)  : {res.get('roe', '-')}%",
        f"  • 負債權益比 (D/E)     : {res.get('debt_to_equity', '-')}%",
        f"  • 營業利益率 (OpMargin): {res.get('operating_margin', '-')}%",
        f"  • 盈餘配發率 (Payout)  : {res.get('payout_ratio', '-')}%",
        f"  • FCF 股利覆蓋倍數     : {res.get('fcf_coverage', '-')} 倍",
        f"  • 本益比 (P/E)         : {res.get('pe', '-')}",
        f"  • 股價淨值比 (P/B)     : {res.get('pb', '-')}",
        f"  • 當前殖利率 (Yield)   : {res.get('yield_pct', '-')}%",
        "=" * 68,
    ]
    return "\n".join(lines)


def format_etf_ascii(res: dict) -> str:
    """格式化 ETF 穿透聚合基本面 ASCII 儀表板。"""
    scores = res.get("scores", {})
    lines = [
        "=" * 72,
        f"🏛️ ETF 穿透加權基本面評分：【{res.get('etf_id')}】",
        "=" * 72,
        f"  覆蓋成分股檔數: 前 {res.get('covered_holdings_count')} 大重倉 ｜ 覆蓋總權重: {res.get('total_weight_covered_pct')}%",
        f"  加權 ROE: {res.get('weighted_roe', '-')}%",
        "-" * 72,
        "【穿透聚合四象限評分】：",
        f"  • 綜合財務健康分 (netScore)  : {scores.get('netScore', 0):>5} / 100",
        f"  • 股利可持續性分 (divScore)  : {scores.get('divScore', 0):>5} / 100",
        f"  • 估值與安全邊際 (valScore)  : {scores.get('valScore', 0):>5} / 100",
        f"  • 摩擦阻力評分 (fricScore)   : {scores.get('fricScore', 0):>5} / 100",
        "-" * 72,
        f"{'個股代號':<10} {'個股名稱':<12} {'權重%':<8} {'ROE%':<8} {'PE':<8} {'財務分':<8} {'股利分':<8}",
        "-" * 72,
    ]
    for h in res.get("holdings_breakdown", []):
        h_scores = h.get("scores", {})
        ticker = h.get("ticker", "")
        name = h.get("name", "")[:6]
        w = f"{h.get('weight_pct', 0.0):.2f}%"
        roe = f"{h.get('roe', '-')}%" if h.get("roe") is not None else "-"
        pe = f"{h.get('pe', '-')}" if h.get("pe") is not None else "-"
        net_s = f"{h_scores.get('netScore', '-')}"
        div_s = f"{h_scores.get('divScore', '-')}"
        lines.append(f"{ticker:<10} {name:<12} {w:<8} {roe:<8} {pe:<8} {net_s:<8} {div_s:<8}")
    lines.append("=" * 72)
    return "\n".join(lines)


def cmd_stock(args) -> int:
    """處理 stock 命令。"""
    res = calculate_stock_fundamentals(args.symbol)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(format_stock_ascii(res))
    return 0


def cmd_etf(args) -> int:
    """處理 etf 命令。"""
    models_dir = Path(args.models_dir) if args.models_dir else REPO_ROOT
    res = aggregate_etf_fundamentals(args.etf_id, top_n=args.top, repo_root=models_dir)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(format_etf_ascii(res))
    return 0


def cmd_portfolio(args) -> int:
    """處理 portfolio 命令，掃描全標的。"""
    models_dir = Path(args.models_dir) if args.models_dir else REPO_ROOT / "models"
    if not models_dir.exists():
        print(f"❌ 找不到目錄：{models_dir}", file=sys.stderr)
        return 1

    etf_dirs = [d.name for d in sorted(models_dir.iterdir()) if d.is_dir()]
    print("=" * 80)
    print(f"📊 投資組合全標的基本面穿透評分矩陣（涵蓋 {len(etf_dirs)} 檔標的）")
    print("=" * 80)
    print(f"{'標的代號':<10} {'資產類型':<8} {'加權ROE':<10} {'netScore':<10} {'divScore':<10} {'valScore':<10} {'fricScore':<10}")
    print("-" * 80)

    for ticker in etf_dirs:
        res = aggregate_etf_fundamentals(ticker, top_n=args.top, repo_root=REPO_ROOT)
        sc = res.get("scores", {})
        cat = "債券ETF" if res.get("is_bond") else "股票ETF"
        roe_str = f"{res.get('weighted_roe', '-')}%" if res.get("weighted_roe") is not None else "-"
        print(
            f"{ticker:<10} {cat:<8} {roe_str:<10} "
            f"{sc.get('netScore', 0):<10.1f} {sc.get('divScore', 0):<10.1f} "
            f"{sc.get('valScore', 0):<10.1f} {sc.get('fricScore', 0):<10.1f}"
        )
    print("=" * 80)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="基本面財務指標與評分引擎 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # stock
    p_stock = subparsers.add_parser("stock", help="查詢單一個股財報體檢與評分")
    p_stock.add_argument("symbol", help="股票代號（例如 2330.TW, NVDA, 7203.T）")
    p_stock.add_argument("--json", action="store_true", help="輸出 JSON 格式")
    p_stock.set_defaults(func=cmd_stock)

    # etf
    p_etf = subparsers.add_parser("etf", help="查詢 ETF 穿透聚合基本面與評分")
    p_etf.add_argument("etf_id", help="ETF 代號（例如 00878, 0050）")
    p_etf.add_argument("--top", type=int, default=10, help="計算前 N 大重倉成分股（預設 10）")
    p_etf.add_argument("--models-dir", help="指定 REPO 根目錄")
    p_etf.add_argument("--json", action="store_true", help="輸出 JSON 格式")
    p_etf.set_defaults(func=cmd_etf)

    # portfolio
    p_port = subparsers.add_parser("portfolio", help="全投資組合標的基本面評分矩陣")
    p_port.add_argument("--top", type=int, default=10, help="每檔 ETF 計算前 N 大重倉股")
    p_port.add_argument("--models-dir", help="指定 models 目錄")
    p_port.set_defaults(func=cmd_portfolio)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
