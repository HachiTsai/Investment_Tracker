"""ETF 成分股股利與財報明細頁的共用渲染（港股 00882 與台股 ETF 共用同一份範本）。

範本在 references/constituents_template.html，市場差異（幣別、資料來源說明、金融業判斷、有無中期配息）
全放在 PROFILES；新增市場只要加一份設定，不必改範本。
"""
import re
from pathlib import Path
from typing import Any, Dict, List

from etf_market import json_for_script

TEMPLATE = Path(__file__).resolve().parent.parent / "references" / "constituents_template.html"

# 頭條數字是成分股殖利率的權重加權平均；說明文字放在 PROFILES，Market.unit_note 可以覆寫（港股 00882 頁的頭條是每單位台幣股利）
YIELD_NOTE = "成分股近 12 月殖利率的權重加權平均（毛額，未含 ETF 費用與稅，持股以外部位視為 0）"

PROFILES: Dict[str, Dict[str, Any]] = {
    "hk": dict(
        cur="港元", src="東方財富", unit_note="以今日持股推算的每單位年股利（台幣，毛額）", fin_orgs=["银行", "保险", "证券"], mid=True, split_fin=True,
        qnote="港股沒有季配，單季配息率以最近一期（中期或年度）為準。",
        fxnote="用同公司其他筆分配的隱含匯率近似換算，沒有就用全部成分股的人民幣對港幣中位數。",
        ynote="殖利率以近 12 月股息除以 Google Finance 股價（股息來自東方財富，採最近幾次定期分配）",
        ysrc="Google Finance 股價、東方財富股息，港元"),
    "tw": dict(
        cur="新台幣元", src="FinMind", unit_note=YIELD_NOTE, fin_orgs=["金融保險", "金融保險業"], mid=False, split_fin=False,
        qnote="台股配息頻率不一（年配、半年配、季配），單季配息率以最近一次宣派為準。",
        fxnote="台股股息與報表同為新台幣，不需換算。",
        ynote="殖利率以近 12 月股息除以 Google Finance 股價（股息來自 FinMind，採最近幾次定期分配）",
        ysrc="Google Finance 股價、FinMind 股息，新台幣元"),
}


def render(profile: str, etf: str, ncomp: int, data: List[dict], miss: List[dict], fin: Dict[str, Any],
           asof: str, n: int, top: str, unit: str, nav: str = "", unit_note: str = "") -> str:
    """把資料與市場設定代入範本。佔位符皆為 __NAME__，缺任何一個會讓 assert 失敗，避免漏填。"""
    p = PROFILES[profile]
    dump = json_for_script
    page = TEMPLATE.read_text(encoding="utf-8")
    pairs = [
        ("__DATA__", dump(data)), ("__MISS__", dump(miss)), ("__FIN__", dump(fin)),
        ("__QNOTE__", p["qnote"]), ("__FXNOTE__", p["fxnote"]), ("__YNOTE__", p["ynote"]), ("__YSRC__", p["ysrc"]),
        ("__FINORGS__", dump(p["fin_orgs"])), ("__MID__", "true" if p["mid"] else "false"), ("__SPLIT__", "true" if p["split_fin"] else "false"),
        ("__ASOF__", asof), ("__NAV__", nav), ("__N__", str(n)), ("__TOP__", top), ("__UNIT__", unit), ("__UNITNOTE__", unit_note or p["unit_note"]),
        ("__NCOMP__", str(ncomp)), ("__ETF__", etf), ("__CUR__", p["cur"]), ("__SRC__", p["src"]),
    ]
    for k, v in pairs:
        page = page.replace(k, v)
    left = sorted(set(re.findall(r"__[A-Z0-9]+__", page)))
    assert not left, f"範本還有未填的佔位符：{left}"
    return page
