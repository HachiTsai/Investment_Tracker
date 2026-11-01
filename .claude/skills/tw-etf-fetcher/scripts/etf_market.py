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

SUFFIXES = ("TW", "TWO", "US", "JP", "HK", "TF", "TX", "SH", "SZ")
_SUFFIX_RE = re.compile(r"\.(?:%s)$" % "|".join(SUFFIXES), re.IGNORECASE)
_PREFIX_RE = re.compile(r"^(?:TPE|TWO|HKG|NYSE|NASDAQ|TYO):", re.IGNORECASE)
# 只認大寫的國別後綴，與 Drive 的判定對齊；小寫網域（例如 .com.tw）不在此列
_FORBIDDEN_RE = re.compile(r"[A-Za-z0-9]+\.(?:%s)(?![A-Za-z0-9])" % "|".join(SUFFIXES))


class CoreWriteRefused(RuntimeError):
    """要寫入的目標是 Investment_Tracker_Core。"""


def pure_code(raw: str) -> str:
    """'TPE:2330' → '2330'、'2330.TW' → '2330'、'nvda.us' → 'NVDA'。"""
    return _SUFFIX_RE.sub("", _PREFIX_RE.sub("", str(raw).strip())).upper()


_STRIP_RE = re.compile(r"\.(?:%s)(?![A-Za-z0-9])" % "|".join(SUFFIXES))


def strip_suffixes(text: str) -> str:
    """去掉文字中任何位置的國別後綴（'FITXN*1.TF)' → 'FITXN*1)'、'ABC.US' → 'ABC'）；只認大寫，與 find_forbidden_suffix 對齊。"""
    return _STRIP_RE.sub("", str(text))


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
    accept_coverage: Tuple[str, ...] = ("full",)  # 採用官方持股的 coverage；美股只有前幾大持股，允許 partial（頁面標示）


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


# ---- 成分股所屬市場（全市場 ETF 表的 constituent_market 欄）----
# 代碼：TW 台股、US 美股、JP 日股、HK 港股、CN 陸股（A 股）、DERIV 期貨選擇權、BOND 債券、CASH 現金與應收付、OTHER 無法判定
CONSTITUENT_MARKETS = ("TW", "US", "JP", "HK", "CN", "DERIV", "BOND", "CASH", "OTHER")
_RAW_SUFFIX_MARKET = {"TW": "TW", "TWO": "TW", "US": "US", "JP": "JP", "T": "JP", "HK": "HK", "SH": "CN", "SZ": "CN", "SS": "CN", "TF": "DERIV"}
_RAW_SUFFIX_RE = re.compile(r"\.([A-Za-z]{1,3})$")
_DERIV_RE = re.compile(r"期貨|選擇權|股票期貨|FIT[A-Z]*\*|\d{4}/\d{1,2}|\s\d{6}$|\(CBT\)|\bFUT")
_BOND_RE = re.compile(r"^[A-Z0-9.&/-]+ \d+(\.\d+)? \d{2}/\d{2}/\d{2,4}|\s.*(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}[A-Z]{3}\d{4}|\d%|\bPERP\b)")
_CASH_RE = re.compile(r"現金|NTD|USD|應收|應付|保證金|款項")
_HINT_RULES = (  # (市場, 關鍵字)；依序比對 ETF 名稱與追蹤指數，用來判定沒有字母也沒有後綴的純數字代號
    ("JP", ("日本", "日經", "東証", "東證", "TOPIX", "NIKKEI")),
    ("HK", ("恒生", "恆生", "港", "中國高股息", "H股")),
    ("CN", ("滬深", "上証", "上證", "深証", "深證", "A50", "中國", "中小企業")),
    ("US", ("標普", "S&P", "那斯達克", "NASDAQ", "費城", "美國", "美債")),
)


def etf_market_hint(etf_name: str = "", benchmark: str = "") -> str:
    """由 ETF 名稱與追蹤指數推出主要曝險市場，只用來解讀純數字代號；沒有線索就是 TW。"""
    text = f"{etf_name} {benchmark}".upper()
    for market, keys in _HINT_RULES:
        if any(k.upper() in text for k in keys):
            return market
    return "TW"


def classify_constituent(raw_ticker: str, name: str = "", hint: str = "TW") -> str:
    """成分股所屬市場。raw_ticker 是未去後綴的原始代號（有後綴時直接採信），hint 是 ETF 的曝險市場（解讀純數字代號用）。"""
    t = str(raw_ticker or "").strip()
    n = str(name or "").strip()
    t = re.sub(r"^(?:TPE|TWO|HKG|NYSE|NASDAQ|TYO):", "", t, flags=re.IGNORECASE)
    if _DERIV_RE.search(t) and "(CBT)" in t:
        return "DERIV"
    if _BOND_RE.search(t):
        return "BOND"
    m = _RAW_SUFFIX_RE.search(t)
    if m and m.group(1).upper() in _RAW_SUFFIX_MARKET:
        return _RAW_SUFFIX_MARKET[m.group(1).upper()]
    if _DERIV_RE.search(t) or _DERIV_RE.search(n):
        return "DERIV"
    if _CASH_RE.search(t) or (not t and _CASH_RE.search(n)):
        return "CASH"
    code = t.upper()
    if re.fullmatch(r"\d{3,6}[A-Z]?", code):
        if re.fullmatch(r"00\d{3,4}[A-Z]?", code) and hint != "HK":
            return "TW"  # ETF 持有 ETF（例如 00645）
        if hint == "CN":
            return "CN" if len(code) == 6 else "HK"
        if hint in ("JP", "HK"):
            return hint
        return "TW"
    if re.fullmatch(r"[A-Z]{1,5}([.-][A-Z])?", code):
        return "US"
    return "OTHER"
