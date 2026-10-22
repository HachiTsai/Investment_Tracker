"""台股 ETF 成分股頁（etf_table／etf_page）單元測試：離線。"""

import sys
from datetime import date
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent
for sub in ("tw-etf-fetcher", "fundamental-analyzer", "price-dividend-fetcher"):
    sys.path.insert(0, str(SKILLS / sub / "scripts"))

import etf_holdings_scraper  # noqa: E402
import etf_page  # noqa: E402
import etf_table  # noqa: E402


def test_render_fills_every_placeholder_for_each_profile():
    for profile in etf_page.PROFILES:
        page = etf_page.render(profile, "00000", 2, [], [], {}, "2026-01-01", 0, "x 1%", "1%")
        assert "__" not in page.replace("__proto__", "") and "const MID=" in page


def test_tw_profile_hides_midyear_columns():
    page = etf_page.render("tw", "00985A", 1, [], [], {}, "d", 0, "t", "u")
    assert "const MID=false,SPLIT=false;" in page and "<title>00985A 成分股股利與財報明細</title>" in page
    hk = etf_page.render("hk", "00882", 1, [], [], {}, "d", 0, "t", "u")
    assert "const MID=true,SPLIT=true;" in hk and "港元" in hk


def test_moneydj_data_date_parser():
    assert etf_holdings_scraper._data_date("資料日期：2026/10/21") == "2026-10-21"
    assert etf_holdings_scraper._data_date("沒有日期") is None


def test_build_survives_partial_failures(monkeypatch):
    holdings = {"as_of_date": "2026-10-21", "source": "MoneyDJ", "total_weight_pct": 90.0, "constituents": [
        {"symbol": "1111.TW", "name": "甲", "weight_pct": 60.0, "shares": 1000},
        {"symbol": "2222.TW", "name": "乙", "weight_pct": 30.0, "shares": 500},
        {"symbol": "CASH", "name": "現金", "weight_pct": 10.0, "shares": 0}]}

    def price(t):
        if t.endswith("2222"):
            raise RuntimeError("no price")
        return {"price": 100.0}

    def boom(*a, **k):
        raise RuntimeError("fm down")
    monkeypatch.setattr(etf_table.price_fetch, "get_price", price)
    monkeypatch.setattr(etf_table.finmind_detail, "industries", lambda: {})
    monkeypatch.setattr(etf_table.finmind_detail, "tw_detail", boom)
    monkeypatch.setattr(etf_table.finmind_detail, "tw_dividends", lambda c: [
        {"nd": None, "year": "2025", "kind": "年度", "ex": "2026-01-02", "pay": None, "amt": 5.0, "cur": "新台幣", "hkd": 5.0, "shares": 1}])
    monkeypatch.setattr(etf_table.finmind_detail, "tw_pbr", lambda c: None)
    r = etf_table.build("00000", date(2026, 10, 22), holdings)
    s = r["summary"]
    assert s["holdings"] == 2 and s["rows"] == 1 and s["no_price"] == ["2222"] and sorted(s["no_fin"]) == ["1111", "2222"]
    assert "financials:RuntimeError" in s["errors"]["1111"] and r["rows"][0]["y"] == 5.0
