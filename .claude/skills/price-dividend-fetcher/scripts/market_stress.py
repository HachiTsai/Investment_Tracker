"""市場修正追蹤：台股急跌後的「趨緩訊號」與追蹤持股的回本試算（只讀、只用標準函式庫）。

  python3 market_stress.py                      只看市場訊號
  python3 market_stress.py --track 00406A:8.51  另加追蹤持股（代號:成本）

資料來源：期交所 OpenAPI（三大法人台指期未平倉）、證交所（三大法人買賣超、信用交易統計）、
Yahoo 日線（加權指數、費城半導體、追蹤標的與配息）。任一來源抓不到時該欄為 None，頁面顯示 `-`，不以舊值代替。
訊號只描述市場狀態，不構成買賣指示。
"""
import argparse
import json
import math
import statistics
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from fetch_common import YAHOO_UA, http_get

TAIFEX_OI_URL = "https://openapi.taifex.com.tw/v1/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate"
TWSE_INST_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate={date}&type=day&response=json"
TWSE_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={date}&response=json"
TWSE_MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={date}&selectType=MS&response=json"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d&events=div"
TW = timezone(timedelta(hours=8))

# 歷史類比：2000-2026 加權指數距 60 日高點跌 7% 以上且 RSI14 < 30 的 33 次（2026-11-05 計算，
# 報告 /mnt/project-files/reports/00406A選後震盪趨緩時間推估.md）。中位數僅供對照，不是預測。
ANALOG = {"n": 33, "days_to_low": 13, "days_to_calm": 20, "days_to_prior_high": 121}

# 趨緩訊號門檻（同上報告第六節）
FOREIGN_SPOT_OK = -300e8      # 外資現貨賣超縮小到 300 億以內
FUT_SHORT_EXTREME = 90000     # 外資台指期淨空單 9 萬口以上視為極端
FUT_SHORT_OK = 70000          # 降到 7 萬口以下視為空單回補
RV_OK = 20.0                  # 加權 10 日實現波動（年化 %）
DD_TRIGGER = -7.0             # 修正期觸發：距 60 日高點跌幅（%）
RSI_TRIGGER = 30.0
DD_EPISODE = -5.0             # 跌幅收斂到這以內視為修正期結束

Getter = Callable[..., str]


def _num(s) -> Optional[float]:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


# ---------- 抓取 ----------

def taifex_futures_oi(http: Getter = http_get) -> Optional[Dict]:
    """期交所三大法人臺股期貨未平倉淨額（口）：最新一日的外資與投信。"""
    rows = json.loads(http(TAIFEX_OI_URL, attempts=2))
    out: Dict = {}
    for r in rows:
        if r.get("ContractCode") != "臺股期貨":
            continue
        out["date"] = r.get("Date")
        if r.get("Item", "").startswith("外資"):
            out["foreign_net"] = _num(r.get("OpenInterest(Net)"))
        elif r.get("Item") == "投信":
            out["trust_net"] = _num(r.get("OpenInterest(Net)"))
    return out if "foreign_net" in out else None


def twse_foreign_net(date: str, http: Getter = http_get) -> Optional[float]:
    """證交所三大法人買賣金額：外資及陸資（不含外資自營商）買賣差額（元）。date 為 YYYYMMDD。"""
    d = json.loads(http(TWSE_INST_URL.format(date=date), attempts=2))
    if d.get("stat") != "OK":
        return None
    for row in d.get("data") or []:
        if str(row[0]).startswith("外資及陸資"):
            return _num(row[3])
    return None


def twse_margin_balance(date: str, http: Getter = http_get) -> Optional[float]:
    """證交所信用交易統計：融資金額今日餘額（仟元）。"""
    d = json.loads(http(TWSE_MARGIN_URL.format(date=date), attempts=2))
    if d.get("stat") != "OK":
        return None
    for t in d.get("tables") or []:
        for row in t.get("data") or []:
            if str(row[0]).startswith("融資金額"):
                return _num(row[-1])
    return None


def twse_index_month(date: str, http: Getter = http_get) -> Dict[str, float]:
    """證交所市場成交資訊：該月每日加權指數收盤，鍵為 YYYY-MM-DD（民國年轉西元）。"""
    d = json.loads(http(TWSE_INDEX_URL.format(date=date), attempts=2))
    out: Dict[str, float] = {}
    if d.get("stat") != "OK":
        return out
    for row in d.get("data") or []:
        y, m, dd = str(row[0]).split("/")
        v = _num(row[4])
        if v is not None:
            out[f"{int(y) + 1911:04d}-{int(m):02d}-{int(dd):02d}"] = v
    return out


def fill_index_tail(days: List[str], close: List[float], adj: List[float], extra: Dict[str, float]) -> Tuple[List[str], List[float], List[float]]:
    """Yahoo 指數常晚一天：把證交所有、Yahoo 還沒有的最新交易日補在尾端。"""
    tail = sorted(k for k in extra if not days or k > days[-1])
    return days + tail, close + [extra[k] for k in tail], adj + [extra[k] for k in tail]


def yahoo_series(sym: str, rng: str = "2y", http: Getter = http_get) -> Tuple[List[str], List[float], List[float], List[Tuple[str, float]]]:
    """Yahoo 日線：(日期, 收盤, 還原收盤, 配息[(日期, 金額)])，日期以台北時間計。"""
    d = json.loads(http(YAHOO_CHART_URL.format(sym=urllib.parse.quote(sym), rng=rng), ua=YAHOO_UA, attempts=2))
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]["close"]
    adj = ((r["indicators"].get("adjclose") or [{}])[0].get("adjclose")) or q
    by_day: Dict[str, Tuple[float, float]] = {}
    for ts, c, a in zip(r.get("timestamp") or [], q, adj):
        if c is not None:
            by_day[datetime.fromtimestamp(ts, TW).strftime("%Y-%m-%d")] = (c, a if a is not None else c)
    days = sorted(by_day)
    divs = sorted((datetime.fromtimestamp(int(v["date"]), TW).strftime("%Y-%m-%d"), float(v["amount"]))
                  for v in ((r.get("events") or {}).get("dividends") or {}).values())
    return days, [by_day[k][0] for k in days], [by_day[k][1] for k in days], divs


# ---------- 計算 ----------

def rsi(c: List[float], n: int = 14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(c)
    g = loss = 0.0
    for i in range(1, len(c)):
        ch = c[i] - c[i - 1]
        up, dn = max(ch, 0.0), max(-ch, 0.0)
        if i <= n:
            g += up / n
            loss += dn / n
        else:
            g = (g * (n - 1) + up) / n
            loss = (loss * (n - 1) + dn) / n
        if i >= n:
            out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + g / loss)
    return out


def realized_vol(c: List[float], j: int, n: int = 10) -> Optional[float]:
    """第 j 日往前 n 日的年化實現波動（%）。"""
    if j < n:
        return None
    r = [math.log(c[k] / c[k - 1]) for k in range(j - n + 1, j + 1)]
    return statistics.pstdev(r) * math.sqrt(252) * 100


def drawdown60(c: List[float], j: int) -> float:
    return (c[j] / max(c[max(0, j - 60):j + 1]) - 1) * 100


def episode_start(c: List[float], rs: List[Optional[float]]) -> Optional[int]:
    """目前修正期的觸發日索引：往回找到跌幅仍在 DD_EPISODE 以下的連續區間，取其中第一次跌幅 ≤ DD_TRIGGER 且 RSI < 30 的日子。"""
    end = len(c) - 1
    if end < 0 or drawdown60(c, end) > DD_EPISODE:
        return None
    s = end
    while s > 0 and drawdown60(c, s - 1) <= DD_EPISODE:
        s -= 1
    for j in range(s, end + 1):
        if drawdown60(c, j) <= DD_TRIGGER and rs[j] is not None and rs[j] < RSI_TRIGGER:
            return j
    return None


def index_state(days: List[str], c: List[float]) -> Dict:
    j = len(c) - 1
    rs = rsi(c)
    ma10 = sum(c[j - 9:j + 1]) / 10 if j >= 9 else None
    st = episode_start(c, rs)
    return {
        "date": days[j], "close": round(c[j], 2), "dd60_pct": round(drawdown60(c, j), 1),
        "rsi14": round(rs[j], 1) if rs[j] is not None else None,
        "rv10": round(realized_vol(c, j), 1) if realized_vol(c, j) is not None else None,
        "ma10": round(ma10, 2) if ma10 else None, "above_ma10": bool(ma10 and c[j] > ma10),
        "ret5_pct": round((c[j] / c[j - 5] - 1) * 100, 1) if j >= 5 else None,
        "episode_start": days[st] if st is not None else None,
        "episode_days": (j - st) if st is not None else None,
    }


def capture(etf: Dict[str, float], idx: Dict[str, float]) -> Optional[Dict]:
    """以共同交易日的日報酬計算 β、上漲與下跌捕獲率。"""
    ks = sorted(k for k in etf if k in idx)
    if len(ks) < 30:
        return None
    ra = [etf[ks[i]] / etf[ks[i - 1]] - 1 for i in range(1, len(ks))]
    rt = [idx[ks[i]] / idx[ks[i - 1]] - 1 for i in range(1, len(ks))]
    ma, mt = statistics.mean(ra), statistics.mean(rt)
    var = sum((y - mt) ** 2 for y in rt)
    up = [(x, y) for x, y in zip(ra, rt) if y > 0]
    dn = [(x, y) for x, y in zip(ra, rt) if y < 0]
    return {
        "days": len(ra),
        "beta": round(sum((x - ma) * (y - mt) for x, y in zip(ra, rt)) / var, 2) if var else None,
        "up_capture": round(sum(x for x, _ in up) / sum(y for _, y in up), 2) if up else None,
        "down_capture": round(sum(x for x, _ in dn) / sum(y for _, y in dn), 2) if dn else None,
    }


def holding_state(code: str, cost: float, idx_adj: Dict[str, float], http: Getter = http_get) -> Dict:
    """追蹤持股：現價、相對成本、最近一次配息、以最近配息維持估算的回本月數、對加權的捕獲率。"""
    days, close, adj, divs = yahoo_series(f"{code}.TW", "1y", http)
    last = close[-1]
    last_div = divs[-1][1] if divs else None
    gap = cost - last
    months = math.ceil(gap / last_div) if (last_div and gap > 0) else (0 if gap <= 0 else None)
    return {
        "code": code, "date": days[-1], "close": round(last, 2), "cost": cost,
        "vs_cost_pct": round((last / cost - 1) * 100, 1),
        "last_div": last_div, "last_div_date": divs[-1][0] if divs else None,
        "months_to_breakeven": months,
        "capture": capture(dict(zip(days, adj)), idx_adj),
    }


def _status(ok: Optional[bool], bad: bool = False) -> str:
    if ok is None:
        return "na"
    return "ok" if ok else ("bad" if bad else "warn")


def signals(idx: Optional[Dict], sox: Optional[Dict], fut: Optional[Dict], spot: List[Optional[float]],
            margin: List[Optional[float]], dates: Optional[Dict[str, Optional[str]]] = None) -> List[Dict]:
    """六個趨緩訊號：ok 已趨緩、warn 未達、bad 仍在極端、na 抓不到。spot、margin 為由舊到新的近幾日數列。"""
    out = []
    s = spot[-1] if spot else None
    out.append({"key": "spot", "label": "外資現貨賣超縮小", "value": s, "unit": "元",
                "rule": "單日賣超在 300 億以內或轉買超", "status": _status(None if s is None else s >= FOREIGN_SPOT_OK)})
    f = fut.get("foreign_net") if fut else None
    out.append({"key": "fut", "label": "外資台指期淨空單回補", "value": f, "unit": "口",
                "rule": "淨空單降到 7 萬口以下（9 萬口以上為極端）",
                "status": _status(None if f is None else -f < FUT_SHORT_OK, bad=f is not None and -f >= FUT_SHORT_EXTREME)})
    m = [x for x in margin if x is not None]
    m_ok = None if len(m) < 4 else all(m[i] >= m[i - 1] for i in range(len(m) - 3, len(m)))
    out.append({"key": "margin", "label": "融資餘額連 3 日止跌", "value": m[-1] if m else None, "unit": "仟元",
                "rule": "最近 3 日融資餘額都沒有減少", "status": _status(m_ok)})
    out.append({"key": "ma10", "label": "加權站回 10 日線", "value": idx.get("ma10") if idx else None, "unit": "點",
                "rule": "收盤高於 10 日均線", "status": _status(idx.get("above_ma10") if idx else None)})
    rv = idx.get("rv10") if idx else None
    out.append({"key": "rv", "label": "加權波動回落", "value": rv, "unit": "%",
                "rule": "10 日實現波動（年化）低於 20%", "status": _status(None if rv is None else rv < RV_OK)})
    r5 = sox.get("ret5_pct") if sox else None
    out.append({"key": "sox", "label": "費城半導體止跌", "value": r5, "unit": "%",
                "rule": "近 5 日報酬轉正", "status": _status(None if r5 is None else r5 >= 0)})
    for g in out:
        g["date"] = (dates or {}).get(g["key"])
    return out


def _try(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (RuntimeError, ValueError, KeyError, IndexError, TypeError, OSError):
        return None


def build(track: List[Tuple[str, float]], http: Getter = http_get, now: Optional[datetime] = None) -> Dict:
    """組合市場修正追蹤資料。每個來源獨立失敗，失敗欄位為 None。"""
    today = (now or datetime.now(TW))
    tw = _try(yahoo_series, "^TWII", "2y", http)
    if tw:
        extra = _try(twse_index_month, today.strftime("%Y%m%d"), http) or {}
        tw = fill_index_tail(tw[0], tw[1], tw[2], extra) + (tw[3],)
    idx = index_state(tw[0], tw[1]) if tw else None
    sx = _try(yahoo_series, "^SOX", "6mo", http)
    sox = index_state(sx[0], sx[1]) if sx else None
    cands = [d.replace("-", "") for d in (tw[0][-5:] if tw else [])]
    if today.weekday() < 5 and (not cands or today.strftime("%Y%m%d") > cands[-1]):
        cands.append(today.strftime("%Y%m%d"))  # Yahoo 指數常晚一天，證交所當日資料可能已公布
    spot_all = {d: _try(twse_foreign_net, d, http) for d in cands[-4:]}
    margin_all = {d: _try(twse_margin_balance, d, http) for d in cands}
    spot_d = {d: v for d, v in spot_all.items() if v is not None}
    margin_d = {d: v for d, v in margin_all.items() if v is not None}
    spot_keys, margin_keys = sorted(spot_d)[-3:], sorted(margin_d)[-4:]
    spot = [spot_d[d] for d in spot_keys]
    margin = [margin_d[d] for d in margin_keys]
    fut = _try(taifex_futures_oi, http)
    idx_adj = dict(zip(tw[0], tw[2])) if tw else {}
    holdings = [h for h in (_try(holding_state, code, cost, idx_adj, http) for code, cost in track) if h]
    iso = lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]}" if d else None  # noqa: E731
    dates = {"spot": iso(spot_keys[-1] if spot_keys else None), "fut": iso(fut.get("date") if fut else None),
             "margin": iso(margin_keys[-1] if margin_keys else None), "ma10": idx.get("date") if idx else None,
             "rv": idx.get("date") if idx else None, "sox": sox.get("date") if sox else None}
    sig = signals(idx, sox, fut, spot, margin, dates)
    return {
        "generated": (now or datetime.now(TW)).strftime("%Y-%m-%d %H:%M"),
        "active": bool(idx and idx.get("episode_start")),
        "index": idx, "sox": sox, "futures": fut,
        "foreign_spot": {d: spot_d[d] for d in spot_keys}, "margin": {d: margin_d[d] for d in margin_keys},
        "signals": sig, "calm_count": sum(1 for s in sig if s["status"] == "ok"),
        "analog": ANALOG, "holdings": holdings,
    }


def parse_track(items: List[str]) -> List[Tuple[str, float]]:
    out = []
    for it in items:
        code, _, cost = it.partition(":")
        if not code or _num(cost) is None:
            raise ValueError(f"--track 格式應為 代號:成本，收到 {it}")
        out.append((code.strip(), float(cost)))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="市場修正追蹤（只讀）")
    p.add_argument("--track", action="append", default=[], metavar="代號:成本", help="追蹤持股，例如 00406A:8.51，可重複")
    a = p.parse_args(argv)
    print(json.dumps(build(parse_track(a.track)), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
