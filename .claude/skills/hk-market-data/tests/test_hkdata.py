import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import hkdata as h  # noqa: E402


def test_norm():
    assert h.norm("0939") == "939"
    assert h.norm("00939") == "939"
    assert h.norm("939 HK") == "939"


def test_parse_prefix():
    assert h.parse_prefix('callback({"more":"1","stockInfo":[{"stockId":9970,"code":"00939"}]});') == 9970
    assert h.parse_prefix('callback({"stockInfo":[]});') is None


def test_parse_titles_filters_keywords():
    rows = [
        {"DATE_TIME": "28/08/2026 18:23", "TITLE": "Interim Dividend for the Six Months", "FILE_LINK": "/a.pdf"},
        {"DATE_TIME": "27/08/2026 10:00", "TITLE": "Monthly Return &amp; Movements", "FILE_LINK": "/b.pdf"},
        {"DATE_TIME": "26/08/2026 12:00", "TITLE": "ANNOUNCEMENT OF\nINTERIM RESULTS", "FILE_LINK": "/c.pdf"},
    ]
    payload = json.dumps({"result": json.dumps(rows)})
    got = h.parse_titles(payload)
    assert [g["url"] for g in got] == [h.HKEXNEWS + "/a.pdf", h.HKEXNEWS + "/c.pdf"]
    assert got[1]["title"] == "ANNOUNCEMENT OF INTERIM RESULTS"
    assert len(h.parse_titles(payload, keep_all=True)) == 3
    assert h.parse_titles(json.dumps({"result": "null"})) == []


def test_parse_eastmoney():
    payload = json.dumps({"success": True, "result": {"data": [
        {"TRADE_DATE": "2026-10-09 00:00:00", "NET_DEAL_AMT": 290.670000000002, "DEAL_AMT": 78941.45,
         "BUY_AMT": 39616.06, "SELL_AMT": 39325.39, "INDEX_CLOSE_PRICE": 24000.1, "INDEX_CHANGE_RATE": 1.79}]}})
    assert h.parse_eastmoney(payload)[0] == dict(date="2026-10-09", net=290.67, buy=39616.06, sell=39325.39,
                                                 turnover=78941.45, hsi=24000.1, hsi_chg_pct=1.79)


def test_parse_hkex_daily_matches_eastmoney():
    def mk(market, total, buy, sell, day=1):
        return {"date": "2026-10-09", "market": market, "tradingDay": day, "content": [{"table": {
            "schema": [["Total Turnover", "Buy Turnover", "Sell Turnover"]],
            "tr": [{"td": [[total]]}, {"td": [[buy]]}, {"td": [[sell]]}]}}]}
    data = [mk("SSE Northbound", "1", "1", "1"), mk("SSE Southbound", "50,388.45", "24,028.79", "26,359.66"),
            mk("SZSE Southbound", "28,553.00", "15,587.27", "12,965.73")]
    got = h.parse_hkex_daily("tabData = " + json.dumps(data) + ";")
    assert got["net"] == 290.67
    assert h.parse_hkex_daily("tabData = " + json.dumps([mk("SSE Southbound", "0", "0", "0", day=0)])) is None


def test_parse_yahoo():
    payload = json.dumps({"chart": {"error": None, "result": [{
        "meta": {"symbol": "0939.HK", "currency": "HKD", "regularMarketPrice": 9.9, "chartPreviousClose": 9.0,
                 "regularMarketTime": 1791965304, "fiftyTwoWeekHigh": 10, "fiftyTwoWeekLow": 7},
        "indicators": {"quote": [{"close": [9.0, None, 9.5, 9.9]}]}}]}})
    got = h.parse_yahoo(payload)
    assert got["prev_close"] == 9.5
    assert got["range_change_pct"] == 10.0
    assert got["as_of"].startswith("2026-10-")


def test_sector_returns():
    now = {"939": {"weights_": "2", "price_": "11", "name_": "建行"},
           "1398": {"weights_": "2", "price_": "9", "name_": "工行"},
           "9999": {"weights_": "1", "price_": "1", "name_": "新股"}}
    prev = {"939": {"price_": "10"}, "1398": {"price_": "10"}}
    base = {"939": {"price_": "10"}}
    sec, stocks, unmapped = h.sector_returns(now, prev, base)
    bank = next(s for s in sec if s["sector"] == "銀行")
    assert bank["weight"] == 4
    assert abs(bank["r1w"]) < 1e-9
    assert abs(bank["rytd"] - 0.1) < 1e-9
    assert unmapped == ["9999"]


def test_pdf_rejects_other_hosts():
    import pytest
    with pytest.raises(ValueError):
        h.pdf_text("https://example.com/x.pdf")


def test_parse_ccass_and_southbound_share():
    def cell(v):
        return f'<div class="mobile-list-body">{v}</div>'
    page = "".join(cell(v) for v in [
        "C00019", "THE HONGKONG AND SHANGHAI BANKING", "addr", "33,551,231,626", "13.95%",
        "A00003", "CHINA SECURITIES DEPOSITORY AND CLEARING", "addr", "31,221,801,869", "12.98%",
        "A00004", "CHINA SECURITIES DEPOSITORY AND CLEARING", "addr", "5,088,055,068", "2.11%"])
    rows = h.parse_ccass(page)
    assert [r["id"] for r in rows] == ["C00019", "A00003", "A00004"]
    assert rows[0]["shares"] == 33551231626
    assert h.southbound_share(rows) == dict(shares=36309856937, pct=15.09)


def test_parse_lpr():
    payload = json.dumps({"success": True, "result": {"data": [{"TRADE_DATE": "2026-09-20 00:00:00", "LPR1Y": 3.0, "LPR5Y": 3.5}]}})
    res = h.parse_lpr(payload)
    assert res == dict(date="2026-09-20", lpr_1y=3.0, lpr_5y=3.5)


def test_parse_chinabond():
    html = """
    <tr><td>中债国债收益率曲线</td><td>2026-10-16</td><td>1.15</td><td>1.16</td><td>1.17</td><td>1.27</td><td>1.38</td><td>1.47</td><td>1.6480</td><td>2.0600</td></tr>
    """
    res = h.parse_chinabond(html)
    assert res == dict(date="2026-10-16", yield_10y=1.648, yield_30y=2.06)


def test_parse_sse_index():
    html = """
    <tr><td>综合指数 Comprehensive Index</td><td>USD/TEU</td><td>100%</td><td>3664.11</td><td>3679.58</td><td>15.47</td></tr>
    """
    res = h.parse_sse_index(html, "综合指数 Comprehensive Index")
    assert res == dict(prev=3664.11, current=3679.58, change=15.47)



def test_wind_report_template_is_complete_page():
    t = (Path(__file__).resolve().parent.parent / "references" / "wind_report.html").read_text(encoding="utf-8")
    assert "<title>00882 舊經濟風向</title>" in t
    assert t.count("<main>") == 1 and t.count("</main>") == 1
    assert "prefers-color-scheme:dark" in t
