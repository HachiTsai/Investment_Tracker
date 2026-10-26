"""tw-etf-fetcher 的市場介面與共用安全防線（只用標準函式庫）。

每個市場是一個 Market：代號解析、ETF 持股、個股資料、產業別，外加頁面設定。台股是第一個實作（etf_table.TW）；
港股、美股、日股之後各自提供一份 Market，頁面與資料池流程不必再改。

安全防線放在這裡，所有入口共用：
- pure_code：輸出一律是純代號，不帶 .TW／.TWO／.US／.JP 等國別後綴（這類文字上傳 Drive 後會被標成危險檔案）。
- find_forbidden_suffix：寫檔前掃描輸出，出現後綴就中止。
- guard_sheet_id：寫入試算表前檢查目標，Investment_Tracker_Core 一律拒絕。
- json_for_script：把 JSON 放進頁面的 script 區塊前跳脫 < > &，外部名稱不會截斷頁面。
- gate_reasons：排程健康門檻判定（ETF 數量、缺價與財報、列數下限），資料池與全市場試算表共用同一套規則。
"""
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = 1

# Investment_Tracker_Core 是 APP 後台資料庫，程式不得寫入（規則見 .claude/rules/core-database.md）
CORE_SHEET_IDS = frozenset({"1QBEgUi-kTOuLgj2yGHmP-0g_ug-Sl_M21SN0g93b6xI"})

# 持股來源：MoneyDJ 與中信投信 ETFHoldingWeight 是官方完整持股（coverage full）；repo 內的 models 卡片只是備援
CTBC_SOURCE = "中信投信 ETFHoldingWeight"
FULL_SOURCES = ("MoneyDJ", CTBC_SOURCE)

SUFFIXES = ("TW", "TWO", "US", "JP", "HK", "TF")
_SUFFIX_RE = re.compile(r"\.(?:%s)$" % "|".join(SUFFIXES), re.IGNORECASE)
_PREFIX_RE = re.compile(r"^(?:TPE|TWO|HKG|NYSE|NASDAQ|TYO):", re.IGNORECASE)
# 只認大寫的國別後綴，與 Drive 的判定對齊；小寫網域（例如 .com.tw）不在此列
_FORBIDDEN_RE = re.compile(r"[A-Za-z0-9]+\.(?:%s)(?![A-Za-z0-9])" % "|".join(SUFFIXES))


class CoreWriteRefused(RuntimeError):
    """要寫入的目標是 Investment_Tracker_Core。"""


def pure_code(raw: str) -> str:
    """'TPE:2330' → '2330'、'2330.TW' → '2330'、'nvda.us' → 'NVDA'。"""
    return _SUFFIX_RE.sub("", _PREFIX_RE.sub("", str(raw).strip())).upper()


def find_forbidden_suffix(text: str) -> List[str]:
    """回傳文字中出現的國別後綴片段（排序去重）；空清單代表乾淨。"""
    return sorted(set(_FORBIDDEN_RE.findall(text)))


def guard_sheet_id(sheet_id: str) -> str:
    """寫入前檢查目標試算表：Core 一律拒絕，其餘原樣回傳。"""
    if str(sheet_id).strip() in CORE_SHEET_IDS:
        raise CoreWriteRefused("目標是 Investment_Tracker_Core，嚴禁寫入（見 .claude/rules/core-database.md）")
    return sheet_id


def json_for_script(obj: Any) -> str:
    """JSON 文字，可安全放進 HTML 的 script 區塊；跳脫後解析結果與原物件相同。"""
    s = json.dumps(obj, ensure_ascii=False)
    for ch, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), (" ", "\\u2028"), (" ", "\\u2029")):
        s = s.replace(ch, esc)
    return s


class TimeLimitExceeded(RuntimeError):
    """抓取超過市場的總時間上限：中止，且不寫入任何檔案。"""


@dataclass(frozen=True)
class Limits:
    """限流與逾時：並行數、補抓次數與補抓前的等待秒數、整段抓取的總時間上限（秒，預設 15 分鐘）。"""
    workers: int = 6
    retries: int = 1
    retry_wait: float = 3.0
    max_seconds: float = 900.0


@dataclass(frozen=True)
class Gate:
    """健康門檻：排程資料池（ETF 數量、缺價與缺財報合計、異常 ETF、每檔持股檔數）與全市場試算表（列數）的下限與上限。"""
    min_pool_etfs: int = 15
    max_pool_missing: int = 10
    max_pool_error_etfs: int = 0
    min_holdings: int = 0  # 每檔 ETF 的持股檔數下限；0 不檢查（台股沿用）
    min_summary_rows: int = 200
    min_constituent_rows: int = 10000


def gate_reasons(rules: Sequence[Tuple[str, float, float, str]]) -> List[str]:
    """健康門檻判定：每條規則是 (說明, 實際值, 門檻, "min" 或 "max")。min 低於門檻、max 高於門檻就是一條失敗原因。"""
    reasons = []
    for label, value, limit, kind in rules:
        if kind == "min" and value < limit:
            reasons.append(f"{label}：{value} < {limit}")
        elif kind == "max" and value > limit:
            reasons.append(f"{label}：{value} > {limit}")
        elif kind not in ("min", "max"):
            raise ValueError(f"未知的門檻種類：{kind}")
    return reasons


@dataclass(frozen=True)
class Market:
    """一個市場的接點。持股與個股函式由呼叫端注入，測試可替換；coverage_label 判定持股是否完整。"""
    code: str                                             # 輸出用的市場代號，例如 TW
    name: str                                             # 顯示名稱，例如 台股
    profile: str                                          # etf_page.PROFILES 的鍵
    currency: str                                         # 個股報價幣別
    parse_code: Callable[[str], Optional[str]]            # 成分股原始代號 → 純代號；不屬於此市場回 None
    holdings: Callable[[str], Dict[str, Any]]             # ETF 代號 → 持股（as_of_date、source、constituents）
    stock: Callable[[str, str, Optional[str], Any], Dict[str, Any]]  # (代號, 名稱, 產業, 日期) → 個股結果
    industry: Callable[[], Dict[str, str]]                # 代號 → 產業別；抓不到就拋例外，由呼叫端退回空值
    limits: Limits = Limits()                             # 並行數、補抓與總時間上限（台股用預設值）
    gate: Gate = Gate()                                   # 健康門檻（資料池與全市場試算表共用）
    unit_note: str = ""  # 頁首頭條數字的說明；空白沿用 etf_page.PROFILES
    source_note: str = ""  # 索引頁的財報與股價來源說明
    finish: Optional[Callable[[Dict[str, Dict[str, Any]], date], Dict[str, Dict[str, Any]]]] = None  # 資料池完成後的跨檔步驟


def market_stocks(market: Market, holdings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """持股中屬於此市場的個股列；現金、海外股票、期貨等不列入個股頁。"""
    return [c for c in holdings["constituents"] if market.parse_code(c["symbol"]) is not None]


def coverage_label(holdings: Dict[str, Any]) -> str:
    """持股完整度：官方完整來源為 full；repo 內舊卡片為 fallback；其餘來源視為 partial。"""
    src = str(holdings.get("source", ""))
    if src in FULL_SOURCES:
        return "full"
    if "備援" in src or "models" in src:
        return "fallback"
    return "partial"
