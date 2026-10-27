#!/usr/bin/env python3
"""美股、日股的持股來源：讀取 Drive「全市場 ETF 成分股資料庫」（只讀，ETF_Summary 與 ETF_Constituents）。

2026-10-27 Hachi 指示：美股、日股的持股到全市場表找，不用 Yahoo 前幾大。表內的 last_model_update 是模型卡片的建立日期
（model_date），表內沒有來源的持股日期，所以 as_of_date 一律是 None。找不到的代號拋 NotInPool，由各市場退回 yfinance；
讀取失敗（沒有 GCP_SA_KEY、網路或權限）拋 RuntimeError，由 etf_pool.holdings_for 退回 models 卡片。
"""
import functools
import os
import sys
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(SKILLS, "price-dividend-fetcher", "scripts"))

# 與 etf_sheets_sync.DEFAULT_SHEET_ID 相同；環境變數 ETF_CONSTITUENTS_SHEET_ID 可覆寫
POOL_SHEET_ID = os.environ.get("ETF_CONSTITUENTS_SHEET_ID", "1GIhbRyL-h96ACVjlSSW9YUFMiAItg_SP9Wi0o3WwG70")
# 來源名稱不含「備援」或「models」，coverage 判為 partial，美股與日股採用
SOURCE = "全市場 ETF 成分股資料庫（Drive）"


class NotInPool(LookupError):
    """這檔 ETF 不在全市場表的成分股裡。"""


@functools.lru_cache(maxsize=None)
def _tables(sheet_id: str = POOL_SHEET_ID) -> tuple:
    """整張表只讀一次，整段程序共用。使用 GCP_SA_KEY（與寫入同一把服務帳號）。"""
    from google_sheets import GoogleSheetsClient  # 延後匯入：只有實際讀表時才需要 requests 與認證

    client = GoogleSheetsClient()
    return client.get_values(sheet_id, "ETF_Summary!A:Z"), client.get_values(sheet_id, "ETF_Constituents!A:G")


def _col(header: List[Any], name: str) -> int:
    """欄名在表頭的位置；表頭沒有這欄就拋 RuntimeError，表的結構改了不硬猜。"""
    names = [str(h).strip() for h in header]
    if name not in names:
        raise RuntimeError(f"全市場表缺欄位：{name}")
    return names.index(name)


def _cell(row: List[Any], i: int) -> str:
    return str(row[i]).strip() if i < len(row) else ""


def parse(summary: List[List[Any]], cons: List[List[Any]], etf: str) -> Dict[str, Any]:
    """從 ETF_Summary 與 ETF_Constituents 的列取出一檔 ETF 的持股（純函式，測試直接餵列）。
    成分股表沒有這檔就拋 NotInPool；model_date 取自摘要表的 last_model_update（建立日期），沒有就是 None。"""
    code = etf.strip().upper()
    if len(cons) < 2:
        raise NotInPool(code)
    ci = {k: _col(cons[0], k) for k in ("etf_id", "constituent_ticker", "constituent_name", "weight_pct", "shares")}
    rows = []
    for r in cons[1:]:
        if _cell(r, ci["etf_id"]).upper() != code:
            continue
        try:
            weight = float(_cell(r, ci["weight_pct"]))
        except ValueError:
            continue
        shares = _cell(r, ci["shares"])
        rows.append(dict(symbol=_cell(r, ci["constituent_ticker"]), name=_cell(r, ci["constituent_name"]),
                         weight_pct=round(weight, 4), shares=int(shares) if shares.isdigit() else None))
    if not rows:
        raise NotInPool(code)
    model_date = None
    if summary:
        ei, mi = _col(summary[0], "etf_id"), _col(summary[0], "last_model_update")
        for r in summary[1:]:
            if _cell(r, ei).upper() == code:
                model_date = _cell(r, mi) or None
                break
    return dict(ticker=code, as_of_date=None, model_date=model_date, source=SOURCE, total_count=len(rows),
                total_weight_pct=round(sum(c["weight_pct"] for c in rows), 2), constituents=rows)


def holdings(etf: str) -> Dict[str, Any]:
    """市場介面用：讀表（整段程序只讀一次）後取出這檔 ETF 的持股。"""
    summary, cons = _tables()
    return parse(summary, cons, etf)
