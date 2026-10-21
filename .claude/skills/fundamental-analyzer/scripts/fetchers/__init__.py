"""多市場財報資料層：各市場官方或公開來源 → yfinance 風格的 info dict。

評分公式（fundamental_calculator）只認 yfinance 欄位名，這裡統一輸出：
returnOnEquity（比率）、debtToEquity（百分比）、operatingMargins（比率）、freeCashflow、
operatingCashflow、netIncomeToCommon、payoutRatio、trailingPE、priceToBook。
抓不到的欄位直接省略，不用估值補；整檔失敗回 {}，由呼叫端退回 yfinance。
"""

import gzip
import json
import re
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

UA = "Mozilla/5.0 (X11; Linux x86_64) Chrome/120 Safari/537.36"
SEC_UA = "InvestmentTracker research hachi.tsai@gmail.com"


def http_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def http_bytes(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def classify(symbol: str) -> Tuple[str, str]:
    """回傳 (市場, 代號)；市場為 HK／CN／TW／US／JP／''。"""
    s = (symbol or "").strip().upper()
    if ":" in s:
        ex, code = s.split(":", 1)
        suffix = {"HKG": "HK", "SHA": "SH", "SHE": "SZ", "TPE": "TW", "TYO": "JP"}.get(ex, "US")
        s = f"{code}.{suffix}" if suffix != "US" else code
    m = re.fullmatch(r"(\w+)\.(HK|SH|SS|SZ|TW|TWO|T|JP|US)", s)
    if m:
        code, suf = m.groups()
        return {"HK": "HK", "SH": "CN", "SS": "CN", "SZ": "CN", "TW": "TW", "TWO": "TW",
                "T": "JP", "JP": "JP", "US": "US"}[suf], (code.zfill(5) if suf == "HK" else code)
    if s.isdigit():
        return ("TW", s) if len(s) in (4, 5, 6) else ("", s)
    return ("US", s) if re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", s) else ("", s)


def fetch_info(symbol: str, fetchers: Optional[Dict[str, Callable[[str], Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """依市場取財報 info；任何錯誤回 {}。"""
    market, code = classify(symbol)
    if fetchers is None:
        from . import eastmoney, edinet, sec, twse
        fetchers = {"HK": eastmoney.fetch_hk, "CN": eastmoney.fetch_cn, "TW": twse.fetch, "US": sec.fetch, "JP": edinet.fetch}
    fn = fetchers.get(market)
    if not fn:
        return {}
    try:
        return fn(code) or {}
    except Exception:
        return {}


def ratio(a: Any, b: Any) -> Optional[float]:
    try:
        return float(a) / float(b) if a is not None and b not in (None, 0, "0") else None
    except (TypeError, ValueError):
        return None


def clean(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
