"""台股 ETF 完整成分股與持股權重解析模組 (ETF Holdings Scraper)。

以 MoneyDJ 公開數據端點為主，提供 100% 完整成分股穿透解析，並以 yfinance 前十大持股作為備援。
"""

import datetime
import json
import re
import urllib.request
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

MONEYDJ_HOLDINGS_URL = "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={ticker}.TW"


def clean_ticker(ticker: str) -> str:
    """清理標的代碼（例如 '00878.TW' 或 'TPE:00878' -> '00878'）。"""
    t = ticker.strip().upper()
    t = re.sub(r"^(TPE:|TWO:)", "", t)
    t = re.sub(r"(\.TW|\.TWO)$", "", t)
    return t


def _data_date(html: str) -> Optional[str]:
    """MoneyDJ 頁面上的「資料日期：2026/10/21」→ 2026-10-21；找不到回 None（呼叫端退回抓取日）。"""
    m = re.search(r"資料日期[：:]\s*(\d{4})/(\d{1,2})/(\d{1,2})", html)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def fetch_etf_holdings(
    ticker: str,
    timeout: int = 10,
    mock_html: Optional[str] = None,
    mock_yfinance_holdings: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """抓取指定 ETF 之完整成分股、權重與股數。"""
    code = clean_ticker(ticker)
    as_of_date = datetime.date.today().isoformat()

    # 1. 若有 Mock HTML（單元測試用）
    if mock_html is not None:
        constituents = _parse_moneydj_html(mock_html)
        return _build_holdings_result(code, constituents, as_of_date, "Mock")

    # 2. 主要來源：MoneyDJ
    try:
        url = MONEYDJ_HOLDINGS_URL.format(ticker=code)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        constituents = _parse_moneydj_html(html)
        if constituents:
            return _build_holdings_result(code, constituents, _data_date(html) or as_of_date, "MoneyDJ")
    except Exception:
        pass

    # 3. 備援來源：yfinance
    if mock_yfinance_holdings is not None:
        return _build_holdings_result(code, mock_yfinance_holdings, as_of_date, "yfinance (Mock)")

    yf_constituents = _fetch_yfinance_top_holdings(code)
    if yf_constituents:
        return _build_holdings_result(code, yf_constituents, as_of_date, "yfinance (Top10)")

    return _build_holdings_result(code, [], as_of_date, "None")


def _parse_moneydj_html(html: str) -> List[Dict[str, Any]]:
    """解析 MoneyDJ 持股 HTML 表格。"""
    soup = BeautifulSoup(html, "html.parser")
    constituents = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_text = rows[0].get_text()
        if "投資比例" not in header_text and "個股名稱" not in header_text:
            continue

        for r in rows[1:]:
            cols = [td.get_text(strip=True) for td in r.find_all("td")]
            if len(cols) < 2:
                continue

            raw_name = cols[0]
            raw_weight = cols[1]
            raw_shares = cols[2] if len(cols) > 2 else "0"

            # 解析名稱與代號：例如 '台積電(2330.TW)' 或 '中信金(2891.TW)'
            m = re.search(r"^(.*?)\(([0-9A-Za-z.]+)\)$", raw_name)
            if m:
                name = m.group(1).strip()
                symbol = m.group(2).strip()
            else:
                name = raw_name
                symbol = raw_name

            # 解析權重比例
            try:
                weight_val = float(raw_weight.replace("%", "").replace(",", ""))
            except ValueError:
                continue

            # 解析持有股數
            try:
                shares_val = int(raw_shares.replace(",", ""))
            except ValueError:
                shares_val = 0

            constituents.append({
                "symbol": symbol,
                "name": name,
                "weight_pct": round(weight_val, 4),
                "shares": shares_val,
            })
        if constituents:
            break

    return constituents


def _fetch_yfinance_top_holdings(code: str) -> List[Dict[str, Any]]:
    """以 yfinance 作為前十大成分股備援。"""
    try:
        import yfinance as yf
        t = yf.Ticker(f"{code}.TW")
        fd = t.funds_data
        if fd is None or fd.top_holdings is None:
            return []
        df = fd.top_holdings
        items = []
        for sym, row in df.iterrows():
            weight = float(row.get("Holding Percent", 0.0)) * 100.0
            name = str(row.get("Name", sym))
            items.append({
                "symbol": str(sym),
                "name": name,
                "weight_pct": round(weight, 4),
                "shares": 0,
            })
        return items
    except Exception:
        return []


def _build_holdings_result(
    ticker: str,
    constituents: List[Dict[str, Any]],
    as_of_date: str,
    source: str,
) -> Dict[str, Any]:
    """組合標準成分股結果字典。"""
    total_weight = sum(c["weight_pct"] for c in constituents)
    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "source": source,
        "total_count": len(constituents),
        "total_weight_pct": round(total_weight, 2),
        "constituents": constituents,
    }


def format_holdings_ascii(data: Dict[str, Any], limit: Optional[int] = None) -> str:
    """產出終端可讀 ASCII 表格。"""
    ticker = data["ticker"]
    count = data["total_count"]
    weight = data["total_weight_pct"]
    src = data["source"]
    as_of = data["as_of_date"]

    lines = []
    lines.append("=" * 72)
    lines.append(f"📊 {ticker} 成分股持股明細 ｜ 共 {count} 檔 (總權重: {weight}%)")
    lines.append(f"⏱️ 數據日期：{as_of} ｜ 來源：{src}")
    lines.append("-" * 72)
    lines.append(f"{'排名':<6} {'個股代號':<14} {'個股名稱':<18} {'投資權重(%)':<14} {'持有股數'}")
    lines.append("-" * 72)

    items = data["constituents"]
    if limit is not None and limit > 0:
        items = items[:limit]

    for idx, c in enumerate(items, 1):
        sym = c["symbol"]
        name = c["name"][:14]
        w = f"{c['weight_pct']:.2f}%"
        s = f"{c['shares']:,}" if c["shares"] > 0 else "-"
        lines.append(f"{idx:<6} {sym:<14} {name:<18} {w:<14} {s}")

    lines.append("=" * 72)
    return "\n".join(lines)
