"""成分股財報趨勢：由 hk_detail 的累計數推算單季／單期 EPS、年增與規則式訊號（事實彙整，非買賣建議）。"""
from datetime import date
from typing import Any, Dict, List, Optional

RANK = {"一季报": 1, "中报": 2, "三季报": 3, "年报": 4}


def _rank(kind: str) -> int:
    return next((v for k, v in RANK.items() if k in (kind or "")), 0)


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _prev_same_year(hist: List[Dict[str, Any]], i: int) -> Optional[Dict[str, Any]]:
    """同一會計年度內、排名較低的上一份累計報表（新到舊排序，往後找）。"""
    cur = hist[i]
    for h in hist[i + 1:]:
        gap = (_d(cur["p"]) - _d(h["p"])).days
        if gap > 200:
            return None
        if _rank(h.get("k")) < _rank(cur.get("k")):
            return h
    return None


def _year_ago(hist: List[Dict[str, Any]], i: int) -> Optional[Dict[str, Any]]:
    cur = hist[i]
    for h in hist[i + 1:]:
        if h.get("k", "")[4:] == cur.get("k", "")[4:] and 340 <= (_d(cur["p"]) - _d(h["p"])).days <= 390:
            return h
    return None


def _pct(a, b):
    return round((a / b - 1) * 100, 1) if a is not None and b not in (None, 0) and b > 0 else None


def enrich(fin: Dict[str, Any]) -> Dict[str, Any]:
    """回傳加上 qeps（單季或單期 EPS）、yoy 年增與 sigs 訊號的新字典；無歷史時原樣回傳。"""
    hist = fin.get("hist") or []
    if not hist:
        return fin
    rows = []
    for i, h in enumerate(hist):
        prev = _prev_same_year(hist, i)
        r = dict(h)
        if h.get("eps") is not None:
            r["qeps"] = round(h["eps"] - prev["eps"], 4) if prev and prev.get("eps") is not None else (h["eps"] if _rank(h.get("k")) == 1 or not prev else None)
        ya = _year_ago(hist, i)
        r["yoy_rev"] = _pct(h.get("rev"), ya.get("rev")) if ya else None
        r["yoy_np"] = _pct(h.get("np"), ya.get("np")) if ya else None
        r["_ya"] = ya
        rows.append(r)
    top = rows[0]
    ya = top.pop("_ya")
    for r in rows[1:]:
        r.pop("_ya", None)
    ya_q = None
    if ya:
        j = hist.index(next(h for h in hist if h["p"] == ya["p"] and h.get("k") == ya.get("k")))
        ya_q = rows[j].get("qeps")
    yoy_q = _pct(top.get("qeps"), ya_q)
    roe_chg = round(top["roe"] - ya["roe"], 1) if ya and top.get("roe") is not None and ya.get("roe") is not None else None
    debt_chg = round(top["debt"] - ya["debt"], 1) if ya and top.get("debt") is not None and ya.get("debt") is not None else None
    gpm_chg = round(top["gpm"] - ya["gpm"], 1) if ya and top.get("gpm") is not None and ya.get("gpm") is not None else None
    financial = fin.get("org") in ("银行", "保险", "证券")
    sigs = []

    def add(text, tone):
        sigs.append({"t": text, "tone": tone})

    if top["yoy_rev"] is not None and abs(top["yoy_rev"]) >= 5:
        add(f"營收年增減 {top['yoy_rev']:+.1f}%", "up" if top["yoy_rev"] > 0 else "down")
    if top["yoy_np"] is not None and abs(top["yoy_np"]) >= 10:
        add(f"股東淨利年增減 {top['yoy_np']:+.1f}%", "up" if top["yoy_np"] > 0 else "down")
    if yoy_q is not None and abs(yoy_q) >= 10:
        add(f"單季 EPS 較去年同期 {yoy_q:+.1f}%", "up" if yoy_q > 0 else "down")
    if roe_chg is not None and abs(roe_chg) >= 1:
        add(f"ROE 較去年同期 {roe_chg:+.1f} 個百分點", "up" if roe_chg > 0 else "down")
    if debt_chg is not None and abs(debt_chg) >= 3 and not financial:
        add(f"負債/資產較去年同期 {debt_chg:+.1f} 個百分點", "down" if debt_chg > 0 else "up")
    if gpm_chg is not None and abs(gpm_chg) >= 2 and not financial:
        add(f"毛利率較去年同期 {gpm_chg:+.1f} 個百分點", "up" if gpm_chg > 0 else "down")
    if not financial and fin.get("cr") is not None and fin["cr"] < 1:
        add(f"流動比率 {fin['cr']:.2f}，低於 1", "warn")
    ocf, np_ = top.get("ocf"), top.get("np")
    if not financial and ocf is not None:
        if ocf < 0:
            add("經營現金流為負", "down")
        elif np_ and np_ > 0 and ocf < np_ * 0.5:
            add("經營現金流不到淨利一半", "warn")
    if fin.get("payout") and fin["payout"] > 100:
        add(f"配發率 {fin['payout']:.0f}%，股息超過盈餘", "warn")
    return dict(fin, hist=rows, qeps=top.get("qeps"), yoy_rev=top["yoy_rev"], yoy_np=top["yoy_np"], yoy_q=yoy_q,
                roe_chg=roe_chg, debt_chg=debt_chg, gpm_chg=gpm_chg, sigs=sigs)


CUR = {"港币": "港元", "人民币": "人民币", "美元": "美元"}
KIND_PREFIX = {"中期": "中报", "年度": "年报", "一季度": "一季报", "三季度": "三季报"}


def _eps_of(hist, year, suffix):
    return next((h.get("eps") for h in hist if (h.get("k") or "") == f"{year}年{suffix}"), None)


def _ratio(amt, eps):
    return round(amt / eps * 100, 1) if amt is not None and eps and eps > 0 else None


def add_dividends(fin: Dict[str, Any], divs: List[Dict[str, Any]], today: date, fx_hint: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """加入歷次分配與配息率：ytd＝今年已付款（港元）、pending＝已宣派尚未付款；
    dr_cur＝最近一次宣派 ÷ 對應期間累計 EPS；dr_fy＝上一個已公布年報的該財年全部現金分配 ÷ 年報 EPS。
    股息幣別與報表幣別不同時，用同公司他筆分配的隱含匯率近似換算；同公司沒有可用的匯率時改用 fx_hint（全體成分股的中位數）；換不了就留空。EPS 為負時不算配息率。"""
    if not divs:
        return fin
    hist, cur = fin.get("hist") or [], fin.get("cur")
    ytd = sum(d["hkd"] for d in divs if d.get("pay") and d.get("hkd") and d["pay"][:4] == str(today.year) and d["pay"] <= today.isoformat())
    pending = sum(d["hkd"] for d in divs if d.get("pay") and d.get("hkd") and d["pay"] > today.isoformat())
    out = dict(fin, divs=divs[:8], ytd=round(ytd, 4), pending=round(pending, 4))
    rate = 1.0 if cur == "港元" else next((d["hkd"] / d["amt"] for d in divs if CUR.get(d.get("cur"), d.get("cur")) == cur and d.get("amt") and d.get("hkd")), (fx_hint or {}).get(cur))

    def conv(d):
        """換成報表幣別；幣別不同時用同公司他筆分配的隱含匯率（近似）。"""
        if d.get("amt") is None:
            return None
        if d["amt"] == 0 or CUR.get(d.get("cur"), d.get("cur")) == cur:
            return d["amt"]
        return d["hkd"] / rate if d.get("hkd") and rate else None

    last = divs[0]
    suffix = next((v for k, v in KIND_PREFIX.items() if k in (last.get("kind") or "")), None)
    if suffix and last.get("amt"):  # 東方財富對尚未更新的期別也標「未派發」，0 不當成真的零配息
        out["dr_cur"] = _ratio(conv(last), _eps_of(hist, last.get("year"), suffix))
        out["dr_cur_lab"] = f"{last.get('year')} {last.get('kind', '')[:2]}"
    out.update(_dps_summary(divs))
    ann = next((h for h in hist if "年报" in (h.get("k") or "")), None)
    if ann:
        y = ann["k"][:4]
        rows = [conv(d) for d in divs if d.get("year") == y and d.get("amt") is not None]
        if rows and None not in rows:
            out["dr_fy"] = _ratio(sum(rows), ann.get("eps"))
            if out["dr_fy"]:
                out["cover"] = round(100 / out["dr_fy"], 2)  # 股息覆蓋倍數＝年報 EPS ÷ 全年股息
            out["dr_fy_lab"] = f"{y} 年度"
    return {k: v for k, v in out.items() if v is not None}


def rmb_hint(all_divs: List[List[Dict[str, Any]]]) -> Dict[str, float]:
    """全體成分股人民幣分配的「港元÷人民幣」中位數，供同公司缺匯率時近似換算。"""
    rates = sorted(d["hkd"] / d["amt"] for divs in all_divs for d in divs if d.get("cur") == "人民币" and d.get("amt") and d.get("hkd"))
    return {"人民币": rates[len(rates) // 2]} if rates else {}


def _chg(a, b):
    return round((a / b - 1) * 100, 1) if a is not None and b else None


def _dps_summary(divs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """股利明細用：上一財年全年與前一財年全年股息（港元，含特別股息）、最近一次中期與去年中期的增減。"""
    out: Dict[str, Any] = {}
    fy = next((d for d in divs if "年度" in (d.get("kind") or "")), None)
    if fy and fy.get("year", "").isdigit():
        y = int(fy["year"])
        total = lambda yr: sum(d["hkd"] for d in divs if d.get("year") == str(yr) and d.get("hkd"))  # noqa: E731
        cur_, prev = total(y), total(y - 1)
        out.update(fy_lab=f"{y} 年度", fy_hkd=round(cur_, 4), fy_prev_hkd=round(prev, 4) if prev else None, fy_chg=_chg(cur_, prev))
        streak = 0
        while total(y - streak) > 0:
            streak += 1
        out["streak"] = streak  # 連續有現金股息的財年數（資料窗內最多回溯約十年）
        years = [yr for yr in range(y - 9, y) if total(yr) > 0]
        if years and cur_ > 0 and y - years[0] >= 3:
            n = y - years[0]
            out.update(cagr=round(((cur_ / total(years[0])) ** (1 / n) - 1) * 100, 1), cagr_n=n)
    h1 = next((d for d in divs if "中期" in (d.get("kind") or "")), None)
    if h1 and h1.get("year", "").isdigit():
        prev_h = next((d for d in divs if "中期" in (d.get("kind") or "") and d.get("year") == str(int(h1["year"]) - 1)), None)
        out.update(h_lab=f"{h1['year']} 中期", h_hkd=h1.get("hkd"), h_pay=h1.get("pay"), h_ex=h1.get("ex"),
                   h_prev_hkd=prev_h.get("hkd") if prev_h else None,
                   h_chg=_chg(h1.get("hkd"), prev_h.get("hkd") if prev_h else None) if h1.get("hkd") else None)
    return out


FIN_ORGS = ("银行", "保险", "证券")


def add_cashflow(fin: Dict[str, Any], cf: Dict[str, Any]) -> Dict[str, Any]:
    """加入自由現金流（經營現金流減資本支出）與其對全年已付股息的覆蓋倍數（fcf_cover）。
    金融業的經營現金流含存貸款變動，沒有意義，不算。已付股息為零時不算倍數。"""
    if not fin or not cf or any(o in (fin.get("org") or "") for o in FIN_ORGS):
        return fin
    fcf = cf["ocf"] - cf["capex"]
    out = dict(fin, fcf_fy=cf["fy"], fcf=fcf)
    if cf["paid"] > 0:
        out["fcf_cover"] = round(fcf / cf["paid"], 2)
    return out


def add_valuation(fin: Dict[str, Any], required_roe: float = 10.0) -> Dict[str, Any]:
    """PB 相對合理值：合理 PB＝ROE ÷ 要求報酬率（預設 10%，假設）；pb_fair＝實際 PB ÷ 合理 PB，
    低於 1 代表相對 ROE 偏便宜。ROE 或 PB 缺或 ROE 非正時不算。"""
    roe, pb = fin.get("roe"), fin.get("pb")
    if not fin or not roe or not pb or roe <= 0:
        return fin
    return dict(fin, pb_fair=round(pb / (roe / required_roe), 2))
