#!/usr/bin/env python3
"""price-dividend-fetcher：抓股價與配息（Google Finance、FinLab、證交所），只讀、不寫任何檔案。

用法：
  fetch.py price 00882 NASDAQ:AAPL TYO:7203 HKG:0005   現價、漲跌、前收（可混合多市場）
  fetch.py dividends 00882 [--since 2024-01-01]        逐次配息、年度合計、近 12 個月合計（台股附證交所交叉驗證；海外取自 Yahoo）
  fetch.py both 00882                                  價格＋配息＋殖利率（現價基準）

代號格式為「交易所:代號」，與 Core 的 TPE:00882 一致；只寫代號時視為台股（TPE）。
支援交易所：TPE、NASDAQ、NYSE、NYSEARCA、NYSEAMERICAN、TYO、HKG。
價格順序：Google Finance → Yahoo Finance →（台股）證交所收盤價；--source 可指定單一來源。
輸出為 JSON（stdout）。有任何錯誤時回傳碼 1，錯誤寫在該筆結果的 error 欄位；不用猜測值補資料。
來源與解析規則見 references/sources.md。
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

EXCHANGES = {"TPE", "NASDAQ", "NYSE", "NYSEARCA", "NYSEAMERICAN", "TYO", "HKG"}
GF_URL = "https://www.google.com/finance/quote/{code}:{exch}?hl=en"
FINLAB_URL = "https://finlab.finance/stocks/{code}/dividend"
FINLAB_STOCK_URL = "https://finlab.finance/stocks/{code}"   # 個股沒有 /dividend 頁，改讀個股頁的「近期除息紀錄」
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d&events=div"
YAHOO_UA = "Mozilla/5.0"   # 長的瀏覽器 UA 會被 Yahoo 回 429，短 UA 才正常
TWSE_EXRIGHT_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={start}&endDate={end}&response=json"
TWSE_CLOSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=&type=ALLBUT0999&response=json"
# 證交所的防護頁面會擋沒有瀏覽器標頭的請求
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
TWSE_REFERER = "https://www.twse.com.tw/"

NUM = r"-?\d+\.?\d*(?:e-?\d+)?"
FINLAB_ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>(\d{4}-\d{2}-\d{2})</td>\s*<td[^>]*>([\d.]+)</td>\s*"
    r"<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*</tr>"
)
FINLAB_STOCK_ROW_RE = re.compile(
    r'<tr><th scope="row"[^>]*>(\d{4}-\d{2}-\d{2})</th><td[^>]*>([^<]*)</td>'
    r'<td[^>]*>([^<]*)</td>(?:<!--[^>]*-->)?<td[^>]*>([^<]*)</td>'
)
GF_STAT_RE = re.compile(r'class="SwQK7">([^<]*)</div><div class="dO6ijd">([^<]*)')
ROC_DATE_RE = re.compile(r"(\d+)年(\d+)月(\d+)日")


def parse_ticker(ticker: str) -> Tuple[str, str]:
    """'TPE:00882'、'00882'、'NASDAQ:AAPL' → (交易所, 代號)。"""
    t = ticker.strip().upper()
    exch, _, code = t.rpartition(":")
    exch = exch or "TPE"
    if exch not in EXCHANGES or not re.fullmatch(r"[0-9A-Z][0-9A-Z.\-]{0,9}", code):
        raise ValueError(f"不合法的代號：{ticker}（格式 交易所:代號，交易所限 {', '.join(sorted(EXCHANGES))}）")
    return exch, code


def http_get(url: str, referer: Optional[str] = None, attempts: int = 1, ua: str = UA) -> str:
    # 用 curl：沿用環境的 proxy 與 CA 設定，不自行處理 TLS
    cmd = ["curl", "-sS", "-L", "-m", "40", "-A", ua, "-H", "Accept-Language: zh-TW,en;q=0.8"]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    err = ""
    for i in range(attempts):
        if i:
            time.sleep(3 * i)
        r = subprocess.run(cmd + ["-w", "\n%{http_code}", url], capture_output=True, text=True, check=False)
        if r.returncode != 0:
            err = f"連線失敗（{url}）：{r.stderr.strip() or r.returncode}"
            continue
        body, _, status = r.stdout.rpartition("\n")
        if status == "200":
            return body
        err = f"HTTP {status}（{url}）"
    raise RuntimeError(err)


def twse_get(url: str) -> str:
    # 證交所的防護機制偶爾會擋下請求（實測約每 6 次 1 次），重試 3 次
    return http_get(url, TWSE_REFERER, attempts=3)


# ---------- Google Finance（全市場現價）----------

def parse_price(html: str, exch: str, code: str) -> Dict:
    # 頁面內嵌多檔商品，用「["代號","交易所"],"名稱",型別,"幣別",[現價,漲跌,漲跌幅,…],null,前收,…,[epoch]」定位主報價
    rx = re.compile(
        rf'\["{re.escape(code)}","{exch}"\],"([^"]*)",\d+,"([A-Z]{{3}})",'
        rf"\[({NUM}),({NUM}),({NUM}),\d+,\d+,\d+\],null,({NUM}),[^\]]{{0,80}}?\[(\d{{10}})\]"
    )
    m = rx.search(html)
    if not m:
        raise ValueError(f"{exch}:{code}：Google Finance 頁面找不到報價（代號錯誤，或頁面格式已變，見 references/sources.md）")
    name, cur, price, change, pct, prev, ts = m.groups()
    out = {
        "ticker": f"{exch}:{code}", "name": json.loads(f'"{name}"'), "price": float(price),
        "change": round(float(change), 4), "change_pct": round(float(pct), 4), "prev_close": float(prev),
        "currency": cur, "as_of": datetime.fromtimestamp(int(ts), timezone.utc).isoformat(timespec="seconds"),
        "price_type": "last", "source": "Google Finance",
    }
    div = {k: v for k, v in GF_STAT_RE.findall(html) if "ividend" in k}
    if div:
        out["dividend_summary"] = div   # 頁面顯示的原文（殖利率、最近除息日、最近一次金額）
    return out


# ---------- Yahoo Finance（全市場報價、配息歷史）----------

def yahoo_symbol(exch: str, code: str) -> str:
    if exch == "TPE":
        return f"{code}.TW"   # 上櫃（.TWO）標的 Yahoo 查不到時會報錯，見 references/sources.md
    if exch == "TYO":
        return f"{code}.T"
    if exch == "HKG":
        return f"{code.lstrip('0').zfill(4)}.HK"
    return code.replace(".", "-")   # 美股：BRK.B → BRK-B


def get_yahoo(exch: str, code: str, rng: str) -> Dict:
    return json.loads(http_get(YAHOO_URL.format(sym=yahoo_symbol(exch, code), rng=rng), ua=YAHOO_UA))


def yahoo_result(data: Dict, exch: str, code: str) -> Dict:
    chart = data.get("chart") or {}
    if chart.get("error") or not chart.get("result"):
        desc = (chart.get("error") or {}).get("description", "沒有資料")
        raise ValueError(f"{exch}:{code}：Yahoo Finance {desc}")
    return chart["result"][0]


def parse_yahoo_price(data: Dict, exch: str, code: str) -> Dict:
    r = yahoo_result(data, exch, code)
    meta = r["meta"]
    off = meta.get("gmtoffset", 0)
    local = lambda ts: datetime.fromtimestamp(ts + off, timezone.utc).date()
    price, now = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    if price is None or now is None:
        raise ValueError(f"{exch}:{code}：Yahoo Finance 回應缺少現價")
    # 前收 = 最近一個「早於今日交易日」的收盤；meta.chartPreviousClose 是區間起點前的收盤，不能用
    bars = zip(r.get("timestamp") or [], r["indicators"]["quote"][0].get("close") or [])
    prevs = [c for ts, c in bars if c is not None and local(ts) < local(now)]
    if not prevs:
        raise ValueError(f"{exch}:{code}：Yahoo Finance 找不到前一日收盤")
    prev = prevs[-1]
    change = price - prev
    return {
        "ticker": f"{exch}:{code}", "name": meta.get("longName") or meta.get("shortName"), "price": round(price, 4),
        "change": round(change, 4), "change_pct": round(change / prev * 100, 4) if prev else None,
        "prev_close": round(prev, 4), "currency": meta.get("currency"),
        "as_of": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
        "price_type": "last", "source": "Yahoo Finance",
    }


def parse_yahoo_dividends(data: Dict, exch: str, code: str) -> Tuple[List[Dict], Optional[str]]:
    r = yahoo_result(data, exch, code)
    events = (r.get("events") or {}).get("dividends") or {}
    rows = [
        {"ex_date": datetime.fromtimestamp(e["date"], timezone.utc).date().isoformat(), "amount": round(e["amount"], 6)}
        for e in events.values()
    ]
    return sorted(rows, key=lambda x: x["ex_date"], reverse=True), r["meta"].get("currency")


# ---------- 證交所（台股官方收盤價、除權息）----------

def roc_to_iso(s: str) -> str:
    m = ROC_DATE_RE.search(s)
    if not m:
        raise ValueError(f"無法解析民國日期：{s}")
    y, mo, d = (int(x) for x in m.groups())
    return f"{y + 1911:04d}-{mo:02d}-{d:02d}"


def to_float(s: str) -> Optional[float]:
    s = s.replace(",", "").strip()
    return float(s) if re.fullmatch(r"-?\d+\.?\d*", s) else None


def parse_twse_close(data: Dict, code: str) -> Dict:
    for t in data.get("tables", []):
        fields = t.get("fields", [])
        if "收盤價" not in fields:
            continue
        for row in t["data"]:
            if row[0] != code:
                continue
            rec = dict(zip(fields, row))
            close = to_float(rec["收盤價"])
            if close is None:
                raise ValueError(f"{code}：證交所當日無收盤價（未成交）")
            diff = to_float(rec["漲跌價差"]) or 0.0
            sign = -1 if ">-<" in rec["漲跌(+/-)"] else 1
            change = round(sign * diff, 4)
            d = data["date"]
            return {
                "ticker": f"TPE:{code}", "name": rec["證券名稱"], "price": close, "change": change,
                "change_pct": round(change / (close - change) * 100, 4) if close != change else None,
                "prev_close": round(close - change, 4), "currency": "TWD",
                "as_of": f"{d[:4]}-{d[4:6]}-{d[6:]}", "price_type": "close", "source": "TWSE",
            }
    raise ValueError(f"{code}：證交所收盤表找不到此代號（非上市標的，或當日無資料）")


def parse_twse_dividends(data: Dict, code: str) -> List[Dict]:
    if data.get("stat") != "OK":
        raise ValueError(f"證交所除權息表回應異常：{data.get('stat')}")
    return [
        # 「權息」列的金額是權值＋息值，無法拆出現金股利，只用來比對除息日
        {"ex_date": roc_to_iso(r[0]), "amount": float(r[5]) if r[6] == "息" else None}
        for r in data["data"] if r[1] == code and "息" in r[6]
    ]


def get_twse_dividends(code: str, years: List[int]) -> List[Dict]:
    out: List[Dict] = []
    for i, y in enumerate(years):   # 區間過長會被重置連線，所以逐年查；連續請求易被擋，間隔 3 秒
        if i:
            time.sleep(3)
        end = min(date(y, 12, 31), date.today())   # 結束日在未來會被擋
        url = TWSE_EXRIGHT_URL.format(start=f"{y}0101", end=end.strftime("%Y%m%d"))
        out += parse_twse_dividends(json.loads(twse_get(url)), code)
    return out


def crosscheck(finlab_rows: List[Dict], twse_rows: List[Dict], years: List[int]) -> Dict:
    """以證交所為準，比對同年度的 FinLab 配息；金額差 > 0.005 視為不一致。"""
    ys = {str(y) for y in years}
    fin = {r["ex_date"]: r["amount"] for r in finlab_rows if r["ex_date"][:4] in ys}
    tw = {r["ex_date"]: r["amount"] for r in twse_rows}
    diffs = []
    for d in sorted(set(fin) | set(tw), reverse=True):
        if d not in tw:
            diffs.append({"ex_date": d, "finlab": fin[d], "twse": None})
        elif d not in fin:
            diffs.append({"ex_date": d, "finlab": None, "twse": tw[d]})
        elif tw[d] is not None and abs(fin[d] - tw[d]) > 0.005:
            diffs.append({"ex_date": d, "finlab": fin[d], "twse": tw[d]})
    return {"source": "TWSE", "years": sorted(years), "consistent": not diffs, "differences": diffs}


# ---------- FinLab（台股配息歷史）----------

def parse_dividends(html: str, code: str) -> List[Dict]:
    rows = [
        {"ex_date": ex, "amount": float(amt), "record_date": rec.strip() or None, "pay_date": pay.strip() or None}
        for ex, amt, rec, pay in FINLAB_ROW_RE.findall(html)
    ]
    if not rows:
        raise ValueError(f"{code}：FinLab 頁面找不到配息明細（無配息紀錄，或頁面格式已變）")
    return sorted(rows, key=lambda r: r["ex_date"], reverse=True)


def parse_stock_dividends(html: str, code: str) -> List[Dict]:
    """個股頁的除息紀錄：除息日、股利所屬期間、現金股利、股票股利（「—」代表沒有）。"""
    num = lambda v: None if v.strip() in ("", "—", "-") else float(v)
    rows = [
        {"ex_date": ex, "amount": num(cash) or 0.0, "stock_dividend": num(stock), "period": period.strip() or None}
        for ex, period, cash, stock in FINLAB_STOCK_ROW_RE.findall(html)
    ]
    if not rows:
        raise ValueError(f"{code}：FinLab 個股頁找不到除息紀錄（無配息紀錄，或頁面格式已變）")
    return sorted(rows, key=lambda r: r["ex_date"], reverse=True)


def yearly_totals(rows: List[Dict]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for r in rows:
        y = r["ex_date"][:4]
        out[y] = round(out.get(y, 0) + r["amount"], 4)
    return dict(sorted(out.items(), reverse=True))


def ttm_total(rows: List[Dict], today: date) -> float:
    start = (today - timedelta(days=365)).isoformat()
    return round(sum(r["amount"] for r in rows if start < r["ex_date"] <= today.isoformat()), 4)


def build_dividends(rows: List[Dict], code: str, today: date, since: Optional[str] = None,
                    label: Optional[str] = None) -> Dict:
    shown = [r for r in rows if not since or r["ex_date"] >= since]
    return {
        "ticker": label or f"TPE:{code}", "source": "FinLab", "count": len(shown), "events": shown,
        "yearly_totals": yearly_totals(rows), "ttm_total": ttm_total(rows, today), "as_of": today.isoformat(),
    }


def add_yield(result: Dict, price: Dict) -> None:
    result["yield_pct"] = round(result["ttm_total"] / price["price"] * 100, 2) if price["price"] else None
    result["yield_basis"] = f"近 12 個月配息 {result['ttm_total']} ÷ {price['price_type']}價 {price['price']}"


# ---------- 組合 ----------

def _google(exch: str, code: str) -> Dict:
    return parse_price(http_get(GF_URL.format(code=code, exch=exch)), exch, code)


def _yahoo(exch: str, code: str) -> Dict:
    return parse_yahoo_price(get_yahoo(exch, code, "5d"), exch, code)


def _twse(exch: str, code: str) -> Dict:
    return parse_twse_close(json.loads(twse_get(TWSE_CLOSE_URL)), code)


PRICE_SOURCES = {"google": ("Google Finance", _google), "yahoo": ("Yahoo Finance", _yahoo), "twse": ("證交所收盤價", _twse)}


def get_price(ticker: str, source: str = "auto") -> Dict:
    exch, code = parse_ticker(ticker)
    if source == "twse" and exch != "TPE":
        raise ValueError("--source twse 只支援台股")
    order = ["google", "yahoo"] + (["twse"] if exch == "TPE" else []) if source == "auto" else [source]
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


def finlab_rows(code: str) -> Tuple[List[Dict], bool]:
    """回傳 (配息列, 是否來自個股頁)。ETF 有 /dividend 頁；個股沒有，改讀個股頁。"""
    try:
        return parse_dividends(http_get(FINLAB_URL.format(code=code)), code), False
    except (ValueError, RuntimeError):
        return parse_stock_dividends(http_get(FINLAB_STOCK_URL.format(code=code)), code), True


def yahoo_dividends(exch: str, code: str, since: Optional[str]) -> Dict:
    rows, cur = parse_yahoo_dividends(get_yahoo(exch, code, "10y"), exch, code)
    out = build_dividends(rows, code, date.today(), since, label=f"{exch}:{code}")
    out["source"] = "Yahoo Finance（已還原股票分割，金額為交易幣別）"
    out["currency"] = cur
    return out


def get_dividends(ticker: str, since: Optional[str] = None, check: bool = True) -> Dict:
    exch, code = parse_ticker(ticker)
    if exch != "TPE":
        return yahoo_dividends(exch, code, since)
    try:
        rows, stock_page = finlab_rows(code)
    except (ValueError, RuntimeError) as e:   # FinLab 兩個頁面都讀不到：改用 Yahoo，不做證交所驗證
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
    try:
        return fn()
    except (ValueError, RuntimeError, json.JSONDecodeError) as e:
        return {"ticker": ticker, "error": str(e)}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="抓股價與配息（只讀）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("price")
    sp.add_argument("tickers", nargs="+")
    sp.add_argument("--source", choices=["auto", "google", "yahoo", "twse"], default="auto",
                    help="auto：Google Finance → Yahoo Finance →（台股）證交所收盤價")
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
