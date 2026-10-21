"""台股整合：FinMind（現金流、近四季 ROE 與利潤率）→ Yahoo 股市補現金流 → 證交所（官方最新一期）補缺。

各來源獨立失敗不影響其他來源；先到先得，後面的來源只補缺的欄位；證交所口徑為年初累計，故排最後。全部失敗回 {}，由呼叫端退回 yfinance。
"""

from typing import Any, Callable, Dict, List

from . import finmind, twse, yahoo_tw

SOURCES: List[Callable[[str], Dict[str, Any]]] = [finmind.fetch, yahoo_tw.fetch, twse.fetch]


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
