"""短、中、長三週期的狀態分級與回測（原型）：只用標準函式庫，唯讀。

每個週期用「趨勢＋動能」打分（-2 到 +2）得 5 級，另有費波那契位置 6 級與過熱／超跌旗標。
週期：短期 20 日內（20 日線、RSI14、20 日費波那契）、中期 20 到 60 日（60 日線、MACD、60 日費波那契）、
長期 120 日以上（半年線、120 日報酬、250 日費波那契）。
只描述條件，不是買賣指示。
"""
import json
import sys
from typing import Dict, List, Optional

from swing import backtest_fib, bollinger, ema, load_ohlcv, macd_hist, rsi, sma, watchlist  # noqa: F401

HORIZONS = {"短": 20, "中": 60, "長": 250}  # 費波那契回看日數
FWD = {"短": (5, 10), "中": (20, 40), "長": (60, 120)}  # 各週期對應的後續報酬天數
STATES = {2: "強勢", 1: "偏多", 0: "中性", -1: "偏弱", -2: "弱勢"}
FIB_EDGES = ((0.236, "F1"), (0.382, "F2"), (0.5, "F3"), (0.618, "F4"), (0.786, "F5"), (float("inf"), "F6"))


def fib_level(bars: List[Dict], i: int, lookback: int) -> Optional[Dict]:
    """第 i 根收盤相對近 lookback 日高低點的位置，6 級（F1 近前高或近反彈起點，F6 回檔或反彈 78.6% 以上）。"""
    lo_i = max(0, i - lookback + 1)
    if i - lo_i + 1 < 5:
        return None
    w = bars[lo_i:i + 1]
    hi_k = max(range(len(w)), key=lambda k: (w[k]["high"], k))
    lo_k = max(range(len(w)), key=lambda k: (-w[k]["low"], k))
    high, low = w[hi_k]["high"], w[lo_k]["low"]
    if high <= low:
        return None
    up = lo_k < hi_k
    pct = ((high - w[-1]["close"]) if up else (w[-1]["close"] - low)) / (high - low)
    pct = min(max(pct, 0.0), 1.0)
    return {"dir": "up" if up else "down", "level": next(n for e, n in FIB_EDGES if pct < e), "pct": round(pct * 100, 1)}


def build_series(bars: List[Dict]) -> Dict:
    c = [b["close"] for b in bars]
    up, _, lo = bollinger(c)
    return {"c": c, "s20": sma(c, 20), "s60": sma(c, 60), "s120": sma(c, 120), "rsi": rsi(c),
            "hist": macd_hist(c), "bb_up": up, "bb_lo": lo}


def _sign(x: float, pos: float, neg: float) -> int:
    return 1 if x >= pos else -1 if x <= neg else 0


def horizon_states(bars: List[Dict], ser: Dict, i: int) -> Optional[Dict]:
    """第 i 根 K 棒的短、中、長期分級；資料不足回 None。"""
    c, s20, s60, s120, r, h = ser["c"][i], ser["s20"][i], ser["s60"][i], ser["s120"][i], ser["rsi"][i], ser["hist"][i]
    if None in (s20, s60, s120, r) or i < 120:
        return None
    ret120 = (c / ser["c"][i - 120] - 1) * 100
    # 趨勢分（-1/0/+1）
    t = {"短": 1 if c > s20 else -1,
         "中": 1 if c > s60 and s20 > s60 else -1 if c < s60 and s20 < s60 else 0,
         "長": 1 if c > s120 and s60 > s120 else -1 if c < s120 and s60 < s120 else 0}
    # 動能分（-1/0/+1）
    m = {"短": _sign(r, 55, 45), "中": 1 if h > 0 else -1, "長": _sign(ret120, 5, -5)}
    out = {}
    for k, lb in HORIZONS.items():
        score = t[k] + m[k]
        out[k] = {"score": score, "state": STATES[score], "fib": fib_level(bars, i, lb)}
    out["flag"] = ("過熱" if r >= 70 or c >= ser["bb_up"][i] else "超跌" if r <= 30 or c <= ser["bb_lo"][i] else "")
    return out


def combo(st: Dict) -> str:
    """三週期關係：以短、中、長的多空方向（偏多以上為多、偏弱以下為空、其餘為平）組合成名稱。"""
    d = {k: ("多" if st[k]["score"] >= 1 else "空" if st[k]["score"] <= -1 else "平") for k in "短中長"}
    s, m, l_ = d["短"], d["中"], d["長"]
    if s == m == l_ == "多":
        return "三週期共振偏多"
    if s == m == l_ == "空":
        return "三週期共振偏空"
    if l_ == "多" and s != "多":
        return "長多短回檔"
    if l_ == "空" and s == "多":
        return "長空短反彈"
    if l_ == "多" and s == "多":
        return "長多短多（中期未跟上）"
    return "其他"


KEY_COMBOS = ("三週期共振偏多", "三週期共振偏空", "長多短回檔", "長空短反彈")  # 組合變成這幾種才提醒
FIB_FAR = 0.786
FIB_NEAR = 0.236


def mid_label(score: int) -> str:
    """中期 3 級（回測顯示中期 5 級不單調，合併為偏多／中性／偏空）。"""
    return "偏多" if score >= 1 else "偏空" if score <= -1 else "中性"


def fib3(bars: List[Dict], lookback: int = 30) -> Optional[str]:
    """費波那契 3 段：近端、中段、遠端（上升波看回檔，下跌波看反彈）。極端段才有統計差異，中間幾級合併。"""
    from swing import fib_zone
    z = fib_zone(bars, lookback)
    if not z:
        return None
    p = z["pct"] / 100
    up = z["dir"] == "up"
    if p < FIB_NEAR:
        return "近前高" if up else "近波段低點"
    if p >= FIB_FAR:
        return "深度回檔" if up else "反彈近前高"
    return "回檔中段" if up else "反彈中段"


def current_levels(bars: List[Dict]) -> Optional[Dict]:
    """最新一根的正式分級：長期 5 級、中期 3 級、短期只標註、費波那契 3 段、三週期組合。資料不足回 None。"""
    st = horizon_states(bars, build_series(bars), len(bars) - 1)
    if not st:
        return None
    ser_c, s20 = bars[-1]["close"], sma([b["close"] for b in bars], 20)[-1]
    short = ("站上20日線" if ser_c > s20 else "跌破20日線") + {"過熱": "・短線偏熱", "超跌": "・短線超跌"}.get(st["flag"], "")
    return {"long": st["長"]["state"], "mid": mid_label(st["中"]["score"]), "short": short,
            "fib3": fib3(bars), "combo": combo(st)}


def _stat(xs: List[float]) -> Optional[Dict]:
    if not xs:
        return None
    return {"n": len(xs), "avg": round(sum(xs) / len(xs), 2), "win_pct": round(sum(x > 0 for x in xs) / len(xs) * 100, 1)}


def backtest_levels(per_ticker: Dict[str, List[Dict]]) -> Dict:
    """各週期 5 級狀態、6 級費波那契、三週期組合與過熱／超跌旗標之後的含息報酬（還原收盤價）。

    各週期用對應的後續天數（短 5/10、中 20/40、長 60/120）。baseline 為同樣天數、任選一天買進。
    已含存活者偏差、不含手續費與稅；同一檔連續多日落在同一級，樣本彼此高度重疊，僅供判斷級別是否值得保留。
    """
    days = sorted({d for v in FWD.values() for d in v})
    base: Dict[int, List[float]] = {d: [] for d in days}
    state: Dict[str, Dict[int, List[float]]] = {}
    fibs: Dict[str, Dict[int, List[float]]] = {}
    combos: Dict[str, Dict[int, List[float]]] = {}
    flags: Dict[str, Dict[int, List[float]]] = {}
    for bars in per_ticker.values():
        ser, adj = build_series(bars), [b["adj"] for b in bars]
        for i in range(len(bars)):
            st = horizon_states(bars, ser, i)
            if not st:
                continue
            fwd = {d: (adj[i + d] / adj[i] - 1) * 100 for d in days if i + d < len(bars) and adj[i]}
            for d, v in fwd.items():
                base[d].append(v)
            for k in "短中長":
                for d in FWD[k]:
                    if d not in fwd:
                        continue
                    state.setdefault(f"{k}期 {st[k]['state']}", {}).setdefault(d, []).append(fwd[d])
                    if st[k]["fib"]:
                        f = st[k]["fib"]
                        fibs.setdefault(f"{k}期 {f['level']}", {}).setdefault(d, []).append(fwd[d])
            cb = combo(st)
            for d in (5, 20, 60):
                if d in fwd:
                    combos.setdefault(cb, {}).setdefault(d, []).append(fwd[d])
                    if st["flag"]:
                        flags.setdefault(st["flag"], {}).setdefault(d, []).append(fwd[d])
    fmt = lambda g: {k: {d: _stat(v.get(d, [])) for d in sorted(v)} for k, v in sorted(g.items())}
    return {"baseline": {d: _stat(base[d]) for d in days}, "state": fmt(state), "fib": fmt(fibs), "combo": fmt(combos), "flag": fmt(flags)}


def main(argv=None) -> int:
    data = {}
    for it in watchlist(None):
        try:
            data[it["ticker"]] = load_ohlcv(it["ticker"], "5y")
        except (ValueError, RuntimeError, KeyError, IndexError):
            continue
    print(json.dumps(backtest_levels(data), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
