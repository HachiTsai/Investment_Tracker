"""台股成分股明細：FinMind 財報與配息 → 與 eastmoney.hk_detail／hk_dividends 相同格式。

輸出格式刻意對齊港股版（累計數、「一季报／中报／三季报／年报」類別字串），這樣 fin_trend 的單季 EPS、年增、
訊號、配息率、估值位置可以原封重用，不必為台股另寫一套。FinMind 的損益表是單季值，這裡換成年內累計。
所有請求都過 get()：同一請求在快取有效期內只打一次，遇到頻率限制會退避重試，失敗拋例外由呼叫端記錄。
"""

import datetime
import hashlib
import json
import os
import re
import tempfile
import time
from typing import Any, Dict, List, Optional

from . import clean, http_json, ratio

BASE = "https://api.finmindtrade.com/api/v4/data"
CACHE_DIR = os.path.join(tempfile.gettempdir(), "finmind_cache")
CACHE_TTL = 6 * 3600
KINDS = {"03-31": "一季报", "06-30": "中报", "09-30": "三季报", "12-31": "年报"}
CUR = "新台幣"


def get(dataset: str, code: str = "", start: str = "", attempts: int = 3) -> List[Dict[str, Any]]:
    """FinMind 原始資料列。有 FINMIND_TOKEN 環境變數就帶上（提高頻率上限）；快取 6 小時；限流時退避重試。"""
    q = f"dataset={dataset}" + (f"&data_id={code}" if code else "") + (f"&start_date={start}" if start else "")
    if os.environ.get("FINMIND_TOKEN"):
        q += "&token=" + os.environ["FINMIND_TOKEN"]
    path = os.path.join(CACHE_DIR, hashlib.sha1(q.split("&token=")[0].encode()).hexdigest() + ".json")
    try:
        if time.time() - os.path.getmtime(path) < CACHE_TTL:
            cached = json.load(open(path, encoding="utf-8"))
            if cached:  # 空結果多半是限流時的降級回應，不沿用
                return cached
    except (OSError, ValueError):
        pass
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            resp = http_json(f"{BASE}?{q}")
            if resp.get("status") not in (None, 200):
                raise RuntimeError(f"FinMind {resp.get('status')}: {resp.get('msg')}")
            data = resp.get("data") or []
            if data:  # 只快取有資料的回應，避免限流造成的空結果被快取 6 小時
                try:
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False)
                except OSError:
                    pass
            return data
        except Exception as e:  # noqa: BLE001  網路、限流、格式錯誤都退避重試
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"FinMind {dataset} {code} 失敗：{last}")


def series(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        out.setdefault(r["type"], {})[r["date"]] = r["value"]
    return out


def industries() -> Dict[str, str]:
    """代號 → 產業別。同一代號可有多筆（例如電子工業與半導體業），以「/」串接，金融業判斷用包含比對。"""
    out: Dict[str, List[str]] = {}
    for r in get("TaiwanStockInfo"):
        cat = r.get("industry_category")
        if cat and cat not in out.setdefault(r["stock_id"], []):
            out[r["stock_id"]].append(cat)
    return {k: "/".join(v) for k, v in out.items()}


def _cumulative(single: Dict[str, float]) -> Dict[str, float]:
    """單季值 → 年內累計；該年前面的季度缺任何一季就不輸出，避免累計失真。"""
    out: Dict[str, float] = {}
    for d in sorted(single):
        y, md = d[:4], d[5:]
        need = [f"{y}-{m}" for m in ("03-31", "06-30", "09-30", "12-31")[: list(KINDS).index(md) + 1]] if md in KINDS else []
        if need and all(n in single for n in need):
            out[d] = sum(single[n] for n in need)
    return out


def _ttm(single: Dict[str, float], d: str) -> Optional[float]:
    ds = sorted(x for x in single if x <= d)[-4:]
    return sum(single[x] for x in ds) if len(ds) == 4 and ds[-1] == d else None


def tw_detail(code: str, industry: Optional[str] = None, periods: int = 10) -> Dict[str, Any]:
    """最近 periods 期（新到舊）的累計財報；欄位與 eastmoney.hk_detail 相同。查不到財報回 {}。"""
    start = f"{datetime.date.today().year - 4}-01-01"
    inc = series(get("TaiwanStockFinancialStatements", code, start))
    if not inc.get("EPS"):
        return {}
    bs = series(get("TaiwanStockBalanceSheet", code, start))
    cf = series(get("TaiwanStockCashFlowsStatement", code, start))
    eps_c, rev_c = _cumulative(inc["EPS"]), _cumulative(inc.get("Revenue", {}))
    ni_s, gp_c = inc.get("EquityAttributableToOwnersOfParent", {}), _cumulative(inc.get("GrossProfit", {}))
    ni_c = _cumulative(ni_s)
    # 金融業資產負債表沒有「歸屬母公司權益」，改用總權益（含少數股權，ROE 略偏低）
    eq = bs.get("EquityAttributableToOwnersOfParent") or bs.get("Equity", {})
    liab, assets = bs.get("Liabilities", {}), bs.get("TotalAssets", {})
    ca, cl = bs.get("CurrentAssets", {}), bs.get("CurrentLiabilities", {})
    eq_dates = sorted(eq)
    hist = []
    for d in sorted(eps_c, reverse=True)[:periods]:
        ttm_ni = _ttm(ni_s, d)
        prev_eq = eq_dates[eq_dates.index(d) - 4] if d in eq and eq_dates.index(d) >= 4 else None
        avg_eq = (eq[d] + eq[prev_eq]) / 2 if prev_eq else None
        hist.append(clean({
            "p": d, "k": f"{d[:4]}年{KINDS[d[5:]]}", "eps": eps_c[d], "rev": rev_c.get(d), "np": ni_c.get(d),
            "roe": ratio(ttm_ni, avg_eq) * 100 if ratio(ttm_ni, avg_eq) is not None else None,
            "debt": ratio(liab.get(d), assets.get(d)) * 100 if ratio(liab.get(d), assets.get(d)) is not None else None,
            "ocf": cf.get("CashFlowsFromOperatingActivities", {}).get(d),
            "gpm": ratio(gp_c.get(d), rev_c.get(d)) * 100 if ratio(gp_c.get(d), rev_c.get(d)) is not None else None,
            "npm": ratio(ni_c.get(d), rev_c.get(d)) * 100 if ratio(ni_c.get(d), rev_c.get(d)) is not None else None,
            "roa": ratio(ttm_ni, assets.get(d)) * 100 if ratio(ttm_ni, assets.get(d)) is not None else None,
            "cr": ratio(ca.get(d), cl.get(d)),
        }))
    if not hist:
        return {}
    top = hist[0]
    eps_s = inc["EPS"]
    return clean({
        "period": top["p"], "kind": top["k"], "cur": CUR, "org": industry, "hist": hist,
        "rev": top.get("rev"), "np": top.get("np"), "eps": top.get("eps"), "roe": top.get("roe"), "debt": top.get("debt"),
        "ocf": top.get("ocf"), "gpm": top.get("gpm"), "npm": top.get("npm"), "roa": top.get("roa"), "cr": top.get("cr"),
        "ttm_eps": _ttm(eps_s, top["p"]),
    })


def tw_pbr(code: str) -> Optional[float]:
    """最近一個交易日的股價淨值比（FinMind，與當日股價同口徑）。"""
    start = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
    rows = get("TaiwanStockPER", code, start)
    return rows[-1].get("PBR") if rows else None


def _kind(label: str) -> str:
    """FinMind 年度標籤（如「114年第4季」「114年」「114年上半年」）→ 類別：季配為 Q1～Q4，半年配「中期」，其餘「年度」。
    Q4 同時是該財年的收尾，fin_trend 以它計算上財年全年股息。"""
    tail = label.split("年", 1)[-1]
    m = re.search(r"第\s*([1-4一二三四])\s*季", tail)
    if m:
        return "Q" + ("1234"["1234一二三四".index(m.group(1)) % 4])
    if ("上半" in tail or "期中" in tail) and "下半" not in tail:
        return "中期"
    return "年度"


def q_label(kind: Optional[str]) -> Optional[str]:
    """報表類別 → 台股慣用顯示：2026年中报 → 2026 Q2（累計報表，Q4 即全年）。內部計算仍用港股相容字串。"""
    m = re.fullmatch(r"(\d{4})年(一季报|中报|三季报|年报)", kind or "")
    return f"{m.group(1)} Q{ {'一季报': 1, '中报': 2, '三季报': 3, '年报': 4}[m.group(2)] }" if m else kind


def tw_dividends(code: str, years: int = 10) -> List[Dict[str, Any]]:
    """現金股利歷次分配（新到舊），格式同 eastmoney.hk_dividends；hkd 欄在台股就是新台幣金額（沿用欄名以重用趨勢計算）。
    只列有現金股利的紀錄，純配股不列。shares 為參與分配股數，供推算已付股息。"""
    rows = get("TaiwanStockDividend", code, f"{datetime.date.today().year - years}-01-01")
    out = []
    for r in rows:
        amt = (r.get("CashEarningsDistribution") or 0) + (r.get("CashStatutorySurplus") or 0)
        m = re.match(r"(\d+)年", r.get("year") or "")
        if amt <= 0 or not m:
            continue
        out.append({
            "nd": r.get("AnnouncementDate") or None, "year": str(int(m.group(1)) + 1911), "kind": _kind(r["year"]),
            "ex": r.get("CashExDividendTradingDate") or None, "pay": r.get("CashDividendPaymentDate") or None,
            "amt": round(amt, 4), "cur": CUR, "hkd": round(amt, 4), "shares": r.get("ParticipateDistributionOfTotalShares"),
        })
    return sorted(out, key=lambda d: (d["ex"] or d["nd"] or ""), reverse=True)


def tw_cashflow(code: str, divs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """最近一個完整財年的經營現金流與資本支出；已付股息＝該年內付款的每股現金股利 × 參與股數（近似，FinMind 現金流量表沒有此項）。"""
    cf = series(get("TaiwanStockCashFlowsStatement", code, f"{datetime.date.today().year - 4}-01-01"))
    ocf, capex = cf.get("CashFlowsFromOperatingActivities", {}), cf.get("PropertyAndPlantAndEquipment", {})
    for d in sorted((x for x in ocf if x.endswith("12-31")), reverse=True):
        if d in capex:
            y = d[:4]
            paid = sum(x["amt"] * (x.get("shares") or 0) for x in divs if (x.get("pay") or "")[:4] == y)
            return {"fy": y, "ocf": ocf[d], "capex": abs(capex[d]), "paid": paid}
    return {}
