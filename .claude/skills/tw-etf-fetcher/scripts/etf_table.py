#!/usr/bin/env python3
"""台股 ETF 成分股股利與財報明細頁。用法：python3 etf_table.py <ETF代號> <輸出html> [輸出json]

持股來自 MoneyDJ（etf_holdings_scraper）；股價 Google Finance（price-dividend-fetcher，Yahoo／證交所／櫃買備援）；
財報與配息 FinMind（fundamental-analyzer 的 finmind_detail，格式同港股，趨勢計算共用 fin_trend）。
每一步獨立失敗：單檔缺資料只讓該欄空白並記在輸出的 errors，不中斷整頁。
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, "..", "..")
for sub in ("fundamental-analyzer", "price-dividend-fetcher", "tw-etf-fetcher"):
    sys.path.insert(0, os.path.join(SKILLS, sub, "scripts"))
import etf_holdings_scraper  # noqa: E402
import etf_page  # noqa: E402
import fetch as price_fetch  # noqa: E402
from fetchers import finmind_detail  # noqa: E402
from fin_trend import add_cashflow, add_dividends, add_valuation, enrich, ttm_dividend, valuation_position  # noqa: E402


def one(c: Dict[str, Any], industry: Dict[str, str], today: date) -> Dict[str, Any]:
    """單檔：回傳 d（表格列）、f（財報＋配息欄位）、errs（失敗步驟）。每步各自 try，互不牽連。"""
    code = c["symbol"].split(".")[0]
    d: Dict[str, Any] = dict(c=code, n=c["name"], w=c["weight_pct"], q=int(c.get("shares") or 0), px=None)
    errs: List[str] = []

    def step(name, fn, default=None):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name}:{type(e).__name__}")
            return default

    d["px"] = step("price", lambda: float(price_fetch.get_price("TPE:" + code)["price"]))
    f = step("financials", lambda: enrich(finmind_detail.tw_detail(code, industry.get(code))), {}) or {}
    divs = step("dividends", lambda: finmind_detail.tw_dividends(code), []) or []
    pbr = step("pbr", lambda: finmind_detail.tw_pbr(code))
    if f:
        cf = step("cashflow", lambda: finmind_detail.tw_cashflow(code, divs), {})
        f = add_cashflow(f, cf) if cf else f
        ttm_eps = f.get("ttm_eps")
        if d["px"] and ttm_eps and ttm_eps > 0:
            f["pe"] = round(d["px"] / ttm_eps, 1)
        if pbr:
            f["pb"] = pbr
        if ttm_eps and ttm_eps > 0 and divs:
            f["payout"] = round(ttm_dividend(divs, today) / ttm_eps * 100, 1)  # 近 12 月股息 ÷ 近四季 EPS
        f = add_valuation(f)
        if divs:
            f = add_dividends(f, divs, today)

    def history():
        ch = price_fetch.get_yahoo("TPE", code, "5y")["chart"]["result"][0]
        return [(datetime.fromtimestamp(t + ch["meta"].get("gmtoffset", 0), timezone.utc).date().isoformat(), v)
                for t, v in zip(ch["timestamp"], ch["indicators"]["quote"][0]["close"]) if v is not None]
    if f and divs:
        f = dict(f, **(valuation_position(step("history", history, []), divs, today) or {}))
    ttm = round(ttm_dividend(divs, today), 4) if divs else 0.0  # 沒有配息紀錄＝不配息，殖利率 0（財報頁仍列）
    d.update(ttm=ttm, lfy=f.get("fy_hkd") or 0.0, i26="", p25="", cmp="")
    if d["px"]:
        d["y"] = round(ttm / d["px"] * 100, 2)
        d["chg"] = round((ttm / d["lfy"] - 1) * 100, 1) if d["lfy"] else 0
    f.pop("ttm_eps", None)
    if f:  # 計算完成後才換成台股顯示：2026 Q2；配息類別已是 Q1～Q4
        f["kind"] = finmind_detail.q_label(f.get("kind"))
        f["hist"] = [dict(h, k=finmind_detail.q_label(h.get("k"))) for h in f.get("hist", [])]
    return dict(d=d, f=f, errs=errs)


def build(etf: str, today: Optional[date] = None, holdings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    today = today or date.today()
    holdings = holdings or etf_holdings_scraper.fetch_etf_holdings(etf)
    stocks = [c for c in holdings["constituents"] if c["symbol"].split(".")[0].isdigit()]
    try:
        industry = finmind_detail.industries()
    except Exception:  # noqa: BLE001  產業別抓不到只影響金融股判斷
        industry = {}
    with ThreadPoolExecutor(6) as ex:
        got = list(ex.map(lambda c: one(c, industry, today), stocks))
    rows = [g["d"] for g in got]
    ok = [r for r in rows if r["px"]]
    fin = {g["d"]["c"]: g["f"] for g in got if g["f"]}
    wsum = sum(r["w"] for r in ok) or 1
    wy = sum(r["w"] * r["y"] for r in ok) / wsum if ok else 0.0
    top = max(ok, key=lambda r: r["w"])
    rows_out = [dict(c=r["c"], n=r["n"], w=r["w"], q=r["q"], px=r["px"], ttm=r["ttm"], lfy=r["lfy"], chg=r["chg"], y=r["y"],
                     i26=r["i26"], p25=r["p25"], cmp=r["cmp"]) for r in ok]
    miss = [dict(c=r["c"], n=r["n"], w=r["w"], px=r["px"]) for r in rows if not r["px"]]
    page = etf_page.render("tw", etf, len(stocks), rows_out, miss, fin, f"{today.isoformat()}（持股 {holdings['as_of_date']}，{holdings['source']}）",
                           len(ok), f'{top["n"]} {top["w"]}%', f"{wy:.2f}%")
    errors = {g["d"]["c"]: g["errs"] for g in got if g["errs"]}
    summary = dict(etf=etf, rows=len(ok), holdings=len(stocks), weight_pct=holdings.get("total_weight_pct"), no_price=[m["c"] for m in miss],
                   no_fin=[g["d"]["c"] for g in got if not g["f"]], errors=errors, weighted_yield_pct=round(wy, 2))
    return dict(page=page, summary=summary, rows=rows_out, fin=fin)


def main(argv: List[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    r = build(argv[1].upper())
    open(argv[2], "w", encoding="utf-8").write(r["page"])
    print(json.dumps(r["summary"], ensure_ascii=False))
    if len(argv) > 3:
        json.dump(dict(summary=r["summary"], rows=r["rows"], fin=r["fin"]), open(argv[3], "w", encoding="utf-8"), ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
