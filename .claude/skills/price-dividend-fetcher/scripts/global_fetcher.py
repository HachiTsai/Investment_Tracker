"""海外與跨市場報價與配息模組 (Global & Yahoo/Google Finance Fetcher)。

負責 Google Finance 即時報價解析、Yahoo Finance 報價與還原配息歷程抓取。
"""

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fetch_common import (
    GF_STAT_RE,
    NUM,
    YAHOO_UA,
    YAHOO_URL,
    http_get,
)


def parse_price(html: str, exch: str, code: str) -> Dict:
    """解析 Google Finance 頁面報價（代號、幣別、現價、漲跌、前收與除息摘要）。"""
    rx = re.compile(
        rf'\["{re.escape(code)}","{exch}"\],"([^"]*)",\d+,"([A-Z]{{3}})",'
        rf"\[({NUM}),({NUM}),({NUM}),\d+,\d+,\d+\],null,({NUM}),[^\]]{{0,80}}?\[(\d{{10}})\]"
    )
    m = rx.search(html)
    if not m:
        raise ValueError(f"{exch}:{code}：Google Finance 頁面找不到報價（代號錯誤，或頁面格式已變，見 references/sources.md）")
    name, cur, price, change, pct, prev, ts = m.groups()
    out = {
        "ticker": f"{exch}:{code}",
        "name": json.loads(f'"{name}"'),
        "price": float(price),
        "change": round(float(change), 4),
        "change_pct": round(float(pct), 4),
        "prev_close": float(prev),
        "currency": cur,
        "as_of": datetime.fromtimestamp(int(ts), timezone.utc).isoformat(timespec="seconds"),
        "price_type": "last",
        "source": "Google Finance",
    }
    div = {k: v for k, v in GF_STAT_RE.findall(html) if "ividend" in k}
    if div:
        out["dividend_summary"] = div
    return out


def yahoo_symbol(exch: str, code: str) -> str:
    """將標準代號轉換為 Yahoo Finance 代號格式。"""
    if exch == "TPE":
        return f"{code}.TW"
    if exch == "TYO":
        return f"{code}.T"
    if exch == "HKG":
        return f"{code.lstrip('0').zfill(4)}.HK"
    return code.replace(".", "-")


def get_yahoo(exch: str, code: str, rng: str, http_fn=None) -> Dict:
    """抓取 Yahoo Finance Chart API 資料（支援台股 .TW/.TWO 自動備援重試）。"""
    getter = http_fn or http_get
    syms = [f"{code}.TW", f"{code}.TWO"] if exch == "TPE" else [yahoo_symbol(exch, code)]
    err: Optional[RuntimeError] = None
    for sym in syms:
        try:
            return json.loads(getter(YAHOO_URL.format(sym=sym, rng=rng), ua=YAHOO_UA))
        except RuntimeError as e:
            err = e
    raise err  # type: ignore[misc]


def yahoo_result(data: Dict, exch: str, code: str) -> Dict:
    """自 Yahoo Finance 回應中提取 result 區塊。"""
    chart = data.get("chart") or {}
    if chart.get("error") or not chart.get("result"):
        desc = (chart.get("error") or {}).get("description", "沒有資料")
        raise ValueError(f"{exch}:{code}：Yahoo Finance {desc}")
    return chart["result"][0]


def parse_yahoo_price(data: Dict, exch: str, code: str) -> Dict:
    """解析 Yahoo Finance 現價、前收與漲跌幅。"""
    r = yahoo_result(data, exch, code)
    meta = r["meta"]
    off = meta.get("gmtoffset", 0)
    local = lambda ts: datetime.fromtimestamp(ts + off, timezone.utc).date()
    price, now = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    if price is None or now is None:
        raise ValueError(f"{exch}:{code}：Yahoo Finance 回應缺少現價")
    bars = zip(r.get("timestamp") or [], r["indicators"]["quote"][0].get("close") or [])
    prevs = [c for ts, c in bars if c is not None and local(ts) < local(now)]
    if not prevs:
        raise ValueError(f"{exch}:{code}：Yahoo Finance 找不到前一日收盤")
    prev = prevs[-1]
    change = price - prev
    return {
        "ticker": f"{exch}:{code}",
        "name": meta.get("longName") or meta.get("shortName"),
        "price": round(price, 4),
        "change": round(change, 4),
        "change_pct": round(change / prev * 100, 4) if prev else None,
        "prev_close": round(prev, 4),
        "currency": meta.get("currency"),
        "as_of": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
        "price_type": "last",
        "source": "Yahoo Finance",
    }


def parse_yahoo_dividends(data: Dict, exch: str, code: str) -> Tuple[List[Dict], Optional[str]]:
    """解析 Yahoo Finance 除息歷史事件。"""
    r = yahoo_result(data, exch, code)
    events = (r.get("events") or {}).get("dividends") or {}
    rows = [
        {"ex_date": datetime.fromtimestamp(e["date"], timezone.utc).date().isoformat(), "amount": round(e["amount"], 6)}
        for e in events.values()
    ]
    return sorted(rows, key=lambda x: x["ex_date"], reverse=True), r["meta"].get("currency")
