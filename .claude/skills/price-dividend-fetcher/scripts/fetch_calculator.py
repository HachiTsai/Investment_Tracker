"""殖利率與股利統計計算模組 (Dividend & Yield Calculator)。

負責配息年度合計、近 12 個月合計 (TTM) 與即時殖利率計算。
"""

from datetime import date, timedelta
from typing import Dict, List, Optional


def yearly_totals(rows: List[Dict]) -> Dict[str, float]:
    """計算歷年配息加總金額。"""
    out: Dict[str, float] = {}
    for r in rows:
        y = r["ex_date"][:4]
        out[y] = round(out.get(y, 0) + r["amount"], 4)
    return dict(sorted(out.items(), reverse=True))


def ttm_total(rows: List[Dict], today: date) -> float:
    """計算近 12 個月（365 天）除息之累計配息總額。"""
    start = (today - timedelta(days=365)).isoformat()
    return round(sum(r["amount"] for r in rows if start < r["ex_date"] <= today.isoformat()), 4)


def build_dividends(
    rows: List[Dict],
    code: str,
    today: date,
    since: Optional[str] = None,
    label: Optional[str] = None,
) -> Dict:
    """組裝標準配息輸出結構。"""
    shown = [r for r in rows if not since or r["ex_date"] >= since]
    return {
        "ticker": label or f"TPE:{code}",
        "source": "FinLab",
        "count": len(shown),
        "events": shown,
        "yearly_totals": yearly_totals(rows),
        "ttm_total": ttm_total(rows, today),
        "as_of": today.isoformat(),
    }


def add_yield(result: Dict, price: Dict) -> None:
    """根據現價計算當前殖利率並注入結果。"""
    result["yield_pct"] = round(result["ttm_total"] / price["price"] * 100, 2) if price["price"] else None
    result["yield_basis"] = f"近 12 個月配息 {result['ttm_total']} ÷ {price['price_type']}價 {price['price']}"
