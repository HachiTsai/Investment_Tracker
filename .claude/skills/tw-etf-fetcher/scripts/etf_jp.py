#!/usr/bin/env python3
"""日股成分股市場介面（etf_jp）。持股來自 yfinance 的前幾大持股，只有前幾大、不是完整持股：coverage 為 partial，頁面與 pool.json 標示來源與抓取日。
股價先 Google Finance、失敗改用 Yahoo Finance，股利來自 Yahoo Finance；財報來自 EDINET 有價證券報告書（合併報表，主要經營指標的近五年數字）。
每一步獨立失敗：單檔缺資料只讓該欄空白並記在 errs。
用法：`etf_pool.py outdir --market jp --etfs 1306`（日股沒有模型卡片可自動探索，要用 --etfs 指定，代號為 4 碼）。
"""
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
from fetchers import edinet  # noqa: E402
from fin_trend import add_cashflow, add_valuation, enrich  # noqa: E402

TOP_SOURCE = "Yahoo Finance 前幾大持股（抓取日）"
HIST_YEARS = 5
SHARES_TAG = "NumberOfIssuedSharesAsOfFiscalYearEndIssuedSharesTotalNumberOfSharesEtc"  # 期末發行股數（含庫藏股）
TREASURY_TAG = "TotalNumberOfSharesHeldTreasurySharesEtc"  # 期末自己株式總數（自己名義與他人名義合計）
FIN_SUFFIX = ("BNK", "INS", "SEC")  # 銀行、保險、證券的業種別標籤後綴；這類公司的現金流與負債比沒有參考性，留空
# 欄位 → 候選標籤，依序取第一個有值的。已對照 Toyota（IFRS）、Sony（IFRS）、MUFG（銀行）、Nomura（美國會計準則）等報告書；
# 日本會計準則的 EPS 標籤仍待更多樣本核對
EPS = ("BasicEarningsLossPerShareIFRSSummaryOfBusinessResults", "BasicEarningsLossPerShareSummaryOfBusinessResults",
       "BasicEarningsLossPerShareUSGAAPSummaryOfBusinessResults")
REV = edinet.REVENUE + ("RevenuesUSGAAPSummaryOfBusinessResults",)
NI = edinet.NET_INCOME + ("NetIncomeLossAttributableToOwnersOfParentUSGAAPSummaryOfBusinessResults",)
EQ = edinet.EQUITY + ("EquityAttributableToOwnersOfParentIFRS",  # 資產負債表的列，沒有經營指標摘要時使用
                      "EquityIncludingPortionAttributableToNonControllingInterestUSGAAPSummaryOfBusinessResults")  # 含非控制權益
ROE = edinet.ROE + ("RateOfReturnOnEquityUSGAAPSummaryOfBusinessResults",)
OCF = edinet.OCF
ASSETS = ("TotalAssetsIFRSSummaryOfBusinessResults", "AssetsIFRS", "TotalAssetsSummaryOfBusinessResults",
          "TotalAssetsUSGAAPSummaryOfBusinessResults")
LIAB = edinet.LIABILITIES
CAPEX = ("AdditionsToFixedAssetsExcludingEquipmentLeasedToOthersInvCFIFRS",) + edinet.CAPEX + (
    "PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssetsInvCFIFRS", "PurchaseOfPropertyPlantAndEquipmentInvCFIFRS",
    "PurchaseOfTangibleAndIntangibleAssetsInvCFIFRS")
DIV = edinet.DIVIDENDS + ("DividendsPaidFinCFIFRS", "CashDividendsPaidFinCF")
_JP_CODE = re.compile(r"(?:(?:TYO|TSE):)?(\d[0-9A-Z]{3})(?:\.(?:T|JP))?", re.IGNORECASE)


def parse_jp_code(symbol: str) -> Optional[str]:
    """日股原始代號 → 4 碼純代號（可帶 TYO:、TSE: 前綴或 .T、.JP 後綴，英文字母一律大寫）；其他市場的代號回 None。"""
    m = _JP_CODE.fullmatch(str(symbol).strip())
    return m.group(1).upper() if m else None


def _top_holdings_rows(etf: str) -> List[Tuple[str, str, float]]:
    """yfinance 的前幾大持股：(原始代號, 名稱, 權重%)。測試時替換這個函式，不連網。"""
    import yfinance as yf  # 延後匯入：只有抓日股持股時才需要

    fd = yf.Ticker(f"{etf}.T").funds_data
    df = None if fd is None else fd.top_holdings
    if df is None:
        return []
    return [(str(sym), str(row.get("Name", sym)), float(row.get("Holding Percent", 0.0)) * 100.0) for sym, row in df.iterrows()]


def fetch_holdings(etf: str) -> Dict[str, Any]:
    """ETF 的日股前幾大持股。只留日股個股列（代號能解析為 4 碼、權重為有限數）；來源是 Yahoo 前幾大，coverage 為 partial。"""
    code = parse_jp_code(etf)
    if code is None:
        raise ValueError(f"日股 ETF 代號需為 4 碼，例如 1306：{etf}")
    cons = []
    for sym, name, w in _top_holdings_rows(code):
        c = parse_jp_code(sym)
        if c is not None and math.isfinite(w):
            cons.append(dict(symbol=c, name=name, weight_pct=round(w, 2), shares=None))
    return dict(ticker=code, as_of_date=date.today().isoformat(), source=TOP_SOURCE, total_count=len(cons),
                total_weight_pct=round(sum(c["weight_pct"] for c in cons), 2), constituents=cons)


def _shift(base: date, years: int) -> date:
    """往前推 years 年的會計年度末日；2 月 29 日遇到平年改成 2 月 28 日。"""
    try:
        return base.replace(year=base.year - years)
    except ValueError:
        return base.replace(year=base.year - years, day=28)


def _pick(vals: Dict[str, Dict[int, float]], tags: Tuple[str, ...], n: int) -> Optional[float]:
    """依序取第一個在年數偏移 n 有值的候選標籤。"""
    return next((vals[t][n] for t in tags if n in vals.get(t, {})), None)


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """a ÷ b 的百分比（一位小數）；分母缺或不為正就留空。"""
    return round(a / b * 100, 1) if a is not None and b is not None and b > 0 else None


def _split_guard(hist: List[Dict[str, Any]]) -> None:
    """每股盈餘在股票分割前後不可比：EDINET 各年報是當年的原始數字，沒有還原分割。以淨利 ÷ 每股盈餘推算各年股數，
    與最近年報相差 1.5 倍以上，就留空該年的每股盈餘（不推估）；淨利與 ROE 不受影響。hist 第一筆是最近年報。"""
    cur = hist[0]
    if not (cur.get("np") and cur.get("eps")):
        return
    base = cur["np"] / cur["eps"]
    for h in hist[1:]:
        if h.get("np") and h.get("eps") and not 1 / 1.5 <= (h["np"] / h["eps"]) / base <= 1.5:
            del h["eps"]


def _num(val: str) -> Optional[float]:
    try:
        return float(val.replace(",", ""))
    except ValueError:
        return None


def _dei(raw: bytes) -> Tuple[Optional[str], Optional[float]]:
    """當期的會計年度末日（YYYY-MM-DD）與期末流通股數（發行股數扣掉自己株式）。淨資產已扣除自己株式，每股淨資產要用流通股數；
    報告書沒有自己株式欄位（或填「－」）就視為 0。"""
    fy_end, issued, treasury = None, None, 0.0
    for tag, ctx, val in edinet.xbrl_rows(raw):
        num = _num(val)
        if ctx == "FilingDateInstant" and tag == "CurrentFiscalYearEndDateDEI" and fy_end is None:
            fy_end = val.strip()
        elif ctx == "FilingDateInstant" and tag == SHARES_TAG and issued is None:
            issued = num
        elif ctx == "CurrentYearInstant" and tag == TREASURY_TAG and num is not None:
            treasury = num
    shares = issued - treasury if issued is not None and issued > treasury else None
    return fy_end, shares


def jp_financials(code: str, px: Optional[float], ttm: float) -> Dict[str, Any]:
    """EDINET 近五年的 EPS、營收、淨利、ROE、負債比與經營現金流；最新年度算出 PE、PB、配發率與自由現金流覆蓋。
    沒有有價證券報告書就回空字典（頁面列為缺財報）；報告書缺會計年度末日就拋例外（頁面記在 errs）。"""
    raw = edinet.report_bytes(code)
    if raw is None:
        return {}
    fy_end, shares = _dei(raw)
    if not fy_end:
        raise RuntimeError("有價證券報告書缺會計年度末日")
    base = date.fromisoformat(fy_end)
    vals = edinet.parse_history(raw)
    fin_sector = any(t.endswith(FIN_SUFFIX) for t in vals)
    offs = sorted({n for t in REV + NI + EPS + EQ if t in vals for n in vals[t]})[:HIST_YEARS]
    if not offs:
        return {}
    hist = []
    for n in offs:
        p = _shift(base, n)
        ni, eq, roe = _pick(vals, NI, n), _pick(vals, EQ, n), _pick(vals, ROE, n)
        row = dict(p=p.isoformat(), k=f"{p.year}年报", eps=_pick(vals, EPS, n), rev=_pick(vals, REV, n), np=ni,
                   ocf=_pick(vals, OCF, n), roe=round(roe * 100, 1) if roe is not None else _pct(ni, eq),
                   debt=None if fin_sector else _pct(_pick(vals, LIAB, n), _pick(vals, ASSETS, n)))
        hist.append({k: v for k, v in row.items() if v is not None})
    _split_guard(hist)
    top = hist[0]
    f = enrich(dict(kind="有價證券報告書", cur="日圓", hist=hist, eps=top.get("eps"), roe=top.get("roe"),
                    rev=top.get("rev"), np=top.get("np"), ocf=top.get("ocf"), debt=top.get("debt")))
    eps, eq = top.get("eps"), _pick(vals, EQ, 0)
    f.update(pe=round(px / eps, 1) if px and eps and eps > 0 else None,
             pb=round(px / (eq / shares), 2) if px and eq and eq > 0 and shares else None,
             payout=round(ttm / eps * 100, 1) if ttm and eps and eps > 0 else None)  # 配發率以最近年報的 EPS 計，不是近四季
    ocf, capex, paid = _pick(vals, OCF, 0), _pick(vals, CAPEX, 0), _pick(vals, DIV, 0)
    if not fin_sector and ocf is not None and capex is not None and paid is not None:
        f = add_cashflow(f, dict(fy=str(base.year), ocf=ocf, capex=abs(capex), paid=abs(paid)))
    f = add_valuation(f)
    f["hist"] = [dict(h, k=h["k"].replace("年报", "年報")) for h in f["hist"]]  # 計算完成後才換成繁體顯示
    return {k: v for k, v in f.items() if v is not None}


def jp_stock(code: str, name: str, industry: Optional[str], today: date) -> Dict[str, Any]:
    """單檔日股：股價與股利（Google Finance、Yahoo）、財報（EDINET）。每步各自 try，互不牽連。日股沒有產業別，industry 不使用。"""
    errs: List[str] = []

    def step(name_, fn, default=None):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name_}:{type(e).__name__}")
            return default

    px = step("price", lambda: float(price_fetch.get_price("TYO:" + code)["price"]))
    div = step("dividends", lambda: price_fetch.yahoo_dividends("TYO", code, None), {}) or {}
    ttm = round(div.get("ttm_total") or 0.0, 4)  # 近 12 月（除息日計）
    yearly = div.get("yearly_totals") or {}
    lfy = round(yearly.get(str(today.year - 1), 0.0), 4)  # 上一個日曆年的合計
    f = step("financials", lambda: jp_financials(code, px, ttm), {}) or {}
    if f and lfy:  # 範本的上財年欄位沿用 fy_* 名稱，數值為日圓；Yahoo 沒有付款日與類別，所以只列日曆年合計
        prev = yearly.get(str(today.year - 2))
        fy = dict(fy_lab=f"{today.year - 1} 年（日曆年）", fy_hkd=lfy, fy_prev_hkd=round(prev, 4) if prev else None,
                  fy_chg=round((lfy / prev - 1) * 100, 1) if prev else None)
        f = dict(f, **{k: v for k, v in fy.items() if v is not None})
    out: Dict[str, Any] = dict(c=code, n=name, px=px, ttm=ttm, lfy=lfy, chg=0, i26="", p25="", cmp="", errs=errs, f=f)
    if px:
        out["y"] = round(ttm / px * 100, 2)
        out["chg"] = round((ttm / lfy - 1) * 100, 1) if lfy else 0
    return out


# 日股持股只有 Yahoo 前幾大（coverage partial），與美股相同允許採用；財報缺漏只讓該欄空白，所以異常 ETF 不擋頁。
# EDINET 第一次掃描日期很慢，並行數壓低，避免同時打太多請求。
JP = etf_market.Market(
    code="JP", name="日股", profile="jp", currency="JPY",
    parse_code=parse_jp_code,
    holdings=lambda etf: fetch_holdings(etf),
    stock=lambda code, name, industry, today: jp_stock(code, name, industry, today),
    industry=lambda: {},
    limits=etf_market.Limits(workers=3),
    accept_coverage=("full", "partial"),
    gate=etf_market.Gate(min_pool_etfs=1, max_pool_missing=10, max_pool_error_etfs=1, min_holdings=1),
    unit_note=etf_page.YIELD_NOTE,
    source_note="財報來自 EDINET（有價證券報告書，合併報表），股價與股利來自 Yahoo Finance（股價先 Google Finance），持股為 Yahoo 前幾大持股（部分持股）",
)
