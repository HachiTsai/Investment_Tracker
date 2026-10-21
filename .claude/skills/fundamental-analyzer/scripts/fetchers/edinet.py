"""日股：EDINET API v2 有價證券報告書（官方，合併報表當期）。

API key 由環境代理以標頭注入（主機 api.edinet-fsa.go.jp），腳本不帶 key，也不得印出或寫入 git。
HTTP 200 仍要查 body 的 metadata.status；IFRS 與日本會計準則的要素 ID 不同，兩套都對照。
"""

import datetime
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import clean, http_bytes, http_json, ratio

BASE = "https://api.edinet-fsa.go.jp/api/v2"
CACHE_FILE = Path.home() / ".cache" / "investment_tracker" / "edinet_docs.json"
CACHE_MAX_DAYS = 300

REVENUE = ("TotalNetRevenuesIFRS", "SalesRevenuesIFRS", "OperatingRevenuesIFRSKeyFinancialData", "NetSalesIFRS",
           "SalesAndFinancialServicesRevenueIFRSKeyFinancialData", "RevenueIFRS", "NetSales",
           "NetSalesSummaryOfBusinessResults", "OperatingRevenue1", "OperatingRevenue1SummaryOfBusinessResults")
OPERATING = ("OperatingProfitLossIFRS", "OperatingIncome")
NET_INCOME = ("ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", "ProfitLossAttributableToOwnersOfParent",
              "ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults")
EQUITY = ("EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", "NetAssetsSummaryOfBusinessResults", "NetAssets")
LIABILITIES = ("LiabilitiesIFRS", "Liabilities")
ROE = ("RateOfReturnOnEquityIFRSSummaryOfBusinessResults", "RateOfReturnOnEquitySummaryOfBusinessResults")
OCF = ("CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults", "NetCashProvidedByUsedInOperatingActivities",
       "NetCashProvidedByUsedInOperatingActivitiesSummaryOfBusinessResults")
CAPEX = ("PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssetsInvCF", "PurchaseOfPropertyPlantAndEquipmentInvCF")
DIVIDENDS = ("DividendsPaidToOwnersOfParentFinCFIFRS", "DividendsPaidFinCF")


def api(path: str) -> Any:
    return http_json(f"{BASE}/{path}")


def list_docs(day: datetime.date) -> List[Dict[str, Any]]:
    data = api(f"documents.json?date={day.isoformat()}&type=2")
    status = str((data.get("metadata") or {}).get("status", data.get("StatusCode")))
    if status != "200":
        raise RuntimeError(f"EDINET status {status}")
    return data.get("results") or []


def scan_order(today: datetime.date, days: int = 366) -> List[datetime.date]:
    """3、6 月下旬申報最密集，先掃；其餘由近到遠。"""
    def rank(d: datetime.date) -> int:
        if d.month == 6 and d.day >= 15:
            return 0
        if d.month == 3 and d.day >= 15:
            return 1
        return 2 if d.month in (3, 6) else 3
    return sorted((today - datetime.timedelta(days=i) for i in range(days)), key=lambda d: (rank(d), -d.toordinal()))


def find_doc(sec_code: str, today: Optional[datetime.date] = None,
             lister: Callable[[datetime.date], List[Dict[str, Any]]] = list_docs) -> Optional[Dict[str, str]]:
    """掃日期找該證券代碼最新的有價證券報告書（docTypeCode 120）。

    每次並行查 8 天；3、6 月下旬先掃，這兩段掃完且已有命中就收手，沒命中才繼續掃其他日期。
    同一份報告可能有多個候選時取最新申報日。"""
    today = today or datetime.date.today()
    order = scan_order(today)
    best: Optional[Dict[str, str]] = None
    with ThreadPoolExecutor(8) as ex:
        for i in range(0, len(order), 8):
            chunk = order[i:i + 8]
            if best and all(d.month not in (3, 6) for d in chunk):
                break
            for d, docs in zip(chunk, ex.map(lister, chunk)):
                hit = next((r for r in docs if r.get("secCode") == sec_code and r.get("docTypeCode") == "120"), None)
                if hit and (best is None or d.isoformat() > best["date"]):
                    best = {"docID": hit["docID"], "date": d.isoformat()}
    return best


def cached_doc(sec_code: str) -> Optional[Dict[str, str]]:
    try:
        entry = json.loads(CACHE_FILE.read_text(encoding="utf-8")).get(sec_code)
        if entry and (datetime.date.today() - datetime.date.fromisoformat(entry["date"])).days <= CACHE_MAX_DAYS:
            return entry
    except Exception:
        pass
    return None


def save_doc(sec_code: str, entry: Dict[str, str]) -> None:
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
        cache[sec_code] = entry
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")
    except Exception:
        pass


def parse_rows(zip_bytes: bytes) -> Dict[str, float]:
    """取 jpcrp030000-asr 主檔（UTF-16、tab 分隔），只留合併當期的數值，鍵為不含命名空間的要素 ID。"""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if "jpcrp030000-asr" in n)
        text = z.read(name).decode("utf-16")
    out: Dict[str, float] = {}
    for line in text.splitlines()[1:]:
        f = [c.strip('"') for c in line.split("\t")]
        if len(f) < 9 or f[2] not in ("CurrentYearDuration", "CurrentYearInstant"):
            continue
        try:
            out.setdefault(f[0].split(":")[-1], float(f[8].replace(",", "")))
        except ValueError:
            continue
    return out


def first(vals: Dict[str, float], names) -> Optional[float]:
    return next((vals[n] for n in names if n in vals), None)


def edinet_info(vals: Dict[str, float]) -> Dict[str, Any]:
    ni, eq, liab = first(vals, NET_INCOME), first(vals, EQUITY), first(vals, LIABILITIES)
    ocf, capex, div = first(vals, OCF), first(vals, CAPEX), first(vals, DIVIDENDS)
    return clean({
        "returnOnEquity": first(vals, ROE) if first(vals, ROE) is not None else ratio(ni, eq),
        "debtToEquity": (ratio(liab, eq) or 0) * 100 or None,
        "operatingMargins": ratio(first(vals, OPERATING), first(vals, REVENUE)),
        "operatingCashflow": ocf,
        "freeCashflow": ocf - abs(capex) if ocf is not None and capex is not None else None,
        "netIncomeToCommon": ni,
        "payoutRatio": ratio(abs(div), ni) if div is not None else None,
    })


def fetch(code: str) -> Dict[str, Any]:
    sec_code = f"{code}0" if len(code) == 4 else code
    doc = cached_doc(sec_code)
    if not doc:
        doc = find_doc(sec_code)
        if not doc:
            return {}
        save_doc(sec_code, doc)
    return edinet_info(parse_rows(http_bytes(f"{BASE}/documents/{doc['docID']}?type=5")))
