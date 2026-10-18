"""基本面財務指標與評分演算技能單元測試 (Unit Tests for fundamental-analyzer)。"""

import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TEST_DIR.parent / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import analyzer_cli as cli  # noqa: E402
from fundamental_calculator import (  # noqa: E402
    calculate_div_score,
    calculate_fric_score,
    calculate_net_score,
    calculate_stock_fundamentals,
    calculate_val_score,
    score_debt_to_equity,
    score_fcf_coverage,
    score_operating_margin,
    score_payout_ratio,
    score_pb,
    score_pe,
    score_roe,
    score_yield,
)
from lookthrough_fundamentals import aggregate_etf_fundamentals  # noqa: E402


def test_sub_score_calculations():
    # 1. 自由現金流覆蓋
    assert score_fcf_coverage(2.5) == 100.0
    assert 85.0 <= score_fcf_coverage(1.8) <= 100.0
    assert 60.0 <= score_fcf_coverage(1.2) <= 85.0
    assert 30.0 <= score_fcf_coverage(0.7) <= 60.0
    assert score_fcf_coverage(0.2) < 30.0
    assert score_fcf_coverage(None) == 50.0

    # 2. 盈餘配發率
    assert score_payout_ratio(0.55) == 100.0
    assert 75.0 <= score_payout_ratio(0.75) <= 90.0
    assert 50.0 <= score_payout_ratio(0.90) <= 75.0
    assert score_payout_ratio(1.30) < 50.0
    assert score_payout_ratio(None) == 50.0

    # 3. ROE
    assert score_roe(0.25) == 100.0
    assert 85.0 <= score_roe(0.18) <= 100.0
    assert 70.0 <= score_roe(0.12) <= 85.0
    assert score_roe(0.03) < 45.0
    assert score_roe(None) == 50.0

    # 4. 負債權益比
    assert score_debt_to_equity(0.30) == 100.0
    assert 80.0 <= score_debt_to_equity(0.80) <= 100.0
    assert 65.0 <= score_debt_to_equity(1.20) <= 80.0
    assert score_debt_to_equity(2.50) < 45.0
    assert score_debt_to_equity(None) == 50.0

    # 5. 營業利益率
    assert score_operating_margin(0.35) == 100.0
    assert 85.0 <= score_operating_margin(0.25) <= 100.0
    assert 65.0 <= score_operating_margin(0.15) <= 85.0
    assert score_operating_margin(0.02) < 45.0

    # 6. 本益比、淨值比、殖利率
    assert score_pe(10.0) == 100.0
    assert score_pe(30.0) < 60.0
    assert score_pb(1.0) == 100.0
    assert score_pb(4.0) < 55.0
    assert score_yield(0.08) == 100.0
    assert score_yield(0.02) == 40.0


def test_yield_trap_vs_healthy_stock_scoring():
    # 案例 A：優質健康企業（台積電型態：高 ROE、高利潤率、充沛 FCF）
    healthy_mock = {
        "returnOnEquity": 0.40,
        "debtToEquity": 0.20,
        "operatingMargins": 0.42,
        "freeCashflow": 100000,
        "operatingCashflow": 150000,
        "netIncome": 80000,
        "payoutRatio": 0.35,
        "trailingPE": 22.0,
        "priceToBook": 6.5,
        "dividendYield": 0.02,
    }
    res_a = calculate_stock_fundamentals("2330.TW", mock_data=healthy_mock)
    scores_a = res_a["scores"]
    assert scores_a["netScore"] >= 80.0
    assert scores_a["divScore"] >= 75.0
    assert res_a["roe"] == 40.0

    # 案例 B：高息陷阱警報企業（殖利率 12%、但 FCF 嚴重不足、借款超額配息 150%、高負債）
    trap_mock = {
        "returnOnEquity": 0.04,
        "debtToEquity": 2.80,
        "operatingMargins": 0.03,
        "freeCashflow": 500,
        "operatingCashflow": 2000,
        "netIncome": 3000,
        "payoutRatio": 1.50,
        "trailingPE": 15.0,
        "priceToBook": 0.9,
        "dividendYield": 0.12,
    }
    res_b = calculate_stock_fundamentals("TRAP.TW", mock_data=trap_mock)
    scores_b = res_b["scores"]
    assert scores_b["netScore"] < 50.0
    # 自由現金流覆蓋嚴重不足加上超額配發，divScore 必須掉入 40 分警戒區以下！
    assert scores_b["divScore"] < 40.0


def test_friction_scores():
    assert calculate_fric_score("00679B") == 95.0
    assert calculate_fric_score("00882") == 85.0
    assert calculate_fric_score("2330.TW") == 80.0
    assert calculate_fric_score("7203.T") == 75.0
    assert calculate_fric_score("NVDA") == 55.0


def test_etf_lookthrough_aggregation():
    mock_constituents = [
        {"ticker": "AAA.TW", "name": "優質A", "weight_pct": 60.0},
        {"ticker": "BBB.TW", "name": "普通B", "weight_pct": 40.0},
    ]
    mock_stock_data = {
        "AAA.TW": {
            "returnOnEquity": 0.30,
            "debtToEquity": 0.30,
            "operatingMargins": 0.30,
            "freeCashflow": 5000,
            "netIncome": 4000,
            "payoutRatio": 0.50,
        },
        "BBB.TW": {
            "returnOnEquity": 0.15,
            "debtToEquity": 0.80,
            "operatingMargins": 0.15,
            "freeCashflow": 2000,
            "netIncome": 2000,
            "payoutRatio": 0.60,
        },
    }

    res = aggregate_etf_fundamentals(
        etf_id="00999",
        top_n=5,
        mock_constituents=mock_constituents,
        mock_stock_fundamentals=mock_stock_data,
    )

    assert res["status"] == "success"
    assert res["covered_holdings_count"] == 2
    assert res["total_weight_covered_pct"] == 100.0
    assert res["weighted_roe"] == 24.0  # 30*0.6 + 15*0.4 = 18 + 6 = 24.0
    assert res["scores"]["netScore"] > 80.0
    assert res["scores"]["divScore"] > 80.0


def test_cli_commands(tmp_path, monkeypatch, capsys):
    # 測試 stock
    mock_stock = {
        "returnOnEquity": 0.25,
        "debtToEquity": 0.40,
        "operatingMargins": 0.25,
        "freeCashflow": 5000,
        "netIncome": 4000,
        "payoutRatio": 0.50,
        "trailingPE": 15.0,
        "priceToBook": 2.0,
        "dividendYield": 0.04,
    }
    monkeypatch.setattr(
        cli,
        "calculate_stock_fundamentals",
        lambda s: calculate_stock_fundamentals(s, mock_data=mock_stock),
    )

    rc_stock = cli.main(["stock", "2330.TW"])
    assert rc_stock == 0
    captured_stock = capsys.readouterr()
    assert "個股財務體檢與多維評分報告" in captured_stock.out
    assert "2330.TW" in captured_stock.out

    # 測試 etf fallback (債券 ETF)
    rc_etf = cli.main(["etf", "00679B", "--models-dir", str(tmp_path)])
    assert rc_etf == 0
    captured_etf = capsys.readouterr()
    assert "00679B" in captured_etf.out

    # 測試 portfolio
    m_dir = tmp_path / "models"
    (m_dir / "00878").mkdir(parents=True)
    (m_dir / "00679B").mkdir(parents=True)
    rc_port = cli.main(["portfolio", "--models-dir", str(m_dir)])
    assert rc_port == 0
    captured_port = capsys.readouterr()
    assert "投資組合全標的基本面穿透評分矩陣" in captured_port.out
    assert "00878" in captured_port.out
