"""港股市場介面（etf_hk）與港股資料池（etf_pool --market hk）離線測試：持股、股價與財報全部換成固定資料。"""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent.parent
for sub in ("tw-etf-fetcher", "fundamental-analyzer", "price-dividend-fetcher"):
    sys.path.insert(0, str(SKILLS / sub / "scripts"))
import etf_fx  # noqa: E402
import etf_hk  # noqa: E402
import etf_market  # noqa: E402
import etf_page  # noqa: E402
import etf_pool  # noqa: E402

TODAY = date(2026, 10, 26)
CTBC_HOLD = {
    "FundAssets": [{"資料日期": "2026/10/23"}],
    "FundAssetsDetail": [{"Data": [
        {"code_": "1919 HK", "name_": "中遠海控", "qty_": "1,200", "weights_": "5.5"},
        {"code_": "700 HK", "name_": "騰訊控股", "qty_": "300", "weights_": "20.0"},
        {"code_": "TWD", "name_": "現金", "qty_": "1", "weights_": "0.5"},
    ]}],
}
DIVS = [
    dict(nd="2026-08-01", year="2026", kind="中期", ex="2026-08-20", pay="2026-09-10", amt=1.2, cur="港币", hkd=1.2),
    dict(nd="2026-03-01", year="2025", kind="年度", ex="2026-05-10", pay="2026-06-01", amt=2.0, cur="港币", hkd=2.0),
]
FIN = dict(kind="年报", cur="港元", org="互联网", hist=[dict(p="2025-12-31", k="2025年年报", eps=10.0)], eps=10.0, roe=15.0, pb=3.0)
PRICES = {"HKG:1919": 12.5, "HKG:0700": 400.0}
A_DIVS = [dict(year="2025", kind="年度", amt=0.5, cur="港币", hkd=0.5, ex="2026-05-01", pay="2026-06-01")]
B_DIVS = [dict(year="2025", kind="年度", amt=1.0, cur="人民币", hkd=1.1, ex="2026-05-01", pay="2026-06-01")]


def _stock(px, ttm, cur, eps, divs):
    return dict(px=px, ttm=ttm, f=dict(cur=cur, org="互联网", hist=[dict(p="2025-12-31", k="2025年年报", eps=eps)]), divs=divs)


def _fake_post(holdings):
    def post(path, body, token="www.ctbcinvestments.com"):
        return {"token": "t"} if path == "home/AuthToken" else holdings
    return post


@pytest.mark.parametrize("raw,code", [
    ("1919 HK", "1919"), ("700 HK", "0700"), ("00700.HK", "0700"), ("HKG:0005", "0005"), ("09988 hk", "9988"),
])
def test_parse_hk_code_pads_to_four_digits(raw, code):
    assert etf_hk.parse_hk_code(raw) == code


@pytest.mark.parametrize("raw", ["2330.TW", "2330", "NVDA.US", "CASH", "600519 CH", "TPE:2330"])
def test_parse_hk_code_refuses_other_markets(raw):
    assert etf_hk.parse_hk_code(raw) is None


def test_fetch_holdings_keeps_hk_stocks_and_marks_full(monkeypatch):
    paths = []
    fake = _fake_post(CTBC_HOLD)

    def recording_post(path, body, token="www.ctbcinvestments.com"):
        paths.append(path)
        return fake(path, body, token)

    monkeypatch.setattr(etf_hk, "_post", recording_post)
    h = etf_hk.fetch_holdings("00882")
    assert [c["symbol"] for c in h["constituents"]] == ["1919 HK", "700 HK"]
    assert h["source"] == etf_market.CTBC_SOURCE and h["as_of_date"] == "2026/10/23"
    assert h["total_weight_pct"] == 25.5 and h["constituents"][0]["shares"] == 1200
    assert etf_market.coverage_label(h) == "full"
    assert paths == ["home/AuthToken", "etf/ETFHoldingWeight"]


def test_fetch_holdings_refuses_an_etf_without_a_fund_code():
    with pytest.raises(ValueError):
        etf_hk.fetch_holdings("0050")


def test_hk_stock_keeps_the_other_steps_when_one_source_fails(monkeypatch):
    def hk_detail_down(code, periods=10):
        raise RuntimeError("東方財富斷線")

    monkeypatch.setattr(etf_hk.price_fetch, "get_price", lambda ticker, source="auto": {"price": PRICES[ticker]})
    monkeypatch.setattr(etf_hk.eastmoney, "hk_detail", hk_detail_down)
    monkeypatch.setattr(etf_hk.eastmoney, "hk_dividends", lambda code, size=20: DIVS)
    g = etf_hk.hk_stock("1919", "中遠海控", None, TODAY)
    assert g["errs"] == ["financials:RuntimeError"] and g["f"] == {}
    assert g["px"] == 12.5 and g["ttm"] == 3.2 and g["y"] == round(3.2 / 12.5 * 100, 2)


def test_hk_finish_applies_the_pool_wide_rmb_hint():
    # 甲的報表是人民幣、只派港幣，要靠乙派人民幣時附的港幣金額來估匯率
    pool = etf_hk.hk_finish({"0700": _stock(10.0, 0.5, "人民币", 1.0, list(A_DIVS)),
                             "1919": _stock(20.0, 1.1, "人民币", 2.0, list(B_DIVS))}, TODAY)
    assert pool["0700"]["f"]["dr_fy"] == 45.5 and pool["0700"]["lfy"] == 0.5
    assert pool["1919"]["f"]["dr_fy"] == 50.0
    assert "divs" not in pool["0700"]


def test_hk_finish_leaves_the_fx_dependent_ratio_blank_without_a_hint():
    pool = etf_hk.hk_finish({"0700": _stock(10.0, 0.5, "人民币", 1.0, list(A_DIVS))}, TODAY)
    assert "dr_fy" not in pool["0700"]["f"]


@pytest.fixture
def hk_offline(monkeypatch):
    monkeypatch.setattr(etf_hk, "_post", _fake_post(CTBC_HOLD))
    monkeypatch.setattr(etf_hk.price_fetch, "get_price", lambda ticker, source="auto": {"price": PRICES[ticker]})
    monkeypatch.setattr(etf_hk.eastmoney, "hk_detail", lambda code, periods=10: dict(FIN))
    monkeypatch.setattr(etf_hk.eastmoney, "hk_cashflow", lambda code: dict(fy="2025", ocf=100.0, capex=20.0, paid=50.0))
    monkeypatch.setattr(etf_hk.eastmoney, "hk_dividends", lambda code, size=20: [dict(d) for d in DIVS])
    monkeypatch.setattr(etf_fx, "fetch_rate",  # 池流程會取匯率，測試不連 Google Finance
                        lambda currency, **k: dict(currency=currency, rate=4.15, as_of="2026-01-02", source="測試"))

    def yahoo_down(*_, **__):
        raise RuntimeError("Yahoo 斷線")

    monkeypatch.setattr(etf_hk.price_fetch, "get_yahoo", yahoo_down)


def test_hk_pool_writes_pure_codes_and_hk_pages(tmp_path, hk_offline):
    out = tmp_path / "out"
    assert etf_pool.main(["etf_pool.py", str(out), "--market", "hk", "--etfs", "00882"]) == 0
    payload = json.loads((out / "pool.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == etf_market.SCHEMA_VERSION and payload["market"] == "HK"
    assert {s["code"] for s in payload["stocks"]} == {"1919", "0700"}
    assert {h["code"] for h in payload["holdings"]} == {"1919", "0700"}
    summary = payload["summaries"][0]
    assert summary["coverage"] == "full" and summary["source"] == etf_market.CTBC_SOURCE
    index = (out / "index.html").read_text(encoding="utf-8")
    page = (out / "00882.html").read_text(encoding="utf-8")
    assert "<h1>港股 ETF 成分股明細</h1>" in index and "財報與配息來自東方財富" in index
    # 頭條是權重加權殖利率，不是港股 00882 頁原本的每單位台幣股利
    assert etf_page.YIELD_NOTE in page and "以今日持股推算的每單位年股利" not in page
    for text in (index, page, (out / "pool.json").read_text(encoding="utf-8")):
        assert etf_market.find_forbidden_suffix(text) == []


def test_hk_gate_flags_short_holdings(tmp_path, hk_offline, capsys):
    assert etf_pool.main(["etf_pool.py", str(tmp_path / "out"), "--market", "hk", "--etfs", "00882", "--gate"]) == 1
    assert "00882 持股檔數不足：2 < 45" in capsys.readouterr().err


def test_hk_suffix_guard_refuses_to_write(tmp_path, hk_offline, monkeypatch):
    leaky = dict(CTBC_HOLD, FundAssetsDetail=[{"Data": [{"code_": "1919 HK", "name_": "中遠海控 1919.HK", "qty_": "1", "weights_": "5"}]}])
    monkeypatch.setattr(etf_hk, "_post", _fake_post(leaky))
    out = tmp_path / "out"
    assert etf_pool.main(["etf_pool.py", str(out), "--market", "hk", "--etfs", "00882"]) == 1
    assert not out.exists()


def test_hk_market_requires_explicit_etfs(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        etf_pool.main(["etf_pool.py", str(tmp_path / "out"), "--market", "hk"])
    assert exc.value.code == 2
    assert "請用 --etfs 指定 ETF 代號" in capsys.readouterr().err
