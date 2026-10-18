#!/usr/bin/env python3
"""price-dividend-fetcher：抓股價與配息（Google Finance、FinLab、證交所），只讀、不寫任何檔案。

用法：
  fetch.py price 00882 NASDAQ:AAPL TYO:7203 HKG:0005   現價、漲跌、前收（可混合多市場）
  fetch.py dividends 00882 [--since 2024-01-01]        逐次配息、年度合計、近 12 個月合計（台股附證交所交叉驗證；海外取自 Yahoo）
  fetch.py both 00882                                  價格＋配息＋殖利率（現價基準）

代號格式為「交易所:代號」，與 Core 的 TPE:00882 一致；只寫代號時視為台股（TPE）。
支援交易所：TPE、NASDAQ、NYSE、NYSEARCA、NYSEAMERICAN、TYO、HKG。
價格順序：Google Finance → Yahoo Finance →（台股）證交所收盤價 → 櫃買中心收盤價（上櫃）；--source 可指定單一來源。
輸出為 JSON（stdout）。有任何錯誤時回傳碼 1，錯誤寫在該筆結果的 error 欄位；不用猜測值補資料。
來源與解析規則見 references/sources.md。
"""

import argparse
import json
import sys
from datetime import date
from typing import Dict, List, Optional, Tuple

import fetch_calculator
import fetch_common
import global_fetcher
import tw_fetcher
from fetch_calculator import (
    add_yield,
    build_dividends,
    ttm_total,
    yearly_totals,
)
from fetch_common import (
    EXCHANGES,
    FINLAB_ROW_RE,
    FINLAB_STOCK_ROW_RE,
    FINLAB_STOCK_URL,
    FINLAB_URL,
    GF_STAT_RE,
    GF_URL,
    NUM,
    ROC_DATE_RE,
    TPEX_CLOSE_URL,
    TWSE_CLOSE_URL,
    TWSE_EXRIGHT_URL,
    TWSE_REFERER,
    UA,
    YAHOO_UA,
    YAHOO_URL,
    parse_ticker,
    roc_to_iso,
    to_float,
)
from global_fetcher import (
    parse_price,
    parse_yahoo_dividends,
    parse_yahoo_price,
    yahoo_result,
    yahoo_symbol,
)
from tw_fetcher import (
    crosscheck,
    parse_dividends,
    parse_stock_dividends,
    parse_tpex_close,
    parse_twse_close,
    parse_twse_dividends,
)


def http_get(url: str, referer: Optional[str] = None, attempts: int = 1, ua: str = UA) -> str:
    """HTTP GET 連線（可被測試動態 monkeypatch）。"""
    return fetch_common.http_get(url, referer=referer, attempts=attempts, ua=ua)


def twse_get(url: str) -> str:
    """證交所請求包裝器（透過 http_get）。"""
    return fetch_common.twse_get(url, http_fn=http_get)


def get_yahoo(exch: str, code: str, rng: str) -> Dict:
    """抓取 Yahoo Finance 資料（動態傳入當前 http_get 實作）。"""
    return global_fetcher.get_yahoo(exch, code, rng, http_fn=http_get)


def finlab_rows(code: str) -> Tuple[List[Dict], bool]:
    """讀取 FinLab 配息列（動態傳入當前 http_get 實作）。"""
    return tw_fetcher.finlab_rows(code, http_fn=http_get)


def get_twse_dividends(code: str, years: List[int]) -> List[Dict]:
    """查詢證交所歷年除息紀錄（動態傳入當前 twse_get 實作）。"""
    return tw_fetcher.get_twse_dividends(code, years, twse_get_fn=twse_get)


# ---------- 組合調度 ----------

def _google(exch: str, code: str) -> Dict:
    return parse_price(http_get(GF_URL.format(code=code, exch=exch)), exch, code)


def _yahoo(exch: str, code: str) -> Dict:
    return parse_yahoo_price(get_yahoo(exch, code, "5d"), exch, code)


def _twse(exch: str, code: str) -> Dict:
    return parse_twse_close(json.loads(twse_get(TWSE_CLOSE_URL)), code)


def _tpex(exch: str, code: str) -> Dict:
    return parse_tpex_close(json.loads(http_get(TPEX_CLOSE_URL)), code)


PRICE_SOURCES = {
    "google": ("Google Finance", _google),
    "yahoo": ("Yahoo Finance", _yahoo),
    "twse": ("證交所收盤價", _twse),
    "tpex": ("櫃買中心收盤價", _tpex),
}


def get_price(ticker: str, source: str = "auto") -> Dict:
    """依優先序取得現價行情（支援自動降級 fallback）。"""
    exch, code = parse_ticker(ticker)
    if source in ("twse", "tpex") and exch != "TPE":
        raise ValueError(f"--source {source} 只支援台股")
    order = ["google", "yahoo"] + (["twse", "tpex"] if exch == "TPE" else []) if source == "auto" else [source]
    failures: List[str] = []
    for name in order:
        label, fn = PRICE_SOURCES[name]
        try:
            out = fn(exch, code)
        except (ValueError, RuntimeError, json.JSONDecodeError) as e:
            failures.append(f"{label}失敗：{e}")
            continue
        if failures:
            out["fallback_reason"] = "；".join(failures)
        return out
    raise RuntimeError("；".join(failures))


def yahoo_dividends(exch: str, code: str, since: Optional[str]) -> Dict:
    """抓取並組裝 Yahoo 海外配息歷程。"""
    rows, cur = parse_yahoo_dividends(get_yahoo(exch, code, "10y"), exch, code)
    out = build_dividends(rows, code, date.today(), since, label=f"{exch}:{code}")
    out["source"] = "Yahoo Finance（已還原股票分割，金額為交易幣別）"
    out["currency"] = cur
    return out


def get_dividends(ticker: str, since: Optional[str] = None, check: bool = True) -> Dict:
    """取得標的除息歷史（台股以 FinLab 為主、證交所交叉比對；海外以 Yahoo 為準）。"""
    exch, code = parse_ticker(ticker)
    if exch != "TPE":
        return yahoo_dividends(exch, code, since)
    try:
        rows, stock_page = finlab_rows(code)
    except (ValueError, RuntimeError) as e:
        out = yahoo_dividends(exch, code, since)
        out["fallback_reason"] = f"FinLab 失敗：{e}"
        return out
    out = build_dividends(rows, code, date.today(), since)
    if stock_page:
        out["source"] = "FinLab 個股頁（金額四捨五入到 0.1 元，只列近幾次）"
    if check:
        years = [date.today().year - 1, date.today().year]
        try:
            out["crosscheck"] = crosscheck(rows, get_twse_dividends(code, years), years)
        except (ValueError, RuntimeError, json.JSONDecodeError) as e:
            out["crosscheck"] = {"source": "TWSE", "error": str(e)}
    return out


def safely(fn, ticker: str):
    """異常安全捕捉包裝器。"""
    try:
        return fn()
    except (ValueError, RuntimeError, json.JSONDecodeError) as e:
        return {"ticker": ticker, "error": str(e)}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="抓股價與配息（只讀）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("price")
    sp.add_argument("tickers", nargs="+")
    sp.add_argument(
        "--source",
        choices=["auto", "google", "yahoo", "twse", "tpex"],
        default="auto",
        help="auto：Google Finance → Yahoo Finance →（台股）證交所收盤價 → 櫃買中心收盤價",
    )
    for name in ("dividends", "both"):
        s = sub.add_parser(name)
        s.add_argument("ticker")
        s.add_argument("--since", help="只列出此日（含）之後的除息，格式 YYYY-MM-DD")
        s.add_argument("--no-crosscheck", action="store_true", help="不查證交所交叉驗證")
    a = p.parse_args(argv)
    if a.cmd == "price":
        out = [safely(lambda t=t: get_price(t, a.source), t) for t in a.tickers]
        failed = any("error" in r for r in out)
    elif a.cmd == "dividends":
        out = safely(lambda: get_dividends(a.ticker, a.since, not a.no_crosscheck), a.ticker)
        failed = "error" in out
    else:
        price = safely(lambda: get_price(a.ticker), a.ticker)
        div = None if "error" in price else safely(lambda: get_dividends(a.ticker, a.since, not a.no_crosscheck), a.ticker)
        if div and "error" not in div:
            add_yield(div, price)
        out = {"price": price, "dividends": div}
        failed = "error" in price or bool(div and "error" in div)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
