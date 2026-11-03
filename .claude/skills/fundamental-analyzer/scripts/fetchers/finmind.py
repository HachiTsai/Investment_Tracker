"""台股財報：FinMind 開放資料（現金流量表、近四季 ROE），上市與上櫃皆可。

現金流量表為累季值，換算成近四季合計；損益表為單季值。匿名呼叫有頻率限制，失敗回 {}。
"""

import datetime
from typing import Any, Dict, List, Optional

from . import clean, finmind_detail, ratio


def load(dataset: str, code: str, start: str) -> Dict[str, Dict[str, float]]:
    """回傳 {type: {date: value}}。

    走 finmind_detail.get：有 FINMIND_TOKEN 就帶上（提高頻率上限）、同一請求快取 6 小時，避免每次巡檢重複耗用配額。
    只嘗試一次：配額用盡（402）時退避重試無效，會拖慢整輪巡檢；失敗由 tw.fetch 接住並退回其他來源。
    """
    return finmind_detail.series(finmind_detail.get(dataset, code, start, attempts=1))


def ttm_from_cumulative(series: Dict[str, float]) -> Optional[float]:
    """累季值 → 近四季合計：本期累季 + 去年全年 − 去年同期累季；缺任一值回 None。"""
    if not series:
        return None
    latest = max(series)
    year, md = int(latest[:4]), latest[5:]
    cur = series[latest]
    if md == "12-31":
        return cur
    prior_fy, prior_same = series.get(f"{year - 1}-12-31"), series.get(f"{year - 1}-{md}")
    if prior_fy is None or prior_same is None:
        return None
    return cur + prior_fy - prior_same


def last_four(series: Dict[str, float]) -> Optional[float]:
    dates = sorted(series)[-4:]
    return sum(series[d] for d in dates) if len(dates) == 4 else None


def finmind_info(cf: Dict[str, Dict[str, float]], inc: Dict[str, Dict[str, float]],
                 bs: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    ocf = ttm_from_cumulative(cf.get("CashFlowsFromOperatingActivities", {}))
    capex = ttm_from_cumulative(cf.get("PropertyAndPlantAndEquipment", {}))
    ni = last_four(inc.get("EquityAttributableToOwnersOfParent", {}))
    eq: List[float] = [bs["EquityAttributableToOwnersOfParent"][d]
                       for d in sorted(bs.get("EquityAttributableToOwnersOfParent", {}))]
    avg_eq = (eq[-1] + eq[-5]) / 2 if len(eq) >= 5 else (eq[-1] if eq else None)
    op, rev = last_four(inc.get("OperatingIncome", {})), last_four(inc.get("Revenue", {}))
    liab, tot_eq = bs.get("Liabilities", {}), bs.get("Equity", {})
    de = ratio(liab[max(liab)], tot_eq[max(tot_eq)]) if liab and tot_eq else None
    return clean({
        "returnOnEquity": ratio(ni, avg_eq),
        "operatingCashflow": ocf,
        "freeCashflow": ocf - abs(capex) if ocf is not None and capex is not None else None,
        "operatingMargins": ratio(op, rev),
        "debtToEquity": de * 100 if de is not None else None,
        "netIncomeToCommon": ni,
    })


def fetch(code: str) -> Dict[str, Any]:
    start = f"{datetime.date.today().year - 3}-01-01"
    cf = load("TaiwanStockCashFlowsStatement", code, start)
    if not cf:
        return {}
    inc = load("TaiwanStockFinancialStatements", code, start)
    bs = load("TaiwanStockBalanceSheet", code, start)
    return finmind_info(cf, inc, bs)
