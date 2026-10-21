"""多市場財報資料層單元測試（離線，不連網）。"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fetchers import classify, eastmoney, fetch_info, sec, twse  # noqa: E402


def test_classify_symbols():
    assert classify("1919.HK") == ("HK", "01919")
    assert classify("HKG:0700") == ("HK", "00700")
    assert classify("600519.SH") == ("CN", "600519")
    assert classify("000001.SZ") == ("CN", "000001")
    assert classify("2330") == ("TW", "2330")
    assert classify("TPE:2330") == ("TW", "2330")
    assert classify("AAPL") == ("US", "AAPL")
    assert classify("NASDAQ:AAPL") == ("US", "AAPL")
    assert classify("7203.T") == ("JP", "7203")
    assert classify("") == ("", "")


def test_fetch_info_dispatch_and_failure():
    assert fetch_info("AAPL", {"US": lambda c: {"x": c}}) == {"x": "AAPL"}
    assert fetch_info("7203.T", {"US": lambda c: {"x": 1}}) == {}

    def boom(code):
        raise RuntimeError("down")

    assert fetch_info("AAPL", {"US": boom}) == {}


def test_hk_info_mapping():
    row = {"ROE_YEARLY": 21.0, "TOTAL_LIABILITIES": 50.0, "TOTAL_PARENT_EQUITY": 100.0, "OPERATE_PROFIT": 30.0,
           "OPERATE_INCOME": 100.0, "NETCASH_OPERATE": 9, "HOLDER_PROFIT": 8, "DIVI_RATIO": 0.2, "PE_TTM": 14.0}
    out = eastmoney.hk_info(row)
    assert out["returnOnEquity"] == 0.21 and out["debtToEquity"] == 50.0 and out["operatingMargins"] == 0.3
    assert out["payoutRatio"] == 0.2 and "priceToBook" not in out


def test_annual_picks_year_report():
    rows = [{"DATE_TYPE_CODE": "002", "v": 1}, {"DATE_TYPE_CODE": "001", "v": 2}]
    assert eastmoney.annual(rows)["v"] == 2 and eastmoney.annual([]) == {}


def test_cn_info_fcf():
    out = eastmoney.cn_info({"PARENT_NETPROFIT": 10, "OPERATE_PROFIT": 20, "TOTAL_OPERATE_INCOME": 100},
                            {"TOTAL_EQUITY": 100, "TOTAL_LIABILITIES": 40}, {"NETCASH_OPERATE": 15, "CONSTRUCT_LONG_ASSET": 5})
    assert out["freeCashflow"] == 10 and out["returnOnEquity"] == 0.1 and out["debtToEquity"] == 40.0


def test_twse_info_skips_roe():
    out = twse.twse_info({"營業收入": "100", "營業利益（損失）": "40", "淨利（淨損）歸屬於母公司業主": "30"},
                         {"負債總計": "50", "權益總計": "100"})
    assert out == {"debtToEquity": 50.0, "operatingMargins": 0.4, "netIncomeToCommon": 30.0}


def test_sec_latest_annual_picks_newest_10k():
    facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        {"form": "10-K", "fp": "FY", "fy": 2023, "start": "2023-01-01", "end": "2023-12-31", "val": 1},
        {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2024-01-01", "end": "2024-12-31", "val": 2},
        {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2024-10-01", "end": "2024-12-31", "val": 7},
        {"form": "10-Q", "fp": "Q1", "fy": 2025, "end": "2025-03-31", "val": 9}]}}}}}
    assert sec.latest_annual(facts, "NetIncomeLoss") == 2
    assert sec.latest_annual(facts, "Missing") is None
    assert sec.sec_info(facts) == {"netIncomeToCommon": 2}


def test_sec_prefers_freshest_tag():
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [{"form": "10-K", "fp": "FY", "start": "2017-10-01", "end": "2018-09-29", "val": 1}]}},
        "SalesRevenueNet": {"units": {"USD": [{"form": "10-K", "fp": "FY", "start": "2024-10-01", "end": "2025-09-27", "val": 5}]}}}}}
    assert sec.latest_annual(facts, "Revenues", "SalesRevenueNet") == 5
