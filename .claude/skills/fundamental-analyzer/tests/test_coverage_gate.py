"""覆蓋率門檻與降級結果不快取的單元測試（離線，以假資料代替網路來源）。

涵蓋：netScore 輸入判定、ETF 穿透覆蓋率與快取閘門、個股快取閘門、FinMind 空回應不快取、金融業 ROE 補值。
"""

import json
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TEST_DIR.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fundamental_calculator as fc  # noqa: E402
import lookthrough_fundamentals as lt  # noqa: E402
from fetchers import finmind_detail as fd  # noqa: E402
from fetchers import tw  # noqa: E402
import fetchers  # noqa: E402

CONSTITUENTS = [
    {"ticker": "2881.TW", "name": "富邦金", "weight_pct": 60.0},
    {"ticker": "2330.TW", "name": "台積電", "weight_pct": 40.0},
]
SCORES = {"netScore": 50.0, "divScore": 50.0, "valScore": 47.0, "fricScore": 80.0}


def _patch_etf(monkeypatch, tmp_path, fund):
    monkeypatch.setattr(lt, "ETF_CACHE_FILE", tmp_path / "etf.json")
    monkeypatch.setattr(lt, "load_etf_constituents", lambda etf_id, repo_root: [dict(c) for c in CONSTITUENTS])
    monkeypatch.setattr(lt, "calculate_stock_fundamentals", lambda t, mock_data=None, use_cache=True: dict(fund))


def test_has_netscore_input():
    assert fc.has_netscore_input({"roe": None, "debt_to_equity": 972.0, "operating_margin": None})
    assert not fc.has_netscore_input({"roe": None, "debt_to_equity": None, "operating_margin": None})


def test_etf_below_coverage_is_not_cached(tmp_path, monkeypatch):
    degraded = {"roe": None, "debt_to_equity": None, "operating_margin": None, "scores": dict(SCORES)}
    _patch_etf(monkeypatch, tmp_path, degraded)

    res = lt.aggregate_etf_fundamentals("00919", top_n=10, repo_root=tmp_path, use_cache=True)

    assert res["coverage_pct"] == 0.0
    assert res["coverage_sufficient"] is False
    assert not (tmp_path / "etf.json").exists()


def test_etf_at_coverage_is_cached(tmp_path, monkeypatch):
    complete = {"roe": 12.0, "debt_to_equity": 80.0, "operating_margin": 20.0, "scores": dict(SCORES)}
    _patch_etf(monkeypatch, tmp_path, complete)

    res = lt.aggregate_etf_fundamentals("00919", top_n=10, repo_root=tmp_path, use_cache=True)

    assert res["coverage_pct"] == 100.0
    assert res["coverage_sufficient"] is True
    assert "00919" in json.loads((tmp_path / "etf.json").read_text(encoding="utf-8"))


def test_stock_degraded_result_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(fc, "CACHE_FILE", tmp_path / "stock.json")
    monkeypatch.setattr(fetchers, "fetch_info", lambda symbol: {})
    monkeypatch.setattr(fc, "normalize_ticker_for_yf", lambda symbol: "")

    fc.calculate_stock_fundamentals("2881.TW", use_cache=True)

    assert not (tmp_path / "stock.json").exists()


def test_finmind_empty_response_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(fd, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(fd, "http_json", lambda url: {"status": 200, "data": []})

    assert fd.get("TaiwanStockInfo") == []
    assert list(tmp_path.glob("*.json")) == []


def test_financial_roe_fills_only_financials(monkeypatch):
    monkeypatch.setattr(fd, "industries", lambda: {"2881": "金融保險業", "2330": "半導體業"})
    monkeypatch.setattr(fd, "tw_detail", lambda code, *a, **k: {"roe": 9.5})

    assert tw.financial_roe("2881") == {"returnOnEquity": 0.095}
    assert tw.financial_roe("2330") == {}
