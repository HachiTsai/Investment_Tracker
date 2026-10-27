"""台股整合：FinMind（現金流、近四季 ROE 與利潤率）→ Yahoo 股市補現金流 → 證交所（官方最新一期）補缺。

各來源獨立失敗不影響其他來源；先到先得，後面的來源只補缺的欄位；證交所口徑為年初累計，故排最後。全部失敗回 {}，由呼叫端退回 yfinance。
"""

from typing import Any, Callable, Dict, List

from . import finmind, finmind_detail, twse, yahoo_tw


def financial_info(code: str) -> Dict[str, Any]:
    """金融業資訊：金融業的資產負債表沒有「歸屬母公司權益」，評分路徑因此算不出 ROE。改用成分股明細頁的總權益口徑補上（ROE 略偏低）。
    屬金融業即回 sector=financial（評分端據此不計負債比）；非金融業或產業查不到回 {}。"""
    try:
        if "金融" not in finmind_detail.industries().get(code, ""):
            return {}
    except Exception:
        return {}
    info: Dict[str, Any] = {"sector": "financial"}
    try:
        roe = (finmind_detail.tw_detail(code) or {}).get("roe")
    except Exception:
        roe = None
    if roe is not None:
        info["returnOnEquity"] = roe / 100.0
    return info


SOURCES: List[Callable[[str], Dict[str, Any]]] = [finmind.fetch, yahoo_tw.fetch, twse.fetch, financial_info]


def fetch(code: str, sources: List[Callable[[str], Dict[str, Any]]] = None) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    for fn in sources or SOURCES:
        try:
            got = fn(code) or {}
        except Exception:
            continue
        for k, v in got.items():
            info.setdefault(k, v)
    return info
