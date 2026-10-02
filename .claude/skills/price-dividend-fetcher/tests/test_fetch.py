import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch as f  # noqa: E402

GF_HTML = ('x,5,"TWD",[14.75,-0.09000015,-0.60647005,2,3,2],null,14.84,null,"TW","/g/11m9rw8gqt",'
           '[1790911474],"Asia/Taipei",28800')


def row(ex, amt, rec="2026-07-22", pay="2026-08-11"):
    td = '<td class="tnum x">{}</td>'
    return ('<tr class="x">' + td.format(ex) + '<td class="col-num tnum x">' + str(amt) + "</td>"
            + td.format(rec) + td.format(pay) + "</tr>")


FL_HTML = "<tbody>" + row("2026-07-16", 0.55) + row("2026-01-19", 0.45) + row("2025-07-16", 0.55) + "</tbody>"


def test_norm_code():
    assert f.norm_code("TPE:00882") == "00882"
    assert f.norm_code("00882") == "00882"
    with pytest.raises(ValueError):
        f.norm_code("../etc")


def test_parse_price():
    p = f.parse_price(GF_HTML, "00882")
    assert p["price"] == 14.75
    assert p["prev_close"] == 14.84
    assert p["change"] == -0.09
    assert p["as_of"].startswith("2026-10-02")


def test_parse_price_missing_raises():
    with pytest.raises(ValueError):
        f.parse_price("<html></html>", "00882")


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
    f.add_yield(d, {"price": 14.84})
    assert d["yield_pct"] == 6.74
