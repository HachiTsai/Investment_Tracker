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
    ocf, np_ = top.get("ocf"), top.get("np")
    if not financial and ocf is not None:
        if ocf < 0:
            add("經營現金流為負", "down")
        elif np_ and np_ > 0 and ocf < np_ * 0.5:
            add("經營現金流不到淨利一半", "warn")
    if fin.get("payout") and fin["payout"] > 100:
        add(f"配發率 {fin['payout']:.0f}%，股息超過盈餘", "warn")
    return dict(fin, hist=rows, qeps=top.get("qeps"), yoy_rev=top["yoy_rev"], yoy_np=top["yoy_np"], yoy_q=yoy_q,
                roe_chg=roe_chg, debt_chg=debt_chg, sigs=sigs)
