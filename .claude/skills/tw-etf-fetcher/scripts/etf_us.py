#!/usr/bin/env python3
"""美股成分股市場介面（美股 ETF 的前幾大持股，Yahoo Finance）。

持股來自 yfinance 的 funds_data.top_holdings，只有前幾大、不是完整持股：coverage 為 partial，頁面與 pool.json 標示來源與抓取日。
股價與股利來自 Yahoo Finance（price-dividend-fetcher），財報來自 SEC EDGAR 的 10-K 年度數字（companyfacts），
全年數字的判斷沿用 fundamental-analyzer 的 fetchers.sec。每一步獨立失敗：單檔缺資料只讓該欄空白並記在 errs。
用法：`etf_pool.py outdir --market us --etfs VOO`（美股沒有模型卡片可自動探索，要用 --etfs 指定）。
"""
import functools
import math
import os
import re
import sys
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, "..", "..")
for sub in ("fundamental-analyzer", "price-dividend-fetcher"):
    sys.path.insert(0, os.path.join(SKILLS, sub, "scripts"))
import etf_market  # noqa: E402
import etf_page  # noqa: E402
import fetch as price_fetch  # noqa: E402
from fetchers import SEC_UA, http_json  # noqa: E402
from fetchers.sec import full_year  # noqa: E402
from fin_trend import add_cashflow, add_valuation, enrich  # noqa: E402

TOP_SOURCE = "Yahoo Finance 前幾大持股（抓取日）"
HIST_YEARS = 5
HDR = {"User-Agent": SEC_UA}
NOT_STOCK = frozenset({"CASH", "USD", "TWD", "HKD", "CNY", "JPY", "EUR"})  # 現金與幣別，不是個股
# 可帶交易所前綴（NASDAQ:NVDA）或 .US 後綴；類別股的 . 與 - 都接受（BRK.B、BRK-B）
_US_CODE = re.compile(r"(?:(?:NASDAQ|NYSE|NYSEARCA|NYSEAMERICAN|AMEX):)?([A-Z]{1,5}(?:[.-][A-Z])?)(?:\.US)?", re.IGNORECASE)

# 欄位 → (us-gaap 候選標籤, 單位)；同一欄位的候選標籤取最新申報的全年數字
ANNUAL = dict(
    eps=(("EarningsPerShareDiluted",), "USD/shares"),
    rev=(("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"), "USD"),
    np=(("NetIncomeLoss", "ProfitLoss"), "USD"),  # 母公司淨利缺值（部分公司改報 ProfitLoss）時退回含非控制權益的數字
    gp=(("GrossProfit",), "USD"),
    eq=(("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"), "USD"),  # 母公司權益缺值時退回含非控制權益
    liab=(("Liabilities",), "USD"),
    assets=(("Assets",), "USD"),
    ocf=(("NetCashProvidedByUsedInOperatingActivities",), "USD"),
    capex=(("PaymentsToAcquirePropertyPlantAndEquipment",), "USD"),
    paid=(("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"), "USD"),
)


def parse_us_code(symbol: str) -> Optional[str]:
    """美股原始代號 → 純代號（類別股的 . 換成 -，與 Yahoo 相同）；台股、港股、現金與幣別回 None。"""
    m = _US_CODE.fullmatch(str(symbol).strip())
    if not m:
        return None
    code = m.group(1).upper().replace(".", "-")
    return None if code in NOT_STOCK else code


def _top_holdings_rows(etf: str) -> List[Tuple[str, str, float]]:
    """yfinance 的前幾大持股：(原始代號, 名稱, 權重%)。測試時替換這個函式，不連網。"""
    import yfinance as yf  # 延後匯入：只有抓美股持股時才需要

    fd = yf.Ticker(etf).funds_data
    df = None if fd is None else fd.top_holdings
    if df is None:
        return []
    return [(str(sym), str(row.get("Name", sym)), float(row.get("Holding Percent", 0.0)) * 100.0) for sym, row in df.iterrows()]


def fetch_holdings(etf: str) -> Dict[str, Any]:
    """ETF 的美股前幾大持股。只留美股個股列（現金、幣別與權重為 NaN 的列不列入）；來源是 Yahoo 前幾大，coverage 為 partial。"""
    cons = []
    for sym, name, w in _top_holdings_rows(etf):
        code = parse_us_code(sym)
        if code is not None and math.isfinite(w):
            cons.append(dict(symbol=code, name=name, weight_pct=round(w, 2), shares=None))
    return dict(ticker=etf, as_of_date=date.today().isoformat(), source=TOP_SOURCE, total_count=len(cons),
                total_weight_pct=round(sum(c["weight_pct"] for c in cons), 2), constituents=cons)


def _sec_json(url: str) -> Any:
    """SEC 的 JSON 回應；必須帶含聯絡資訊的 User-Agent（SEC_UA）。"""
    return http_json(url, HDR)


@functools.lru_cache(maxsize=None)
def cik_map() -> Dict[str, int]:
    """SEC 代號對照表：代號 → CIK（整段程序只抓一次）。"""
    return {v["ticker"]: int(v["cik_str"]) for v in _sec_json("https://www.sec.gov/files/company_tickers.json").values()}


def _annual(facts: Dict[str, Any], tags: Tuple[str, ...], unit: str) -> Dict[str, float]:
    """10-K 全年數字：{期末日: 值}。候選標籤依序，同一期末取第一個有值的標籤（母公司數字優先）；同一標籤的流量科目排除季度值（full_year），
    同一期末取最後申報的那一筆（重編後的數字）。"""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    out: Dict[str, float] = {}
    for tag in tags:
        best: Dict[str, Tuple[str, float]] = {}
        for r in gaap.get(tag, {}).get("units", {}).get(unit) or []:
            if r.get("form") == "10-K" and r.get("fp") == "FY" and r.get("end") and r.get("val") is not None and full_year(r):
                if r["end"] not in best or r.get("filed", "") > best[r["end"]][0]:
                    best[r["end"]] = (r.get("filed", ""), r["val"])
        for end, (_, val) in best.items():
            out.setdefault(end, val)
    return out


def _shares_outstanding(facts: Dict[str, Any]) -> Optional[float]:
    """最新的已發行股數（dei 的 EntityCommonStockSharesOutstanding）。"""
    dei = (facts.get("facts") or {}).get("dei") or {}
    rows = [r for r in dei.get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares") or [] if r.get("val")]
    return max(rows, key=lambda r: r.get("end", ""))["val"] if rows else None


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """a ÷ b 的百分比（一位小數）；分母缺或不為正就留空（負的股東權益不算 ROE）。"""
    return round(a / b * 100, 1) if a is not None and b is not None and b > 0 else None


def us_financials(code: str, px: Optional[float], ttm: float) -> Dict[str, Any]:
    """SEC 10-K 近幾個財年的 EPS、營收、淨利、ROE、負債比、毛利率、經營現金流；最新年報算出 PE、PB、配發率與自由現金流覆蓋。
    股價缺就不算 PE、PB；沒有任何年報數字就回空字典（頁面列為缺財報）；代號不在 SEC 對照表就拋例外。"""
    cik = cik_map().get(code)
    if cik is None:
        raise ValueError(f"SEC 代號對照表沒有 {code}")
    facts = _sec_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
    s = {k: _annual(facts, tags, unit) for k, (tags, unit) in ANNUAL.items()}
    periods = sorted(set(s["rev"]) | set(s["np"]) | set(s["eps"]), reverse=True)[:HIST_YEARS]
    if not periods:
        return {}
    hist = []
    for p in periods:
        v = {k: s[k].get(p) for k in s}
        row = dict(p=p, k=f"{p[:4]}年报", eps=v["eps"], rev=v["rev"], np=v["np"], ocf=v["ocf"],
                   roe=_pct(v["np"], v["eq"]), debt=_pct(v["liab"], v["assets"]), gpm=_pct(v["gp"], v["rev"]))
        hist.append({k: val for k, val in row.items() if val is not None})
    top, p0 = hist[0], periods[0]
    f = enrich(dict(kind="10-K 年報", cur="美元", hist=hist, eps=top.get("eps"), roe=top.get("roe"),
                    rev=top.get("rev"), np=top.get("np"), ocf=top.get("ocf"), debt=top.get("debt")))
    eps, eq, shares = top.get("eps"), s["eq"].get(p0), _shares_outstanding(facts)
    f.update(pe=round(px / eps, 1) if px and eps and eps > 0 else None,
             pb=round(px / (eq / shares), 2) if px and eq and eq > 0 and shares else None,
             payout=round(ttm / eps * 100, 1) if ttm and eps and eps > 0 else None)  # 配發率以最近年報 EPS 計，不是近四季
    if all(s[k].get(p0) is not None for k in ("ocf", "capex", "paid")):
        f = add_cashflow(f, dict(fy=p0[:4], ocf=s["ocf"][p0], capex=s["capex"][p0], paid=s["paid"][p0]))
    f = add_valuation(f)
    f["hist"] = [dict(h, k=h["k"].replace("年报", "年報")) for h in f["hist"]]  # 計算完成後才換成繁體顯示
    return {k: val for k, val in f.items() if val is not None}


def us_stock(code: str, name: str, industry: Optional[str], today: date) -> Dict[str, Any]:
    """單檔美股：股價與股利（Yahoo）、財報（SEC）。每步各自 try，互不牽連。美股沒有產業別，industry 不使用。"""
    errs: List[str] = []

    def step(name_, fn, default=None):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name_}:{type(e).__name__}")
            return default

    px = step("price", lambda: float(price_fetch.get_price("NASDAQ:" + code, source="yahoo")["price"]))
    div = step("dividends", lambda: price_fetch.yahoo_dividends("NASDAQ", code, None), {}) or {}
    ttm = round(div.get("ttm_total") or 0.0, 4)  # 近 12 月（除息日計）
    yearly = div.get("yearly_totals") or {}
    lfy = round(yearly.get(str(today.year - 1), 0.0), 4)  # 上一個日曆年的合計
    f = step("financials", lambda: us_financials(code, px, ttm), {}) or {}
    if f and lfy:  # 範本的上財年欄位沿用 fy_* 名稱，數值為美元；Yahoo 沒有付款日與類別，所以只列日曆年合計
        prev = yearly.get(str(today.year - 2))
        fy = dict(fy_lab=f"{today.year - 1} 年度", fy_hkd=lfy, fy_prev_hkd=round(prev, 4) if prev else None,
                  fy_chg=round((lfy / prev - 1) * 100, 1) if prev else None)
        f = dict(f, **{k: v for k, v in fy.items() if v is not None})
    out: Dict[str, Any] = dict(c=code, n=name, px=px, ttm=ttm, lfy=lfy, chg=0, i26="", p25="", cmp="", errs=errs, f=f)
    if px:
        out["y"] = round(ttm / px * 100, 2)
        out["chg"] = round((ttm / lfy - 1) * 100, 1) if lfy else 0
    return out


# 美股個股的財報缺漏（外國發行人、欄位缺）只讓該欄空白，所以異常 ETF 不擋頁；前幾大持股不完整，持股檔數門檻只要求至少一檔
US = etf_market.Market(
    code="US", name="美股", profile="us", currency="USD",
    parse_code=parse_us_code,
    holdings=lambda etf: fetch_holdings(etf),
    stock=lambda code, name, industry, today: us_stock(code, name, industry, today),
    industry=lambda: {},
    accept_coverage=("full", "partial"),
    gate=etf_market.Gate(min_pool_etfs=1, max_pool_missing=10, max_pool_error_etfs=1, min_holdings=1),
    unit_note=etf_page.YIELD_NOTE,
    source_note="財報來自 SEC EDGAR（10-K 年度數字），股價與股利來自 Yahoo Finance，持股為 Yahoo 前幾大持股（部分持股）",
)
