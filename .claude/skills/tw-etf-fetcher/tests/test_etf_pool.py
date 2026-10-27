import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import etf_holdings_scraper  # noqa: E402
import etf_pool  # noqa: E402


def _card(tmp_path, etf, tickers):
    d = tmp_path / etf / "cards"
    d.mkdir(parents=True)
    rows = [dict(ticker=t, name=t, weight_pct=1.0) for t in tickers]
    (d / "constituents.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_discover_keeps_only_tw_stock_etfs(tmp_path):
    _card(tmp_path, "0050", [f"{2300 + i}.TW" for i in range(6)])
    _card(tmp_path, "00882", [f"{i}.HK" for i in range(6)])
    _card(tmp_path, "tiny", ["2330.TW"])
    assert etf_pool.discover(str(tmp_path)) == ["0050"]


def test_holdings_fall_back_to_cards(tmp_path, monkeypatch):
    _card(tmp_path, "0050", ["2330.TW"])
    (tmp_path / "0050" / "cards" / "ticker.yml").write_text('title: "0050"\nlast_model_update: "2026-10-18"\n', encoding="utf-8")

    def down(_):
        raise RuntimeError("moneydj down")
    monkeypatch.setattr(etf_pool.etf_table.etf_holdings_scraper, "fetch_etf_holdings", down)
    h = etf_pool.holdings_for("0050", str(tmp_path))
    assert "備援" in h["source"] and h["constituents"][0]["symbol"] == "2330.TW"
    assert h["as_of_date"] is None and h["model_date"] == "2026-10-18"  # 備援不填持股日期，建立日期取卡片


def test_moneydj_holdings_keep_source_date_and_card_model_date(tmp_path, monkeypatch):
    (tmp_path / "0050" / "cards").mkdir(parents=True)
    (tmp_path / "0050" / "cards" / "ticker.yml").write_text('last_model_update: "2026-10-18"\n', encoding="utf-8")
    fresh = dict(ticker="0050", as_of_date="2026-10-21", source="MoneyDJ", total_count=1, total_weight_pct=50.0,
                 constituents=[dict(symbol="2330.TW", name="台積電", weight_pct=50.0, shares=1)])
    monkeypatch.setattr(etf_pool.etf_table.etf_holdings_scraper, "fetch_etf_holdings", lambda etf, **_: fresh)
    h = etf_pool.holdings_for("0050", str(tmp_path))
    assert h["as_of_date"] == "2026-10-21" and h["model_date"] == "2026-10-18" and h["source"] == "MoneyDJ"


def test_card_model_date_is_none_without_a_card_or_a_field(tmp_path):
    assert etf_pool.card_model_date(str(tmp_path), "0050") is None
    (tmp_path / "0050" / "cards").mkdir(parents=True)
    (tmp_path / "0050" / "cards" / "ticker.yml").write_text('title: "x"\n', encoding="utf-8")
    assert etf_pool.card_model_date(str(tmp_path), "0050") is None


def test_moneydj_date_is_only_the_source_date():
    assert etf_holdings_scraper._data_date("<td>資料日期：2026/10/21</td>") == "2026-10-21"
    assert etf_holdings_scraper._data_date("<td>沒有日期</td>") is None
    assert etf_holdings_scraper.fetch_etf_holdings("0050", mock_html="<html></html>")["as_of_date"] is None


def test_nav_marks_current_and_as_page_wraps_fragment():
    nav = etf_pool.nav_html(["0050", "0056"], "0056")
    assert 'value="0056.html" selected' in nav and 'value="index.html"' in nav
    page = etf_pool.as_page("<title>t</title><style>a{}</style><main>x</main>")
    assert page.startswith("<!doctype html>") and "</head><body><main>x</main></body></html>" in page


def test_index_page_links_each_etf():
    s = [dict(etf="0050", holdings=50, rows=50, weighted_yield_pct=1.234, model_date="2026-10-18", holdings_asof=None,
              source="models 持股卡片（備援）", no_fin=[])]
    out = etf_pool.index_page(s, "2026-10-22", 214)
    assert 'href="0050.html"' in out and "214" in out and "1.23" in out
    assert "建立日期" not in out and "持股日期" not in out and "持股來源" not in out and "資料日期" not in out and "有股價" not in out


def test_check_gate():
    ok, reasons = etf_pool.check_gate(17, ["2330"], ["2330"], {})
    assert ok and len(reasons) == 0

    ok, reasons = etf_pool.check_gate(10, [], [], {})
    assert not ok and any("ETF 數量不足" in r for r in reasons)

    ok, reasons = etf_pool.check_gate(17, [str(i) for i in range(8)], [str(i) for i in range(5)], {})
    assert not ok and any("缺價格與財報檔數超標" in r for r in reasons)

    ok, reasons = etf_pool.check_gate(17, [], [], {"0050": 1})
    assert not ok and any("存在異常 ETF" in r for r in reasons)
