"""美股市場介面（etf_us）與美股資料池（etf_pool --market us）離線測試：持股、股價、股利與 SEC 財報全部換成固定資料。"""

import json
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent.parent
for sub in ("tw-etf-fetcher", "fundamental-analyzer", "price-dividend-fetcher"):
    sys.path.insert(0, str(SKILLS / sub / "scripts"))
import etf_market  # noqa: E402
import etf_page  # noqa: E402
import etf_pool  # noqa: E402
import etf_table  # noqa: E402
import etf_us  # noqa: E402

TODAY = date(2026, 10, 26)
TOP = [("NVDA", "NVIDIA", 7.12), ("BRK-B", "Berkshire", 1.5), ("2330.TW", "TSMC", 2.0), ("CASH", "Cash", 0.5),
       ("ABBV", "AbbVie", float("nan"))]
PRICES = {"NASDAQ:NVDA": 100.0, "NASDAQ:BRK-B": 400.0}
DIVS = {"NVDA": dict(ttm_total=2.0, yearly_totals={"2025": 1.8, "2024": 1.5})}
NVDA_CIK, BRK_CIK = 1045810, 1067983
TICKERS = {
    "0": {"cik_str": NVDA_CIK, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": BRK_CIK, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
}


def _flow(values, filed="2026-02-20"):
    """10-K 全年（約一年期間）的流量科目，values 為 {期末日: 數字}。"""
    return [dict(start=(date.fromisoformat(end) - timedelta(days=364)).isoformat(), end=end, val=val,
                 form="10-K", fp="FY", filed=filed) for end, val in values.items()]


def _point(values, filed="2026-02-20"):
    """時點科目（資產負債表）：沒有 start。"""
    return [dict(end=end, val=val, form="10-K", fp="FY", filed=filed) for end, val in values.items()]


ACME_FACTS = {"facts": {
    "us-gaap": {
        "EarningsPerShareDiluted": {"units": {"USD/shares": _flow({"2025-12-31": 2.5, "2024-12-31": 2.0})}},
        "Revenues": {"units": {"USD": _flow({"2025-12-31": 1000.0, "2024-12-31": 800.0})}},
        "NetIncomeLoss": {"units": {"USD": _flow({"2025-12-31": 250.0, "2024-12-31": 160.0})}},
        "GrossProfit": {"units": {"USD": _flow({"2025-12-31": 500.0})}},
        "StockholdersEquity": {"units": {"USD": _point({"2025-12-31": 1000.0, "2024-12-31": 900.0})}},
        "Liabilities": {"units": {"USD": _point({"2025-12-31": 400.0})}},
        "Assets": {"units": {"USD": _point({"2025-12-31": 1400.0})}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": _flow({"2025-12-31": 300.0})}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": _flow({"2025-12-31": 50.0})}},
        "PaymentsOfDividends": {"units": {"USD": _flow({"2025-12-31": 100.0})}},
    },
    "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [dict(end="2026-02-01", val=100.0)]}}},
}}
NO_10K = {"facts": {"us-gaap": {}}}


def _fake_sec(url):
    if url.endswith("company_tickers.json"):
        return TICKERS
    cik = int(url.split("CIK")[1].split(".")[0])
    return {NVDA_CIK: ACME_FACTS, BRK_CIK: NO_10K}[cik]


@pytest.fixture
def us_offline(monkeypatch):
    monkeypatch.setattr(etf_us, "_top_holdings_rows", lambda etf: list(TOP))
    monkeypatch.setattr(etf_us, "_sec_json", _fake_sec)
    monkeypatch.setattr(etf_us.price_fetch, "get_price", lambda ticker, source="auto": {"price": PRICES.get(ticker, 1.0)})
    monkeypatch.setattr(etf_us.price_fetch, "yahoo_dividends",
                        lambda exch, code, since: dict(DIVS.get(code, dict(ttm_total=0.0, yearly_totals={}))))
    etf_us.cik_map.cache_clear()
    yield
    etf_us.cik_map.cache_clear()


@pytest.mark.parametrize("raw,code", [
    ("NVDA", "NVDA"), ("nvda.us", "NVDA"), ("NASDAQ:NVDA", "NVDA"), ("NYSE:JPM", "JPM"), ("BRK.B", "BRK-B"), ("BRK-B", "BRK-B"),
])
def test_parse_us_code_accepts_us_tickers(raw, code):
    assert etf_us.parse_us_code(raw) == code


@pytest.mark.parametrize("raw", ["2330.TW", "2330", "1919 HK", "00882", "CASH", "USD", "TPE:2330", "NVDA-TOOLONG"])
def test_parse_us_code_refuses_other_markets_and_cash(raw):
    assert etf_us.parse_us_code(raw) is None


def test_fetch_holdings_keeps_us_stocks_and_marks_partial(us_offline):
    h = etf_us.fetch_holdings("VOO")
    assert [c["symbol"] for c in h["constituents"]] == ["NVDA", "BRK-B"]
    assert h["source"] == etf_us.TOP_SOURCE and h["as_of_date"] == date.today().isoformat()
    assert h["total_weight_pct"] == 8.62 and etf_market.coverage_label(h) == "partial"


def test_annual_keeps_only_10k_full_years_and_the_latest_filing():
    rows = [
        dict(start="2025-01-01", end="2025-12-31", val=1.0, form="10-K", fp="FY", filed="2026-02-01"),
        dict(start="2025-01-01", end="2025-12-31", val=2.0, form="10-K", fp="FY", filed="2026-03-01"),
        dict(start="2025-07-01", end="2025-09-30", val=9.0, form="10-Q", fp="Q3", filed="2025-11-01"),
    ]
    facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": rows}}}}}
    assert etf_us._annual(facts, ("NetIncomeLoss",), "USD") == {"2025-12-31": 2.0}


def test_annual_prefers_the_earlier_candidate_tag_for_each_period():
    parent = dict(start="2024-01-01", end="2024-12-31", val=5.0, form="10-K", fp="FY", filed="2025-02-01")
    later_nci = dict(start="2024-01-01", end="2024-12-31", val=6.0, form="10-K", fp="FY", filed="2026-02-01")
    only_nci = dict(start="2025-01-01", end="2025-12-31", val=7.0, form="10-K", fp="FY", filed="2026-02-01")
    facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [parent]}},
                                   "ProfitLoss": {"units": {"USD": [later_nci, only_nci]}}}}}
    assert etf_us._annual(facts, etf_us.ANNUAL["np"][0], "USD") == {"2024-12-31": 5.0, "2025-12-31": 7.0}


def test_equity_uses_the_noncontrolling_line_only_when_the_parent_line_is_missing():
    rows = _point({"2025-11-02": 81.0})  # 只有含非控制權益的標籤（AVGO 這類公司）
    facts = {"facts": {"us-gaap": {"StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": {"units": {"USD": rows}}}}}
    assert etf_us._annual(facts, etf_us.ANNUAL["eq"][0], "USD") == {"2025-11-02": 81.0}


def test_cik_map_fetches_the_sec_table_once(monkeypatch):
    calls = []

    def fake(url):
        calls.append(url)
        return TICKERS

    monkeypatch.setattr(etf_us, "_sec_json", fake)
    etf_us.cik_map.cache_clear()
    assert etf_us.cik_map()["NVDA"] == NVDA_CIK and etf_us.cik_map()["BRK-B"] == BRK_CIK
    assert len(calls) == 1
    etf_us.cik_map.cache_clear()


def test_us_stock_computes_yield_growth_and_the_latest_annual_ratios(us_offline):
    g = etf_us.us_stock("NVDA", "NVIDIA", None, TODAY)
    assert g["errs"] == [] and g["px"] == 100.0
    assert g["ttm"] == 2.0 and g["y"] == 2.0 and g["lfy"] == 1.8 and g["chg"] == 11.1
    f = g["f"]
    assert f["cur"] == "美元" and f["pe"] == 40.0 and f["pb"] == 10.0 and f["payout"] == 80.0
    assert f["fcf_cover"] == 2.5 and f["pb_fair"] == 4.0
    assert f["fy_lab"] == "2025 年度" and f["fy_hkd"] == 1.8 and f["fy_prev_hkd"] == 1.5 and f["fy_chg"] == 20.0
    assert f["hist"][0]["k"] == "2025年報" and f["hist"][0]["roe"] == 25.0 and f["hist"][0]["debt"] == 28.6


def test_us_stock_keeps_the_price_when_sec_is_down(us_offline, monkeypatch):
    def down(url):
        raise RuntimeError("SEC 斷線")

    monkeypatch.setattr(etf_us, "_sec_json", lambda url: TICKERS if url.endswith("company_tickers.json") else down(url))
    g = etf_us.us_stock("NVDA", "NVIDIA", None, TODAY)
    assert g["errs"] == ["financials:RuntimeError"] and g["f"] == {}
    assert g["px"] == 100.0 and g["y"] == 2.0


def test_us_stock_records_a_missing_sec_mapping(us_offline):
    g = etf_us.us_stock("ZZZZ", "Unknown", None, TODAY)
    assert g["errs"] == ["financials:ValueError"] and g["f"] == {}


def test_company_without_10k_facts_has_no_financials(us_offline):
    assert etf_us.us_financials("BRK-B", 400.0, 0.0) == {}


def test_holdings_for_takes_partial_us_holdings_and_refuses_partial_tw(tmp_path, us_offline):
    assert etf_pool.holdings_for("VOO", str(tmp_path), etf_us.US)["source"] == etf_us.TOP_SOURCE
    partial_tw = replace(etf_table.TW, holdings=lambda etf: dict(
        ticker=etf, as_of_date="2026-10-26", source=etf_us.TOP_SOURCE, total_count=1, total_weight_pct=40.0,
        constituents=[dict(symbol="2330.TW", name="台積電", weight_pct=40.0, shares=None)]))
    with pytest.raises(RuntimeError, match="沒有備援卡片"):
        etf_pool.holdings_for("0050", str(tmp_path), partial_tw)


def test_pool_registers_the_us_market():
    assert set(etf_pool.markets()) == {"TW", "HK", "US"}
    assert etf_us.US.accept_coverage == ("full", "partial") and etf_table.TW.accept_coverage == ("full",)


def test_us_pool_writes_pure_codes_and_partial_pages(tmp_path, us_offline):
    out = tmp_path / "out"
    assert etf_pool.main(["etf_pool.py", str(out), "--market", "us", "--etfs", "voo"]) == 0
    payload = json.loads((out / "pool.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == etf_market.SCHEMA_VERSION and payload["market"] == "US"
    assert {s["code"] for s in payload["stocks"]} == {"NVDA", "BRK-B"}
    assert {h["code"] for h in payload["holdings"]} == {"NVDA", "BRK-B"}
    summary = payload["summaries"][0]
    assert summary["coverage"] == "partial" and summary["source"] == etf_us.TOP_SOURCE and summary["no_fin"] == ["BRK-B"]
    index = (out / "index.html").read_text(encoding="utf-8")
    page = (out / "VOO.html").read_text(encoding="utf-8")
    assert "<h1>美股 ETF 成分股明細</h1>" in index and "財報來自 SEC EDGAR" in index
    assert etf_page.YIELD_NOTE in page and "美元" in page and "前幾大持股" in page
    assert "占基金 '+pa.w.toFixed(1)" in page and "（只含前幾大持股，合計約占基金 8.6%，其餘持股未納入計算）" in page
    for text in (index, page, (out / "pool.json").read_text(encoding="utf-8")):
        assert etf_market.find_forbidden_suffix(text) == []


def test_full_holdings_keep_the_weight_wording_and_partial_pages_say_share_of_fund():
    tw = etf_page.render("tw", "0050", 1, [], [], {}, "asof", 0, "top", "unit")
    assert "檔、權重 '+(pa.w/tw*100).toFixed(0)+'%）" in tw and "占基金" not in tw and "只含前幾大持股" not in tw
    us = etf_page.render("us", "VOO", 1, [], [], {}, "asof", 0, "top", "unit", partial_total=8.62)
    assert "占基金 '+pa.w.toFixed(1)+'%）" in us and "只含前幾大持股，合計約占基金 8.6%" in us


def test_us_gate_passes_with_partial_holdings(tmp_path, us_offline):
    assert etf_pool.main(["etf_pool.py", str(tmp_path / "out"), "--market", "us", "--etfs", "VOO", "--gate"]) == 0


def test_us_empty_holdings_without_a_card_stops_before_writing(tmp_path, us_offline, monkeypatch, capsys):
    monkeypatch.setattr(etf_us, "_top_holdings_rows", lambda etf: [])
    out = tmp_path / "out"
    assert etf_pool.main(["etf_pool.py", str(out), "--market", "us", "--etfs", "VOO", "--models-dir", str(tmp_path / "none")]) == 1
    assert not out.exists() and "沒有備援卡片" in capsys.readouterr().err


def test_us_suffix_guard_refuses_to_write(tmp_path, us_offline, monkeypatch):
    monkeypatch.setattr(etf_us, "_top_holdings_rows", lambda etf: [("NVDA", "NVIDIA NVDA.US", 7.0)])
    out = tmp_path / "out"
    assert etf_pool.main(["etf_pool.py", str(out), "--market", "us", "--etfs", "VOO"]) == 1
    assert not out.exists()


def test_us_market_requires_explicit_etfs(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        etf_pool.main(["etf_pool.py", str(tmp_path / "out"), "--market", "us"])
    assert exc.value.code == 2 and "請用 --etfs 指定 ETF 代號" in capsys.readouterr().err
