#!/usr/bin/env python3
"""港股成分股市場介面（中信投信 ETF 的港股部位，目前為 00882）。

持股來自中信投信 ETFHoldingWeight（個股完整清單，coverage full）；股價 Google Finance、歷史價 Yahoo（price-dividend-fetcher），
財報、現金流與歷次分配來自東方財富（fundamental-analyzer 的 eastmoney）。來源與 hk-market-data 的 00882 頁相同，
這裡產出的是 etf_pool 的資料池（純代號、schema_version、健康門檻），用 `etf_pool.py outdir --market hk --etfs 00882` 執行。
每一步獨立失敗：單檔缺資料只讓該欄空白並記在 errs。
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, "..", "..")
for sub in ("fundamental-analyzer", "price-dividend-fetcher"):
    sys.path.insert(0, os.path.join(SKILLS, sub, "scripts"))
import etf_market  # noqa: E402
import etf_page  # noqa: E402
import fetch as price_fetch  # noqa: E402
from fetchers import eastmoney  # noqa: E402
from fin_trend import add_cashflow, add_dividends, add_valuation, enrich, mid_note, rmb_hint, ttm_dividend, valuation_position  # noqa: E402

CTBC_URL = "https://www.ctbcinvestments.com.tw/API/"
CTBC_HEADERS = {"content-type": "application/json; charset=utf-8", "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.ctbcinvestments.com.tw/"}
FIDS = {"00882": "E0014"}  # 中信投信 ETF 代號 → ETFHoldingWeight 的基金代碼；沒有對照的 ETF 不抓

# 港股代號要帶市場標記：CTBC 的「1919 HK」、Google Finance 的「HKG:1919」或「1919.HK」；裸數字不算，避免與台股混淆
_HK_CODE = re.compile(r"HKG:(\d{1,5})|(\d{1,5})(?:\s+|\.)HK", re.IGNORECASE)


def parse_hk_code(symbol: str) -> Optional[str]:
    """港股原始代號 → 純代號（不足四位補零，與 Yahoo、Google Finance 的寫法相同）；不是港股代號回 None。"""
    m = _HK_CODE.fullmatch(str(symbol).strip())
    if not m:
        return None
    return (m.group(1) or m.group(2)).lstrip("0").zfill(4)


def _post(path: str, body: Dict[str, Any], token: str = "www.ctbcinvestments.com") -> Any:
    """中信投信 API 的呼叫方式與 hk-market-data 的 00882 頁相同。"""
    req = urllib.request.Request(CTBC_URL + path + "?" + urllib.parse.urlencode({"token": token}),
                                 data=json.dumps(body).encode(), headers=CTBC_HEADERS, method="POST")
    r = json.load(urllib.request.urlopen(req, timeout=40))
    if r.get("ResultCode") != 0:
        raise RuntimeError(f"{path}: {r.get('ResultMsg')}")
    return r["Data"]


def fetch_holdings(etf: str) -> Dict[str, Any]:
    """中信投信 ETF 的港股持股（權重、持股數）。只保留港股個股列，現金與期貨不列入，所以 total_weight_pct 是港股權重合計。
    沒有基金代碼對照就拋例外，由呼叫端退回備援。"""
    if etf not in FIDS:
        raise ValueError(f"中信投信持股來源沒有 {etf} 的基金代碼")
    tok = _post("home/AuthToken", {})["token"]
    hold = _post("etf/ETFHoldingWeight", {"FID": FIDS[etf], "StartDate": date.today().isoformat()}, tok)
    cons = [dict(symbol=x["code_"], name=x["name_"], weight_pct=float(x["weights_"]),
                 shares=int(float(x["qty_"].replace(",", ""))))
            for x in hold["FundAssetsDetail"][0]["Data"] if parse_hk_code(x["code_"]) is not None]
    return dict(ticker=etf, as_of_date=hold["FundAssets"][0]["資料日期"], source=etf_market.CTBC_SOURCE, total_count=len(cons),
                total_weight_pct=round(sum(c["weight_pct"] for c in cons), 2), constituents=cons)


def _closes(code: str) -> List[Tuple[str, float]]:
    """Yahoo 歷史收盤（由舊到新，略過缺值）。"""
    ch = price_fetch.get_yahoo("HKG", code, "5y")["chart"]["result"][0]
    return [(datetime.fromtimestamp(t + ch["meta"].get("gmtoffset", 0), timezone.utc).date().isoformat(), v)
            for t, v in zip(ch["timestamp"], ch["indicators"]["quote"][0]["close"]) if v is not None]


def hk_stock(code: str, name: str, industry: Optional[str], today: date) -> Dict[str, Any]:
    """單檔港股：股價、財報與現金流、歷次分配、歷史價位估值。每步各自 try，互不牽連。
    需要全體資料的計算（人民幣匯率中位數、財年股息、中期說明）留給 hk_finish。港股不用產業別，東方財富的機構類型已在財報。"""
    errs: List[str] = []

    def step(name_, fn, default=None):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name_}:{type(e).__name__}")
            return default

    px = step("price", lambda: float(price_fetch.get_price("HKG:" + code)["price"]))
    f = step("financials", lambda: enrich(eastmoney.hk_detail(code)), {}) or {}
    if f:
        cf = step("cashflow", lambda: eastmoney.hk_cashflow(code), {})
        f = add_valuation(add_cashflow(f, cf) if cf else f)
    divs = step("dividends", lambda: eastmoney.hk_dividends(code), []) or []
    if f and divs:
        f = dict(f, **(valuation_position(step("history", lambda: _closes(code), []), divs, today) or {}))
    ttm = round(ttm_dividend(divs, today), 4) if divs else 0.0  # 沒有配息紀錄＝不配息，殖利率 0（與台股相同）
    out: Dict[str, Any] = dict(c=code, n=name, px=px, ttm=ttm, lfy=0.0, chg=0, i26="", p25="", cmp="", errs=errs, f=f, divs=divs)
    if px:
        out["y"] = round(ttm / px * 100, 2)
    return out


def hk_finish(pool: Dict[str, Dict[str, Any]], today: date) -> Dict[str, Dict[str, Any]]:
    """資料池的跨檔步驟：人民幣對港元的中位數由全體成分股的分配算出，再套用到每檔的股息換算、財年股息與中期說明。"""
    hint = rmb_hint([g.get("divs") or [] for g in pool.values()])
    for g in pool.values():
        divs = g.pop("divs", [])
        if g["f"] and divs:
            g["f"] = add_dividends(g["f"], divs, today, hint)
        g["lfy"] = g["f"].get("fy_hkd") or 0.0
        g["i26"] = mid_note(g["f"], today.year) if g["f"] else ""
        if g["px"]:
            g["chg"] = round((g["ttm"] / g["lfy"] - 1) * 100, 1) if g["lfy"] else 0
    return pool


# 港股個股的歷史價、現金流等步驟缺漏很常見（只讓該欄空白），所以異常 ETF 不擋頁；單檔 ETF 的上限設為 1，等於不啟用
HK = etf_market.Market(
    code="HK", name="港股", profile="hk", currency="HKD",
    parse_code=parse_hk_code,
    holdings=lambda etf: fetch_holdings(etf),
    stock=lambda code, name, industry, today: hk_stock(code, name, industry, today),
    industry=lambda: {},
    gate=etf_market.Gate(min_pool_etfs=1, max_pool_missing=10, max_pool_error_etfs=1, min_holdings=45),
    unit_note=etf_page.YIELD_NOTE,
    source_note="財報與配息來自東方財富，股價 Google Finance，歷史價 Yahoo",
    finish=hk_finish,
)
