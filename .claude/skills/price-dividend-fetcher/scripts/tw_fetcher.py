"""台股市場報價與配息歷史模組 (Taiwan Stock & Dividend Fetcher)。

負責 TWSE 證交所收盤與除息、TPEx 櫃買中心收盤、FinLab 配息爬蟲及交叉驗證。
"""

import json
import time
from datetime import date
from typing import Dict, List, Optional, Tuple

from fetch_common import (
    FINLAB_ROW_RE,
    FINLAB_STOCK_ROW_RE,
    FINLAB_STOCK_URL,
    FINLAB_URL,
    TWSE_EXRIGHT_URL,
    http_get,
    roc_to_iso,
    to_float,
    twse_get,
)


def parse_twse_close(data: Dict, code: str) -> Dict:
    """解析證交所收盤價資料。"""
    for t in data.get("tables", []):
        fields = t.get("fields", [])
        if "收盤價" not in fields:
            continue
        for row in t["data"]:
            if row[0] != code:
                continue
            rec = dict(zip(fields, row))
            close = to_float(rec["收盤價"])
            if close is None:
                raise ValueError(f"{code}：證交所當日無收盤價（未成交）")
            diff = to_float(rec["漲跌價差"]) or 0.0
            sign = -1 if ">-<" in rec["漲跌(+/-)"] else 1
            change = round(sign * diff, 4)
            d = data["date"]
            return {
                "ticker": f"TPE:{code}",
                "name": rec["證券名稱"],
                "price": close,
                "change": change,
                "change_pct": round(change / (close - change) * 100, 4) if close != change else None,
                "prev_close": round(close - change, 4),
                "currency": "TWD",
                "as_of": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                "price_type": "close",
                "source": "TWSE",
            }
    raise ValueError(f"{code}：證交所收盤表找不到此代號（非上市標的，或當日無資料）")


def parse_tpex_close(data: Dict, code: str) -> Dict:
    """櫃買中心上櫃股票每日收盤行情。漲跌欄為「+5.00」「-3.00」「0.00」，特殊日為文字。"""
    t = (data.get("tables") or [{}])[0]
    fields = [f.strip() for f in t.get("fields", [])]
    if data.get("stat") != "ok" or "收盤" not in fields:
        raise ValueError(f"櫃買中心回應異常：{data.get('stat')}")
    for row in t["data"]:
        if row[0] != code:
            continue
        rec = dict(zip(fields, row))
        close = to_float(rec["收盤"])
        if close is None:
            raise ValueError(f"{code}：櫃買中心當日無收盤價（未成交）")
        change = to_float(rec["漲跌"].replace("+", ""))
        d = data["date"]
        return {
            "ticker": f"TPE:{code}",
            "name": rec["名稱"],
            "price": close,
            "change": change,
            "change_pct": round(change / (close - change) * 100, 4) if change is not None and close != change else None,
            "prev_close": round(close - change, 4) if change is not None else None,
            "currency": "TWD",
            "as_of": f"{d[:4]}-{d[4:6]}-{d[6:]}",
            "price_type": "close",
            "source": "TPEx",
        }
    raise ValueError(f"{code}：櫃買中心收盤表找不到此代號（非上櫃標的，或當日無資料）")


def parse_twse_dividends(data: Dict, code: str) -> List[Dict]:
    """解析證交所除權息明細表。"""
    if data.get("stat") != "OK":
        raise ValueError(f"證交所除權息表回應異常：{data.get('stat')}")
    return [
        {"ex_date": roc_to_iso(r[0]), "amount": float(r[5]) if r[6] == "息" else None}
        for r in data["data"]
        if r[1] == code and "息" in r[6]
    ]


def get_twse_dividends(code: str, years: List[int], twse_get_fn=None) -> List[Dict]:
    """逐年查詢證交所除權息歷史。"""
    getter = twse_get_fn or twse_get
    out: List[Dict] = []
    for i, y in enumerate(years):
        if i:
            time.sleep(3)
        end = min(date(y, 12, 31), date.today())
        url = TWSE_EXRIGHT_URL.format(start=f"{y}0101", end=end.strftime("%Y%m%d"))
        out += parse_twse_dividends(json.loads(getter(url)), code)
    return out


def crosscheck(finlab_rows: List[Dict], twse_rows: List[Dict], years: List[int]) -> Dict:
    """以證交所為準，比對同年度的 FinLab 配息；金額差 > 0.005 視為不一致。"""
    ys = {str(y) for y in years}
    fin = {r["ex_date"]: r["amount"] for r in finlab_rows if r["ex_date"][:4] in ys}
    tw = {r["ex_date"]: r["amount"] for r in twse_rows}
    diffs = []
    for d in sorted(set(fin) | set(tw), reverse=True):
        if d not in tw:
            diffs.append({"ex_date": d, "finlab": fin[d], "twse": None})
        elif d not in fin:
            diffs.append({"ex_date": d, "finlab": None, "twse": tw[d]})
        elif tw[d] is not None and abs(fin[d] - tw[d]) > 0.005:
            diffs.append({"ex_date": d, "finlab": fin[d], "twse": tw[d]})
    return {"source": "TWSE", "years": sorted(years), "consistent": not diffs, "differences": diffs}


def parse_dividends(html: str, code: str) -> List[Dict]:
    """解析 FinLab ETF 配息明細頁面。"""
    rows = [
        {"ex_date": ex, "amount": float(amt), "record_date": rec.strip() or None, "pay_date": pay.strip() or None}
        for ex, amt, rec, pay in FINLAB_ROW_RE.findall(html)
    ]
    if not rows:
        raise ValueError(f"{code}：FinLab 頁面找不到配息明細（無配息紀錄，或頁面格式已變）")
    return sorted(rows, key=lambda r: r["ex_date"], reverse=True)


def parse_stock_dividends(html: str, code: str) -> List[Dict]:
    """解析 FinLab 個股頁的除息紀錄（含股票股利與所屬期間）。"""
    num = lambda v: None if v.strip() in ("", "—", "-") else float(v)
    rows = [
        {"ex_date": ex, "amount": num(cash) or 0.0, "stock_dividend": num(stock), "period": period.strip() or None}
        for ex, period, cash, stock in FINLAB_STOCK_ROW_RE.findall(html)
    ]
    if not rows:
        raise ValueError(f"{code}：FinLab 個股頁找不到除息紀錄（無配息紀錄，或頁面格式已變）")
    return sorted(rows, key=lambda r: r["ex_date"], reverse=True)


def finlab_rows(code: str, http_fn=None) -> Tuple[List[Dict], bool]:
    """回傳 (配息列, 是否來自個股頁)。ETF 有 /dividend 頁；個股沒有，改讀個股頁。"""
    getter = http_fn or http_get
    try:
        return parse_dividends(getter(FINLAB_URL.format(code=code)), code), False
    except (ValueError, RuntimeError):
        return parse_stock_dividends(getter(FINLAB_STOCK_URL.format(code=code)), code), True
