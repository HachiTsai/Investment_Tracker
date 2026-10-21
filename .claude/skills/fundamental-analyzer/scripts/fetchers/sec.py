"""美股：SEC EDGAR XBRL companyfacts（官方），取最近一份 10-K 年度數字。"""

from datetime import date
from typing import Any, Dict, Optional

from . import SEC_UA, clean, http_json, ratio

HDR = {"User-Agent": SEC_UA}


def full_year(row: Dict[str, Any]) -> bool:
    """流量科目要涵蓋一整年（排除 10-K 內夾帶的季度值）；時點科目沒有 start，直接通過。"""
    if not row.get("start"):
        return True
    days = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
    return 330 <= days <= 380


def latest_annual(facts: Dict[str, Any], *tags: str, unit: str = "USD") -> Optional[float]:
    """候選 us-gaap 標籤中，取 10-K 全年數字結束日最新者（舊標籤停用後會留下過期值）。"""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    best = None
    for tag in tags:
        rows = [r for r in (gaap.get(tag, {}).get("units", {}).get(unit) or [])
                if r.get("form") == "10-K" and r.get("fp") == "FY" and r.get("end") and full_year(r)]
        if rows:
            top = max(rows, key=lambda r: r["end"])
            if best is None or top["end"] > best["end"]:
                best = top
    return best.get("val") if best else None


def sec_info(facts: Dict[str, Any]) -> Dict[str, Any]:
    ni = latest_annual(facts, "NetIncomeLoss")
    eq = latest_annual(facts, "StockholdersEquity")
    liab = latest_annual(facts, "Liabilities")
    rev = latest_annual(facts, "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet")
    op = latest_annual(facts, "OperatingIncomeLoss")
    ocf = latest_annual(facts, "NetCashProvidedByUsedInOperatingActivities")
    capex = latest_annual(facts, "PaymentsToAcquirePropertyPlantAndEquipment")
    div = latest_annual(facts, "PaymentsOfDividends", "PaymentsOfDividendsCommonStock")
    return clean({
        "returnOnEquity": ratio(ni, eq),
        "debtToEquity": (ratio(liab, eq) or 0) * 100 or None,
        "operatingMargins": ratio(op, rev),
        "operatingCashflow": ocf,
        "freeCashflow": ocf - capex if ocf is not None and capex is not None else None,
        "netIncomeToCommon": ni,
        "payoutRatio": ratio(div, ni),
    })


def fetch(ticker: str) -> Dict[str, Any]:
    table = http_json("https://www.sec.gov/files/company_tickers.json", HDR)
    cik = next((v["cik_str"] for v in table.values() if v["ticker"] == ticker.replace(".", "-")), None)
    if cik is None:
        return {}
    return sec_info(http_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", HDR))
