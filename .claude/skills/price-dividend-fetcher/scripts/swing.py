"""個股波段（5 天到 4 週）指標與訊號：只用標準函式庫，唯讀 Yahoo 日線。

  python3 swing.py TPE:2356            指標與目前狀態
  python3 swing.py TPE:2356 --backtest  加跑超跌反彈規則回測

訊號只描述條件與機率參考，不構成買賣指示；波段部位與股利再投入部位分開看。
"""
import argparse
import json
import sys
from typing import Dict, List, Optional

from fetch_common import parse_ticker
from global_fetcher import get_yahoo, yahoo_result


def load_ohlcv(ticker: str, rng: str = "2y") -> List[Dict]:
    """抓日線並丟掉缺值的 K 棒。"""
    exch, code = parse_ticker(ticker)
    r = yahoo_result(get_yahoo(exch, code, rng), exch, code)
    q = r["indicators"]["quote"][0]
    bars = []
    for i, ts in enumerate(r.get("timestamp") or []):
        vals = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        if None not in vals:
            bars.append(dict(ts=ts, open=vals[0], high=vals[1], low=vals[2], close=vals[3], volume=vals[4]))
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
        return {"state": "OVERHEATED", "label": "🟠 過熱", "reason": "RSI≥70 或觸及布林上緣，追高風險升高，已持有者留意減碼條件"}
    if c < s20 < s60 and h < 0:
        return {"state": "DOWNTREND", "label": "🔴 偏空迴避", "reason": "收盤在 20、60 日線之下且 MACD 柱為負，順勢方向向下"}
    if (r <= 30 or c <= lo) and (s120 is None or c >= s120 * 0.9):
        return {"state": "OVERSOLD_WATCH", "label": "🟢 超跌觀察", "reason": "RSI≤30 或觸及布林下緣，且未明顯跌離半年線，可觀察反彈訊號"}
    if c > s20 > s60 and h > 0:
        return {"state": "UPTREND", "label": "🔵 趨勢偏多", "reason": "收盤在 20、60 日線之上且 MACD 柱為正"}
    return {"state": "NEUTRAL", "label": "⚪ 無訊號", "reason": "指標未達任何條件"}


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
    """超跌反彈規則：RSI 由 30 以下進場（收盤價），RSI≥50、持有滿 hold_max 日或跌破停損出場。"""
    closes = [b["close"] for b in bars]
    rs, at, s120 = rsi(closes), atr(bars), sma(closes, 120)
    trades, i = [], 1
    while i < len(bars) - 1:
        if rs[i] is not None and rs[i] <= 30 and at[i] and (s120[i] is None or closes[i] >= s120[i] * 0.9):
            entry, stop, j, reason = closes[i], closes[i] - stop_atr * at[i], i + 1, "time"
            while j < len(bars):
                if bars[j]["low"] <= stop:
                    exit_p, reason = stop, "stop"; break
                if (rs[j] or 0) >= 50:
                    exit_p, reason = closes[j], "rsi50"; break
                if j - i >= hold_max:
                    exit_p = closes[j]; break
                j += 1
            else:
                break
            trades.append(round((exit_p / entry - 1) * 100, 2))
            i = j + 1
        else:
            i += 1
    wins = [t for t in trades if t > 0]
    return {
        "rule": f"RSI≤30 進場；RSI≥50／持有滿 {hold_max} 日／跌破 {stop_atr}×ATR 停損出場（不含手續費與證交稅）",
        "trades": len(trades), "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "avg_return_pct": round(sum(trades) / len(trades), 2) if trades else None,
        "worst_pct": min(trades) if trades else None, "returns_pct": trades,
        "caveat": "樣本少且為歷史結果，不代表未來；請同時看筆數與最差一筆",
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="個股波段指標與訊號（只讀）")
    p.add_argument("ticker", help="例如 TPE:2356、HKG:1919、NASDAQ:AAPL")
    p.add_argument("--backtest", action="store_true", help="加跑超跌反彈規則回測（抓 5 年日線）")
    a = p.parse_args(argv)
    bars = load_ohlcv(a.ticker, "5y" if a.backtest else "2y")
    out = {"ticker": a.ticker, "bars": len(bars), "swing": snapshot(bars)}
    if a.backtest:
        out["backtest"] = backtest_oversold(bars)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
