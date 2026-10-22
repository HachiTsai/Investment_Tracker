import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
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

    def down(_):
        raise RuntimeError("moneydj down")
    monkeypatch.setattr(etf_pool.etf_holdings_scraper, "fetch_etf_holdings", down)
    h = etf_pool.holdings_for("0050", str(tmp_path))
    assert "備援" in h["source"] and h["constituents"][0]["symbol"] == "2330.TW"


def test_nav_marks_current_and_as_page_wraps_fragment():
    nav = etf_pool.nav_html(["0050", "0056"], "0056")
    assert 'value="0056.html" selected' in nav and 'value="index.html"' in nav
    page = etf_pool.as_page("<title>t</title><style>a{}</style><main>x</main>")
    assert page.startswith("<!doctype html>") and "</head><body><main>x</main></body></html>" in page


def test_index_page_links_each_etf():
    s = [dict(etf="0050", holdings=50, rows=50, weighted_yield_pct=1.234, holdings_asof="2026-10-21", source="MoneyDJ", no_fin=[])]
    out = etf_pool.index_page(s, "2026-10-22", 214)
    assert 'href="0050.html"' in out and "214" in out and "1.23" in out
