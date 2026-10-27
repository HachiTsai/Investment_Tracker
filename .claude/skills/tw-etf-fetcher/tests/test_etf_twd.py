"""外幣市場的台幣參考值離線測試：每單位台幣股利、頁面與索引頁的匯率說明、pool.json 的 fx 與台幣欄位。台股輸出不變。"""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent.parent
for sub in ("tw-etf-fetcher", "fundamental-analyzer", "price-dividend-fetcher"):
    sys.path.insert(0, str(SKILLS / sub / "scripts"))
import etf_hk  # noqa: E402
import etf_market  # noqa: E402
import etf_page  # noqa: E402
import etf_pool  # noqa: E402
import etf_table  # noqa: E402

FX = dict(currency="HKD", rate=4.0, as_of="2026-10-26T17:10:00+00:00", source="Google Finance")
TODAY = date(2026, 10, 26)


def _pool_row(code, name, px, ttm, weight_y=20.0):
    return dict(c=code, n=name, px=px, ttm=ttm, lfy=ttm, chg=0.0, y=weight_y, i26="", p25="", cmp="", errs=[],
                f=dict(kind="FY", org="測試", pe=8.0, pb=1.0, hist=[]))


def _hk_holdings(units=1000.0):
    return dict(ticker="00882", as_of_date="2026-10-21", source=etf_market.CTBC_SOURCE, total_count=1, total_weight_pct=50.0,
                constituents=[dict(symbol="1919 HK", name="中遠海控", weight_pct=50.0, shares=100)], units=units, nav=12.0)


def test_per_unit_twd_dividend_is_shares_times_dividend_times_rate_over_units():
    ok = [dict(q=100, ttm=2.0), dict(q=300, ttm=1.0)]
    assert etf_table.per_unit_twd_dividend(dict(units=1000), ok, FX) == pytest.approx((200 + 300) * 4.0 / 1000)
    assert etf_table.per_unit_twd_dividend(dict(), ok, FX) is None
    assert etf_table.per_unit_twd_dividend(dict(units=1000), ok, None) is None


def test_hk_page_headline_is_per_unit_twd_dividend_and_states_the_rate():
    pool = {"1919": _pool_row("1919", "中遠海控", 10.0, 2.0)}
    r = etf_table.build_page("00882", _hk_holdings(), pool, TODAY, market=etf_hk.HK, fx=FX)
    assert r["summary"]["per_unit_twd"] == 0.8
    assert "0.800 元" in r["page"] and etf_page.PER_UNIT_NOTE in r["page"]
    assert "股價（約新台幣）" in r["page"] and "近 12 月股息（約新台幣）" in r["page"]
    assert "台幣參考值：1 港元 ≈ 4.0000 元新台幣" in r["page"]
    assert etf_market.find_forbidden_suffix(r["page"]) == []


def test_hk_page_falls_back_to_weighted_yield_without_units():
    pool = {"1919": _pool_row("1919", "中遠海控", 10.0, 2.0)}
    r = etf_table.build_page("00882", _hk_holdings(units=None), pool, TODAY, market=etf_hk.HK, fx=FX)
    assert "per_unit_twd" not in r["summary"]
    assert etf_page.PER_UNIT_NOTE not in r["page"]


def test_tw_page_has_no_foreign_currency_text():
    pool = {"2330": _pool_row("2330", "台積電", 1000.0, 30.0)}
    holdings = dict(ticker="0050", as_of_date="2026-10-21", source="MoneyDJ", total_count=1, total_weight_pct=100.0,
                    constituents=[dict(symbol="2330.TW", name="台積電", weight_pct=100.0, shares=10)])
    r = etf_table.build_page("0050", holdings, pool, TODAY, market=etf_table.TW)
    assert "股價（約新台幣）" not in r["page"] and "台幣參考值" not in r["page"]
    assert "per_unit_twd" not in r["summary"]


def test_pool_payload_adds_fx_and_twd_fields_only_for_foreign_markets():
    pool = {"1919": _pool_row("1919", "中遠海控", 10.0, 2.0)}
    payload = etf_pool.pool_payload(["00882"], {"00882": _hk_holdings()}, pool, TODAY, [], market=etf_hk.HK, fx=FX)
    assert payload["fx"] == dict(currency="HKD", rate=4.0, asOf=FX["as_of"], source="Google Finance")
    assert payload["stocks"][0]["pxTwd"] == 40.0 and payload["stocks"][0]["ttmDivTwd"] == 8.0
    assert payload["holdings"][0]["code"] == "1919"
    assert etf_market.find_forbidden_suffix(json.dumps(payload, ensure_ascii=False)) == []

    tw_holdings = dict(ticker="0050", as_of_date="2026-10-21", source="MoneyDJ", total_count=1, total_weight_pct=100.0,
                       constituents=[dict(symbol="2330.TW", name="台積電", weight_pct=100.0, shares=10)])
    tw = etf_pool.pool_payload(["0050"], {"0050": tw_holdings}, {"2330": _pool_row("2330", "台積電", 1000.0, 30.0)}, TODAY, [])
    assert "fx" not in tw and "pxTwd" not in tw["stocks"][0] and "ttmDivTwd" not in tw["stocks"][0]


def test_index_page_states_the_rate_and_quote_time_only_for_foreign_markets():
    summaries = [dict(etf="00882", name="中國信託恒生高息", rows=1, holdings=1, weighted_yield_pct=20.0, holdings_asof="2026-10-21",
                      source=etf_market.CTBC_SOURCE, no_fin=[], errors={}, coverage="full", weight_pct=50.0)]
    page = etf_pool.index_page(summaries, 1, market=etf_hk.HK, fx=FX)
    assert "台幣參考值：1 港元 ≈ 4.0000 元新台幣，匯率來自 Google Finance，報價時間 2026-10-26 17:10 UTC" in page
    assert "台幣參考值" not in etf_pool.index_page(summaries, 1, market=etf_table.TW)


def test_hk_holdings_keep_fund_units_and_nav(monkeypatch):
    fund = {"FundAssets": [{"資料日期": "2026/10/21", "基金在外流通單位數": "1,000", "基金每單位淨值": "12.5"}],
            "FundAssetsDetail": [{"Data": [{"code_": "1919 HK", "name_": "中遠海控", "weights_": "50.0", "qty_": "100"}]}]}

    def fake_post(path, body, token=None):
        return {"token": "t"} if path == "home/AuthToken" else fund

    monkeypatch.setattr(etf_hk, "_post", fake_post)
    h = etf_hk.fetch_holdings("00882")
    assert h["units"] == 1000.0 and h["nav"] == 12.5
    assert h["constituents"] == [dict(symbol="1919 HK", name="中遠海控", weight_pct=50.0, shares=100)]
