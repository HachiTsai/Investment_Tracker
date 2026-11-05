"""報價與配息共用常數與基礎網路工具模組 (Common & Networking)。

定義交易所支援白名單、來源端點、正規表示式與基礎 HTTP 連線工具。
"""

import re
import subprocess
import threading
import time
from typing import Optional, Tuple

EXCHANGES = {"TPE", "NASDAQ", "NYSE", "NYSEARCA", "NYSEAMERICAN", "TYO", "HKG"}
GF_URL = "https://www.google.com/finance/quote/{code}:{exch}?hl=en"
FINLAB_URL = "https://finlab.finance/stocks/{code}/dividend"
FINLAB_STOCK_URL = "https://finlab.finance/stocks/{code}"
TPEX_CLOSE_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?type=EW&response=json"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d&events=div"
YAHOO_UA = "Mozilla/5.0"
TWSE_EXRIGHT_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={start}&endDate={end}&response=json"
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={date}&stockNo={code}&response=json"
TWSE_CLOSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=&type=ALLBUT0999&response=json"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
TWSE_REFERER = "https://www.twse.com.tw/"

NUM = r"-?\d+\.?\d*(?:e-?\d+)?"
FINLAB_ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>(\d{4}-\d{2}-\d{2})</td>\s*<td[^>]*>([\d.]+)</td>\s*"
    r"<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*</tr>"
)
FINLAB_STOCK_ROW_RE = re.compile(
    r'<tr><th scope="row"[^>]*>(\d{4}-\d{2}-\d{2})</th><td[^>]*>([^<]*)</td>'
    r'<td[^>]*>([^<]*)</td>(?:<!--[^>]*-->)?<td[^>]*>([^<]*)</td>'
)
GF_STAT_RE = re.compile(r'class="SwQK7">([^<]*)</div><div class="dO6ijd">([^<]*)')
ROC_DATE_RE = re.compile(r"(\d+)年(\d+)月(\d+)日")


def parse_ticker(ticker: str) -> Tuple[str, str]:
    """'TPE:00882'、'00882'、'NASDAQ:AAPL' → (交易所, 代號)。"""
    t = ticker.strip().upper()
    exch, _, code = t.rpartition(":")
    exch = exch or "TPE"
    if exch not in EXCHANGES or not re.fullmatch(r"[0-9A-Z][0-9A-Z.\-]{0,9}", code):
        raise ValueError(f"不合法的代號：{ticker}（格式 交易所:代號，交易所限 {', '.join(sorted(EXCHANGES))}）")
    return exch, code


def http_get(url: str, referer: Optional[str] = None, attempts: int = 1, ua: str = UA) -> str:
    """底層 curl HTTP GET 連線包裝器。"""
    cmd = ["curl", "-sS", "-L", "-m", "40", "-A", ua, "-H", "Accept-Language: zh-TW,en;q=0.8"]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    err = ""
    for i in range(attempts):
        if i:
            time.sleep(3 * i)
        r = subprocess.run(cmd + ["-w", "\n%{http_code}", url], capture_output=True, text=True, check=False)
        if r.returncode != 0:
            err = f"連線失敗（{url}）：{r.stderr.strip() or r.returncode}"
            continue
        body, _, status = r.stdout.rpartition("\n")
        if status == "200":
            return body
        err = f"HTTP {status}（{url}）"
    raise RuntimeError(err)


# 證交所防護（WAF）在短時間連續請求時回 HTTP 307 加「因為安全性考量」頁面，跟隨轉址也拿不到資料。
# 2026-11-05 實測：連發約六成被擋，間隔 3 秒約一成。做法是放慢、被擋就等久一點再試，不偽裝瀏覽器。
TWSE_MIN_INTERVAL = 3.0          # 同一程序內任兩次證交所請求的最小間隔（秒，跨執行緒共用）
TWSE_BLOCK_BACKOFF = (10, 20, 30)  # 被 307 擋下後第 1、2、3 次重試前的等待（秒）
_twse_lock = threading.Lock()
_twse_last = [0.0]


def _twse_throttle(sleep=None, clock=time.monotonic) -> None:
    sleep = sleep or time.sleep
    with _twse_lock:
        wait = _twse_last[0] + TWSE_MIN_INTERVAL - clock()
        if wait > 0:
            sleep(wait)
        _twse_last[0] = clock()


def twse_get(url: str, http_fn=None, attempts: int = 4, sleep=None) -> str:
    """證交所請求：全程序節流（每 TWSE_MIN_INTERVAL 秒最多一次），被 307 防護擋下時依 TWSE_BLOCK_BACKOFF 退避重試，其他錯誤等 3 秒倍數。"""
    getter = http_fn or http_get
    sleep = sleep or time.sleep
    err: Optional[RuntimeError] = None
    for i in range(attempts):
        if i:
            blocked = "HTTP 307" in str(err)
            sleep(TWSE_BLOCK_BACKOFF[min(i - 1, len(TWSE_BLOCK_BACKOFF) - 1)] if blocked else 3 * i)
        _twse_throttle(sleep)
        try:
            return getter(url, TWSE_REFERER, attempts=1)
        except RuntimeError as e:
            err = e
    raise err  # type: ignore[misc]


def roc_to_iso(s: str) -> str:
    """民國日期轉 ISO 8601（例如：115年01月19日 → 2026-01-19）。"""
    m = ROC_DATE_RE.search(s)
    if not m:
        raise ValueError(f"無法解析民國日期：{s}")
    y, mo, d = (int(x) for x in m.groups())
    return f"{y + 1911:04d}-{mo:02d}-{d:02d}"


def to_float(s: str) -> Optional[float]:
    """字串轉浮點數（處理逗號分隔符）。"""
    s = s.replace(",", "").strip()
    return float(s) if re.fullmatch(r"-?\d+\.?\d*", s) else None
