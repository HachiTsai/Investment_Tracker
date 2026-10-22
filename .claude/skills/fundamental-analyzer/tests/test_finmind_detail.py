"""台股明細資料層（finmind_detail）單元測試：離線，以假資料代替 FinMind。"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fetchers import finmind_detail as fd  # noqa: E402
from fin_trend import add_dividends, enrich, ttm_dividend  # noqa: E402
from datetime import date  # noqa: E402


def _rows(**types):
    return [{"type": t, "date": d, "value": v} for t, series in types.items() for d, v in series.items()]


QS = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]


def fake_get(dataset, code="", start="", attempts=3):
    eps = dict(zip(QS, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))
    if dataset == "TaiwanStockFinancialStatements":
        return _rows(EPS=eps, Revenue={d: 100.0 for d in QS}, GrossProfit={d: 50.0 for d in QS},
                     EquityAttributableToOwnersOfParent={d: 10.0 for d in QS})
    if dataset == "TaiwanStockBalanceSheet":
        return _rows(EquityAttributableToOwnersOfParent={d: 200.0 for d in QS}, Liabilities={d: 100.0 for d in QS},
                     TotalAssets={d: 400.0 for d in QS}, CurrentAssets={d: 300.0 for d in QS}, CurrentLiabilities={d: 150.0 for d in QS})
    if dataset == "TaiwanStockCashFlowsStatement":
        return _rows(CashFlowsFromOperatingActivities={"2025-12-31": 90.0, "2026-06-30": 40.0},
                     PropertyAndPlantAndEquipment={"2025-12-31": -30.0})
    if dataset == "TaiwanStockDividend":
        base = {"StockEarningsDistribution": 0, "ParticipateDistributionOfTotalShares": 1000.0}
        return [dict(base, year="114年第4季", CashEarningsDistribution=2.0, CashExDividendTradingDate="2026-06-11",
                     CashDividendPaymentDate="2026-07-09", AnnouncementDate="2026-05-27"),
                dict(base, year="115年第1季", CashEarningsDistribution=3.0, CashExDividendTradingDate="2026-09-16",
                     CashDividendPaymentDate="2026-10-08", AnnouncementDate="2026-09-01"),
                dict(base, year="114年", CashEarningsDistribution=0.0, StockEarningsDistribution=1.5, year_note="配股")]
    return []


def test_single_quarter_values_become_cumulative(monkeypatch):
    monkeypatch.setattr(fd, "get", fake_get)
    d = fd.tw_detail("9999", "金融保險")
    by_k = {h["k"]: h for h in d["hist"]}
    assert by_k["2026年中报"]["eps"] == 11.0 and by_k["2026年一季报"]["eps"] == 5.0 and by_k["2025年年报"]["eps"] == 10.0
    assert d["kind"] == "2026年中报" and d["ttm_eps"] == 3 + 4 + 5 + 6 and d["org"] == "金融保險"
    assert round(by_k["2026年中报"]["gpm"], 1) == 50.0 and by_k["2026年中报"]["debt"] == 25.0


def test_detail_feeds_shared_trend_logic(monkeypatch):
    monkeypatch.setattr(fd, "get", fake_get)
    e = enrich(fd.tw_detail("9999"))
    assert e["qeps"] == 6.0  # 中報累計 11 減一季報 5
    assert e["yoy_q"] == 200.0  # 去年同期單季 2.0


def test_dividends_kinds_and_cash_only(monkeypatch):
    monkeypatch.setattr(fd, "get", fake_get)
    divs = fd.tw_dividends("9999")
    assert [d["kind"] for d in divs] == ["Q1", "Q4"] and divs[0]["year"] == "2026" and divs[1]["year"] == "2025"
    assert all(d["amt"] > 0 for d in divs)  # 純配股不列
    assert ttm_dividend(divs, date(2026, 10, 22)) == 5.0
    out = add_dividends(enrich(fd.tw_detail("9999")), divs, date(2026, 10, 22))
    assert out["fy_lab"] == "2025 年度" and out["fy_hkd"] == 2.0 and out["ytd"] == 5.0


def test_cashflow_paid_uses_payment_year(monkeypatch):
    monkeypatch.setattr(fd, "get", fake_get)
    cf = fd.tw_cashflow("9999", [{"amt": 2.0, "pay": "2025-07-09", "shares": 1000.0}, {"amt": 9.0, "pay": "2026-07-09", "shares": 1000.0}])
    assert cf == {"fy": "2025", "ocf": 90.0, "capex": 30.0, "paid": 2000.0}


def test_kind_labels():
    assert fd._kind("114年第4季") == "Q4" and fd._kind("114年第2季") == "Q2"
    assert fd.q_label("2026年中报") == "2026 Q2" and fd.q_label("2025年年报") == "2025 Q4" and fd.q_label("x") == "x"
    assert fd._kind("114年上半年") == "中期" and fd._kind("114年") == "年度" and fd._kind("114年下半年") == "年度"


def test_get_retries_then_raises(monkeypatch):
    calls = []

    def bad(url, *a, **k):
        calls.append(url)
        raise OSError("limit")
    monkeypatch.setattr(fd, "http_json", bad)
    monkeypatch.setattr(fd.time, "sleep", lambda s: None)
    monkeypatch.setattr(fd, "CACHE_DIR", "/nonexistent/cache-dir-for-test")
    try:
        fd.get("TaiwanStockPER", "0000", "2026-01-01")
    except RuntimeError as e:
        assert "失敗" in str(e)
    assert len(calls) == 3
