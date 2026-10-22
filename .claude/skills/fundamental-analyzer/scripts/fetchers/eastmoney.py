"""港股、A 股：東方財富公開資料中心（免登入）。非官方彙整源，關鍵數字需對公告原文。"""

import urllib.parse
from typing import Any, Dict, List

from . import clean, http_json, ratio

HK_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
CN_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def query(base: str, report: str, code: str, size: int = 6) -> List[Dict[str, Any]]:
    q = urllib.parse.urlencode({
        "reportName": report, "columns": "ALL", "filter": f'(SECURITY_CODE="{code}")',
        "pageSize": size, "sortColumns": "REPORT_DATE", "sortTypes": "-1",
    })
    return ((http_json(f"{base}?{q}").get("result") or {}).get("data")) or []


def annual(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """最近一筆年報（DATE_TYPE_CODE 001）。"""
    return next((r for r in rows if str(r.get("DATE_TYPE_CODE")) == "001"), {})


def hk_info(row: Dict[str, Any]) -> Dict[str, Any]:
    pct = lambda v: v / 100 if v is not None else None  # noqa: E731
    return clean({
        "returnOnEquity": pct(row.get("ROE_YEARLY")),
        "debtToEquity": (ratio(row.get("TOTAL_LIABILITIES"), row.get("TOTAL_PARENT_EQUITY")) or 0) * 100 or None,
        "operatingMargins": ratio(row.get("OPERATE_PROFIT"), row.get("OPERATE_INCOME")),
        "operatingCashflow": row.get("NETCASH_OPERATE"),
        "netIncomeToCommon": row.get("HOLDER_PROFIT"),
        "payoutRatio": row.get("DIVI_RATIO"),
        "trailingPE": row.get("PE_TTM"),
        "priceToBook": row.get("PB_TTM"),
    })


def fetch_hk(code: str) -> Dict[str, Any]:
    return hk_info(annual(query(HK_URL, "RPT_HKF10_FN_MAININDICATOR", code.zfill(5))))


def cn_info(inc: Dict[str, Any], bal: Dict[str, Any], cf: Dict[str, Any]) -> Dict[str, Any]:
    ocf, capex = cf.get("NETCASH_OPERATE"), cf.get("CONSTRUCT_LONG_ASSET")
    return clean({
        "returnOnEquity": ratio(inc.get("PARENT_NETPROFIT"), bal.get("TOTAL_EQUITY")),
        "debtToEquity": (ratio(bal.get("TOTAL_LIABILITIES"), bal.get("TOTAL_EQUITY")) or 0) * 100 or None,
        "operatingMargins": ratio(inc.get("OPERATE_PROFIT"), inc.get("TOTAL_OPERATE_INCOME")),
        "operatingCashflow": ocf,
        "freeCashflow": ocf - capex if ocf is not None and capex is not None else None,
        "netIncomeToCommon": inc.get("PARENT_NETPROFIT"),
    })


def fetch_cn(code: str) -> Dict[str, Any]:
    inc, bal, cf = (annual(query(CN_URL, f"RPT_DMSK_FN_{n}", code)) for n in ("INCOME", "BALANCE", "CASHFLOW"))
    return cn_info(inc, bal, cf)


def hk_detail(code: str, periods: int = 10) -> Dict[str, Any]:
    """港股最近一份財報（含中報、季報）的顯示用欄位，附報表期間與幣別，供成分股財報頁使用。
    hist 為最近 periods 期的累計數（新到舊），單季與年增由呼叫端推算。"""
    code = code.zfill(5)
    rows = query(HK_URL, "RPT_HKF10_FN_MAININDICATOR", code, periods)
    latest = (rows or [{}])[0]
    if not latest:
        return {}
    cur = (query(HK_URL, "RPT_HKF10_FN_INCOME", code, 1) or [{}])[0].get("CURRENCY")
    hist = [clean({
        "p": (r.get("REPORT_DATE") or "")[:10], "k": r.get("REPORT_TYPE"), "eps": r.get("BASIC_EPS"),
        "rev": r.get("OPERATE_INCOME"), "np": r.get("HOLDER_PROFIT"), "roe": r.get("ROE_YEARLY"),
        "debt": r.get("DEBT_ASSET_RATIO"), "ocf": r.get("NETCASH_OPERATE"),
    }) for r in rows]
    return clean({
        "period": (latest.get("REPORT_DATE") or "")[:10], "kind": latest.get("REPORT_TYPE"), "cur": cur,
        "org": latest.get("ORG_TYPE"), "hist": hist,
        "rev": latest.get("OPERATE_INCOME"), "np": latest.get("HOLDER_PROFIT"), "eps": latest.get("BASIC_EPS"),
        "roe": latest.get("ROE_YEARLY"), "debt": latest.get("DEBT_ASSET_RATIO"), "ocf": latest.get("NETCASH_OPERATE"),
        "payout": (latest.get("DIVI_RATIO") or 0) * 100 or None, "pe": latest.get("PE_TTM"), "pb": latest.get("PB_TTM"), "dps": latest.get("DPS_HKD"),
    })
