"""日股市場介面（etf_jp）與日股資料池（etf_pool --market jp）離線測試：持股、股價、股利與 EDINET 報告書全部換成固定資料。"""

import io
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent.parent
for sub in ("tw-etf-fetcher", "fundamental-analyzer", "price-dividend-fetcher"):
    sys.path.insert(0, str(SKILLS / sub / "scripts"))
import etf_drive  # noqa: E402
import etf_fx  # noqa: E402
import etf_jp  # noqa: E402
import etf_market  # noqa: E402
import etf_page  # noqa: E402
import etf_pool  # noqa: E402
from fetchers import edinet  # noqa: E402

TODAY = date(2026, 10, 26)
TOP = [("7203.T", "Toyota Motor Corp", 2.5), ("8306.T", "Mitsubishi UFJ", 4.0), ("USD", "Cash", 0.5),
       ("9999.T", "NaN", float("nan"))]
PRICES = {"TYO:7203": 3000.0, "TYO:8306": 1800.0}
DIVS = {"7203": dict(ttm_total=100.0, yearly_totals={"2025": 90.0, "2024": 80.0})}

# 假的有價證券報告書（欄位名沿用 Toyota IFRS 報告書的標籤，數字為假設值）：
# 當期 EPS 200、權益 1,000,000、股數 1,000，所以 BPS 1,000；負債 400、資產 1,400 → 負債比 28.6%
ACME = [
    ("CurrentFiscalYearEndDateDEI", "FilingDateInstant", "2026-03-31"),
    (etf_jp.SHARES_TAG, "FilingDateInstant", "1000"),
    ("BasicEarningsLossPerShareIFRSSummaryOfBusinessResults", "CurrentYearDuration", "200"),
    ("BasicEarningsLossPerShareIFRSSummaryOfBusinessResults", "Prior1YearDuration", "180"),
    ("BasicEarningsLossPerShareIFRSSummaryOfBusinessResults", "Prior4YearDuration", "150"),
    ("OperatingRevenuesIFRSKeyFinancialData", "CurrentYearDuration", "1000"),
    ("OperatingRevenuesIFRSKeyFinancialData", "Prior1YearDuration", "900"),
    ("ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", "CurrentYearDuration", "200"),
    ("ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", "Prior1YearDuration", "180"),
    ("EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", "CurrentYearInstant", "1000000"),
    ("EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", "Prior1YearInstant", "900000"),
    ("EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", "CurrentYearInstant_NonConsolidatedMember", "999"),
    ("RateOfReturnOnEquityIFRSSummaryOfBusinessResults", "CurrentYearDuration", "0.2"),
    ("RateOfReturnOnEquityIFRSSummaryOfBusinessResults", "Prior1YearDuration", "0.2"),
    ("CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults", "CurrentYearDuration", "300"),
    ("AdditionsToFixedAssetsExcludingEquipmentLeasedToOthersInvCFIFRS", "CurrentYearDuration", "-50"),
    ("DividendsPaidToOwnersOfParentFinCFIFRS", "CurrentYearDuration", "-100"),
    ("TotalAssetsIFRSSummaryOfBusinessResults", "CurrentYearInstant", "1400"),
    ("TotalAssetsIFRSSummaryOfBusinessResults", "Prior1YearInstant", "1300"),
    ("LiabilitiesIFRS", "CurrentYearInstant", "400"),
    ("LiabilitiesIFRS", "Prior1YearInstant", "400"),
    ("OtherComprehensiveIncomeRelatedToAssetsHeldForSaleIFRS", "Prior1YearDuration", "－"),  # 非數字，略過
]


def _tsv(rows):
    head = '"要素ID"\t"項目名"\t"コンテキストID"\t"相対年度"\t"連結・個別"\t"期間・時点"\t"ユニットID"\t"単位"\t"値"'
    body = [f'"jpcrp030000-asr:{tag}"\t"項目"\t"{ctx}"\t"相対"\t"連結"\t"期間"\t"JPY"\t"円"\t"{val}"' for tag, ctx, val in rows]
    return "\r\n".join([head, *body]).encode("utf-16")


def _report(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("XBRL_TO_CSV/jpcrp030000-asr-001_E00001-000_2026-03-31_01_2026-06-10.csv", _tsv(rows))
    return buf.getvalue()


ACME_REPORT = _report(ACME)


def _set(rows, tag, ctx, val):
    """換掉其中一列的數值，模擬另一年的報告書。"""
    return [(t, c, val if (t, c) == (tag, ctx) else v) for t, c, v in rows]


def _rename(rows, old, new):
    """把要素 ID 換成另一家公司使用的標籤名。"""
    return [(new if t == old else t, c, v) for t, c, v in rows]


@pytest.fixture
def jp_offline(monkeypatch):
    monkeypatch.setattr(etf_drive, "_tables", lambda *a, **k: ([], []))  # 全市場表沒有資料 → 走 Yahoo 前幾大
    monkeypatch.setattr(etf_jp, "_top_holdings_rows", lambda etf: list(TOP))
    monkeypatch.setattr(etf_jp.price_fetch, "get_price", lambda ticker, source="auto": {"price": PRICES.get(ticker, 1.0)})
    monkeypatch.setattr(etf_jp.price_fetch, "yahoo_dividends",
                        lambda exch, code, since: dict(DIVS.get(code, dict(ttm_total=0.0, yearly_totals={}))))
    monkeypatch.setattr(edinet, "report_bytes", lambda code: ACME_REPORT if code == "7203" else None)
    monkeypatch.setattr(etf_fx, "fetch_rate",  # 池流程會取匯率，測試不連 Google Finance
                        lambda currency, **k: dict(currency=currency, rate=0.21, as_of="2026-01-02", source="測試"))


@pytest.mark.parametrize("raw,code", [
    ("1306", "1306"), ("7203.T", "7203"), ("7203.jp", "7203"), ("TYO:7203", "7203"), ("tse:6758", "6758"), ("130a", "130A"),
])
def test_parse_jp_code_accepts_tokyo_codes(raw, code):
    assert etf_jp.parse_jp_code(raw) == code


@pytest.mark.parametrize("raw", ["NVDA", "2330.TW", "AAPL", "ABCD", "7203.HK", "NASDAQ:NVDA", "USD", "", "7203.TW"])
def test_parse_jp_code_refuses_other_markets(raw):
    assert etf_jp.parse_jp_code(raw) is None


def test_parse_rows_still_returns_only_the_current_period():
    rows = edinet.parse_rows(ACME_REPORT)
    assert rows["BasicEarningsLossPerShareIFRSSummaryOfBusinessResults"] == 200.0
    assert rows["EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults"] == 1000000.0
    assert rows["LiabilitiesIFRS"] == 400.0


def test_parse_history_keeps_each_period_and_skips_members_and_dashes():
    h = edinet.parse_history(ACME_REPORT)
    assert h["BasicEarningsLossPerShareIFRSSummaryOfBusinessResults"] == {0: 200.0, 1: 180.0, 4: 150.0}
    assert h["EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults"] == {0: 1000000.0, 1: 900000.0}
    assert "OtherComprehensiveIncomeRelatedToAssetsHeldForSaleIFRS" not in h


def test_report_bytes_is_none_without_a_filing(monkeypatch):
    monkeypatch.setattr(edinet, "cached_doc", lambda sec_code: None)
    monkeypatch.setattr(edinet, "find_doc", lambda sec_code: None)
    assert edinet.report_bytes("9999") is None
    assert edinet.fetch("9999") == {}


def test_fetch_holdings_keeps_japanese_stocks_and_marks_partial(jp_offline):
    h = etf_jp.fetch_holdings("1306")
    assert [c["symbol"] for c in h["constituents"]] == ["7203", "8306"]
    assert h["source"] == etf_jp.TOP_SOURCE and h["ticker"] == "1306"
    assert h["total_weight_pct"] == 6.5 and etf_market.coverage_label(h) == "partial"


def test_fetch_holdings_needs_a_four_character_code():
    with pytest.raises(ValueError, match="4 碼"):
        etf_jp.fetch_holdings("VOO")


def test_jp_financials_builds_history_and_latest_ratios(jp_offline):
    f = etf_jp.jp_financials("7203", 3000.0, 100.0)
    assert f["cur"] == "日圓" and f["eps"] == 200.0 and f["roe"] == 20.0
    assert f["pe"] == 15.0 and f["pb"] == 3.0 and f["payout"] == 50.0
    assert f["fcf_cover"] == 2.5 and f["pb_fair"] == 1.5
    assert [h["k"] for h in f["hist"]] == ["2026年報", "2025年報", "2022年報"]
    assert f["hist"][0]["debt"] == 28.6 and f["hist"][1]["debt"] == 30.8 and f["debt"] == 28.6
    assert f["ocf"] == 300.0 and f["np"] == 200.0 and f["rev"] == 1000.0  # 頁面卡片讀最近一年的頂層欄位


def test_jp_financials_without_a_filing_is_empty(jp_offline):
    assert etf_jp.jp_financials("8306", 1800.0, 0.0) == {}


def test_pb_uses_outstanding_shares_after_treasury(jp_offline, monkeypatch):
    rows = ACME + [(etf_jp.TREASURY_TAG, "CurrentYearInstant", "200")]  # 流通股數 1000 - 200 = 800，BPS 1,250
    monkeypatch.setattr(edinet, "report_bytes", lambda code: _report(rows))
    assert etf_jp.jp_financials("7203", 3000.0, 100.0)["pb"] == 2.4


def test_eps_before_a_split_is_left_blank(jp_offline, monkeypatch):
    rows = _set(ACME, "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults", "Prior1YearDuration", "60")  # 分割前的數字，股數約 3 倍
    monkeypatch.setattr(edinet, "report_bytes", lambda code: _report(rows))
    f = etf_jp.jp_financials("7203", 3000.0, 100.0)
    assert [h.get("eps") for h in f["hist"]] == [200.0, None, 150.0]
    assert f["eps"] == 200.0 and f["pe"] == 15.0


def test_capex_and_dividends_fall_back_to_ifrs_names(jp_offline, monkeypatch):
    rows = _rename(_rename(ACME, "AdditionsToFixedAssetsExcludingEquipmentLeasedToOthersInvCFIFRS",
                           "PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssetsInvCFIFRS"),
                   "DividendsPaidToOwnersOfParentFinCFIFRS", "DividendsPaidFinCFIFRS")
    monkeypatch.setattr(edinet, "report_bytes", lambda code: _report(rows))
    assert etf_jp.jp_financials("7203", 3000.0, 100.0)["fcf_cover"] == 2.5


def test_financial_filers_leave_cash_flow_and_debt_blank(jp_offline, monkeypatch):
    rows = ACME + [("DepositsLiabilitiesBNK", "CurrentYearInstant", "5000")]  # 銀行業種別標籤
    monkeypatch.setattr(edinet, "report_bytes", lambda code: _report(rows))
    f = etf_jp.jp_financials("7203", 3000.0, 100.0)
    assert f["pb"] == 3.0 and "fcf_cover" not in f and "debt" not in f
    assert all("debt" not in h for h in f["hist"])


def test_us_gaap_filers_use_their_own_tags(jp_offline, monkeypatch):
    names = {
        "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults": "BasicEarningsLossPerShareUSGAAPSummaryOfBusinessResults",
        "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults":
            "NetIncomeLossAttributableToOwnersOfParentUSGAAPSummaryOfBusinessResults",
        "EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults":
            "EquityIncludingPortionAttributableToNonControllingInterestUSGAAPSummaryOfBusinessResults",
        "RateOfReturnOnEquityIFRSSummaryOfBusinessResults": "RateOfReturnOnEquityUSGAAPSummaryOfBusinessResults",
    }
    rows = [(names.get(t, t), c, v) for t, c, v in ACME]
    monkeypatch.setattr(edinet, "report_bytes", lambda code: _report(rows))
    f = etf_jp.jp_financials("7203", 3000.0, 100.0)
    assert f["eps"] == 200.0 and f["roe"] == 20.0 and f["pb"] == 3.0


def test_equity_falls_back_to_the_balance_sheet_tag(jp_offline, monkeypatch):
    rows = _rename(ACME, "EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults", "EquityAttributableToOwnersOfParentIFRS")
    monkeypatch.setattr(edinet, "report_bytes", lambda code: _report(rows))
    assert etf_jp.jp_financials("7203", 3000.0, 100.0)["pb"] == 3.0


def test_jp_financials_refuses_a_report_without_a_fiscal_year_end(monkeypatch):
    no_end = _report([row for row in ACME if row[0] != "CurrentFiscalYearEndDateDEI"])
    monkeypatch.setattr(edinet, "report_bytes", lambda code: no_end)
    with pytest.raises(RuntimeError, match="會計年度末日"):
        etf_jp.jp_financials("7203", 3000.0, 100.0)


def test_shift_keeps_a_leap_day_inside_a_common_year():
    assert etf_jp._shift(date(2028, 2, 29), 1) == date(2027, 2, 28)


def test_jp_stock_computes_yield_growth_and_financials(jp_offline):
    g = etf_jp.jp_stock("7203", "Toyota", None, TODAY)
    assert g["errs"] == [] and g["px"] == 3000.0
    assert g["ttm"] == 100.0 and g["y"] == 3.33 and g["lfy"] == 90.0 and g["chg"] == 11.1
    f = g["f"]
    assert f["fy_lab"] == "2025 年（日曆年）" and f["fy_hkd"] == 90.0 and f["fy_prev_hkd"] == 80.0 and f["fy_chg"] == 12.5
    assert f["pe"] == 15.0


def test_jp_stock_keeps_the_price_when_edinet_is_down(jp_offline, monkeypatch):
    def down(code):
        raise RuntimeError("EDINET 斷線")

    monkeypatch.setattr(edinet, "report_bytes", down)
    g = etf_jp.jp_stock("7203", "Toyota", None, TODAY)
    assert g["errs"] == ["financials:RuntimeError"] and g["f"] == {}
    assert g["px"] == 3000.0 and g["y"] == 3.33


def test_jp_market_is_registered_and_needs_explicit_etfs(tmp_path, capsys):
    assert set(etf_pool.markets()) == {"TW", "HK", "US", "JP"}
    assert etf_jp.JP.accept_coverage == ("full", "partial")
    with pytest.raises(SystemExit) as exc:
        etf_pool.main(["etf_pool.py", str(tmp_path / "out"), "--market", "jp"])
    assert exc.value.code == 2 and "請用 --etfs 指定 ETF 代號" in capsys.readouterr().err


def test_holdings_for_takes_partial_jp_holdings(tmp_path, jp_offline):
    assert etf_pool.holdings_for("1306", str(tmp_path), etf_jp.JP)["source"] == etf_jp.TOP_SOURCE


def test_jp_pool_writes_pure_codes_and_partial_pages(tmp_path, jp_offline):
    out = tmp_path / "out"
    assert etf_pool.main(["etf_pool.py", str(out), "--market", "jp", "--etfs", "1306"]) == 0
    payload = json.loads((out / "pool.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == etf_market.SCHEMA_VERSION and payload["market"] == "JP"
    assert {s["code"] for s in payload["stocks"]} == {"7203", "8306"}
    assert {h["code"] for h in payload["holdings"]} == {"7203", "8306"}
    summary = payload["summaries"][0]
    assert summary["coverage"] == "partial" and summary["source"] == etf_jp.TOP_SOURCE and summary["no_fin"] == ["8306"]
    index = (out / "index.html").read_text(encoding="utf-8")
    page = (out / "1306.html").read_text(encoding="utf-8")
    assert "<h1>日股 ETF 成分股明細</h1>" in index and "財報來自 EDINET" in index
    assert etf_page.YIELD_NOTE in page and "日圓" in page and "前幾大持股" in page
    assert "占基金 '+pa.w.toFixed(1)" in page and "（只含前幾大持股，合計約占基金 6.5%，其餘持股未納入計算）" in page
    for text in (index, page, (out / "pool.json").read_text(encoding="utf-8")):
        assert etf_market.find_forbidden_suffix(text) == []


def test_jp_gate_passes_with_partial_holdings(tmp_path, jp_offline):
    assert etf_pool.main(["etf_pool.py", str(tmp_path / "out"), "--market", "jp", "--etfs", "1306", "--gate"]) == 0


def test_jp_suffix_guard_refuses_to_write(tmp_path, jp_offline, monkeypatch):
    monkeypatch.setattr(etf_jp, "_top_holdings_rows", lambda etf: [("7203.T", "TOYOTA 7203.JP", 3.0)])
    out = tmp_path / "out"
    assert etf_pool.main(["etf_pool.py", str(out), "--market", "jp", "--etfs", "1306"]) == 1
    assert not out.exists()


def test_jp_profile_says_yen_and_share_of_fund():
    page = etf_page.render("jp", "1306", 1, [], [], {}, "asof", 0, "top", "unit", partial_total=6.5)
    assert "占基金 '+pa.w.toFixed(1)+'%）" in page and "只含前幾大持股，合計約占基金 6.5%" in page
