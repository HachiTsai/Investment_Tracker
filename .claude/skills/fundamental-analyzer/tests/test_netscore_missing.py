"""netScore 缺值處理與 FinMind 權杖的單元測試（離線，以假資料代替網路來源）。

涵蓋：
- 個股無財報輸入時 netScore 為 None（不以中性 50 分充數）；有輸入時照常計分。
- ETF 穿透聚合時 netScore 只計有輸入的持股、權重重新歸一化；全部缺值為 None。
- 無成分股時的降級結果不回填固定預設分。
- 主要台股路徑（finmind.load）帶上 FINMIND_TOKEN、經 6 小時快取、只嘗試一次。
- 分數顯示遇 None 不崩潰，顯示 "-"。
"""

import sys
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TEST_DIR.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import analyzer_cli  # noqa: E402
import fundamental_calculator as fc  # noqa: E402
import lookthrough_fundamentals as lt  # noqa: E402
from fetchers import finmind, finmind_detail as fd  # noqa: E402


def _fund(net, roe=None, dte=None, opm=None):
    return {
        "sector": None,
        "roe": roe,
        "debt_to_equity": dte,
        "operating_margin": opm,
        "scores": {"netScore": net, "divScore": 50.0, "valScore": 50.0, "fricScore": 80.0},
    }


def _patch_holdings(monkeypatch, tmp_path, constituents, funds_by_ticker):
    monkeypatch.setattr(lt, "ETF_CACHE_FILE", tmp_path / "etf.json")
    monkeypatch.setattr(lt, "load_etf_constituents", lambda etf_id, repo_root: [dict(c) for c in constituents])
    monkeypatch.setattr(lt, "calculate_stock_fundamentals",
                        lambda t, mock_data=None, use_cache=True: dict(funds_by_ticker[t]))


def test_single_stock_without_netscore_inputs_is_none():
    res = fc.calculate_stock_fundamentals("2357.TW", mock_data={}, use_cache=False)
    assert res["scores"]["netScore"] is None


def test_single_stock_with_roe_keeps_numeric_netscore():
    res = fc.calculate_stock_fundamentals("2881.TW", mock_data={"returnOnEquity": 0.15}, use_cache=False)
    assert isinstance(res["scores"]["netScore"], float)


def test_etf_netscore_excludes_uncovered_holdings(tmp_path, monkeypatch):
    constituents = [{"ticker": "A.TW", "name": "甲", "weight_pct": 60.0},
                    {"ticker": "B.TW", "name": "乙", "weight_pct": 40.0}]
    funds = {
        "A.TW": _fund(80.0, roe=15.0, dte=40.0, opm=20.0),  # 有財報輸入
        "B.TW": _fund(None),                                # 無財報輸入：不應以 50 分拉低整體
    }
    _patch_holdings(monkeypatch, tmp_path, constituents, funds)
    res = lt.aggregate_etf_fundamentals("TEST", top_n=10, repo_root=Path("."))
    assert res["scores"]["netScore"] == 80.0  # 只剩 A，重新歸一化後即 A 本身
    assert res["coverage_pct"] == 60.0
    assert res["coverage_sufficient"] is True


def test_etf_netscore_none_when_no_holding_has_inputs(tmp_path, monkeypatch):
    constituents = [{"ticker": "A.TW", "name": "甲", "weight_pct": 60.0},
                    {"ticker": "B.TW", "name": "乙", "weight_pct": 40.0}]
    funds = {"A.TW": _fund(None), "B.TW": _fund(None)}
    _patch_holdings(monkeypatch, tmp_path, constituents, funds)
    res = lt.aggregate_etf_fundamentals("TEST", top_n=10, repo_root=Path("."))
    assert res["scores"]["netScore"] is None
    assert res["coverage_pct"] == 0.0
    assert res["coverage_sufficient"] is False


def test_fallback_without_constituents_has_no_preset_scores(tmp_path, monkeypatch):
    monkeypatch.setattr(lt, "ETF_CACHE_FILE", tmp_path / "etf.json")
    monkeypatch.setattr(lt, "load_etf_constituents", lambda etf_id, repo_root: [])
    res = lt.aggregate_etf_fundamentals("TEST", top_n=10, repo_root=Path("."))
    assert res["status"] == "fallback"
    assert all(v is None for v in res["scores"].values())


def test_finmind_load_sends_token_and_uses_cache(tmp_path, monkeypatch):
    calls = []

    def fake_http_json(url, headers=None, timeout=30):
        calls.append(url)
        return {"status": 200, "data": [{"type": "CashFlowsFromOperatingActivities", "date": "2025-12-31", "value": 7}]}

    monkeypatch.setenv("FINMIND_TOKEN", "unit-test-token")
    monkeypatch.setattr(fd, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(fd, "http_json", fake_http_json)

    out = finmind.load("TaiwanStockCashFlowsStatement", "2357", "2023-01-01")
    assert out == {"CashFlowsFromOperatingActivities": {"2025-12-31": 7}}
    assert "&token=unit-test-token" in calls[0]

    finmind.load("TaiwanStockCashFlowsStatement", "2357", "2023-01-01")
    assert len(calls) == 1  # 第二次命中 6 小時快取，不再消耗配額


def test_finmind_load_attempts_once_on_quota_error(tmp_path, monkeypatch):
    calls = []

    def quota_error(url, headers=None, timeout=30):
        calls.append(url)
        raise RuntimeError("HTTP 402 upper limit")

    monkeypatch.delenv("FINMIND_TOKEN", raising=False)
    monkeypatch.setattr(fd, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(fd, "http_json", quota_error)
    monkeypatch.setattr(fd.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError):
        finmind.load("TaiwanStockCashFlowsStatement", "2357", "2023-01-01")
    assert len(calls) == 1


def test_show_renders_none_as_dash():
    assert analyzer_cli._show(None, ">5") == "    -"
    assert analyzer_cli._show(53.66, ">5") == " 53.7"
    assert analyzer_cli._show(0.0, "<10") == "0.0       "
