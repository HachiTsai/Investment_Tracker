"""外幣對新台幣的匯率，供港股、美股與日股頁面換算台幣參考值（只用標準函式庫）。

來源是 Google Finance 外匯報價頁（例如 https://www.google.com/finance/quote/USD-TWD），與個股股價同一個來源。
成交價與報價時間寫進 pool.json 的 fx 欄位，頁面也會註明。不讀 Investment_Tracker_Core 的 Exchange_Rates。
抓不到就拋出 RuntimeError，由呼叫端中止且不寫任何檔案，不會悄悄沿用舊匯率。
"""
import re
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

FX_URL = "https://www.google.com/finance/quote/{pair}?hl=en"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NUM = r"\d+(?:\.\d+)?(?:e-?\d+)?"
SOURCE = "Google Finance"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def parse_rate(html: str, currency: str) -> Dict[str, Any]:
    """從外匯頁取出 1 單位外幣對新台幣的成交價與報價時間（UTC，ISO 格式）。找不到或數值離譜就拋出 ValueError。"""
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError(f"幣別代碼不合法：{currency!r}")
    pair = f"{currency}-TWD"
    rx = re.compile(rf'"{pair}","{currency} / TWD",({NUM}),.{{0,400}}?\[(\d{{10}})\]')
    m = rx.search(html)
    if not m:
        raise ValueError(f"{pair}：Google Finance 頁面找不到匯率（頁面格式可能已變）")
    rate = float(m.group(1))
    if not 0 < rate < 1000:
        raise ValueError(f"{pair}：匯率 {rate} 超出合理範圍")
    as_of = datetime.fromtimestamp(int(m.group(2)), timezone.utc).isoformat(timespec="seconds")
    return dict(currency=currency, rate=rate, as_of=as_of, source=SOURCE)


def fetch_rate(currency: str, get: Callable[[str], str] = _get, retries: int = 1, wait: float = 3.0) -> Dict[str, Any]:
    """currency 對新台幣的匯率（1 單位外幣等於幾元台幣）；台幣本身為 1。
    網路錯誤（含逾時）重試 retries 次，仍失敗就拋出 RuntimeError；頁面解析失敗直接拋出 ValueError，不重試。"""
    if currency == "TWD":
        return dict(currency="TWD", rate=1.0, as_of=None, source="本位幣")
    url = FX_URL.format(pair=f"{currency}-TWD")
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            html = get(url)
        except OSError as e:  # URLError 與逾時都是 OSError 的子類
            last = e
            if attempt < retries:
                time.sleep(wait)
            continue
        return parse_rate(html, currency)
    raise RuntimeError(f"{currency}-TWD 匯率抓取失敗：{last}")
