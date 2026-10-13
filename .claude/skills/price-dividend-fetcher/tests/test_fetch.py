import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch as f  # noqa: E402

GF_TW = ('["00882","TPE"],"CTBC Hang Seng China High Dividend Yield ETF",5,"TWD",'
         '[14.75,-0.09000015,-0.60647005,2,3,2],null,14.84,null,"TW","/g/11m9rw8gqt",[1790911474],"Asia/Taipei"')
GF_US = ('["AAPL","NASDAQ"],"Apple Inc",4,"USD",[340.97,4.33,1.2862,2,2,2],null,336.64,null,null,null,[1791874933]'
         '<div class="SwQK7">Dividend</div><div class="dO6ijd">0.32%</div>'
         '<div class="SwQK7">Ex-dividend date</div><div class="dO6ijd">Aug 10, 2026</div>'
         '<div class="SwQK7">Volume</div><div class="dO6ijd">1M</div>')
TWSE_CLOSE = {"date": "20261013", "tables": [{"fields": ["證券代號", "證券名稱", "收盤價", "漲跌(+/-)", "漲跌價差"], "data": [
    ["00882", "中信中國高股息", "15.12", "<p style= color:red>+</p>", "0.06"],
    ["0050", "元大台灣50", "70.00", "<p style= color:green>-</p>", "1.00"],
    ["9999", "無成交", "--", " ", "0.00"]]}]}
TWSE_EX = {"stat": "OK", "data": [
    ["115年07月16日", "00882", "中信中國高股息", "15.16", "14.61", "0.550000", "息"],
    ["115年07月16日", "00878", "其他", "20", "19", "0.400000", "息"],
    ["115年03月01日", "00882", "中信中國高股息", "15", "14", "0.100000", "權"]]}


def row(ex, amt, rec="2026-07-22", pay="2026-08-11"):
    td = '<td class="tnum x">{}</td>'
    return ('<tr class="x">' + td.format(ex) + '<td class="col-num tnum x">' + str(amt) + "</td>"
            + td.format(rec) + td.format(pay) + "</tr>")


FL_HTML = "<tbody>" + row("2026-07-16", 0.55) + row("2026-01-19", 0.45) + row("2025-07-16", 0.55) + "</tbody>"


def test_parse_ticker():
    assert f.parse_ticker("TPE:00882") == ("TPE", "00882")
    assert f.parse_ticker("00882") == ("TPE", "00882")
    assert f.parse_ticker("nasdaq:aapl") == ("NASDAQ", "AAPL")
    assert f.parse_ticker("HKG:0005") == ("HKG", "0005")
    for bad in ("../etc", "FOO:1", "NASDAQ:", "NASDAQ:A B"):
        with pytest.raises(ValueError):
            f.parse_ticker(bad)


def test_parse_price_tw():
    p = f.parse_price(GF_TW, "TPE", "00882")
    assert (p["price"], p["prev_close"], p["change"], p["currency"]) == (14.75, 14.84, -0.09, "TWD")
    assert p["ticker"] == "TPE:00882" and p["as_of"].startswith("2026-10-02")
    assert "dividend_summary" not in p


def test_parse_price_picks_requested_ticker_not_first_quote():
    p = f.parse_price(GF_US + GF_TW, "TPE", "00882")
    assert p["price"] == 14.75
    p = f.parse_price(GF_TW + GF_US, "NASDAQ", "AAPL")
    assert p["price"] == 340.97 and p["currency"] == "USD"


def test_parse_price_dividend_summary_only_dividend_labels():
    p = f.parse_price(GF_US, "NASDAQ", "AAPL")
    assert p["dividend_summary"] == {"Dividend": "0.32%", "Ex-dividend date": "Aug 10, 2026"}


def test_parse_price_missing_raises():
    with pytest.raises(ValueError):
        f.parse_price("<html></html>", "TPE", "00882")
    with pytest.raises(ValueError):
        f.parse_price(GF_TW, "HKG", "00882")   # 交易所不符不能誤配


def test_roc_to_iso():
    assert f.roc_to_iso("115年01月19日") == "2026-01-19"


def test_parse_twse_close():
    p = f.parse_twse_close(TWSE_CLOSE, "00882")
    assert (p["price"], p["change"], p["prev_close"], p["price_type"]) == (15.12, 0.06, 15.06, "close")
    assert p["as_of"] == "2026-10-13"
    d = f.parse_twse_close(TWSE_CLOSE, "0050")
    assert d["change"] == -1.0 and d["prev_close"] == 71.0
    with pytest.raises(ValueError):
        f.parse_twse_close(TWSE_CLOSE, "9999")   # 未成交
    with pytest.raises(ValueError):
        f.parse_twse_close(TWSE_CLOSE, "1234")


def test_parse_twse_dividends_cash_only_for_code():
    rows = f.parse_twse_dividends(TWSE_EX, "00882")
    assert rows == [{"ex_date": "2026-07-16", "amount": 0.55}]
    with pytest.raises(ValueError):
        f.parse_twse_dividends({"stat": "很抱歉，沒有符合條件的資料!"}, "00882")


def test_crosscheck():
    fin = [{"ex_date": "2026-07-16", "amount": 0.55}, {"ex_date": "2026-01-19", "amount": 0.45},
           {"ex_date": "2024-01-17", "amount": 0.26}]
    ok = f.crosscheck(fin, [{"ex_date": "2026-07-16", "amount": 0.55}, {"ex_date": "2026-01-19", "amount": 0.45}], [2026])
    assert ok["consistent"] is True   # 2024 不在比對年度內
    bad = f.crosscheck(fin, [{"ex_date": "2026-07-16", "amount": 0.60}], [2026])
    assert bad["consistent"] is False
    assert {"ex_date": "2026-07-16", "finlab": 0.55, "twse": 0.6} in bad["differences"]
    assert {"ex_date": "2026-01-19", "finlab": 0.45, "twse": None} in bad["differences"]


def test_overseas_dividends_unsupported():
    with pytest.raises(ValueError):
        f.get_dividends("NASDAQ:AAPL")


def test_parse_dividends_sorted_desc():
    rows = f.parse_dividends(FL_HTML, "00882")
    assert [r["ex_date"] for r in rows] == ["2026-07-16", "2026-01-19", "2025-07-16"]
    assert rows[0]["amount"] == 0.55 and rows[0]["pay_date"] == "2026-08-11"


def test_parse_dividends_missing_raises():
    with pytest.raises(ValueError):
        f.parse_dividends("<html></html>", "00882")


def test_yearly_and_ttm():
    rows = f.parse_dividends(FL_HTML, "00882")
    assert f.yearly_totals(rows) == {"2026": 1.0, "2025": 0.55}
    # 2025-07-16 已超過 365 天，不計入
    assert f.ttm_total(rows, date(2026, 10, 2)) == 1.0
    # 2026-07-10：納入 2025-07-16 與 2026-01-19，尚未除息的 2026-07-16 不計
    assert f.ttm_total(rows, date(2026, 7, 10)) == 1.0
    assert f.ttm_total(rows, date(2026, 7, 16)) == 1.0


def test_since_filters_events_not_totals():
    rows = f.parse_dividends(FL_HTML, "00882")
    d = f.build_dividends(rows, "00882", date(2026, 10, 2), since="2026-01-01")
    assert d["count"] == 2
    assert d["yearly_totals"]["2025"] == 0.55


def test_yield():
    d = {"ttm_total": 1.0}
    f.add_yield(d, {"price": 14.84, "price_type": "last"})
    assert d["yield_pct"] == 6.74
