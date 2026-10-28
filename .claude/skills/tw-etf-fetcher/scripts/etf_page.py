"""ETF 成分股股利與財報明細頁的共用渲染（港股 00882 與台股 ETF 共用同一份範本）。

範本在 references/constituents_template.html，市場差異（幣別、資料來源說明、金融業判斷、有無中期配息）
全放在 PROFILES；新增市場只要加一份設定，不必改範本。
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from etf_market import json_for_script

TEMPLATE = Path(__file__).resolve().parent.parent / "references" / "constituents_template.html"
POOL_SECTION = Path(__file__).resolve().parent.parent / "references" / "pool_section.html"  # 收益平準金分頁：分頁鈕、頁面、腳本三段

# 頭條數字是成分股殖利率的權重加權平均；說明文字放在 PROFILES，Market.unit_note 可以覆寫（港股 00882 頁的頭條是每單位台幣股利）
YIELD_NOTE = "成分股近 12 月殖利率的權重加權平均（毛額，未含 ETF 費用與稅，持股以外部位視為 0）"
PER_UNIT_NOTE = "以今日持股推算的每單位年股利（台幣，毛額）：Σ 持股數 × 近 12 月股息 × 匯率 ÷ 在外流通單位數"

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
    "us": dict(
        cur="美元", src="SEC EDGAR", unit_note=YIELD_NOTE, fin_orgs=[], mid=False, split_fin=False,
        qnote="美股這一頁只用 10-K 年報，沒有季度 EPS；股利只有除息日與金額（Yahoo Finance），沒有付款日與類別，「當年度已配發」與「當期配息率」留白。",
        fxnote="股價、股利與財報都是美元，比率不需換算，台幣只作參考。",
        ynote="殖利率以近 12 月股息除以 Yahoo Finance 股價（股息依除息日計）",
        ysrc="Yahoo Finance 股價與股息，美元；財報 SEC EDGAR 10-K，美元"),
    "jp": dict(
        cur="日圓", src="EDINET", unit_note=YIELD_NOTE, fin_orgs=[], mid=False, split_fin=False,
        qnote="日股這一頁只用有價證券報告書（年度），沒有季度 EPS；股利只有除息日與金額（Yahoo Finance），沒有付款日與類別，「當年度已配發」與「當期配息率」留白。",
        fxnote="股價、股利與財報都是日圓，比率不需換算，台幣只作參考。",
        ynote="殖利率以近 12 月股息除以股價（股價先 Google Finance，失敗時改用 Yahoo Finance；股息依除息日計）",
        ysrc="Google Finance 股價（Yahoo Finance 備援）與 Yahoo Finance 股息，日圓；財報 EDINET 有價證券報告書，日圓"),
}


def fx_time(fx: Dict[str, Any]) -> str:
    """報價時間換成 UTC 的可讀格式，例如 2026-10-26 17:10 UTC。"""
    return datetime.fromisoformat(fx["as_of"]).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def fx_parts(fx: Optional[Dict[str, Any]], cur: str) -> Tuple[str, str]:
    """外幣頁的台幣參考值：個股視窗多兩張卡（股價、近 12 月股息約新台幣），頁尾多一行匯率來源與報價時間。
    沒有匯率（台股）就回傳兩個空字串，輸出與沒有這項功能時位元組相同。"""
    if not fx:
        return "", ""
    r = repr(float(fx["rate"]))
    kp = (f",[x.px==null?'':fx(x.px*{r},2)+' 元','股價（約新台幣）',''],"
          f"[x.ttm==null?'':fx(x.ttm*{r},3)+' 元','近 12 月股息（約新台幣）','']")
    li = (f"<li>台幣參考值：1 {cur} ≈ {fx['rate']:.4f} 元新台幣，匯率來自 {fx['source']}，報價時間 {fx_time(fx)}。"
          "個股視窗與頭條的台幣數字只供比較，不是實際成交或入帳金額。</li>\n")
    return kp, li


def pool_parts(pool: Optional[Dict[str, Any]], etf: str) -> Tuple[str, str, str]:
    """收益平準金分頁的三段 HTML（分頁鈕、頁面、腳本）。pool 是 {"rows": [[日期, 淨值, 收益平準金, 資本平準金], …],
    "events": [nav_composition.distribution_events 的結果]}；沒有資料就三段皆空，頁面與沒有這項功能時位元組相同。"""
    if not pool or not pool.get("rows"):
        return "", "", ""
    tab, page, js = POOL_SECTION.read_text(encoding="utf-8").split("\n<!--@@-->\n")
    rows = pool["rows"]
    fill = {"__PASOF__": rows[-1][0], "__PFIRST__": rows[0][0], "__PDATA__": json_for_script(dict(rows=rows, events=pool.get("events", []))),
            "__PETF__": etf}
    for k, v in fill.items():
        page, js = page.replace(k, v), js.replace(k, v)
    return tab.rstrip("\n"), page, js.rstrip("\n")


def render(profile: str, etf: str, ncomp: int, data: List[dict], miss: List[dict], fin: Dict[str, Any],
           asof: str, n: int, top: str, unit: str, nav: str = "", unit_note: str = "", partial_total: Optional[float] = None,
           fx: Optional[Dict[str, Any]] = None, pool: Optional[Dict[str, Any]] = None) -> str:
    """把資料與市場設定代入範本。佔位符皆為 __NAME__，缺任何一個會讓 assert 失敗，避免漏填。
    partial_total 是持股只涵蓋部分基金時的合計權重（%）：整體本益比卡片改寫成「占基金」，不寫成「權重 100%」；完整持股不傳，輸出與原本相同。
    asof 是空白時，頁首不放資料日期，付款日的說明也略去（台股頁，2026-10-27）。
    fx 是外幣頁的匯率（etf_fx.fetch_rate 的結果）；台股不傳，輸出與沒有這項功能時位元組相同。
    pool 是每日淨值組成（見 pool_parts）；只有港股 00882 頁傳入，會多一個「收益平準金」分頁，不傳則輸出不變。"""
    p = PROFILES[profile]
    dump = json_for_script
    page = TEMPLATE.read_text(encoding="utf-8")
    partial = partial_total is not None
    kp_fx, li_fx = fx_parts(fx, p["cur"])
    pool_tab, pool_page, pool_js = pool_parts(pool, etf)
    pairs = [
        ("__DATA__", dump(data)), ("__MISS__", dump(miss)), ("__FIN__", dump(fin)),
        ("__QNOTE__", p["qnote"]), ("__FXNOTE__", p["fxnote"]), ("__YNOTE__", p["ynote"]), ("__YSRC__", p["ysrc"]),
        ("__FINORGS__", dump(p["fin_orgs"])), ("__MID__", "true" if p["mid"] else "false"), ("__SPLIT__", "true" if p["split_fin"] else "false"),
        ("__ASOFLINE__", f'<p class="mut">資料日期 {asof}。</p>' if asof else ""), ("__CUTOFF__", "（付款日不晚於資料日期）" if asof else ""),
        ("__NAV__", nav), ("__N__", str(n)), ("__TOP__", top), ("__UNIT__", unit), ("__UNITNOTE__", unit_note or p["unit_note"]),
        ("__NCOMP__", str(ncomp)), ("__ETF__", etf), ("__CUR__", p["cur"]), ("__SRC__", p["src"]),
        ("__PARTIAL__", f"（只含前幾大持股，合計約占基金 {partial_total:.1f}%，其餘持股未納入計算）" if partial else ""),
        ("__WLABEL__", "占基金 " if partial else "權重 "),
        ("__WEXPR__", "pa.w.toFixed(1)" if partial else "(pa.w/tw*100).toFixed(0)"),
        ("__FXKP__", kp_fx), ("__FXLI__", li_fx),
        ("__POOLTAB__", pool_tab), ("__POOLPAGE__", pool_page), ("__POOLJS__", pool_js),
    ]
    for k, v in pairs:
        page = page.replace(k, v)
    left = sorted(set(re.findall(r"__[A-Z0-9]+__", page)))
    assert not left, f"範本還有未填的佔位符：{left}"
    return page
