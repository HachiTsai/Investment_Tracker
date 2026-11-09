"""穿透計算範圍與快取鍵的單元測試（離線）。

涵蓋：
- top_n 未指定、0 或負數＝全部成分股；正整數＝前 N 大（[:0] 不可變空清單）。
- 快取鍵含計算範圍：全持股與前 N 大不互相覆蓋。
- use_cache=False 不讀不寫 ETF 快取。
- fund_coverage_pct、selected_fund_weight_pct 以全基金權重為分母。
"""

import json
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TEST_DIR.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import analyzer_cli  # noqa: E402
import lookthrough_fundamentals as lt  # noqa: E402

CONSTITUENTS = [{"ticker": f"S{i}.TW", "name": f"股{i}", "weight_pct": w} for i, w in enumerate([40.0, 30.0, 20.0, 10.0])]


def _fund(net):
    return {"sector": None, "roe": 10.0 if net is not None else None, "debt_to_equity": None, "operating_margin": None,
            "scores": {"netScore": net, "divScore": 50.0, "valScore": 50.0, "fricScore": 80.0}}


def _patch(monkeypatch, tmp_path, funds):
    calls = []
    monkeypatch.setattr(lt, "ETF_CACHE_FILE", tmp_path / "etf.json")
    monkeypatch.setattr(lt, "load_etf_constituents", lambda etf_id, repo_root: [dict(c) for c in CONSTITUENTS])

    def fake(t, mock_data=None, use_cache=True):
        calls.append((t, use_cache))
        return dict(funds[t])

    monkeypatch.setattr(lt, "calculate_stock_fundamentals", fake)
    return calls


FUNDS = {"S0.TW": _fund(80.0), "S1.TW": _fund(None), "S2.TW": _fund(60.0), "S3.TW": _fund(40.0)}


def test_default_and_zero_mean_all_holdings(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path, FUNDS)
    for top in (None, 0, -1):
        res = lt.aggregate_etf_fundamentals("T1", top_n=top, repo_root=Path("."), use_cache=False)
        assert res["covered_holdings_count"] == 4
        assert res["holdings_total_count"] == 4
        assert res["selected_fund_weight_pct"] == 100.0


def test_top_n_uses_fund_weight_denominator(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path, FUNDS)
    res = lt.aggregate_etf_fundamentals("T1", top_n=2, repo_root=Path("."), use_cache=False)
    assert res["covered_holdings_count"] == 2
    assert res["selected_fund_weight_pct"] == 70.0   # 40 + 30 占全基金 100
    assert res["coverage_pct"] == 57.1               # 計算範圍內：40 / 70
    assert res["fund_coverage_pct"] == 40.0          # 全基金：只有 S0 有財報輸入


def test_cache_key_separates_scopes(tmp_path, monkeypatch):
    _patch(monkeypatch, tmp_path, FUNDS)
    full = lt.aggregate_etf_fundamentals("T1", repo_root=Path("."))
    top1 = lt.aggregate_etf_fundamentals("T1", top_n=1, repo_root=Path("."))
    cache = json.loads((tmp_path / "etf.json").read_text(encoding="utf-8"))
    assert set(cache) == {"T1:all", "T1:top1"}
    assert cache["T1:all"]["schema"] == lt.CACHE_SCHEMA
    assert full["covered_holdings_count"] == 4 and top1["covered_holdings_count"] == 1
    # 再跑一次全持股，讀到的是全持股快取，不是前 1 大
    again = lt.aggregate_etf_fundamentals("T1", repo_root=Path("."))
    assert again["covered_holdings_count"] == 4


def test_no_cache_skips_etf_and_stock_cache(tmp_path, monkeypatch):
    calls = _patch(monkeypatch, tmp_path, FUNDS)
    lt.aggregate_etf_fundamentals("T1", repo_root=Path("."), use_cache=False)
    assert not (tmp_path / "etf.json").exists()
    assert all(uc is False for _, uc in calls)


def test_cli_etf_defaults_to_all_and_no_cache(monkeypatch, capsys):
    seen = {}

    def fake(etf_id, top_n=None, repo_root=None, use_cache=True):
        seen.update(top_n=top_n, use_cache=use_cache)
        return {"etf_id": etf_id, "scores": {}, "covered_holdings_count": 0}

    monkeypatch.setattr(analyzer_cli, "aggregate_etf_fundamentals", fake)
    analyzer_cli.main(["etf", "00882", "--no-cache"])
    assert seen == {"top_n": None, "use_cache": False}
    analyzer_cli.main(["etf", "00882", "--top", "10"])
    assert seen == {"top_n": 10, "use_cache": True}


def test_scope_top_n_core_vs_pool(tmp_path):
    for etf, tier in (("C1", "core"), ("P1", "pool")):
        d = tmp_path / "models" / etf / "cards"
        d.mkdir(parents=True)
        (d / "ticker.yml").write_text(f"ticker: {etf}\ntier: {tier}  # 註解\n", encoding="utf-8")
    assert lt.scope_top_n("C1", tmp_path) is None
    assert lt.scope_top_n("P1", tmp_path) == lt.POOL_TOP_N
    assert lt.scope_top_n("NONE", tmp_path) == lt.POOL_TOP_N
