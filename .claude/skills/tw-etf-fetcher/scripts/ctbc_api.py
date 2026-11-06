"""中信投信 API 的共用請求層：送出前節流、同一程序只取一次 token、被防護攔截時不重試。

背景（2026-11-06）：00882 的 AuthToken 請求回 HTTP 403，回應是網站防護（Incapsula）的攔截頁。
同一支程式與標頭在 08:42 還能通過，所以主要判斷為請求頻率或來源 IP 信譽；這裡只處理能控制的部分：
- 節流：連續兩次請求之間至少間隔 MIN_INTERVAL 秒（與 TWSE 節流同值，見 price-dividend-fetcher/scripts/fetch_common.py）。
- token：同一程序、同一網域只取一次；回應 ResultCode 非 0 時清掉，下次重取。
- 被攔截（HTTP 403）：拋出 CtbcBlocked。呼叫端不得在這裡重試，應停止並回報。
只用標準函式庫。
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional

HOST = "https://www.ctbcinvestments.com.tw/API/"
HEADERS = {"content-type": "application/json; charset=utf-8", "User-Agent": "Mozilla/5.0",
           "Referer": "https://www.ctbcinvestments.com.tw/"}
TOKEN_SEED = "www.ctbcinvestments.com"
MIN_INTERVAL = 3.0  # 秒；連續兩次中信投信請求之間至少間隔這麼久

_lock = threading.Lock()
_last_sent: Optional[float] = None  # 上一次安排送出的時間點（monotonic）
_tokens: Dict[str, str] = {}  # 網域 → token，只存在本程序


class CtbcError(RuntimeError):
    """回應 ResultCode 非 0，或取不到 token。"""


class CtbcBlocked(CtbcError):
    """被網站防護攔截（HTTP 403）。不重試，呼叫端應停止並回報。"""


def reset() -> None:
    """清除節流時間與 token 快取（測試用）。"""
    global _last_sent
    with _lock:
        _last_sent = None
    _tokens.clear()


def cached_token(host: str = HOST) -> Optional[str]:
    return _tokens.get(host)


def remember_token(host: str, token: str) -> None:
    _tokens[host] = token


def _pace(sleep: Callable[[float], None], clock: Callable[[], float]) -> None:
    """保留下一個送出時段（與其他執行緒共用同一條間隔），不足 MIN_INTERVAL 就等到時段開始。"""
    global _last_sent
    with _lock:
        now = clock()
        slot = now if _last_sent is None else max(now, _last_sent + MIN_INTERVAL)
        _last_sent = slot
    wait = slot - now
    if wait > 0:
        sleep(wait)


def send(path: str, body: Dict[str, Any], token: str, *, host: str = HOST, timeout: int = 40,
         sleep: Optional[Callable[[float], None]] = None, clock: Optional[Callable[[], float]] = None,
         opener: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """送出一次 POST，先節流。回傳解析後的完整 JSON（含 ResultCode）。
    HTTP 403 拋 CtbcBlocked；其他網路或解析錯誤照常拋出，由呼叫端決定是否重試。
    回應 ResultCode 非 0 時，清掉該網域的 token，下次重取。"""
    _pace(sleep or time.sleep, clock or time.monotonic)
    req = urllib.request.Request(host + path + "?" + urllib.parse.urlencode({"token": token}),
                                 data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise CtbcBlocked(f"中信投信 {path} 被網站防護攔截（HTTP 403），停止，不重試") from e
        raise
    if data.get("ResultCode") != 0 and path != "home/AuthToken":
        _tokens.pop(host, None)
    return data


def auth_token(host: str = HOST, **kw: Any) -> str:
    """同一程序、同一網域只向中信投信取一次 token，之後共用。取不到就拋 CtbcError（不快取失敗結果）。"""
    tok = cached_token(host)
    if tok:
        return tok
    r = send("home/AuthToken", {}, TOKEN_SEED, host=host, **kw)
    tok = (r.get("Data") or {}).get("token")
    if r.get("ResultCode") != 0 or not tok:
        raise CtbcError(f"取 token 失敗：{r.get('ResultMsg')}")
    remember_token(host, tok)
    return tok
