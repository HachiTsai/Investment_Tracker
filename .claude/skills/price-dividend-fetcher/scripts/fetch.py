#!/usr/bin/env python3
"""price-dividend-fetcher：抓台股現價（Google Finance）與歷史配息（FinLab），只讀、不寫任何檔案。

用法：
  fetch.py price 00882 [00878 ...]            現價、漲跌、前收、日期
  fetch.py dividends 00882 [--since 2024-01-01]   逐次配息、年度合計、近 12 個月合計與殖利率
  fetch.py both 00882                         價格＋配息＋殖利率（現價基準）

輸出為 JSON（stdout）。錯誤時回傳碼 1，訊息寫到 stderr；不要用猜測值補資料。
Ticker 接受 00882 或 TPE:00882。來源與解析規則見 references/sources.md。
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

GF_URL = "https://www.google.com/finance/quote/{code}:TPE?hl=en"
FINLAB_URL = "https://finlab.finance/stocks/{code}/dividend"
UA = "Mozilla/5.0"

# Google Finance 內嵌資料："TWD",[現價,漲跌,漲跌幅,x,x,x],null,前收,null,"TW","/g/..",[epoch],"Asia/..."
NUM = r"-?\d+\.?\d*(?:e-?\d+)?"
GF_QUOTE_RE = re.compile(
    rf'"TWD",\[({NUM}),({NUM}),({NUM}),\d+,\d+,\d+\],null,({NUM}),null,"[A-Z]{{2}}","[^"]*",\[(\d{{10}})\]'
)
FINLAB_ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>(\d{4}-\d{2}-\d{2})</td>\s*<td[^>]*>([\d.]+)</td>\s*"
    r"<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*</tr>"
)


def norm_code(ticker: str) -> str:
    code = ticker.split(":")[-1].strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{4,6}", code):
        raise ValueError(f"不合法的代號：{ticker}")
    return code


def http_get(url: str) -> str:
    # 用 curl：沿用環境的 proxy 與 CA 設定，不自行處理 TLS
    r = subprocess.run(
        ["curl", "-sS", "-L", "-m", "30", "-A", UA, "-w", "\n%{http_code}", url],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"連線失敗（{url}）：{r.stderr.strip() or r.returncode}")
    body, _, status = r.stdout.rpartition("\n")
    if status != "200":
        raise RuntimeError(f"HTTP {status}（{url}）")
    return body


def parse_price(html: str, code: str) -> Dict:
    m = GF_QUOTE_RE.search(html)
    if not m:
        raise ValueError(f"{code}：Google Finance 頁面找不到報價（頁面格式可能已變，見 references/sources.md）")
    price, change, pct, prev, ts = m.groups()
    as_of = datetime.fromtimestamp(int(ts), timezone.utc).isoformat(timespec="seconds")
    return {
        "ticker": code, "price": float(price), "change": round(float(change), 4),
        "change_pct": round(float(pct), 4), "prev_close": float(prev),
        "currency": "TWD", "as_of": as_of, "source": "Google Finance",
    }


def parse_dividends(html: str, code: str) -> List[Dict]:
    rows = [
        {"ex_date": ex, "amount": float(amt), "record_date": rec.strip() or None, "pay_date": pay.strip() or None}
        for ex, amt, rec, pay in FINLAB_ROW_RE.findall(html)
    ]
    if not rows:
        raise ValueError(f"{code}：FinLab 頁面找不到配息明細（無配息紀錄，或頁面格式已變）")
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


def build_dividends(rows: List[Dict], code: str, today: date, since: Optional[str] = None) -> Dict:
    ttm = ttm_total(rows, today)
    shown = [r for r in rows if not since or r["ex_date"] >= since]
    return {
        "ticker": code, "source": "FinLab", "count": len(shown), "events": shown,
        "yearly_totals": yearly_totals(rows), "ttm_total": ttm, "as_of": today.isoformat(),
    }


def add_yield(result: Dict, price: Dict) -> None:
    result["yield_pct"] = round(result["ttm_total"] / price["price"] * 100, 2) if price["price"] else None
    result["yield_basis"] = f"近 12 個月配息 {result['ttm_total']} ÷ 現價 {price['price']}"


def get_price(code: str) -> Dict:
    return parse_price(http_get(GF_URL.format(code=code)), code)


def get_dividends(code: str, since: Optional[str] = None) -> Dict:
    rows = parse_dividends(http_get(FINLAB_URL.format(code=code)), code)
    return build_dividends(rows, code, date.today(), since)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="抓股價與配息（只讀）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("price")
    sp.add_argument("tickers", nargs="+")
    for name in ("dividends", "both"):
        s = sub.add_parser(name)
        s.add_argument("ticker")
        s.add_argument("--since", help="只列出此日（含）之後的除息，格式 YYYY-MM-DD")
    a = p.parse_args(argv)
    try:
        if a.cmd == "price":
            out = [get_price(norm_code(t)) for t in a.tickers]
        else:
            code = norm_code(a.ticker)
            out = get_dividends(code, a.since)
            if a.cmd == "both":
                price = get_price(code)
                out = {"price": price, "dividends": out}
                add_yield(out["dividends"], price)
    except (ValueError, RuntimeError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
