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


@pytest.fixture
def offline_live_data(monkeypatch):
    """以假行情取代逐檔連網抓價與基本面，讓整份巡檢流程可離線快速執行。"""
    import patrol_evaluator as ev

    scores = {"netScore": 75.0, "divScore": 70.0, "valScore": 75.0, "fricScore": 80.0}
    monkeypatch.setattr(ev, "fetch_ticker_live_data", lambda t, c, r: {
        "price": 15.20 if t == "00882" else 10.00, "annual_dividend": 0.86, "tax_retention": 0.9923,
        "source_notes": "測試假資料", "scores": dict(scores), "southbound_2d_net": 1250.0})
    monkeypatch.setattr(ev, "fetch_stock_live_data", lambda t, c, r: {
        "price": 50.0, "annual_dividend": 2.0, "tax_retention": 1.0, "source_notes": "測試假資料",
        "swing": None, "scores": dict(scores), "southbound_2d_net": 0.0})


def test_discover_tickers(repo_root):
    models_dir = repo_root / "models"
    tickers = patrol.discover_tickers(models_dir)
    assert "00882" in tickers

    # 測試過濾器
    filtered = patrol.discover_tickers(models_dir, filter_tickers=["00882"])
    assert filtered == ["00882"]

    empty_filtered = patrol.discover_tickers(models_dir, filter_tickers=["NON_EXISTENT"])
    assert empty_filtered == []


def test_discover_tickers_tier_filtering(tmp_path):
    models = tmp_path / "models"
    core_cards = models / "0050" / "cards"
    core_cards.mkdir(parents=True)
    (core_cards / "ticker.yml").write_text("ticker: '0050'\ntier: core\n", encoding="utf-8")

    legacy_cards = models / "0056" / "cards"
    legacy_cards.mkdir(parents=True)
    (legacy_cards / "ticker.yml").write_text("ticker: '0056'\n", encoding="utf-8")

    pool_cards = models / "00922" / "cards"
    pool_cards.mkdir(parents=True)
    (pool_cards / "ticker.yml").write_text("ticker: '00922'\ntier: pool\n", encoding="utf-8")

    core_res = patrol.discover_tickers(models)
    assert "0050" in core_res and "0056" in core_res
    assert "00922" not in core_res

    pool_res = patrol.discover_tickers(models, filter_tier="pool")
    assert pool_res == ["00922"]

    all_res = patrol.discover_tickers(models, filter_tier="all")
    assert sorted(all_res) == ["0050", "0056", "00922"]


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


def test_patrol_report_and_mbe_output(repo_root, offline_live_data):
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
    assert "投資組合全標的每日巡檢簡報" in ascii_out
    assert "00882" in ascii_out

    md_out = patrol.format_markdown_briefing(report)
    assert "# 投資組合每日巡檢簡報" in md_out
    assert "## 🚨 今日焦點與指引（例外管理 MBE）" in md_out
    assert "## 📊 投資組合目標達成進度與配置矩陣" in md_out

    # 鐵律驗證：簡報絕對不能洩露個人持股張數 (300,000 / 300 張) 或 成本/本金金額
    assert "300,000" not in md_out
    assert "300張" not in md_out
    assert "本金" not in md_out
    assert "總成本" not in md_out


def test_build_patrol_commit_message(repo_root, offline_live_data):
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


def test_simulate_snowball():
    # 測試複利滾雪球時間線
    years, timeline = patrol.simulate_snowball(
        shares=300000,
        annual_div=0.86,
        tax_retention=0.9923,
        price=15.20,
        target_income=500000.0,
    )
    assert 10 <= years <= 16
    assert len(timeline) >= 10
    assert timeline[-1]["is_goal_met"] is True


def test_inspect_ticker(repo_root):
    data = patrol.inspect_ticker(
        ticker="00882",
        repo_root=repo_root,
        shares=300000,
        price_override=15.20,
    )
    assert data["ticker"] == "00882"
    pv = data["loop_state"]["process_value_pv"]
    sp = data["loop_state"]["setpoint_sp"]
    assert pv > 0
    assert data["loop_state"]["achievement_rate_pct"] == pytest.approx((pv / sp) * 100.0, 0.1)

    ascii_out = patrol.format_inspect_ascii(data)
    assert "00882 中信中國高股息" in ascii_out
    assert "目標控制迴路與個人深度試算" in ascii_out
    assert "500,000 TWD/年" in ascii_out



def test_stock_card_patrol(repo_root, tmp_path, monkeypatch):
    import patrol_evaluator as ev

    card_dir = tmp_path / "models" / "9999" / "cards"
    card_dir.mkdir(parents=True)
    (card_dir / "ticker.yml").write_text(
        'id: card:ticker:9999\ncategory: STOCK\nsymbol: "9999.TW"\ncurrency: TWD\ncontribution:\n  lot_shares: 1000\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(ev, "fetch_stock_live_data", lambda t, c, r: {
        "price": 50.0, "annual_dividend": 5.0, "tax_retention": 1.0,
        "scores": {"netScore": 80, "divScore": 80, "valScore": 60, "fricScore": 90}, "southbound_2d_net": 0.0})
    res = ev.run_portfolio_patrol(repo_root, filter_tickers=["9999"], custom_models_dir=tmp_path / "models",
                                  mock_macro={})
    row = res["targets"][0]
    assert row["category"] == "STOCK"
    assert row["lot_contribution_pct"] == pytest.approx(1.0)  # 1000 股 × 5 元 ÷ 50 萬
    assert row["goal_progress_pct"] == 0.0


def test_stock_uses_swing_posture_not_yield_trap(repo_root, tmp_path, monkeypatch):
    """個股不套高息陷阱互鎖：殖利率 12% 但評分差，ETF 會陷阱警戒，個股依波段狀態判定並顯示含息報酬。"""
    import patrol_evaluator as ev
    import patrol_cards as pc

    card_dir = tmp_path / "models" / "9998" / "cards"
    card_dir.mkdir(parents=True)
    (card_dir / "ticker.yml").write_text(
        'id: card:ticker:9998\ncategory: STOCK\nsymbol: "9998.TW"\ncurrency: TWD\ncontribution:\n  lot_shares: 1000\n',
        encoding="utf-8",
    )
    swing = {"state": "OVERSOLD_WATCH", "returns_total": {"3M": -4.2, "1Y": 12.0}}
    monkeypatch.setattr(ev, "fetch_stock_live_data", lambda t, c, r: {
        "price": 50.0, "annual_dividend": 6.0, "tax_retention": 1.0, "swing": swing,
        "scores": {"netScore": 30, "divScore": 20, "valScore": 40, "fricScore": 50}, "southbound_2d_net": 0.0})
    res = ev.run_portfolio_patrol(repo_root, filter_tickers=["9998"], custom_models_dir=tmp_path / "models", mock_macro={})
    row = res["targets"][0]
    assert row["posture_key"] == "SWING_OVERSOLD_WATCH" and row["posture_key"] != "TRAP_ALERT"
    assert pc.format_yield_or_return(row) == "3M-4.2% 1Y+12.0%"


def test_stock_without_swing_is_no_data(repo_root):
    import patrol_evaluator as ev

    key, label, *_ = ev._stock_posture(None)
    assert key == "NO_DATA" and "資料不足" in label


def test_parallel_patrol_matches_sequential_order(repo_root, offline_live_data):
    """抓價並行不改變結果與順序（fleet 依標的順序、內容與單執行緒一致）。"""
    macro = {"fx": {}}
    seq = patrol.run_portfolio_patrol(repo_root=repo_root, mock_macro=macro, workers=1)
    par = patrol.run_portfolio_patrol(repo_root=repo_root, mock_macro=macro, workers=8)
    assert [f["ticker"] for f in seq["fleet"]] == [f["ticker"] for f in par["fleet"]]
    assert seq["fleet"] == par["fleet"] and seq["alerts"] == par["alerts"]


def test_growth_etf_zero_dividend_multi_track():
    """驗證零配息/成長型 ETF (如 00954, 00757) 走成長型專屬配置狀態，不誤判為過熱防禦，不產出虛假殖利率與 51.2% 達成率。"""
    import patrol_cards as pc
    mock_cards = {
        "ticker_id": "00954",
        "ticker": {
            "title": "中信日本半導體",
            "category": "ETF",
            "strategy_type": "CAPITAL_GROWTH",
            "currency": "TWD",
        },
        "loops": [],
    }
    live_growth = {
        "price": 16.40,
        "annual_dividend": 0.0,
        "tax_retention": 1.0,
        "scores": {"netScore": 75, "divScore": 70},
        "southbound_2d_net": 0.0,
        "swing": {"state": "NEUTRAL", "label": "⚪ 未觸發條件"},
    }
    res = patrol.evaluate_ticker_posture(mock_cards, live_growth)
    # 姿態應走成長型專屬配置狀態 (脫離與個股波段未觸發條件完全重複的現狀)
    assert res["posture_key"] == "GROWTH_NEUTRAL"
    assert res["posture_label"] == "🔵 常態配置"
    # 殖利率與達成率應為 None，格式化輸出應為 -
    assert res["yield_pct"] is None
    assert res["goal_progress_pct"] is None
    assert pc.format_yield_or_return(res) == "-"
    assert pc.format_progress(res) == "-"


def test_growth_etf_postures_mapping():
    """驗證成長型 ETF 各波段狀態映射到長線配置姿態。"""
    mock_cards = {
        "ticker_id": "0050",
        "ticker": {
            "title": "元大台灣50",
            "category": "ETF",
            "strategy_type": "CAPITAL_GROWTH",
            "currency": "TWD",
        },
        "loops": [],
    }

    states_to_test = {
        "UPTREND": ("GROWTH_UPTREND", "🔵 趨勢續抱", 5),
        "OVERSOLD_WATCH": ("GROWTH_OVERSOLD_WATCH", "🟢 回檔加碼", 3),
        "OVERHEATED": ("GROWTH_OVERHEATED", "🟠 乖離防禦", 4),
        "DOWNTREND": ("GROWTH_DOWNTREND", "⚪ 定額微笑", 5),
    }

    for state, (expected_key, expected_label, expected_pri) in states_to_test.items():
        live = {
            "price": 180.0,
            "annual_dividend": 0.0,
            "tax_retention": 1.0,
            "scores": {},
            "swing": {"state": state},
        }
        res = patrol.evaluate_ticker_posture(mock_cards, live)
        assert res["posture_key"] == expected_key
        assert res["posture_label"] == expected_label
        assert res["priority"] == expected_pri


def test_bond_defense_postures():
    """驗證債券防禦型 (BOND_DEFENSE) 脫離高股息門檻，依債券合理息收區間判定。"""
    mock_cards = {
        "ticker_id": "00687B",
        "ticker": {
            "title": "國泰20年美債",
            "category": "ETF",
            "strategy_type": "BOND_DEFENSE",
            "currency": "TWD",
        },
        "loops": [],
    }

    # 1. 殖利率 4.9% (>= 4.8%) -> 積極佈建
    live_accum = {
        "price": 30.0,
        "annual_dividend": 1.47,  # 1.47 / 30 = 4.9%
        "tax_retention": 1.0,
        "scores": {},
    }
    res_accum = patrol.evaluate_ticker_posture(mock_cards, live_accum)
    assert res_accum["posture_key"] == "BOND_ACCUMULATE"
    assert res_accum["posture_label"] == "🟢 積極佈建"
    assert res_accum["priority"] == 3

    # 2. 殖利率 4.2% (3.5% ~ 4.8%) -> 穩健配置 (不再被誤判為 4.8% 以下的 OVERVALUED_HOLD)
    live_steady = {
        "price": 30.0,
        "annual_dividend": 1.26,  # 1.26 / 30 = 4.2%
        "tax_retention": 1.0,
        "scores": {},
    }
    res_steady = patrol.evaluate_ticker_posture(mock_cards, live_steady)
    assert res_steady["posture_key"] == "STEADY_REINVEST"
    assert res_steady["posture_label"] == "🔵 穩健配置"
    assert res_steady["priority"] == 5

    # 3. 殖利率 3.2% (<= 3.5%) -> 防禦觀望
    live_over = {
        "price": 30.0,
        "annual_dividend": 0.96,  # 0.96 / 30 = 3.2%
        "tax_retention": 1.0,
        "scores": {},
    }
    res_over = patrol.evaluate_ticker_posture(mock_cards, live_over)
    assert res_over["posture_key"] == "BOND_OVERBOUGHT"
    assert res_over["posture_label"] == "🟡 防禦觀望"
    assert res_over["priority"] == 4


def test_load_yaml_simple_null_value(tmp_path):
    """驗證 load_yaml_simple 在備援簡易解析模式下能正確將 null 轉為 None 而非字串。"""
    import patrol_cards as pc
    sample_file = tmp_path / "sample.yml"
    sample_file.write_text(
        "id: test\ncontribution:\n  lot_shares: 1000\n  tax_retention_rate: null\n",
        encoding="utf-8",
    )
    data = pc.load_yaml_simple(sample_file)
    assert data["contribution"]["lot_shares"] == 1000
    assert data["contribution"]["tax_retention_rate"] is None


def test_fetch_ticker_live_data_price_fallback(monkeypatch):
    """驗證 fetch_ticker_live_data 在 both 逾時或失敗時，能透過 price 子命令降級取得現價。"""
    import json
    import subprocess
    from pathlib import Path
    import patrol_evaluator as pe

    def mock_subprocess_run(cmd, *args, **kwargs):
        # 模擬 both 逾時拋出例外
        if "both" in cmd:
            raise subprocess.TimeoutExpired(cmd, timeout=15)
        # 模擬 price 成功回傳真實市價
        if "price" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=json.dumps([{"ticker": "TPE:009805", "price": 14.38, "source": "Google Finance"}])
            )
        return subprocess.CompletedProcess(cmd, 1, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    cards_data = {"ticker": {"ticker": "009805", "strategy_type": "DIVIDEND_INCOME"}}
    repo_root = Path(__file__).resolve().parents[4]
    res = pe.fetch_ticker_live_data("009805", cards_data, repo_root)

    assert res["price"] == 14.38
    assert "live-price-fallback" in res["source_notes"]

