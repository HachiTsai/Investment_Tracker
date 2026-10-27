"""多市場財報資料層單元測試（離線，不連網）。"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fetchers import classify, eastmoney, fetch_info, finmind, sec, tw, twse, yahoo_tw  # noqa: E402


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
    assert out == {"debtToEquity": 50.0, "operatingMargins": 0.4}


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


def test_hk_detail_shape(monkeypatch):
    calls = []

    def fake(base, report, code, size=6):
        calls.append(report)
        if report == "RPT_HKF10_FN_MAININDICATOR":
            return [{"REPORT_DATE": "2026-06-30 00:00:00", "REPORT_TYPE": "2026年中报", "OPERATE_INCOME": 5, "DIVI_RATIO": 0.2}]
        return [{"CURRENCY": "人民币"}]

    monkeypatch.setattr(eastmoney, "query", fake)
    out = eastmoney.hk_detail("700")
    assert out["period"] == "2026-06-30" and out["cur"] == "人民币" and out["rev"] == 5 and out["payout"] == 20.0
    monkeypatch.setattr(eastmoney, "query", lambda *a, **k: [])
    assert eastmoney.hk_detail("700") == {}


def test_edinet_scan_order_prefers_filing_season():
    import datetime
    from fetchers import edinet
    order = edinet.scan_order(datetime.date(2026, 10, 21))
    assert len(order) == 366 and order[0] == datetime.date(2026, 6, 30)
    assert all(d.month == 6 and d.day >= 15 for d in order[:16])


def test_edinet_find_doc_picks_latest_hit_and_stops():
    import datetime
    from fetchers import edinet
    calls = []

    def lister(d):
        calls.append(d)
        return [{"secCode": "72030", "docTypeCode": "120", "docID": f"S{d.day}"}] if d == datetime.date(2026, 6, 10) else []

    doc = edinet.find_doc("72030", datetime.date(2026, 10, 21), lister)
    assert doc == {"docID": "S10", "date": "2026-06-10"}
    assert len(calls) < 366


def test_edinet_key_goes_in_query_only_when_configured(monkeypatch):
    from fetchers import edinet
    seen = []
    monkeypatch.setattr(edinet, "http_json", lambda url: seen.append(url) or {})
    monkeypatch.delenv("EDINET_API_KEY", raising=False)
    edinet.api("documents.json?date=2026-10-21&type=2")
    monkeypatch.setenv("EDINET_API_KEY", " k3y ")
    edinet.api("documents.json?date=2026-10-21&type=2")
    assert seen[0] == f"{edinet.BASE}/documents.json?date=2026-10-21&type=2"
    assert seen[1] == f"{edinet.BASE}/documents.json?date=2026-10-21&type=2&Subscription-Key=k3y"


def test_edinet_info_ifrs_and_jgaap():
    from fetchers import edinet
    ifrs = {"TotalNetRevenuesIFRS": 100.0, "OperatingProfitLossIFRS": 10.0,
            "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults": 8.0,
            "EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults": 40.0, "LiabilitiesIFRS": 60.0,
            "CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults": 12.0,
            "DividendsPaidToOwnersOfParentFinCFIFRS": -2.0}
    out = edinet.edinet_info(ifrs)
    assert out["operatingMargins"] == 0.1 and out["returnOnEquity"] == 0.2 and out["debtToEquity"] == 150.0
    assert out["payoutRatio"] == 0.25 and "freeCashflow" not in out
    jg = {"NetSales": 200.0, "OperatingIncome": 30.0, "ProfitLossAttributableToOwnersOfParent": 20.0, "NetAssets": 100.0,
          "Liabilities": 50.0, "RateOfReturnOnEquitySummaryOfBusinessResults": 0.15,
          "NetCashProvidedByUsedInOperatingActivities": 40.0, "PurchaseOfPropertyPlantAndEquipmentInvCF": -10.0}
    out = edinet.edinet_info(jg)
    assert out["returnOnEquity"] == 0.15 and out["freeCashflow"] == 30.0 and out["debtToEquity"] == 50.0


def test_edinet_parse_rows_uses_consolidated_current_year():
    import io
    import zipfile
    from fetchers import edinet
    header = '"要素ID"\t"項目名"\t"コンテキストID"\t"相対年度"\t"連結・個別"\t"期間・時点"\t"ユニットID"\t"単位"\t"値"'
    row = lambda e, c, v: f'"jppfs_cor:{e}"\t"x"\t"{c}"\t"y"\t"z"\t"w"\t"u"\t"円"\t"{v}"'  # noqa: E731
    text = "\n".join([header, row("NetSales", "CurrentYearDuration", "5"), row("NetSales", "Prior1YearDuration", "4"),
                      row("TotalAssets", "CurrentYearInstant_NonConsolidatedMember", "9"), row("Liabilities", "CurrentYearInstant", "－")])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("XBRL_TO_CSV/jpcrp030000-asr-001.csv", text.encode("utf-16"))
    assert edinet.parse_rows(buf.getvalue()) == {"NetSales": 5.0}


def test_finmind_ttm_from_cumulative():
    s = {"2025-12-31": 400, "2025-06-30": 250, "2026-06-30": 300}
    assert finmind.ttm_from_cumulative(s) == 300 + 400 - 250
    assert finmind.ttm_from_cumulative({"2025-12-31": 7}) == 7
    assert finmind.ttm_from_cumulative({"2026-06-30": 1}) is None


def test_finmind_info_roe_and_fcf():
    q = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
    cf = {"CashFlowsFromOperatingActivities": {"2025-12-31": 80, "2026-12-31": 80},
          "PropertyAndPlantAndEquipment": {"2025-12-31": -30, "2026-12-31": -30}}
    inc = {"EquityAttributableToOwnersOfParent": dict(zip(q, [5, 5, 5, 5, 5])),
           "OperatingIncome": dict(zip(q, [10, 10, 10, 10, 10])), "Revenue": dict(zip(q, [50, 50, 50, 50, 50]))}
    bs = {"EquityAttributableToOwnersOfParent": dict(zip(q, [90, 95, 100, 105, 110])),
          "Liabilities": {"2026-06-30": 55}, "Equity": {"2026-06-30": 110}}
    out = finmind.finmind_info(cf, inc, bs)
    assert out["operatingCashflow"] == 80 and out["freeCashflow"] == 50
    assert round(out["returnOnEquity"], 4) == round(20 / 100, 4)
    assert out["debtToEquity"] == 50.0 and out["operatingMargins"] == 0.2


def test_yahoo_requires_four_consecutive_quarters():
    html = "".join('{"symbol":"2330.TW","date":"%s-01T00:00:00+08:00","operatingCashFlow":"%d","freeCashFlow":"%d"}' % (d, o, o // 2)
                   for d, o in [("2026-06", 40), ("2026-03", 30), ("2025-12", 20), ("2025-09", 10)])
    assert yahoo_tw.yahoo_info(yahoo_tw.parse(html)) == {"operatingCashflow": 100.0, "freeCashflow": 50.0}
    assert yahoo_tw.yahoo_info([("2026-06", 1, 1), ("2025-12", 1, 1), ("2025-09", 1, 1), ("2025-06", 1, 1)]) == {}


def test_tw_merge_first_source_wins_and_failures_skipped():
    def boom(_):
        raise RuntimeError

    out = tw.fetch("2330", [lambda c: {"returnOnEquity": 0.4}, boom, lambda c: {"returnOnEquity": 0.1, "debtToEquity": 30}])
    assert out == {"returnOnEquity": 0.4, "debtToEquity": 30}


def test_hk_dividends_parses_amount_currency_and_hkd(monkeypatch):
    rows = [
        {"NOTICE_DATE": "2026-08-26 00:00:00", "YEAR": "2026", "REPORT_TYPE": "中期分配", "EX_DIVIDEND_DATE": "2026/11/02",
         "DIVIDEND_DATE": "2026/12/22", "PLAN_EXPLAIN": "每股派人民币0.203元(相当于港币0.23462元(计算值))"},
        {"NOTICE_DATE": "2026-03-26", "YEAR": "2025", "REPORT_TYPE": "年度分配", "PLAN_EXPLAIN": "每股派港币0.46元(可选择以股代息)"},
        {"NOTICE_DATE": "2025-08-27", "YEAR": "2025", "REPORT_TYPE": "中期分配", "PLAN_EXPLAIN": "未派发或宣派股息"},
        {"NOTICE_DATE": "2024-08-29", "YEAR": "2024", "REPORT_TYPE": "特别分配", "PLAN_EXPLAIN": "每持有1000股获分派193股"},
    ]
    monkeypatch.setattr(eastmoney, "http_json", lambda url: {"result": {"data": rows}})
    out = eastmoney.hk_dividends("998")
    assert out[0]["amt"] == 0.203 and out[0]["cur"] == "人民币" and out[0]["hkd"] == 0.23462 and out[0]["pay"] == "2026-12-22"
    assert out[1]["hkd"] == 0.46 and out[2]["amt"] == 0.0 and "amt" not in out[3]


def test_edinet_day_list_is_fetched_once_and_shared(monkeypatch, tmp_path):
    import datetime
    from fetchers import edinet
    calls = []

    def fake(day):
        calls.append(day)
        return [{"secCode": "72030", "docID": "S1", "docTypeCode": "120"}, {"secCode": "1", "docID": "x", "docTypeCode": "030"}]
    monkeypatch.setattr(edinet, "list_docs", fake)
    monkeypatch.setattr(edinet, "_days", {})
    monkeypatch.setattr(edinet, "DAY_CACHE_FILE", tmp_path / "days.json")
    day = datetime.date.today() - datetime.timedelta(days=3)
    first = edinet.list_docs_cached(day)
    second = edinet.list_docs_cached(day)
    assert len(calls) == 1 and first[0]["docID"] == "S1" and second == [{"secCode": "72030", "docID": "S1", "docTypeCode": "120"}]
    edinet.list_docs_cached(datetime.date.today())
    edinet.list_docs_cached(datetime.date.today())
    assert len(calls) == 3  # 今天不快取
    edinet.save_days()
    assert str(day) in (tmp_path / "days.json").read_text()


def test_edinet_reason_labels_and_status_error(monkeypatch):
    import datetime
    import urllib.error
    import pytest
    from fetchers import edinet
    assert edinet._reason(urllib.error.HTTPError("https://x?Subscription-Key=k", 401, "Unauthorized", {}, None)) == "HTTP 401"
    assert edinet._reason(edinet.EdinetStatusError("400")) == "EDINET status 400"
    assert edinet._reason(ValueError("Subscription-Key=k")) == "ValueError"
    monkeypatch.setattr(edinet, "api", lambda path: {"metadata": {"status": "400"}})
    with pytest.raises(edinet.EdinetStatusError) as info:
        edinet.list_docs(datetime.date(2026, 10, 21))
    assert info.value.status == "400" and str(info.value) == "EDINET status 400"


def test_edinet_failure_reports_reason_without_leaking_key(monkeypatch, capsys):
    import urllib.error
    from fetchers import edinet
    monkeypatch.setenv("EDINET_API_KEY", "SECRET123")
    monkeypatch.setattr(edinet, "cached_doc", lambda sec_code: None)

    def denied(sec_code, *args, **kwargs):
        raise urllib.error.HTTPError(f"{edinet.BASE}/documents.json?Subscription-Key=SECRET123", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(edinet, "find_doc", denied)
    assert fetch_info("7203.T", {"JP": edinet.fetch}) == {}  # 失敗仍退回 yfinance，行為不變
    err = capsys.readouterr().err
    assert err == "EDINET 7203：失敗（HTTP 401）；EDINET_API_KEY 已設定，退回 yfinance\n"
    assert "SECRET123" not in err and "Subscription-Key" not in err


def test_edinet_missing_doc_or_values_are_reported(monkeypatch, capsys):
    from fetchers import edinet
    monkeypatch.delenv("EDINET_API_KEY", raising=False)
    monkeypatch.setattr(edinet, "cached_doc", lambda sec_code: None)
    monkeypatch.setattr(edinet, "find_doc", lambda sec_code, *args, **kwargs: None)
    assert edinet.fetch("7203") == {}
    assert capsys.readouterr().err == "EDINET 7203：近一年查無有價證券報告書；EDINET_API_KEY 未設定，退回 yfinance\n"
    monkeypatch.setattr(edinet, "report_bytes", lambda code: b"zip")
    monkeypatch.setattr(edinet, "parse_rows", lambda raw: {})
    assert edinet.fetch("7203") == {}
    assert capsys.readouterr().err == "EDINET 7203：報告書無可用數值；EDINET_API_KEY 未設定，退回 yfinance\n"
