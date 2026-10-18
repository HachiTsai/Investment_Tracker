"""投資組合穿透持股與實質曝險分析模組 (Portfolio Look-Through Calculator)。

分析個人多檔 ETF 組合背後的實質個股總持股金額、總佔比與集中度風險。
"""

from typing import Any, Dict, List, Optional


def calculate_lookthrough(
    portfolio_sheets: Dict[str, float],
    holdings_map: Dict[str, Dict[str, Any]],
    price_map: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """計算投資組合的穿透實質個股持股。

    Args:
        portfolio_sheets: 例如 {"00878": 10.0, "00919": 5.0} (單位: 張，1張=1000股)
        holdings_map: 各 ETF 的成分股字典 {"00878": {"constituents": [...]}}
        price_map: 各 ETF 市價 {"00878": 22.5, "00919": 24.0}（若無則依權重等比推估）
    """
    prices = price_map or {}
    etf_values = {}
    total_portfolio_value = 0.0

    # 1. 計算各 ETF 總市值
    for ticker, sheets in portfolio_sheets.items():
        price = prices.get(ticker, 20.0)  # 預設基準價
        val = sheets * 1000.0 * price
        etf_values[ticker] = val
        total_portfolio_value += val

    if total_portfolio_value <= 0:
        total_portfolio_value = 1.0

    # 2. 彙總穿透至各底層個股
    stock_aggregates: Dict[str, Dict[str, Any]] = {}

    for etf_code, etf_val in etf_values.items():
        h_data = holdings_map.get(etf_code, {})
        constituents = h_data.get("constituents", [])

        for c in constituents:
            sym = c["symbol"]
            name = c["name"]
            weight_pct = c["weight_pct"]
            eff_val = etf_val * (weight_pct / 100.0)

            if sym not in stock_aggregates:
                stock_aggregates[sym] = {
                    "symbol": sym,
                    "name": name,
                    "effective_value": 0.0,
                    "contributions": {},
                }

            stock_aggregates[sym]["effective_value"] += eff_val
            stock_aggregates[sym]["contributions"][etf_code] = round(eff_val, 2)

    # 3. 排序與計算佔比
    sorted_stocks = sorted(
        stock_aggregates.values(),
        key=lambda x: x["effective_value"],
        reverse=True,
    )

    results = []
    concentration_top5 = 0.0
    alerts = []

    for idx, s in enumerate(sorted_stocks, 1):
        eff_val = s["effective_value"]
        pct = (eff_val / total_portfolio_value) * 100.0
        if idx <= 5:
            concentration_top5 += pct

        # 集中度風控門檻：單一個股穿透佔比 > 15% 警報
        if pct >= 15.0:
            alerts.append(f"⚠️ 個股集中度偏高：{s['name']}({s['symbol']}) 實質佔總投資組合 {pct:.1f}%")

        results.append({
            "rank": idx,
            "symbol": s["symbol"],
            "name": s["name"],
            "effective_value": round(eff_val, 2),
            "effective_pct": round(pct, 2),
            "contributions": s["contributions"],
        })

    return {
        "total_portfolio_value": round(total_portfolio_value, 2),
        "top5_concentration_pct": round(concentration_top5, 2),
        "total_underlying_stocks": len(results),
        "alerts": alerts,
        "stocks": results,
    }


def format_lookthrough_ascii(result: Dict[str, Any], limit: int = 15) -> str:
    """產出穿透透視 ASCII 報告。"""
    total_val = result["total_portfolio_value"]
    top5 = result["top5_concentration_pct"]
    stock_count = result["total_underlying_stocks"]

    lines = []
    lines.append("=" * 80)
    lines.append(f"🔍 投資組合實質穿透持股報告 ｜ 總穿透市值約：{total_val:,.0f} TWD")
    lines.append(f"📊 前 5 大集中度：{top5:.1f}% ｜ 穿透個股總數：{stock_count} 檔")
    lines.append("-" * 80)

    alerts = result.get("alerts", [])
    if alerts:
        for a in alerts:
            lines.append(f"  {a}")
        lines.append("-" * 80)

    lines.append(f"{'排名':<6} {'個股代號':<12} {'個股名稱':<16} {'穿透實質金額(TWD)':<18} {'佔比(%)':<10} {'來源 ETF'}")
    lines.append("-" * 80)

    for item in result["stocks"][:limit]:
        rank = item["rank"]
        sym = item["symbol"]
        name = item["name"][:12]
        val_str = f"{item['effective_value']:,.0f}"
        pct_str = f"{item['effective_pct']:.2f}%"
        contribs = ", ".join(f"{k}:{v:,.0f}" for k, v in item["contributions"].items())
        lines.append(f"{rank:<6} {sym:<12} {name:<16} {val_str:<18} {pct_str:<10} {contribs}")

    lines.append("=" * 80)
    return "\n".join(lines)
