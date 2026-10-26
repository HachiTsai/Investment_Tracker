"""台股 ETF 資料池（etf_pool）離線測試：持股、個股價格與財報全部換成固定資料，驗證輸出與安全防線。"""

import json
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent.parent
for sub in ("tw-etf-fetcher", "fundamental-analyzer", "price-dividend-fetcher"):
    sys.path.insert(0, str(SKILLS / sub / "scripts"))
import etf_holdings_scraper  # noqa: E402
import etf_market  # noqa: E402
import etf_pool  # noqa: E402
import etf_table  # noqa: E402
from etf_sheets_sync import sync_to_google_sheets  # noqa: E402

CONS = {
    "0050": [("2330.TW", "台積電", 45.0, 1000), ("2317.TW", "鴻海", 5.0, 500), ("9999.TW", "測試缺價", 1.0, 50),
             ("NVDA.US", "NVIDIA", 2.0, 10), ("CASH", "現金", 1.5, None)],
    "0056": [("2881.TW", "富邦金", 20.0, 700), ("2317.TW", "鴻海", 10.0, 250)],
}


def _fake_stock(code, name, industry, today):
    if code == "9999":
        return dict(c=code, n=name, px=None, ttm=0.0, lfy=0.0, chg=0, y=None, i26="", p25="", cmp="",
                    errs=["price:ValueError"], f={})
    return dict(c=code, n=name, px=100.0 + int(code), ttm=3.5, lfy=3.2, chg=9.4, y=0.14, i26="", p25="", cmp="", errs=[],
                f=dict(kind="Q2", org=industry or "半導體", pe=20.1, pb=3.2, hist=[]))


@pytest.fixture
def offline(monkeypatch):
    def hold(etf, **_):
        cons = [dict(symbol=s, name=n, weight_pct=w, shares=q) for s, n, w, q in CONS[etf]]
        return dict(ticker=etf, as_of_date="2026-10-21", source="MoneyDJ", total_count=len(cons),
                    total_weight_pct=round(sum(c["weight_pct"] for c in cons), 2), constituents=cons)

    monkeypatch.setattr(etf_holdings_scraper, "fetch_etf_holdings", hold)
    monkeypatch.setattr(etf_table, "fetch_stock", _fake_stock)
    monkeypatch.setattr(etf_table.finmind_detail, "industries", lambda: {"2317": "電子"})


def test_tw_parse_code_keeps_only_numeric_codes():
    symbols = ["2330.TW", "00878.TWO", "NVDA.US", "CASH", "TPE:2317"]
    assert [etf_table.TW.parse_code(s) for s in symbols] == ["2330", "00878", None, None, "2317"]


def test_pool_writes_pure_codes_schema_and_coverage(tmp_path, offline):
    out = tmp_path / "out"
    assert etf_pool.main(["etf_pool.py", str(out), "--etfs", "0050,0056"]) == 0
    payload = json.loads((out / "pool.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == etf_market.SCHEMA_VERSION and payload["market"] == "TW"
    assert {s["code"] for s in payload["stocks"]} == {"2330", "2317", "9999", "2881"}
    assert {h["code"] for h in payload["holdings"]} == {"2330", "2317", "9999", "2881"}
    assert all(s["coverage"] == "full" for s in payload["summaries"])
    for name in ("index.html", "0050.html", "0056.html", "pool.json"):
        assert etf_market.find_forbidden_suffix((out / name).read_text(encoding="utf-8")) == []


def test_suffix_guard_refuses_to_write_anything(tmp_path, offline, monkeypatch):
    monkeypatch.setitem(CONS, "0056", [("2881.TW", "富邦金 2881.TW", 20.0, 700)])
    out = tmp_path / "out"
    assert etf_pool.main(["etf_pool.py", str(out), "--etfs", "0056"]) == 1
    assert not out.exists()


def test_core_sheet_is_refused_before_any_network_call(tmp_path, monkeypatch):
    def no_network(*_, **__):
        raise AssertionError("寫入 Core 時不得連網")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    core = next(iter(etf_market.CORE_SHEET_IDS))
    ok, msg = sync_to_google_sheets(core, tmp_path / "summary.csv", tmp_path / "constituents.csv")
    assert ok is False and "Investment_Tracker_Core" in msg
