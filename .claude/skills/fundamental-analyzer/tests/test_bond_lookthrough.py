"""債券 ETF 穿透測試（離線）：代號解析、兩層指標、與 repo 內真實持股卡片的回測式檢查。"""

import datetime
import json
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import bond_lookthrough as bl  # noqa: E402
import lookthrough_fundamentals as lt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]
TODAY = datetime.date(2026, 11, 3)


@pytest.mark.parametrize(
    "code,issuer,coupon,year",
    [
        ("BBDBCN 8 3/4 11/15/30", "BBDBCN", 8.75, 2030),
        ("AES 7.6 01/15/55", "AES", 7.6, 2055),
        ("VOD 7 04/04/2079", "VOD", 7.0, 2079),
        ("PFIZER INVESTMENT ENTER 5.3% 05/19/2053", "PFIZER INVESTMENT ENTER", 5.3, 2053),
        ("US TREASURY N/B 4.75% 05/15/2055", "US TREASURY N/B", 4.75, 2055),
        ("GOLDMAN SACHS GROUP INC 6.75-2037/10/01", "GOLDMAN SACHS GROUP INC", 6.75, 2037),
        ("ABIBB 4.9 02/01/46 *", "ABIBB", 4.9, 2046),
        ("BAC 5.875 02/07/42 MTN", "BAC", 5.875, 2042),
        ("EIX 4.125 03/01/48 C", "EIX", 4.125, 2048),
    ],
)
def test_parse_bond_formats(code, issuer, coupon, year):
    p = bl.parse_bond(code)
    assert p is not None
    assert p["issuer"] == issuer
    assert p["coupon_pct"] == pytest.approx(coupon)
    assert p["maturity"].year == year


def test_parse_bond_rejects_garbage():
    assert bl.parse_bond("台積電") is None
    assert bl.parse_bond("") is None
    assert bl.parse_bond("XYZ 5 13/45/30") is None


def test_analyze_synthetic_two_layers():
    cons = [
        {"ticker": "AAA 5 01/01/29", "weight_pct": 50.0},
        {"ticker": "BBB 10 01/01/33", "weight_pct": 50.0},
        {"ticker": "壞代號", "weight_pct": 10.0},
    ]
    r = bl.analyze_bond_etf(cons, today=TODAY, risk_free_pct=4.0)
    assert r["parse_coverage_pct"] == pytest.approx(100.0 * 100 / 110, abs=0.1)
    l1, l2 = r["layer1"], r["layer2"]
    assert l1["weighted_coupon_pct"] == 7.5
    assert l1["issuer_count"] == 2
    # 利差 1.0 → 投資等級區間（壓力 0）；利差 6.0 → CCC 區間（壓力 100）；各半 → 壓力 50
    assert l2["avg_stress"] == 50.0
    assert l2["credit_proxy_score"] == 50.0
    assert l2["high_coupon_9pct_share"] == 50.0


def test_analyze_empty_returns_no_layers():
    r = bl.analyze_bond_etf([{"ticker": "壞", "weight_pct": 1.0}], today=TODAY)
    assert r["layer1"] is None and r["layer2"] is None


def _load(code):
    f = REPO_ROOT / "models" / code / "cards" / "constituents.jsonl"
    if not f.exists():
        pytest.skip(f"沒有 {code} 持股卡片")
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_00953b_matches_fund_reported_figures():
    """回測式核對：加權票息約 8.31%、發行人約 280 家（2026-11-03 投信公布與持股清單）。"""
    r = bl.analyze_bond_etf(_load("00953B"), today=TODAY)
    assert r["parse_coverage_pct"] >= 99.0
    assert 8.2 <= r["layer1"]["weighted_coupon_pct"] <= 8.4
    assert 270 <= r["layer1"]["issuer_count"] <= 290
    assert r["layer1"]["top10_issuer_pct"] < 15.0


def test_credit_proxy_orders_treasury_ig_hy():
    """公債型 > 投資等級公司債型 > 非投等債型（跨 ETF 排序，回測見 PR 說明）。"""
    score = {c: bl.analyze_bond_etf(_load(c), today=TODAY)["layer2"]["credit_proxy_score"]
             for c in ("00679B", "00720B", "00751B", "00953B", "00945B")}
    assert score["00679B"] > max(score["00720B"], score["00751B"])
    assert min(score["00720B"], score["00751B"]) > max(score["00953B"], score["00945B"])


def test_bond_branch_has_no_default_scores_and_is_fast(tmp_path):
    cons = _load("00953B")
    t0 = time.perf_counter()
    res = lt.aggregate_etf_fundamentals("00953B", top_n=10, repo_root=REPO_ROOT, mock_constituents=cons)
    assert time.perf_counter() - t0 < 0.5
    assert res["is_bond"] is True
    assert res["status"] == "bond"
    assert res["scores"] == {}  # 不寫固定預設分
    assert res["bond"]["layer1"]["issuer_count"] > 0
