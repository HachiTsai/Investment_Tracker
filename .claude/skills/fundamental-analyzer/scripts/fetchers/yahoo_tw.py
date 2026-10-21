"""台股第二來源：Yahoo 股市現金流量表頁（非官方，資料嵌在網頁 JSON）。

只補營業現金流與自由現金流（近四季合計）；網頁改版或被擋回 {}。
"""

import re
from typing import Any, Dict, List

from . import clean, http_bytes

URL = "https://tw.stock.yahoo.com/quote/{sym}/cash-flow-statement"
ROW = re.compile(r'\{"symbol":"[^"]+","date":"(\d{4}-\d{2})-\d{2}[^{}]*?"operatingCashFlow":"([^"]+)"[^{}]*?"freeCashFlow":"([^"]+)"[^{}]*?\}')


def parse(html: str) -> List[tuple]:
    return [(m.group(1), float(m.group(2)), float(m.group(3))) for m in ROW.finditer(html)]


def yahoo_info(rows: List[tuple]) -> Dict[str, Any]:
    """前四列須為連續四季（月份相差 3）才合計，避免混入年度列。"""
    q = rows[:4]
    if len(q) < 4:
        return {}
    months = [int(d[5:7]) + 12 * int(d[:4]) for d, _, _ in q]
    if any(months[i] - months[i + 1] != 3 for i in range(3)):
        return {}
    return clean({"operatingCashflow": sum(r[1] for r in q), "freeCashflow": sum(r[2] for r in q)})


def fetch(code: str) -> Dict[str, Any]:
    for suffix in ("TW", "TWO"):
        html = http_bytes(URL.format(sym=f"{code}.{suffix}"), timeout=30).decode("utf-8", "ignore")
        info = yahoo_info(parse(html))
        if info:
            return info
    return {}
