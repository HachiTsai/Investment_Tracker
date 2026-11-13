"""個股波段（5 天到 4 週）指標與訊號：只用標準函式庫，唯讀 Yahoo 日線。

  python3 swing.py TPE:2356            指標與目前狀態
  python3 swing.py TPE:2356 --backtest  加跑超跌反彈規則回測

訊號只描述條件與機率參考，不構成買賣指示；波段部位與股利再投入部位分開看。
"""
import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fetch_common import TWSE_STOCK_DAY_URL, parse_ticker, roc_to_iso, to_float, twse_get
from global_fetcher import get_yahoo, yahoo_result


MARKETS = {"TPE": "台股", "HKG": "港股", "TYO": "日股"}


def market_of(ticker: str) -> str:
    """交易所前綴轉市場分類：TPE 台股、HKG 港股、TYO 日股，其餘（NASDAQ、NYSE…）視為美股。"""
    exch, _ = parse_ticker(ticker)
    return MARKETS.get(exch, "美股")


GAP_WINDOW_DAYS = 14


def lagging_tickers(rows: List[Dict]) -> List[str]:
    """同市場內最後一根日線早於該市場最新資料日的代號（證交所補缺後仍落後，如上櫃股或證交所失敗），供報告提示資料落後。"""
    latest: Dict[str, str] = {}
    for r in rows:
        if r.get("last_date"):
            latest[r["market"]] = max(latest.get(r["market"], ""), r["last_date"])
    return [r["ticker"] for r in rows if r.get("last_date") and r["last_date"] < latest[r["market"]]]


RESCAN_DELAYS = (30, 60)  # 秒：證交所限流多為短暫，落後標的等候後重抓（每次只重抓落後的代號）
GAP_BARS = 10  # 中間日缺口只看每檔最近這幾根日線的日期


def missing_days(rows: List[Dict]) -> Dict[str, List[str]]:
    """中間日缺口：同市場超過半數標的有、但某檔在自己的日線區間內缺少的日期（Yahoo 漏掉某天、證交所補缺失敗時會出現）。

    交易日以同市場多數標的為準，不需要假日表：10-26 這類全市場都沒有的日期不會被當成缺口。
    只看每檔自己最早到最晚的區間，尾端落後由 lagging_tickers 判定，新掛牌的早期日期也不算缺口。
    """
    by_market: Dict[str, List[set]] = {}
    for r in rows:
        if r.get("bar_dates"):
            by_market.setdefault(r["market"], []).append(set(r["bar_dates"]))
    consensus = {}
    for m, sets in by_market.items():
        counts = Counter(d for s in sets for d in s)
        consensus[m] = {d for d, c in counts.items() if c * 2 > len(sets)}
    out = {}
    for r in rows:
        if not r.get("bar_dates"):
            continue
        own = set(r["bar_dates"])
        lo, hi = min(own), max(own)
        gaps = sorted(d for d in consensus[r["market"]] if lo <= d <= hi and d not in own)
        if gaps:
            out[r["ticker"]] = gaps
    return out


def stale_tickers(rows: List[Dict]) -> List[str]:
    """需要重抓的標的：尾端落後，或中間有日期缺口。"""
    return list(dict.fromkeys(lagging_tickers(rows) + list(missing_days(rows))))


def _quality(row: Dict, gaps: Dict[str, List[str]]) -> Tuple[str, int]:
    """列的品質：資料日越新越好；同一資料日時，中間缺口越少越好。"""
    return (row.get("last_date") or "", -len(gaps.get(row["ticker"], [])))


def refresh_lagging(rows: List[Dict], items: List[Dict], prev: Optional[Dict[str, Dict]], with_chart: bool = False,
                    delays: Tuple[int, ...] = RESCAN_DELAYS, sleep=time.sleep) -> List[Dict]:
    """落後或有中間缺口的標的等待後重抓；只採用品質較好的新列（資料日較新，或缺口較少），其餘維持原列。重抓仍有問題就保留原列，由 --scan 的 stderr 提示。"""
    for delay in delays:
        lag = set(stale_tickers(rows))
        if not lag:
            break
        sleep(delay)
        fresh = {r["ticker"]: r for r in scan([it for it in items if it["ticker"] in lag], prev, with_chart=with_chart)}
        candidate = [fresh.get(r["ticker"], r) if r["ticker"] in lag else r for r in rows]
        before, after = missing_days(rows), missing_days(candidate)
        rows = [c if r["ticker"] in lag and _quality(c, after) > _quality(r, before) else r for r, c in zip(rows, candidate)]
    return rows


def fill_gaps_from_twse(bars: List[Dict], code: str, now: Optional[datetime] = None, fetch=None) -> List[Dict]:
    """Yahoo 偶爾漏掉台股某一天的日線（實測 0050 缺 10-21、上一輪缺 10-20）：用證交所 STOCK_DAY 補回近 GAP_WINDOW_DAYS 天內缺的交易日。

    只補早於台北今天的日期（避免把盤中價當收盤）；還原價沿用相鄰 K 棒的 adj/close 比；證交所失敗或查無資料（如上櫃股）就原樣回傳。
    """
    if not bars:
        return bars
    fetch = fetch or twse_get
    tz = timedelta(hours=8)
    now = now or datetime.now(timezone.utc)
    today = (now + tz).strftime("%Y-%m-%d")
    have = {(datetime.fromtimestamp(b["ts"], timezone.utc) + tz).strftime("%Y-%m-%d") for b in bars}
    since = (now + tz - timedelta(days=GAP_WINDOW_DAYS)).strftime("%Y-%m-%d")
    first = min(have)
    d0 = datetime.strptime(max(since, first), "%Y-%m-%d")
    missing = [d for d in ((d0 + timedelta(days=k)).strftime("%Y-%m-%d") for k in range(GAP_WINDOW_DAYS + 1))
               if d < today and d not in have and datetime.strptime(d, "%Y-%m-%d").weekday() < 5]
    if not missing:
        return bars  # 窗口內平日都有 K 棒：不打證交所，減少被防護擋下的請求量
    months = sorted({d[:7] for d in missing})
    added = []
    for ym in months:
        try:
            js = json.loads(fetch(TWSE_STOCK_DAY_URL.format(date=ym.replace("-", "") + "01", code=code)))
        except (ValueError, RuntimeError, OSError) as e:
            print(f"證交所補缺失敗（{code} {ym}）：{str(e)[:120]}", file=sys.stderr)
            continue
        for row in js.get("data") or []:
            try:
                day = roc_to_iso(row[0].replace("/", "年", 1).replace("/", "月", 1) + "日")
                o, h, l, c = (to_float(x) for x in row[3:7])
                vol = to_float(row[1])
            except (ValueError, IndexError, AttributeError):
                continue
            if None in (o, h, l, c, vol) or day in have or not (since <= day < today):
                continue
            ts = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 3600
            added.append(dict(ts=ts, open=o, high=h, low=l, close=c, volume=vol, adj=c))
    if not added:
        return bars
    out = sorted(bars + added, key=lambda b: b["ts"])
    for i, b in enumerate(out):
        if b in added:
            ref = next((x for x in out[i + 1:] if x not in added), None) or next((x for x in reversed(out[:i]) if x not in added), None)
            if ref and ref["close"]:
                b["adj"] = b["close"] * ref["adj"] / ref["close"]
    return out


MARKET_CLOSE_HOUR = {"台股": 14, "港股": 17, "日股": 16, "美股": 17}  # 當地時間的收盤後緩衝（台股收盤 13:30、港股 16:00、日股 15:30、美股 16:00 ET）


def drop_unsettled_bar(bars: List[Dict], market: str, now: Optional[datetime] = None) -> List[Dict]:
    """盤中尚未收盤時，丟掉市場當地「今天」的日線：Yahoo 會回傳盤中價，不能當收盤價算指標。

    收盤後（當地時間達 MARKET_CLOSE_HOUR）原樣保留，讓 fresh 能判定當日資料；休市日不受影響。
    """
    now = now or datetime.now(timezone.utc)
    tz = timedelta(hours=MARKET_TZ_HOURS.get(market, 8))
    local = now + tz
    if local.hour >= MARKET_CLOSE_HOUR.get(market, 14):
        return bars
    today = local.strftime("%Y-%m-%d")
    return [b for b in bars if (datetime.fromtimestamp(b["ts"], timezone.utc) + tz).strftime("%Y-%m-%d") != today]


def load_ohlcv(ticker: str, rng: str = "2y", now: Optional[datetime] = None) -> List[Dict]:
    """抓日線並丟掉缺值與盤中未收盤的 K 棒；台股再用證交所補 Yahoo 漏掉的交易日。"""
    exch, code = parse_ticker(ticker)
    r = yahoo_result(get_yahoo(exch, code, rng), exch, code)
    q = r["indicators"]["quote"][0]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    bars = []
    for i, ts in enumerate(r.get("timestamp") or []):
        vals = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        if None not in vals:
            a = adj[i] if adj and adj[i] is not None else vals[3]
            bars.append(dict(ts=ts, open=vals[0], high=vals[1], low=vals[2], close=vals[3], volume=vals[4], adj=a))
    bars = drop_unsettled_bar(bars, market_of(ticker), now)
    if exch == "TPE":
        bars = fill_gaps_from_twse(bars, code, now=now)
    return bars


def sma(xs: List[float], n: int) -> List[Optional[float]]:
    return [None if i + 1 < n else sum(xs[i + 1 - n:i + 1]) / n for i in range(len(xs))]


def ema(xs: List[float], n: int) -> List[float]:
    k, out = 2 / (n + 1), []
    for x in xs:
        out.append(x if not out else x * k + out[-1] * (1 - k))
    return out


def rsi(closes: List[float], n: int = 14) -> List[Optional[float]]:
    """Wilder RSI。"""
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(closes)):
        if i > n:
            ag, al = (ag * (n - 1) + gains[i - 1]) / n, (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr(bars: List[Dict], n: int = 14) -> List[Optional[float]]:
    """Wilder ATR。"""
    trs = [bars[0]["high"] - bars[0]["low"]] + [
        max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"]))
        for p, b in zip(bars, bars[1:])
    ]
    out: List[Optional[float]] = [None] * len(bars)
    if len(bars) < n:
        return out
    cur = sum(trs[:n]) / n
    out[n - 1] = cur
    for i in range(n, len(bars)):
        cur = (cur * (n - 1) + trs[i]) / n
        out[i] = cur
    return out


def macd_hist(closes: List[float]) -> List[float]:
    line = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    return [m - s for m, s in zip(line, ema(line, 9))]


def bollinger(closes: List[float], n: int = 20, k: float = 2.0):
    mid = sma(closes, n)
    up, lo = [], []
    for i, m in enumerate(mid):
        if m is None:
            up.append(None); lo.append(None)
            continue
        sd = (sum((x - m) ** 2 for x in closes[i + 1 - n:i + 1]) / n) ** 0.5
        up.append(m + k * sd); lo.append(m - k * sd)
    return up, mid, lo


def classify(snap: Dict) -> Dict:
    """依指標快照判定狀態；順序即優先序。"""
    c, s20, s60, s120 = snap["close"], snap["sma20"], snap["sma60"], snap["sma120"]
    r, h, lo, up = snap["rsi14"], snap["macd_hist"], snap["bb_lower"], snap["bb_upper"]
    if None in (s20, s60, r, lo, up):
        return {"state": "NO_DATA", "label": "⚪ 資料不足", "reason": "日線不足以計算指標"}
    if r >= 70 or c >= up:
        return {"state": "OVERHEATED", "label": "🟠 短線偏熱", "reason": "RSI≥70 或觸及布林上緣，短線漲幅偏大，已持有者留意減碼條件"}
    if c < s20 < s60 and h < 0:
        return {"state": "DOWNTREND", "label": "🔴 偏空迴避", "reason": "收盤在 20、60 日線之下且 MACD 柱為負，順勢方向向下"}
    if (r <= 30 or c <= lo) and (s120 is None or c >= s120 * 0.9):
        return {"state": "OVERSOLD_WATCH", "label": "🟢 超跌觀察", "reason": "RSI≤30 或觸及布林下緣，且未明顯跌離半年線，可觀察反彈訊號"}
    if c > s20 > s60 and h > 0:
        return {"state": "UPTREND", "label": "🔵 趨勢偏多", "reason": "收盤在 20、60 日線之上且 MACD 柱為正"}
    return {"state": "NEUTRAL", "label": "⚪ 無明確型態", "reason": "指標未達任何條件"}


def snapshot(bars: List[Dict], stop_atr: float = 2.0) -> Dict:
    closes = [b["close"] for b in bars]
    a = atr(bars)[-1]
    up, _, lo = bollinger(closes)
    last252 = bars[-252:]
    hi, low = max(b["high"] for b in last252), min(b["low"] for b in last252)
    vol20 = sum(b["volume"] for b in bars[-20:]) / min(20, len(bars))
    snap = {
        "close": closes[-1],
        "sma20": sma(closes, 20)[-1], "sma60": sma(closes, 60)[-1], "sma120": sma(closes, 120)[-1],
        "rsi14": rsi(closes)[-1], "macd_hist": macd_hist(closes)[-1], "atr14": a,
        "bb_upper": up[-1], "bb_lower": lo[-1],
        "volume_ratio": round(bars[-1]["volume"] / vol20, 2) if vol20 else None,
        "pos_52w_pct": round((closes[-1] - low) / (hi - low) * 100, 1) if hi > low else None,
        "support_20d": min(b["low"] for b in bars[-20:]), "resistance_20d": max(b["high"] for b in bars[-20:]),
    }
    if a:
        snap["stop_price"] = round(closes[-1] - stop_atr * a, 2)
        snap["stop_distance_pct"] = round(stop_atr * a / closes[-1] * 100, 2)
    snap = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in snap.items()}
    snap.update(classify(snap))
    return snap


def backtest_oversold(bars: List[Dict], hold_max: int = 20, stop_atr: float = 2.0) -> Dict:
    """超跌反彈規則：RSI 由 30 以下進場（收盤價），RSI≥50、持有滿 hold_max 日或跌破停損出場。

    交給共用回測引擎（backtest.py）執行：現貨 1 倍、不含成本、資料結束仍未出場的部位不列入。
    """
    import backtest as bt  # 延遲匯入，避免與 backtest.py 互相匯入
    ctx = bt.prepare(bars)
    e, x, s = bt.strategy("oversold", "long", hold_max, stop_atr)
    res = bt.run(bars, e, x, s, ctx, start=1, drop_open=True)
    trades = [t["price_ret_pct"] for t in res["trades"]]
    wins = [t for t in trades if t > 0]
    return {
        "rule": f"RSI≤30 進場；RSI≥50／持有滿 {hold_max} 日／跌破 {stop_atr}×ATR 停損出場（不含手續費與證交稅）",
        "trades": len(trades), "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "avg_return_pct": round(sum(trades) / len(trades), 2) if trades else None,
        "worst_pct": min(trades) if trades else None, "returns_pct": trades,
        "caveat": "樣本少且為歷史結果，不代表未來；請同時看筆數與最差一筆",
    }


FIB_LOOKBACK = 30
FIB_BUCKETS = ((0.236, "0-23.6"), (0.382, "23.6-38.2"), (0.618, "38.2-61.8"), (0.786, "61.8-78.6"), (float("inf"), "78.6以上"))


def fib_zone(bars: List[Dict], lookback: int = FIB_LOOKBACK) -> Optional[Dict]:
    """費波那契回檔位置：取近 lookback 日最高最低（與 APP 彈窗同口徑，以 K 棒高低點）。

    低點在前、高點在後為上升波，回檔 % ＝ (高 − 收) / 區間；高點在前為下跌波，反彈 % ＝ (收 − 低) / 區間。
    只描述收盤相對位置，不是買賣指示；高低點換手時位置會跳動。
    """
    w = bars[-lookback:]
    if len(w) < 5:
        return None
    hi_i = max(range(len(w)), key=lambda i: (w[i]["high"], i))
    lo_i = max(range(len(w)), key=lambda i: (-w[i]["low"], i))
    high, low = w[hi_i]["high"], w[lo_i]["low"]
    if high <= low:
        return None
    up = lo_i < hi_i
    close = w[-1]["close"]
    pct = ((high - close) if up else (close - low)) / (high - low)
    pct = min(max(pct, 0.0), 1.0)
    bucket = next(name for edge, name in FIB_BUCKETS if pct < edge or edge == float("inf"))
    kind = "回檔" if up else "反彈"
    return {"dir": "up" if up else "down", "pct": round(pct * 100, 1), "bucket": bucket,
            "label": f"{kind} {bucket}%", "high": high, "low": low}


def backtest_fib(per_ticker_bars: Dict[str, List[Dict]], horizons=(5, 10, 20), lookback: int = FIB_LOOKBACK) -> Dict:
    """各回檔位置之後 N 日含息報酬（還原收盤價）。baseline 為同樣檔數、任選一天買進的平均。

    已含存活者偏差（只測現在的標的）、不含手續費與稅；同一檔連續多日落在同一位置，樣本彼此高度相關。
    """
    cells: Dict[str, Dict[int, List[float]]] = {}
    base: Dict[int, List[float]] = {h: [] for h in horizons}
    for bars in per_ticker_bars.values():
        adj = [b["adj"] for b in bars]
        for i in range(lookback, len(bars)):
            z = fib_zone(bars[:i + 1], lookback)
            for h in horizons:
                if i + h >= len(bars) or not adj[i]:
                    continue
                r = (adj[i + h] / adj[i] - 1) * 100
                base[h].append(r)
                if z:
                    cells.setdefault(f"{'上升波回檔' if z['dir'] == 'up' else '下跌波反彈'} {z['bucket']}%", {}).setdefault(h, []).append(r)
    stat = lambda xs: {"n": len(xs), "avg": round(sum(xs) / len(xs), 2), "median": round(sorted(xs)[len(xs) // 2], 2),
                       "win_pct": round(sum(x > 0 for x in xs) / len(xs) * 100, 1)} if xs else None
    return {"horizons": list(horizons), "baseline": {h: stat(base[h]) for h in horizons},
            "zones": {k: {h: stat(v.get(h, [])) for h in horizons} for k, v in sorted(cells.items())},
            "caveat": "含息報酬（還原收盤價），已含存活者偏差、不含手續費與稅，樣本高度重疊，僅供判斷位置欄位是否值得接進狀態判斷"}


def backtest_many(tickers: List[str], hold_max: int = 20, stop_atr: float = 2.0) -> Dict:
    """多檔彙總回測；單檔抓取失敗只記錄，不中斷。"""
    per, all_ret, failed, base = {}, [], {}, []
    for t in tickers:
        try:
            bars = load_ohlcv(t, "5y")
            res = backtest_oversold(bars, hold_max, stop_atr)
        except (ValueError, RuntimeError) as e:
            failed[t] = str(e)[:80]
            continue
        closes = [b["close"] for b in bars]
        base += [(closes[i + 10] / closes[i] - 1) * 100 for i in range(len(closes) - 10)]
        per[t] = {k: res[k] for k in ("trades", "win_rate_pct", "avg_return_pct", "worst_pct")}
        all_ret += res["returns_pct"]
    wins = [r for r in all_ret if r > 0]
    return {
        "tickers_ok": len(per), "tickers_failed": failed, "trades": len(all_ret),
        "win_rate_pct": round(len(wins) / len(all_ret) * 100, 1) if all_ret else None,
        "avg_return_pct": round(sum(all_ret) / len(all_ret), 2) if all_ret else None,
        "median_return_pct": round(sorted(all_ret)[len(all_ret) // 2], 2) if all_ret else None,
        "worst_pct": min(all_ret) if all_ret else None, "best_pct": max(all_ret) if all_ret else None,
        "baseline_any_day_10d_avg_pct": round(sum(base) / len(base), 2) if base else None,
        "per_ticker": per,
        "caveat": "baseline 為任選一天買進持有 10 個交易日的平均報酬，用來看規則有沒有比隨機進場好；已含存活者偏差（只測現在的成分股）、不含手續費與稅；僅供判斷指標是否值得接進簡報",
    }


def card_universe(card: str, top: int) -> List[str]:
    """讀 models/<card>/cards/constituents.jsonl 的前 top 大，轉成 fetcher 代號。"""
    path = Path(__file__).resolve().parents[4] / "models" / card / "cards" / "constituents.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines()[:top]:
        row = json.loads(line)
        sym = row["ticker"]
        if sym.endswith(".HK"):
            out.append("HKG:" + sym[:-3].lstrip("0"))
        elif sym.endswith(".TW"):
            out.append("TPE:" + sym[:-3])
    return out


RETURN_WINDOWS = {"1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252}


def period_returns(adj_closes: List[float], closes: List[float]) -> Dict[str, Dict[str, Optional[float]]]:
    """階段性報酬率（%）：total 用還原收盤價（含息再投入），price 用原始收盤價；日線不足該窗口則為 None。"""
    out: Dict[str, Dict[str, Optional[float]]] = {"total": {}, "price": {}}
    for name, n in RETURN_WINDOWS.items():
        for key, xs in (("total", adj_closes), ("price", closes)):
            out[key][name] = round((xs[-1] / xs[-1 - n] - 1) * 100, 2) if len(xs) > n and xs[-1 - n] else None
    return out


def load_adj_closes(ticker: str, rng: str = "2y") -> List[Dict]:
    """抓日線並附還原收盤價 adj（Yahoo adjclose，已含配息調整）；缺值的 K 棒丟掉。"""
    exch, code = parse_ticker(ticker)
    r = yahoo_result(get_yahoo(exch, code, rng), exch, code)
    close = r["indicators"]["quote"][0]["close"]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose") or close
    return [dict(ts=ts, close=close[i], adj=adj[i]) for i, ts in enumerate(r.get("timestamp") or [])
            if close[i] is not None and adj[i] is not None]


def stock_profile(ticker: str) -> Dict:
    """個股卡片用：波段狀態＋階段性含息報酬率。抓取失敗拋 ValueError/RuntimeError，由呼叫端降級。"""
    snap = snapshot(load_ohlcv(ticker, "1y"))
    rows = load_adj_closes(ticker)
    rets = period_returns([b["adj"] for b in rows], [b["close"] for b in rows])
    return {"state": snap["state"], "label": snap["label"], "reason": snap["reason"],
            "stop_price": snap.get("stop_price"), "stop_distance_pct": snap.get("stop_distance_pct"),
            "returns_total": rets["total"], "returns_price": rets["price"]}


def watchlist(universe: Optional[str] = None, filter_tier: Optional[str] = "core", extra: Optional[List[Dict]] = None) -> List[Dict]:
    """觀察清單：models 內指定分級（預設 core: 核心團隊）的 category: STOCK 與 ETF 卡片，加上選填的 ETF 成分股前 N 大（卡片:N）。"""
    root = Path(__file__).resolve().parents[4] / "models"
    items = []
    for card in sorted(root.glob("*/cards/ticker.yml")):
        txt = card.read_text(encoding="utf-8")
        field = lambda k: next((ln.split(":", 1)[1].split("#")[0].strip().strip('"').strip("'") for ln in txt.splitlines() if ln.startswith(k + ":")), "")
        tier = (field("tier") or "core").lower()
        if filter_tier and filter_tier.lower() != "all" and tier != filter_tier.lower():
            continue
        if "category: STOCK" in txt:
            items.append({"ticker": field("symbol"), "name": field("title"), "source": "個股卡片"})
        else:
            # 其餘卡片為 ETF（部分卡片沒有 category 欄）；沒有 symbol 欄，代號是不帶交易所的 ticker（台股 ETF 預設 TPE）
            items.append({"ticker": f"TPE:{field('ticker')}", "name": field("title"), "source": "ETF 卡片"})
    if universe:
        name, _, top = universe.partition(":")
        path = root / name / "cards" / "constituents.jsonl"
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()[:int(top or 15)]]
        for row, t in zip(rows, card_universe(name, int(top or 15))):
            if all(i["ticker"] != t for i in items):
                items.append({"ticker": t, "name": row["name"], "source": f"{name} 成分股"})
    # 全市場 ETF：卡片已有的不重複加，來源欄用「全市場 ETF」，和口袋名單（卡片、成分股）區分
    for e in extra or []:
        if all(i["ticker"] != e["ticker"] for i in items):
            items.append({"ticker": e["ticker"], "name": e.get("name", ""), "source": "全市場 ETF"})
    return items


MARKET_TZ_HOURS = {"台股": 8, "港股": 8, "日股": 9, "美股": -4}
LEGACY_LABELS = {"🟠 過熱": "🟠 短線偏熱", "⚪ 無訊號": "⚪ 無明確型態", "⚪ 未觸發條件": "⚪ 無明確型態"}  # 舊狀態檔的標籤對應到新用語，避免改名被當成狀態變化


def market_today(market: str, now: Optional[datetime] = None) -> str:
    """該市場所在時區的今天日期（YYYY-MM-DD）。"""
    now = now or datetime.now(timezone.utc)
    return (now + timedelta(hours=MARKET_TZ_HOURS.get(market, 8))).strftime("%Y-%m-%d")


CHART_BARS = 120


def chart_series(bars: List[Dict], n: int = CHART_BARS) -> Dict:
    """彈窗圖表用：最近 n 根日 K 與同期指標（指標用完整日線算，不受視窗截斷影響），數值取兩位小數。"""
    closes = [b["close"] for b in bars]
    up, mid, lo = bollinger(closes)
    r2 = lambda xs: [None if x is None else round(x, 2) for x in xs[-n:]]
    return {
        "d": [datetime.fromtimestamp(b["ts"], timezone.utc).strftime("%m-%d") for b in bars[-n:]],
        "o": r2([b["open"] for b in bars]), "h": r2([b["high"] for b in bars]), "l": r2([b["low"] for b in bars]), "c": r2(closes),
        "ma20": r2(mid), "bu": r2(up), "bl": r2(lo), "rsi": r2(rsi(closes)), "hist": [None if x is None else round(x, 3) for x in macd_hist(closes)[-n:]],
    }


def scan(items: List[Dict], prev: Optional[Dict[str, Dict]] = None, now: Optional[datetime] = None, with_chart: bool = False) -> List[Dict]:
    """逐檔取日線算快照；失敗的檔記錄原因，不中斷。

    last_date：最後一根日線的日期。fresh：last_date 是否為該市場的今天（收盤後執行時，False 代表休市或尚未收盤，
    排程應保留該市場舊資料不覆寫）。prev：{代號: {"label":..,"combo":..}}，給了就多出 changed（狀態標籤變化）、combo_changed、alert（三週期組合變成關鍵組合才提醒）。
    """
    out = []
    for it in items:
        market = market_of(it["ticker"])
        try:
            bars = load_ohlcv(it["ticker"], "1y")
            s = snapshot(bars)
        except (ValueError, RuntimeError, KeyError, IndexError) as e:
            out.append({**it, "market": market, "state": "ERROR", "label": "⚠️ 抓取失敗", "reason": str(e)[:80], "last_date": None, "fresh": False})
            continue
        last = datetime.fromtimestamp(bars[-1]["ts"], timezone.utc) + timedelta(hours=MARKET_TZ_HOURS.get(market, 8))
        row = {**it, "market": market, **{k: s.get(k) for k in (
            "state", "label", "reason", "close", "rsi14", "sma20", "sma60", "macd_hist",
            "volume_ratio", "pos_52w_pct", "support_20d", "resistance_20d", "stop_price", "stop_distance_pct")}}
        fz = fib_zone(bars)
        row["fib_label"] = fz["label"] if fz else None
        row["fib_pct"] = fz["pct"] if fz else None
        from swing_levels import current_levels
        lv = current_levels(bars) or {}
        row.update({"long": lv.get("long"), "mid": lv.get("mid"), "short": lv.get("short"), "fib3": lv.get("fib3"), "combo": lv.get("combo")})
        from swing_scores import compute_scores
        row.update(compute_scores(bars) or {})
        if with_chart:
            row["chart"] = chart_series(bars)
            from swing_scores import score_history
            row["chart"]["hs"] = score_history(bars)
        row["last_date"] = last.strftime("%Y-%m-%d")
        row["bar_dates"] = [(datetime.fromtimestamp(b["ts"], timezone.utc) + timedelta(hours=MARKET_TZ_HOURS.get(market, 8))).strftime("%Y-%m-%d") for b in bars[-GAP_BARS:]]
        row["fresh"] = row["last_date"] == market_today(market, now)
        if prev is not None:
            old = prev.get(it["ticker"]) or {}
            row["prev_label"] = LEGACY_LABELS.get(old.get("label"), old.get("label"))
            row["prev_combo"] = old.get("combo")
            row["changed"] = row["prev_label"] is not None and row["prev_label"] != row["label"]
            row["combo_changed"] = row["prev_combo"] is not None and row["combo"] is not None and row["prev_combo"] != row["combo"]
            from swing_levels import KEY_COMBOS
            row["alert"] = row["combo_changed"] and row["combo"] in KEY_COMBOS
        out.append(row)
    return out


SHEET_COLUMNS = (
    ("代號", "ticker"), ("名稱", "name"), ("市場", "market"), ("來源", "source"), ("狀態", "label"), ("收盤", "close"),
    ("RSI14", "rsi14"), ("20日線", "sma20"), ("60日線", "sma60"), ("量比", "volume_ratio"), ("52週位置%", "pos_52w_pct"),
    ("20日支撐", "support_20d"), ("20日壓力", "resistance_20d"), ("2xATR停損價", "stop_price"), ("停損距離%", "stop_distance_pct"),
    ("判定依據", "reason"), ("更新日", "last_date"), ("費波那契位置30日", "fib_label"), ("位置幅度%", "fib_pct"),
    ("長期", "long"), ("中期", "mid"), ("短期", "short"), ("費波那契3段", "fib3"), ("三週期組合", "combo"),
)  # 順序即 Sheet A 欄起；APP 以表頭名稱讀取


def sheet_table(rows: List[Dict]) -> List[List]:
    """掃描結果轉成 Sheet 二維表（第一列表頭、欄位順序固定 A 到 X），排程整張寫入即可，不必自己對欄。"""
    return [[h for h, _ in SHEET_COLUMNS]] + [["" if r.get(k) is None else r[k] for _, k in SHEET_COLUMNS] for r in rows]


def render_page(rows: List[Dict], date: str) -> str:
    """把掃描結果塞進 references/swing_watch_template.html，產出可發布成 Artifact 的頁面。"""
    tpl = (Path(__file__).resolve().parents[1] / "references" / "swing_watch_template.html").read_text(encoding="utf-8")
    keep = ("ticker", "name", "market", "source", "state", "label", "close", "rsi14", "sma20",
            "stop_price", "stop_distance_pct", "pos_52w_pct", "reason")
    data = [{k: r.get(k) for k in keep} for r in rows]
    return tpl.replace("__SWING_DATA__", json.dumps(data, ensure_ascii=False)).replace("__SWING_DATE__", date)


def merge_patrol(rows: List[Dict], patrol: Dict) -> List[Dict]:
    """把 patrol.py --json 的配置狀態、殖利率與數據時效併入掃描列（以代號尾碼對應）。"""
    fleet = {f["ticker"]: f for f in patrol.get("fleet", [])}
    for r in rows:
        f = fleet.get(r["ticker"].split(":")[-1])
        if f:
            r.update({"posture_label": f.get("posture_label"), "yield_pct": f.get("yield_pct"),
                      "watchdog": (f.get("watchdog") or {}).get("label")})
    return rows


SHEET_ALERT_TAB = "告警紀錄"  # 與 swing_sync.ALERT_TAB 同名；波段觀察 Sheet 由 GitHub Actions 的 swing_sync.py 寫入
SHEET_MAIN_TAB = "Untitled"  # 與 swing_sync 寫入 Z1:AA2 的分頁同名
SHEET_ALERT_MAX_AGE_DAYS = 4  # 最近一批告警距今超過 4 天（含週末與連假）就不再點亮，避免顯示過期提醒


def parse_sheet_last_updated(csv_text: str) -> Optional[str]:
    """波段觀察 Sheet 主分頁 Z1:AA2 的第一列（swing_sync 寫入「最後巡檢時間／lastUpdated」與時間）取時間字串；
    休市或互鎖略過的執行也會更新，所以能看出排程有沒有跑。讀不到回傳 None。"""
    import csv
    import io
    for r in csv.reader(io.StringIO(csv_text)):
        if len(r) >= 2 and r[1].strip()[:4].isdigit():
            return r[1].strip()
    return None


def fetch_sheet_last_updated(sheet_id: str, timeout: int = 20) -> Optional[str]:
    """以公開連結（gviz CSV，唯讀）讀主分頁 Untitled!Z1:AA2 的最後更新時間。"""
    import urllib.parse
    import urllib.request
    url = (f"https://docs.google.com/spreadsheets/d/{urllib.parse.quote(sheet_id)}/gviz/tq?tqx=out:csv"
           f"&sheet={SHEET_MAIN_TAB}&range=Z1:AA2")
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return parse_sheet_last_updated(r.read().decode("utf-8"))


def parse_sheet_alerts(csv_text: str, today: str, max_age_days: int = SHEET_ALERT_MAX_AGE_DAYS) -> Dict[str, Dict]:
    """解析「告警紀錄」分頁 CSV（表頭：偵測時間、代號、名稱、上次組合、這次組合…），取最近一個偵測日的告警。

    回傳 {代號: {"prev_combo":..,"combo":..,"date":..}}；最近偵測日早於 today 超過 max_age_days 天時回傳空字典。
    """
    import csv
    import io
    rows = list(csv.reader(io.StringIO(csv_text)))
    if len(rows) < 2:
        return {}
    recs = []
    for r in rows[1:]:
        if len(r) < 5 or len(r[0]) < 10 or not r[1].strip():
            continue
        recs.append((r[0][:10], r[1].strip().lstrip("'"), r[3].strip(), r[4].strip()))
    if not recs:
        return {}
    latest = max(d for d, *_ in recs)
    try:
        age = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(latest, "%Y-%m-%d")).days
    except ValueError:
        return {}
    if age < 0 or age > max_age_days:
        return {}
    return {t: {"prev_combo": pc or None, "combo": c or None, "date": d} for d, t, pc, c in recs if d == latest}


def fetch_sheet_alerts(sheet_id: str, timeout: int = 20) -> str:
    """以公開連結（gviz CSV，免登入、唯讀）讀波段觀察 Sheet 的「告警紀錄」分頁。"""
    import urllib.parse
    import urllib.request
    url = (f"https://docs.google.com/spreadsheets/d/{urllib.parse.quote(sheet_id)}/gviz/tq?tqx=out:csv&sheet="
           + urllib.parse.quote(SHEET_ALERT_TAB))
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8")


def apply_sheet_alerts(rows: List[Dict], alerts: Dict[str, Dict]) -> List[str]:
    """把 Sheet 最近一批告警點亮到巡檢列：只在該列目前組合仍等於告警時的組合才標 alert（組合已變回就不再提醒）。回傳點亮的代號。"""
    lit = []
    for r in rows:
        a = alerts.get(r.get("ticker"))
        if a and not r.get("alert") and a.get("combo") and r.get("combo") == a["combo"]:
            r["alert"] = True
            r["prev_combo"] = a.get("prev_combo")
            lit.append(r["ticker"])
    return lit


def _swing_sheet_id() -> Optional[str]:
    """從環境變數 DRIVE_IDS 取 SWING_SHEET_ID；缺少時回傳 None（訊息只寫鍵名，不印 ID）。"""
    import os
    try:
        return json.loads(os.environ.get("DRIVE_IDS", "") or "{}").get("SWING_SHEET_ID") or None
    except (ValueError, AttributeError):
        return None


DAILY_EXCLUDE = {"HKG:1919"}  # 每日巡檢頁不列的標的（Hachi 2026-10-21 指示拿掉中遠海控；卡片與其他流程不受影響）


def kind_of(source: str) -> str:
    return "ETF" if "ETF 卡片" in source else "個股"


TW_STOCK = re.compile(r"\d{4}\.(TW|TWO)")


def tw_detail_codes(rows: List[Dict], min_stocks: int = 5, models_dir: Optional[Path] = None) -> List[str]:
    """頁面上有台股成分股明細的 ETF 代號：台股 ETF 卡片的成分股有 min_stocks 檔以上台股個股，與 tw-etf-fetcher 的 etf_pool.discover 同一條規則。"""
    root = Path(models_dir) if models_dir else Path(__file__).resolve().parents[4] / "models"
    out = []
    for r in rows:
        exch, _, code = str(r.get("ticker", "")).partition(":")
        if exch != "TPE" or kind_of(r.get("source", "")) != "ETF":
            continue
        path = root / code / "cards" / "constituents.jsonl"
        if not path.exists():
            continue
        tickers = [json.loads(ln).get("ticker", "") for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if sum(1 for t in tickers if TW_STOCK.fullmatch(t)) >= min_stocks:
            out.append(code)
    return out


def render_daily_page(rows: List[Dict], patrol: Dict, date: str, notices: Optional[List[str]] = None,
                      stress: Optional[Dict] = None, etf_detail_url: Optional[str] = None) -> str:
    """每日投資組合巡檢頁：波段觀察加評分矩陣，附配置狀態與數據時效，可依地區與類型篩選。notices 為頁面頂端的警示文字（例如陷阱狀態未寫回）；stress 為 market_stress.build 的市場修正追蹤資料；etf_detail_url 給了就在頁首與有明細的 ETF 視窗放台股 ETF 成分股明細頁連結。"""
    tpl = (Path(__file__).resolve().parents[1] / "references" / "daily_patrol_template.html").read_text(encoding="utf-8")
    keep = ("ticker", "name", "market", "state", "label", "close", "rsi14", "pos_52w_pct", "stop_price", "stop_distance_pct",
            "fib_label", "long", "mid", "short", "combo", "alert", "reason", "trend_score", "macd_score", "vol_score",
            "return_score", "return_1y_pct", "total_score", "posture_label", "yield_pct", "watchdog", "last_date", "fresh",
            "support_20d", "resistance_20d", "chart", "missing_days")
    rows = [r for r in rows if not r.get("source", "").endswith("成分股") and r["ticker"] not in DAILY_EXCLUDE]  # 每日巡檢頁只列觀察清單標的，不含 00882 的港股成分股
    data = [{**{k: r.get(k) for k in keep}, "kind": kind_of(r.get("source", ""))} for r in rows]
    head = {"macro": patrol.get("macro_feed", ""), "stale": [f["ticker"] for f in patrol.get("fleet", []) if (f.get("watchdog") or {}).get("is_stale")], "notices": list(notices or []), "stress": stress}
    if etf_detail_url:
        head["etf_detail"] = {"url": etf_detail_url, "codes": tw_detail_codes(rows)}
    return (tpl.replace("__DAILY_DATA__", json.dumps(data, ensure_ascii=False))
            .replace("__DAILY_HEAD__", json.dumps(head, ensure_ascii=False)).replace("__DAILY_DATE__", date))


GATE_MAX_ERRORS = 10  # 全市場 ETF 納入後清單約 150 檔，容許的抓取失敗數由 5 放寬到 10


SHEET_MAX_AGE_DAYS = 10  # 波段 Sheet 休市判定：最新資料日距今超過此天數視為來源停滯，不當作休市（涵蓋長假）


def _market_age_problems(rows: List[Dict], now: Optional[datetime], max_age_days: int) -> List[str]:
    """各市場最新資料日距今超過 max_age_days 天，或完全沒有有效資料日，回傳說明；空清單代表通過。"""
    problems = []
    for market in sorted({r.get("market", "") for r in rows}):
        dates = [r["last_date"] for r in rows if r.get("market") == market and r.get("last_date")]
        if not dates:
            problems.append(f"{market} 沒有任何有效資料日")
            continue
        latest = max(dates)
        today = datetime.strptime(market_today(market, now), "%Y-%m-%d").date()
        age = (today - datetime.strptime(latest, "%Y-%m-%d").date()).days
        if age > max_age_days:
            problems.append(f"{market} 最新資料日 {latest} 距今 {age} 天，超過 {max_age_days} 天")
    return problems


def check_gate(
    rows: List[Dict],
    max_errors: int = 5,
    require_fresh: bool = False,
    now: Optional[datetime] = None,
    max_age_days: int = SHEET_MAX_AGE_DAYS,
) -> Tuple[bool, bool, List[str]]:
    """排程健康門檻檢核（波段 Sheet 路徑）。回傳：(is_healthy, is_market_closed, reasons)
    - 掃描結果為空：不健康，拒絕寫入（fail-closed）。
    - is_healthy：ERROR 與 NO_DATA 合計不超過 max_errors 檔。NO_DATA 會保留舊值，不計入即為靜默失效。
    - is_market_closed：所有標的皆非 fresh，且各市場最新資料日仍在 max_age_days 天內（休市）。
      資料日過舊或完全沒有資料日時，不判為休市，改為不健康（來源停滯）。
    """
    if not rows:
        return False, False, ["掃描結果為空，拒絕寫入 Sheet"]
    reasons = []
    bad = [r.get("ticker", "未知") for r in rows if r.get("state") in _BAD_STATES]
    is_healthy = len(bad) <= max_errors
    if not is_healthy:
        reasons.append(f"ERROR／NO_DATA 狀態標的超標：{len(bad)} > {max_errors} ({bad[:5]}...)")
    is_market_closed = require_fresh and not any(r.get("fresh") for r in rows)
    if is_market_closed:
        problems = _market_age_problems(rows, now, max_age_days)
        if problems:
            is_healthy = False
            is_market_closed = False
            reasons.append("休市判定失敗，資料日過舊（疑似來源停滯）：" + "；".join(problems))
        else:
            reasons.append("今日所有市場休市或未開盤（無任何 fresh 標的，正常略過）")
    return is_healthy, is_market_closed, reasons


# 每日投資組合巡檢頁的發布門檻：單一來源為 portfolio-patrol/references/publish_gate.json（與 patrol.json 門檻共用）。
# 與 check_gate（波段 Sheet 用）分開，互不影響。
PUBLISH_GATE_PATH = Path(__file__).resolve().parents[2] / "portfolio-patrol" / "references" / "publish_gate.json"


def load_publish_gate(path: Path = PUBLISH_GATE_PATH) -> Dict:
    """讀取發布門檻。缺檔或格式錯誤即拋錯，不以預設值放行（fail-closed）。"""
    gate = json.loads(path.read_text(encoding="utf-8"))
    zero = gate.get("zero_tolerance")
    if not isinstance(zero, list) or not zero or not all(isinstance(c, str) and c for c in zero):
        raise ValueError("publish_gate.json 的 zero_tolerance 必須是非空的代號清單")
    general = gate.get("general_max_anomalies")
    if not isinstance(general, int) or isinstance(general, bool) or general < 0:
        raise ValueError("publish_gate.json 的 general_max_anomalies 必須是非負整數")
    max_age = gate.get("max_age_days")
    if not isinstance(max_age, int) or isinstance(max_age, bool) or max_age <= 0:
        raise ValueError("publish_gate.json 的 max_age_days 必須是正整數")
    return gate


_PUBLISH_GATE = load_publish_gate()
# 核心持股（零容忍）：ERROR、NO_DATA、資料落後或中間缺口任一即失敗。代號加上台股前綴以對應掃描列的 ticker。
DAILY_HOLDINGS = tuple(f"TPE:{code}" for code in _PUBLISH_GATE["zero_tolerance"])
DAILY_GENERAL_MAX = _PUBLISH_GATE["general_max_anomalies"]  # 其餘列的異常合計上限
DAILY_MAX_AGE_DAYS = _PUBLISH_GATE["max_age_days"]  # 市場最新資料日距今超過此天數即視為整體停滯（涵蓋一般長假）
_BAD_STATES = ("ERROR", "NO_DATA")


def check_daily_gate(
    rows: List[Dict],
    holdings: Tuple[str, ...] = DAILY_HOLDINGS,
    general_max: int = DAILY_GENERAL_MAX,
    now: Optional[datetime] = None,
    max_age_days: int = DAILY_MAX_AGE_DAYS,
) -> Tuple[bool, List[str]]:
    """每日巡檢頁的發布門檻。回傳 (ok, reasons)；任一項不過即不發布。
    - 掃描結果為空、持股缺列：失敗。
    - 持股（零容忍）：狀態 ERROR／NO_DATA、資料日落後同市場最新資料日、中間有日期缺口，任一即失敗。
    - 其餘列：上述異常合計超過 general_max 即失敗。
    - 任一市場的最新資料日距今超過 max_age_days 天：整體停滯，失敗。
    """
    if not rows:
        return False, ["掃描結果為空，拒絕發布"]
    reasons: List[str] = []
    stale = set(stale_tickers(rows))
    tickers = {r.get("ticker") for r in rows}
    missing = [h for h in holdings if h not in tickers]
    if missing:
        reasons.append(f"持股缺列：{'、'.join(missing)}")

    def broken(r: Dict) -> bool:
        return r.get("state") in _BAD_STATES or not r.get("last_date") or r.get("ticker") in stale

    held_bad = [r["ticker"] for r in rows if r.get("ticker") in holdings and broken(r)]
    if held_bad:
        reasons.append(f"持股資料異常（零容忍）：{'、'.join(held_bad)}")
    general_bad = [r["ticker"] for r in rows if r.get("ticker") not in holdings and broken(r)]
    if len(general_bad) > general_max:
        reasons.append(f"一般列異常 {len(general_bad)} 檔，超過上限 {general_max}：{'、'.join(general_bad[:5])}")
    reasons.extend(_market_age_problems(rows, now, max_age_days))
    return not reasons, reasons


def validate_daily_html(html: str, date: str) -> List[str]:
    """發布前預檢：占位符已替換、資料日與預期一致、頁面不含成本數值（公開頁）。回傳問題清單，空清單代表通過。"""
    problems = []
    if "__DAILY_" in html:
        problems.append("頁面仍有未替換的占位符")
    if f'var DATE="{date}"' not in html:
        problems.append(f"頁面資料日與預期 {date} 不符")
    if re.search(r'"cost"\s*:\s*[0-9]', html):
        problems.append("頁面含成本數值，公開頁不得出現")
    return problems


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="個股波段指標與訊號（只讀）")
    p.add_argument("ticker", nargs="?", help="例如 TPE:2356、HKG:1919、NASDAQ:AAPL")
    p.add_argument("--scan", nargs="?", const="", metavar="卡片:前N大", help="掃描觀察清單（個股卡片，可加 ETF 成分股）並輸出 JSON")
    p.add_argument("--prev", metavar="JSON", help="上次狀態檔 [{\"ticker\":..,\"label\":..,\"combo\":..}]（即上次 --scan 輸出），給了 --scan 就標出狀態變化與提醒")
    p.add_argument("--sheet", metavar="OUT", help="搭配 --scan：另存 Sheet 二維表 JSON（表頭加資料列，欄位順序固定 A 到 X）")
    p.add_argument("--html", metavar="OUT", help="搭配 --scan：另存 Artifact 頁面（讀 references/swing_watch_template.html）")
    p.add_argument("--patrol", metavar="JSON", help="搭配 --scan：patrol.py --json 輸出檔，併入配置狀態、殖利率與數據時效")
    p.add_argument("--daily-html", metavar="OUT", help="搭配 --scan：另存每日投資組合巡檢頁（讀 references/daily_patrol_template.html）")
    p.add_argument("--notice", action="append", default=[], metavar="TEXT", help="搭配 --daily-html：頁面頂端的警示文字，可重複（例如陷阱狀態未寫回）")
    p.add_argument("--alerts-from-sheet", action="store_true", help="搭配 --daily-html：讀波段觀察 Sheet「告警紀錄」分頁（公開連結唯讀，DRIVE_IDS 的 SWING_SHEET_ID），點亮最近一個偵測日的關鍵組合轉換提醒")
    p.add_argument("--etf-detail", metavar="URL", help="搭配 --daily-html：頁首與台股 ETF 視窗放台股 ETF 成分股明細頁的連結（tw-etf-pool 的 Artifact 網址）")
    p.add_argument("--stress", action="store_true", help="搭配 --daily-html：加入市場修正追蹤區塊（market_stress.py：期交所、證交所、指數）")
    p.add_argument("--stress-track", action="append", default=[], metavar="代號[:成本]", help="搭配 --stress：追蹤持股，例如 00406A；加 :成本 才算相對成本與回本（巡檢頁是公開連結，排程不給成本），可重複")
    p.add_argument("--batch", metavar="卡片:前N大", help="多檔彙總回測，例如 00882:15（讀 models/<卡片>/cards/constituents.jsonl）")
    p.add_argument("--fib-backtest", action="store_true", help="回測各費波那契回檔位置之後 5/10/20 日含息報酬（觀察清單全部標的，抓 5 年日線）")
    p.add_argument("--backtest", action="store_true", help="加跑超跌反彈規則回測（抓 5 年日線）")
    p.add_argument("--gate", action="store_true", help="啟用波段 Sheet 的健康門檻判定（--scan 模式下 ERROR <= 10 檔）；--daily-html 一律套用每日門檻，不需此參數")
    p.add_argument("--extra-tickers", metavar="JSON", help="搭配 --scan：額外的全市場 ETF 清單檔 [{\"ticker\":\"TPE:0050\",\"name\":\"...\"}]，卡片已有的不重複")
    p.add_argument("--tier", choices=["core", "pool", "all"], default="core", help="波段掃描標的分級（預設 core: 核心團隊）")
    a = p.parse_args(argv)
    if a.scan is not None:
        prev = {r["ticker"]: {"label": r.get("label"), "combo": r.get("combo")} for r in json.loads(Path(a.prev).read_text(encoding="utf-8"))} if a.prev else None
        extra = json.loads(Path(a.extra_tickers).read_text(encoding="utf-8")) if a.extra_tickers else None
        items = watchlist(a.scan or None, filter_tier=a.tier, extra=extra)
        rows = scan(items, prev, with_chart=bool(a.daily_html))
        rows = refresh_lagging(rows, items, prev, with_chart=bool(a.daily_html))
        gaps = missing_days(rows)
        for r in rows:
            r["missing_days"] = gaps.get(r["ticker"], [])
        if gaps:
            print("中間日缺口（同市場多數標的有、該檔缺）：" + "；".join(f"{t} 缺 {'、'.join(d[5:] for d in ds)}" for t, ds in gaps.items()) + "；指標以實際存在的 K 棒計算，缺的那天不計", file=sys.stderr)
        patrol = json.loads(Path(a.patrol).read_text(encoding="utf-8")) if a.patrol else {}
        merge_patrol(rows, patrol)
        lag = lagging_tickers(rows)
        if lag:
            print("資料落後（證交所補缺後仍少一天以上）：" + "、".join(lag) + "；該列資料日落後，指標以最後一根日線計算", file=sys.stderr)
        if a.daily_html:
            # 每日巡檢頁一律先過門檻（不需 --gate）；不過就不渲染、不寫檔，rows 仍印出供排查
            ok, gate_reasons = check_daily_gate(rows)
            if not ok:
                print(f"❌ [Gate Failed] {'; '.join(gate_reasons)}", file=sys.stderr)
                print(json.dumps([{k: v for k, v in r.items() if k != "chart"} for r in rows], ensure_ascii=False, indent=1))
                return 1
            date = max((r["last_date"] for r in rows if r.get("last_date")), default="")
            if a.alerts_from_sheet:
                sid = _swing_sheet_id()
                if not sid:
                    print("告警紀錄未讀取：DRIVE_IDS 缺 SWING_SHEET_ID，巡檢頁不顯示關鍵組合轉換提醒", file=sys.stderr)
                else:
                    try:
                        today = market_today("台股")
                        lit = apply_sheet_alerts(rows, parse_sheet_alerts(fetch_sheet_alerts(sid), today))
                        print(f"告警紀錄：點亮 {len(lit)} 檔" + (f"（{'、'.join(lit)}）" if lit else ""), file=sys.stderr)
                        # 排程漏跑時告警會靜默失效，回報附上 Sheet 最後更新時間讓人眼也看得到（Issue #232）
                        print(f"波段 Sheet 最後更新：{fetch_sheet_last_updated(sid) or '讀不到'}", file=sys.stderr)
                    except (OSError, ValueError) as e:
                        print(f"告警紀錄讀取失敗，巡檢頁不顯示關鍵組合轉換提醒：{str(e)[:120]}", file=sys.stderr)
            stress = None
            if a.stress:
                import market_stress
                try:
                    stress = market_stress.build(market_stress.parse_track(a.stress_track))
                except (RuntimeError, ValueError, KeyError, IndexError, TypeError, OSError, ZeroDivisionError) as e:
                    print(f"市場修正追蹤失敗，頁面略過該區塊：{str(e)[:120]}", file=sys.stderr)
            html = render_daily_page(rows, patrol, date, notices=a.notice, stress=stress, etf_detail_url=a.etf_detail)
            problems = validate_daily_html(html, date)
            if problems:
                print(f"❌ [Page Check Failed] {'; '.join(problems)}", file=sys.stderr)
                return 1
            Path(a.daily_html).write_text(html, encoding="utf-8")
        if a.html:
            date = max((r["last_date"] for r in rows if r.get("last_date")), default="")
            Path(a.html).write_text(render_page(rows, date), encoding="utf-8")
        if a.sheet:
            Path(a.sheet).write_text(json.dumps(sheet_table(rows), ensure_ascii=False), encoding="utf-8")
        rows_out = [{k: v for k, v in r.items() if k != "chart"} for r in rows]
        print(json.dumps(rows_out, ensure_ascii=False, indent=1))
        if getattr(a, "gate", False) and not a.daily_html:
            require_fresh = bool(a.sheet and not a.daily_html)
            is_healthy, is_market_closed, reasons = check_gate(rows, max_errors=GATE_MAX_ERRORS, require_fresh=require_fresh)
            if not is_healthy:
                print(f"❌ [Gate Failed] {'; '.join(reasons)}", file=sys.stderr)
                return 1
            if is_market_closed:
                print(f"ℹ️ [Market Closed] {'; '.join(reasons)}", file=sys.stderr)
                return 0
        return 0
    if a.fib_backtest:
        data = {}
        for it in watchlist(a.scan or None, filter_tier=a.tier):
            try:
                data[it["ticker"]] = load_ohlcv(it["ticker"], "5y")
            except (ValueError, RuntimeError, KeyError, IndexError):
                continue
        print(json.dumps(backtest_fib(data), ensure_ascii=False, indent=1))
        return 0
    if a.batch:
        card, _, top = a.batch.partition(":")
        print(json.dumps(backtest_many(card_universe(card, int(top or 15))), ensure_ascii=False, indent=2))
        return 0
    if not a.ticker:
        p.error("需要 ticker 或 --batch")
    bars = load_ohlcv(a.ticker, "5y" if a.backtest else "2y")
    out = {"ticker": a.ticker, "bars": len(bars), "swing": snapshot(bars)}
    if a.backtest:
        out["backtest"] = backtest_oversold(bars)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
