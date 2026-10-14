import sys
from datetime import date, datetime, timezone
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


TPEX_FIELDS = ["代號", "名稱", "收盤 ", "漲跌", "開盤 "]
TPEX = {"stat": "ok", "date": "20261014", "tables": [{"fields": TPEX_FIELDS, "data": [
    ["6488", "環球晶", "1,020.00", "+5.00", "1,020.00"],
    ["8069", "元太", "151.50", "-4.00", "147.50"],
    ["6180", "橘子", "35.00", "除息", "35.00"],
    ["3105", "穩懋", "----", "---", "----"]]}]}


def test_parse_tpex_close():
    p = f.parse_tpex_close(TPEX, "6488")
    assert (p["price"], p["change"], p["prev_close"], p["price_type"], p["source"]) == (1020.0, 5.0, 1015.0, "close", "TPEx")
    assert p["as_of"] == "2026-10-14" and p["ticker"] == "TPE:6488"
    assert f.parse_tpex_close(TPEX, "8069")["prev_close"] == 155.5


def test_parse_tpex_close_special_day_has_no_prev():
    p = f.parse_tpex_close(TPEX, "6180")   # 除息日漲跌欄是文字
    assert p["price"] == 35.0 and p["change"] is None and p["prev_close"] is None and p["change_pct"] is None


def test_parse_tpex_close_errors():
    with pytest.raises(ValueError, match="未成交"):
        f.parse_tpex_close(TPEX, "3105")
    with pytest.raises(ValueError, match="找不到"):
        f.parse_tpex_close(TPEX, "0000")
    with pytest.raises(ValueError, match="回應異常"):
        f.parse_tpex_close({"stat": "error"}, "6488")


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


def _ts(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp())


def yahoo_payload(closes, now, off=-14400, divs=None, cur="USD", error=None):
    """closes：[(日期 UTC 時戳, 收盤)]；now：regularMarketTime。"""
    if error:
        return {"chart": {"result": None, "error": {"code": "Not Found", "description": error}}}
    res = {"meta": {"currency": cur, "regularMarketPrice": closes[-1][1], "regularMarketTime": now,
                    "gmtoffset": off, "chartPreviousClose": 143.76, "longName": "Apple Inc."},
           "timestamp": [t for t, _ in closes], "indicators": {"quote": [{"close": [c for _, c in closes]}]}}
    if divs:
        res["events"] = {"dividends": {str(t): {"amount": a, "date": t} for t, a in divs}}
    return {"chart": {"result": [res], "error": None}}


def test_yahoo_symbol():
    assert f.yahoo_symbol("TPE", "00882") == "00882.TW"
    assert f.yahoo_symbol("TYO", "7203") == "7203.T"
    assert f.yahoo_symbol("HKG", "0005") == "0005.HK"
    assert f.yahoo_symbol("HKG", "00700") == "0700.HK"
    assert f.yahoo_symbol("HKG", "5") == "0005.HK"
    assert f.yahoo_symbol("NYSE", "BRK.B") == "BRK-B"


def test_get_yahoo_tries_otc_suffix_after_404(monkeypatch):
    calls = []

    def fake(url, referer=None, attempts=1, ua=f.UA):
        calls.append(url)
        if ".TW?" in url:
            raise RuntimeError("HTTP 404")
        return '{"chart": {"result": [], "error": null}}'

    monkeypatch.setattr(f, "http_get", fake)
    f.get_yahoo("TPE", "6488", "5d")
    assert ["6488.TW" in calls[0], "6488.TWO" in calls[1]] == [True, True]
    calls.clear()
    f.get_yahoo("HKG", "0005", "5d")
    assert len(calls) == 1 and "0005.HK" in calls[0]   # 非台股不重試


def test_get_yahoo_raises_last_error_when_both_suffixes_fail(monkeypatch):
    def fake(url, referer=None, attempts=1, ua=f.UA):
        raise RuntimeError("HTTP 404")

    monkeypatch.setattr(f, "http_get", fake)
    with pytest.raises(RuntimeError, match="404"):
        f.get_yahoo("TPE", "0000", "5d")


def test_yahoo_price_prev_close_is_previous_session_not_chart_previous_close():
    # 週一 10:00 美東盤中（今日那根日線已含現價）：前收應是週五收盤 100，不是 meta.chartPreviousClose 143.76
    closes = [(_ts(2026, 10, 9, 13), 100.0), (_ts(2026, 10, 12, 13), 103.0)]
    now = _ts(2026, 10, 12, 14)
    p = f.parse_yahoo_price(yahoo_payload(closes, now), "NASDAQ", "AAPL")
    assert (p["price"], p["prev_close"], p["change"], p["change_pct"]) == (103.0, 100.0, 3.0, 3.0)
    assert p["source"] == "Yahoo Finance" and p["currency"] == "USD" and p["ticker"] == "NASDAQ:AAPL"


def test_yahoo_price_when_today_bar_missing():
    # 還沒有今日日線：前收就是最後一根
    closes = [(_ts(2026, 10, 9, 13), 100.0)]
    p = f.parse_yahoo_price(yahoo_payload(closes, _ts(2026, 10, 12, 14), cur="JPY"), "TYO", "7203")
    assert p["prev_close"] == 100.0


def test_yahoo_price_uses_exchange_local_date():
    # 東京 10-13 09:00 開盤 = UTC 00:00（UTC+9 的當地日期為 10-13）：今日那根日線不能當前收
    closes = [(_ts(2026, 10, 9, 0), 2900.0), (_ts(2026, 10, 13, 0), 2984.0)]
    p = f.parse_yahoo_price(yahoo_payload(closes, _ts(2026, 10, 13, 5), off=32400, cur="JPY"), "TYO", "7203")
    assert p["prev_close"] == 2900.0


def test_yahoo_errors():
    with pytest.raises(ValueError, match="No data found"):
        f.parse_yahoo_price(yahoo_payload([], 0, error="No data found"), "NASDAQ", "ZZZZ")
    with pytest.raises(ValueError):
        f.parse_yahoo_price(yahoo_payload([(_ts(2026, 10, 13, 13), 5.0)], _ts(2026, 10, 13, 14)), "NASDAQ", "X")  # 無前收


def test_yahoo_dividends_sorted_and_currency():
    d = yahoo_payload([(_ts(2026, 10, 9, 13), 1.0)], _ts(2026, 10, 12, 14), cur="HKD",
                      divs=[(_ts(2026, 5, 14), 0.783188), (_ts(2026, 8, 13), 0.784088)])
    rows, cur = f.parse_yahoo_dividends(d, "HKG", "0005")
    assert cur == "HKD"
    assert rows == [{"ex_date": "2026-08-13", "amount": 0.784088}, {"ex_date": "2026-05-14", "amount": 0.783188}]


def test_yahoo_dividends_none_is_empty_not_error():
    # 不配息的公司（例如 TSLA）是合法情況，不是錯誤
    rows, _ = f.parse_yahoo_dividends(yahoo_payload([(1, 1.0)], 1), "NASDAQ", "TSLA")
    assert rows == []


def test_build_dividends_label():
    d = f.build_dividends([{"ex_date": "2026-08-10", "amount": 0.27}], "AAPL", date(2026, 10, 14), label="NASDAQ:AAPL")
    assert d["ticker"] == "NASDAQ:AAPL" and d["ttm_total"] == 0.27


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


def stock_row(ex, period, cash, stock):
    return (f'<tr><th scope="row" class="rowh">{ex}</th><td class="fd-text">{period}</td>'
            f'<td class="tnum strong">{cash}</td><!--[0--><td class="tnum">{stock}</td><!--]--></tr>')


def test_parse_stock_dividends_handles_dash_and_stock_dividend():
    html = "<tbody>" + stock_row("2022-08-30", "110年", "—", "0.5") + stock_row("2026-07-08", "114年第4季", "1.8", "0.2") + "</tbody>"
    rows = f.parse_stock_dividends(html, "1229")
    assert rows[0] == {"ex_date": "2026-07-08", "amount": 1.8, "stock_dividend": 0.2, "period": "114年第4季"}
    assert rows[1]["amount"] == 0.0 and rows[1]["stock_dividend"] == 0.5
    with pytest.raises(ValueError):
        f.parse_stock_dividends("<tbody></tbody>", "1229")


def test_parse_twse_dividends_mixed_row_has_no_amount():
    data = {"stat": "OK", "data": [["115年07月08日", "1229", "聯華", "42.70", "40.09", "2.603622", "權息"]]}
    assert f.parse_twse_dividends(data, "1229") == [{"ex_date": "2026-07-08", "amount": None}]
    ok = f.crosscheck([{"ex_date": "2026-07-08", "amount": 1.8}], [{"ex_date": "2026-07-08", "amount": None}], [2026])
    assert ok["consistent"] is True
