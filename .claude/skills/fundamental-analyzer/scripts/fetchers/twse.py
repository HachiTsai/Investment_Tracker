"""台股上市：證交所 OpenAPI 最新一季合併報表（官方）。

只有單季資料，沒有現金流與年度 ROE，故 returnOnEquity、freeCashflow 省略（不拿單季硬年化）。
"""

from typing import Any, Dict

from . import clean, http_json, ratio

BASE = "https://openapi.twse.com.tw/v1/opendata"


def num(v: Any):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def pick(rows, code: str) -> Dict[str, Any]:
    return next((r for r in rows if r.get("公司代號") == code), {})


def twse_info(inc: Dict[str, Any], bal: Dict[str, Any]) -> Dict[str, Any]:
    return clean({
        "debtToEquity": (ratio(num(bal.get("負債總計")), num(bal.get("權益總計"))) or 0) * 100 or None,
        "operatingMargins": ratio(num(inc.get("營業利益（損失）")), num(inc.get("營業收入"))),
        "netIncomeToCommon": num(inc.get("淨利（淨損）歸屬於母公司業主")),
    })


def fetch(code: str) -> Dict[str, Any]:
    inc = pick(http_json(f"{BASE}/t187ap06_L_ci"), code)
    bal = pick(http_json(f"{BASE}/t187ap07_L_ci"), code)
    return twse_info(inc, bal) if inc or bal else {}
