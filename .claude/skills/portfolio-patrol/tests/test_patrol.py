"""portfolio-patrol 單元測試。

測試覆蓋：
1. 標的動態探索 (discover_tickers)
2. 卡片載入與結構驗證 (load_cards)
3. 數據心跳時效性檢查 (check_watchdog)
4. 多空與風控互鎖求值 (evaluate_ticker_posture)
5. 例外管理 (MBE) 彙整與戰報格式化 (ASCII / Markdown)
6. 零隱私外洩防護（無個人張數與成本）
"""

import datetime
from pathlib import Path
import pytest
import sys

SKILLS_DIR = Path(__file__).resolve().parents[2]
PATROL_SCRIPT_DIR = SKILLS_DIR / "portfolio-patrol" / "scripts"
sys.path.insert(0, str(PATROL_SCRIPT_DIR))

import patrol  # type: ignore


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parents[4]


def test_discover_tickers(repo_root):
    models_dir = repo_root / "models"
    tickers = patrol.discover_tickers(models_dir)
    assert "00882" in tickers

    # 測試過濾器
    filtered = patrol.discover_tickers(models_dir, filter_tickers=["00882"])
    assert filtered == ["00882"]

    empty_filtered = patrol.discover_tickers(models_dir, filter_tickers=["NON_EXISTENT"])
    assert empty_filtered == []


def test_load_cards(repo_root):
    models_dir = repo_root / "models"
    cards = patrol.load_cards(models_dir, "00882")
    assert cards["ticker_id"] == "00882"
    assert "spec" in cards["ticker"]
    assert len(cards["loops"]) >= 1
    assert len(cards["interlocks"]) >= 1
    assert len(cards["constituents"]) >= 1
    assert cards["ticker"]["calibration"]["payout_ratio"] == pytest.approx(0.954, 0.001)


def test_watchdog_healthy_and_stale():
    # 測試正常時間戳
    cards_healthy = {
        "files_mtime": {"ticker.yml": datetime.date.today().isoformat()},
        "ticker": {"fail_safe": {"max_stale_days": 5}},
    }
    res_healthy = patrol.check_watchdog(cards_healthy)
    assert res_healthy["status"] == "HEALTHY"
    assert not res_healthy["is_stale"]

    # 測試過期時間戳（例如 10 天前）
    old_date = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    cards_stale = {
        "files_mtime": {"ticker.yml": old_date},
        "ticker": {"fail_safe": {"max_stale_days": 5}},
    }
    res_stale = patrol.check_watchdog(cards_stale)
    assert res_stale["status"] == "STALE"
    assert res_stale["is_stale"]
    assert "過期" in res_stale["label"]


def test_evaluate_ticker_postures():
    mock_cards = {
        "ticker_id": "00882",
        "ticker": {
            "title": "00882 中信中國高股息",
            "currency": "TWD",
            "thresholds": {"yield_cheap": 0.08, "yield_expensive": 0.05},
        },
        "loops": [
            {
                "parameters": {"setpoint_sp": 500000.0},
                "snowball_simulator": {"base_shares": 300000},
            }
        ],
    }

    # 1. 預設穩健複利 (Yield 5.66%, Net 78, Div 70)
    live_steady = {
        "price": 15.20,
        "annual_dividend": 0.86,
        "tax_retention": 0.9923,
        "scores": {"netScore": 78, "divScore": 70},
        "southbound_2d_net": 1000.0,
    }
    res_steady = patrol.evaluate_ticker_posture(mock_cards, live_steady)
    assert res_steady["posture_key"] == "STEADY_REINVEST"
    assert res_steady["priority"] == 5
    assert res_steady["goal_progress_pct"] == pytest.approx(51.2, 0.1)

    # 2. 優先級 1：高息陷阱斷路 (Yield >= 8.0%, 但 netScore < 50)
    live_trap = {
        "price": 10.00,  # yield = 0.86 / 10 = 8.6%
        "annual_dividend": 0.86,
        "tax_retention": 0.9923,
        "scores": {"netScore": 45, "divScore": 38},
        "southbound_2d_net": 500.0,
    }
    res_trap = patrol.evaluate_ticker_posture(mock_cards, live_trap)
    assert res_trap["posture_key"] == "TRAP_ALERT"
    assert res_trap["priority"] == 1
    assert "強制關閉加碼閥門" in res_trap["valve_action"]

    # 3. 優先級 2：流速過快斷路 (南向流出 < -8000)
    live_velocity = {
        "price": 15.20,
        "annual_dividend": 0.86,
        "tax_retention": 0.9923,
        "scores": {"netScore": 75, "divScore": 70},
        "southbound_2d_net": -9500.0,
    }
    res_velocity = patrol.evaluate_ticker_posture(mock_cards, live_velocity)
    assert res_velocity["posture_key"] == "VELOCITY_PAUSE"
    assert res_velocity["priority"] == 2
    assert "暫緩大額市價單買進" in res_velocity["valve_action"]

    # 4. 優先級 3：積極進攻 (Yield >= 8.2%, netScore >= 70, divScore >= 60)
    live_agg = {
        "price": 10.20,  # yield = 0.86 / 10.2 = 8.43%
        "annual_dividend": 0.86,
        "tax_retention": 0.9923,
        "scores": {"netScore": 82, "divScore": 75},
        "southbound_2d_net": 2000.0,
    }
    res_agg = patrol.evaluate_ticker_posture(mock_cards, live_agg)
    assert res_agg["posture_key"] == "AGGRESSIVE_ACCUMULATE"
    assert res_agg["priority"] == 3
    assert "股息 100% 立即再投入" in res_agg["valve_action"]

    # 5. 優先級 4：過熱防禦 (Yield <= 4.8%)
    live_overvalued = {
        "price": 18.50,  # yield = 0.86 / 18.5 = 4.65%
        "annual_dividend": 0.86,
        "tax_retention": 0.9923,
        "scores": {"netScore": 60, "divScore": 60},
        "southbound_2d_net": 100.0,
    }
    res_overvalued = patrol.evaluate_ticker_posture(mock_cards, live_overvalued)
    assert res_overvalued["posture_key"] == "OVERVALUED_HOLD"
    assert res_overvalued["priority"] == 4
    assert "停止加碼買進" in res_overvalued["valve_action"]


def test_patrol_report_and_mbe_output(repo_root):
    mock_macro = {
        "lpr": {"1Y": 3.0, "5Y": 3.5},
        "chinabond_yield": {"10Y": 1.648},
        "fx": {"USDCNH": {"price": 6.6853}},
        "shipping_freight": {"scfi": {"latest_index": 3679.58, "change": 15.47}},
    }

    report = patrol.run_portfolio_patrol(
        repo_root=repo_root,
        mock_macro=mock_macro,
    )

    assert "timestamp" in report
    assert "fleet" in report
    assert len(report["fleet"]) >= 1

    # 測試 ASCII 與 Markdown 格式化
    ascii_out = patrol.format_ascii_dashboard(report)
    assert "投資組合艦隊全標的每日總裁戰報" in ascii_out
    assert "00882" in ascii_out

    md_out = patrol.format_markdown_briefing(report)
    assert "# 投資組合每日總裁戰報" in md_out
    assert "## 🚨 今日焦點與戰術指引（例外管理 MBE）" in md_out
    assert "## 📊 資產艦隊目標控制迴路與戰術矩陣" in md_out

    # 鐵律驗證：戰報絕對不能洩露個人持股張數 (300,000 / 300 張) 或 成本/本金金額
    assert "300,000" not in md_out
    assert "300張" not in md_out
    assert "本金" not in md_out
    assert "總成本" not in md_out


def test_build_patrol_commit_message(repo_root):
    mock_macro = {
        "lpr": {"1Y": 3.0, "5Y": 3.5},
        "chinabond_yield": {"10Y": 1.648},
        "fx": {"USDCNH": {"price": 6.6853}},
        "shipping_freight": {"scfi": {"latest_index": 3679.58, "change": 15.47}},
    }

    report = patrol.run_portfolio_patrol(
        repo_root=repo_root,
        mock_macro=mock_macro,
    )

    msg = patrol.build_patrol_commit_message(report, agent="Antigravity")
    first_line = msg.splitlines()[0]
    assert len(first_line) <= 50
    assert first_line.startswith("patrol(fleet):")
    assert "## 核心變更" in msg
    assert "## 變更理由" in msg
    assert "## 驗證" in msg
    assert "## Session-Sync" in msg

    # 驗證透過 committer 檢查無誤
    committer_path = repo_root / ".claude" / "skills" / "fin-commit" / "scripts"
    if str(committer_path) not in sys.path:
        sys.path.insert(0, str(committer_path))
    import committer as c  # type: ignore
    errors, _ = c.validate_message(msg)
    assert errors == []
