#!/usr/bin/env python3
"""台股 ETF 成分股股利與財報明細頁。用法：python3 etf_table.py <ETF代號> <輸出html> [輸出json]

持股來自 MoneyDJ（etf_holdings_scraper）；股價 Google Finance（price-dividend-fetcher，Yahoo／證交所／櫃買備援）；
財報與配息 FinMind（fundamental-analyzer 的 finmind_detail，格式同港股，趨勢計算共用 fin_trend）。
每一步獨立失敗：單檔缺資料只讓該欄空白並記在輸出的 errors，不中斷整頁。
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, "..", "..")
for sub in ("fundamental-analyzer", "price-dividend-fetcher", "tw-etf-fetcher"):
    sys.path.insert(0, os.path.join(SKILLS, sub, "scripts"))
import etf_holdings_scraper  # noqa: E402
import etf_market  # noqa: E402
import etf_page  # noqa: E402
import fetch as price_fetch  # noqa: E402
from fetchers import finmind_detail  # noqa: E402
from fin_trend import add_cashflow, add_dividends, add_valuation, enrich, ttm_dividend, valuation_position  # noqa: E402


def fetch_stock(code: str, name: str, industry: Optional[str], today: date) -> Dict[str, Any]:
    """單檔個股（與 ETF 無關，可跨 ETF 共用）：股價、財報、配息、估值。每步各自 try，互不牽連。"""
    errs: List[str] = []

    def step(name_, fn, default=None):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name_}:{type(e).__name__}")
            return default

    px = step("price", lambda: float(price_fetch.get_price("TPE:" + code)["price"]))
    f = step("financials", lambda: enrich(finmind_detail.tw_detail(code, industry)), {}) or {}
    divs = step("dividends", lambda: finmind_detail.tw_dividends(code), []) or []
    pbr = step("pbr", lambda: finmind_detail.tw_pbr(code))
    if f:
        cf = step("cashflow", lambda: finmind_detail.tw_cashflow(code, divs), {})
        f = add_cashflow(f, cf) if cf else f
        ttm_eps = f.get("ttm_eps")
        if px and ttm_eps and ttm_eps > 0:
            f["pe"] = round(px / ttm_eps, 1)
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
    lfy = f.get("fy_hkd") or 0.0
    out: Dict[str, Any] = dict(c=code, n=name, px=px, ttm=ttm, lfy=lfy, i26="", p25="", cmp="", errs=errs)
    if px:
        out["y"] = round(ttm / px * 100, 2)
        out["chg"] = round((ttm / lfy - 1) * 100, 1) if lfy else 0
    f.pop("ttm_eps", None)
    if f:  # 計算完成後才換成台股顯示：2026 Q2；配息類別已是 Q1～Q4
        f["kind"] = finmind_detail.q_label(f.get("kind"))
        f["hist"] = [dict(h, k=finmind_detail.q_label(h.get("k"))) for h in f.get("hist", [])]
    out["f"] = f
    return out


def _tw_code(symbol: str) -> Optional[str]:
    """台股個股代號：去掉國別後綴後為純數字才算；美股、現金、期貨等回 None。"""
    code = etf_market.pure_code(symbol)
    return code if code.isdigit() else None


# 台股是目前唯一的市場實作。持股與個股用 lambda 轉接，測試替換模組上的函式時仍會生效。
# 限流與健康門檻沿用 etf_market 的預設值；其他市場在各自的 Market 上覆寫 limits、gate。
TW = etf_market.Market(
    code="TW", name="台股", profile="tw", currency="TWD",
    parse_code=_tw_code,
    holdings=lambda etf: etf_holdings_scraper.fetch_etf_holdings(etf),
    stock=lambda code, name, industry, today: fetch_stock(code, name, industry, today),
    industry=lambda: finmind_detail.industries(),
    source_note="財報與配息來自 FinMind，股價 Google Finance",
)


def tw_stocks(holdings: Dict[str, Any]) -> List[Dict[str, Any]]:
    return etf_market.market_stocks(TW, holdings)


RETRY_ON = ("financials", "dividends", "pbr")  # 限流造成的失敗（FinMind 回錯誤）才補抓


def _retryable(g: Dict[str, Any]) -> bool:
    return any(e.startswith(RETRY_ON) for e in g["errs"])


def build_pool(codes: Dict[str, str], today: Optional[date] = None, workers: Optional[int] = None,
               market: etf_market.Market = TW, deadline: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """資料池：{代號: 名稱} → {代號: 個股結果}。每檔只抓一次，多個 ETF 共用。
    deadline 是 time.monotonic() 的時刻，預設為現在起算的市場總時間上限；超過就拋出 TimeLimitExceeded，不回傳部分結果。"""
    today = today or date.today()
    limits = market.limits
    deadline = time.monotonic() + limits.max_seconds if deadline is None else deadline
    try:
        industry = market.industry()
    except Exception:  # noqa: BLE001  產業別抓不到只影響金融股判斷
        industry = {}
    ex = ThreadPoolExecutor(workers or limits.workers)
    try:
        futures = [ex.submit(market.stock, c, n, industry.get(c), today) for c, n in codes.items()]
        _, pending = wait(futures, timeout=max(0.0, deadline - time.monotonic()))
        if pending:
            raise etf_market.TimeLimitExceeded(f"資料池抓取超過總時間上限 {limits.max_seconds:g} 秒，仍有 {len(pending)} 檔未完成")
        got = [f.result() for f in futures]
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    pool = {g["c"]: g for g in got}
    # 限流造成的失敗退避後單執行緒補抓；成功的請求有快取，不會重複打
    for code in [c for c, g in pool.items() if _retryable(g)]:
        for _ in range(limits.retries):
            if time.monotonic() + limits.retry_wait > deadline:
                raise etf_market.TimeLimitExceeded(f"補抓超過總時間上限 {limits.max_seconds:g} 秒")
            time.sleep(limits.retry_wait)
            again = market.stock(code, pool[code]["n"], industry.get(code), today)
            if len(again["errs"]) < len(pool[code]["errs"]):
                pool[code] = again
            if not _retryable(pool[code]):
                break
    if market.finish:  # 跨檔步驟（港股的人民幣匯率中位數）在所有個股與補抓都完成後才執行
        pool = market.finish(pool, today)
    return pool


def build_page(etf: str, holdings: Dict[str, Any], pool: Dict[str, Dict[str, Any]], today: date, nav: str = "",
               market: etf_market.Market = TW) -> Dict[str, Any]:
    """由持股與資料池組出單一 ETF 的頁面與摘要。"""
    stocks = etf_market.market_stocks(market, holdings)
    rows = []
    for c in stocks:
        g = pool[market.parse_code(c["symbol"])]
        rows.append(dict({k: v for k, v in g.items() if k not in ("f", "errs")}, w=c["weight_pct"], q=int(c.get("shares") or 0)))
    ok = [r for r in rows if r["px"]]
    fin = {r["c"]: pool[r["c"]]["f"] for r in rows if pool[r["c"]]["f"]}
    wsum = sum(r["w"] for r in ok) or 1
    wy = sum(r["w"] * r["y"] for r in ok) / wsum if ok else 0.0
    top = max(ok, key=lambda r: r["w"])
    keys = ("c", "n", "w", "q", "px", "ttm", "lfy", "chg", "y", "i26", "p25", "cmp")
    rows_out = [{k: r[k] for k in keys} for r in ok]
    miss = [dict(c=r["c"], n=r["n"], w=r["w"], px=r["px"]) for r in rows if not r["px"]]
    partial = holdings.get("total_weight_pct", 0.0) if etf_market.coverage_label(holdings) == "partial" else None
    page = etf_page.render(market.profile, etf, len(stocks), rows_out, miss, fin, f"{today.isoformat()}（持股 {holdings['as_of_date']}，{holdings['source']}）",
                           len(ok), f'{top["n"]} {top["w"]}%', f"{wy:.2f}%", nav=nav, unit_note=market.unit_note, partial_total=partial)
    errors = {r["c"]: pool[r["c"]]["errs"] for r in rows if pool[r["c"]]["errs"]}
    summary = dict(etf=etf, rows=len(ok), holdings=len(stocks), weight_pct=holdings.get("total_weight_pct"), no_price=[m["c"] for m in miss],
                   no_fin=[r["c"] for r in rows if not pool[r["c"]]["f"]], errors=errors, weighted_yield_pct=round(wy, 2))
    return dict(page=page, summary=summary, rows=rows_out, fin=fin)


def build(etf: str, today: Optional[date] = None, holdings: Optional[Dict[str, Any]] = None,
          market: etf_market.Market = TW) -> Dict[str, Any]:
    """單一 ETF：抓持股、抓成分股資料池、組頁面。"""
    today = today or date.today()
    holdings = holdings or market.holdings(etf)
    codes = {market.parse_code(c["symbol"]): c["name"] for c in etf_market.market_stocks(market, holdings)}
    pool = build_pool(codes, today, market=market)
    return build_page(etf, holdings, pool, today, market=market)


def main(argv: List[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    try:
        r = build(argv[1].upper())
    except etf_market.TimeLimitExceeded as e:
        print(f"❌ [Time Limit] {e}，未寫入任何檔案", file=sys.stderr)
        return 1
    open(argv[2], "w", encoding="utf-8").write(r["page"])
    print(json.dumps(r["summary"], ensure_ascii=False))
    if len(argv) > 3:
        json.dump(dict(summary=r["summary"], rows=r["rows"], fin=r["fin"]), open(argv[3], "w", encoding="utf-8"), ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
