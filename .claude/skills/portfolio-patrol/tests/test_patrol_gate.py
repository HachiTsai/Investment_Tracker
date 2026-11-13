import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import patrol_gate as pg  # noqa: E402

CORE = ["00406A", "00882", "00918", "00919", "00954", "00955", "00985A", "1216", "2356"]
GATE = {"zero_tolerance": ["00882", "00406A"], "general_max_anomalies": 2, "max_age_days": 7}
DAY = "2026-11-13"


def _item(code, strategy="DIVIDEND_INCOME", yield_pct=6.5, stale=False, price=10.0, posture="🔵 穩健複利", scores=None):
    return {
        "ticker": code,
        "strategy_type": strategy,
        "yield_pct": yield_pct,
        "price": price,
        "posture_label": posture,
        "scores": {"total": 60} if scores is None else scores,
        "watchdog": {"status": "HEALTHY", "is_stale": stale, "days_ago": 0},
    }


def _healthy_patrol():
    """與 2026-11-13 實跑結構相同的 9 檔：4 檔收息、3 檔成長（殖利率為 None 屬正常）、2 檔個股。"""
    fleet = [
        _item("00406A"),
        _item("00882"),
        _item("00918"),
        _item("00919"),
        _item("00954", strategy="CAPITAL_GROWTH", yield_pct=None),
        _item("00955", strategy="CAPITAL_GROWTH", yield_pct=None),
        _item("00985A", strategy="CAPITAL_GROWTH", yield_pct=None),
        _item("1216", strategy="STOCK", yield_pct=3.85),
        _item("2356", strategy="STOCK", yield_pct=4.29),
    ]
    return {
        "date_str": f"{DAY}（週五）",
        "fleet": fleet,
        # 與 patrol.py 實際輸出相同：targets 為 dict 清單
        "targets": [{"ticker": x["ticker"], "title": x["ticker"], "price": x["price"]} for x in fleet],
        "trap_state": {x["ticker"]: {"run_date": DAY, "trap": False} for x in fleet},
        "macro_data": {"lpr": {"value": 3.0}, "fx": {"value": 6.67}},
    }


def _check(patrol, expected=CORE, gate=GATE):
    return pg.check_patrol_gate(patrol, expected, gate)


def test_healthy_patrol_passes():
    ok, reasons, warnings = _check(_healthy_patrol())
    assert ok and reasons == [] and warnings == []


def test_missing_core_holding_fails():
    p = _healthy_patrol()
    p["fleet"] = [x for x in p["fleet"] if x["ticker"] != "00918"]
    p["targets"] = [x["ticker"] for x in p["fleet"]]
    p["trap_state"].pop("00918")
    ok, reasons, _ = _check(p)
    assert not ok and any("缺少核心標的" in r and "00918" in r for r in reasons)


def test_extra_non_core_ticker_fails():
    p = _healthy_patrol()
    p["fleet"].append(_item("0050"))
    p["targets"].append("0050")
    p["trap_state"]["0050"] = {"run_date": DAY, "trap": False}
    ok, reasons, _ = _check(p)
    assert not ok and any("非核心" in r for r in reasons)


def test_zero_tolerance_stale_fails_even_alone():
    p = _healthy_patrol()
    p["fleet"][1]["watchdog"]["is_stale"] = True  # 00882
    ok, reasons, _ = _check(p)
    assert not ok and any("核心持股異常" in r and "00882" in r for r in reasons)


def test_zero_tolerance_missing_price_fails():
    p = _healthy_patrol()
    p["fleet"][0]["price"] = None  # 00406A
    ok, reasons, _ = _check(p)
    assert not ok and any("00406A" in r for r in reasons)


def test_general_budget_allows_two_rejects_three():
    p = _healthy_patrol()
    for i in (2, 3):  # 00918、00919 過舊：兩檔仍通過
        p["fleet"][i]["watchdog"]["is_stale"] = True
    ok, _, _ = _check(p)
    assert ok
    p["fleet"][4]["price"] = None  # 第三檔：超過上限
    ok, reasons, _ = _check(p)
    assert not ok and any("一般標的異常 3 檔" in r for r in reasons)


def test_dividend_strategy_without_yield_counts_as_anomaly():
    """收息標的缺殖利率時，高息陷阱無法判定，計為異常，不可靜默跳過。"""
    p = _healthy_patrol()
    p["fleet"][2]["yield_pct"] = None  # 00918 為 DIVIDEND_INCOME，一檔仍在上限內
    ok, _, _ = _check(p)
    assert ok
    p["fleet"][3]["yield_pct"] = None  # 00919 第二檔：仍在上限內
    p["fleet"][4]["price"] = None  # 00954 第三檔：超過上限，且訊息含異常項目
    ok, reasons, _ = _check(p)
    assert not ok and any("一般標的異常 3 檔" in r and "收息標的缺殖利率" in r for r in reasons)


def test_zero_tolerance_dividend_without_yield_fails():
    p = _healthy_patrol()
    p["fleet"][1]["yield_pct"] = None  # 00882 為收息核心持股
    ok, reasons, _ = _check(p)
    assert not ok and any("核心持股異常" in r and "00882" in r and "收息標的缺殖利率" in r for r in reasons)


def test_growth_strategy_without_yield_is_normal():
    ok, _, _ = _check(_healthy_patrol())
    assert ok  # 00954 等成長型 yield 為 None 不屬異常


def test_trap_state_date_mismatch_fails():
    p = _healthy_patrol()
    p["trap_state"]["2356"]["run_date"] = "2026-11-12"
    ok, reasons, _ = _check(p)
    assert not ok and any("資料日" in r for r in reasons)


def test_empty_fleet_fails():
    p = {"date_str": f"{DAY}（週五）", "fleet": [], "targets": [], "trap_state": {}}
    ok, reasons, _ = _check(p)
    assert not ok and any("fleet 為空" in r for r in reasons)


def test_macro_gap_is_warning_only():
    p = _healthy_patrol()
    p["macro_data"]["lpr"] = None
    ok, reasons, warnings = _check(p)
    assert ok and any("總經資料缺：lpr" in w for w in warnings)


def test_zero_tolerance_must_be_subset_of_core():
    gate = dict(GATE, zero_tolerance=["00882", "9999"])
    ok, reasons, _ = _check(_healthy_patrol(), gate=gate)
    assert not ok and any("不在核心清單內" in r for r in reasons)


def test_load_gate_fails_closed_on_bad_file(tmp_path):
    bad = tmp_path / "g.json"
    bad.write_text(json.dumps({"zero_tolerance": [], "general_max_anomalies": 2, "max_age_days": 7}), encoding="utf-8")
    with pytest.raises(ValueError):
        pg.load_gate(bad)
    with pytest.raises(OSError):
        pg.load_gate(tmp_path / "missing.json")


def test_repo_config_zero_tolerance_is_core_in_repo():
    """設定檔宣告的零容忍標的必須是 repo 裡 tier: core 的卡片（漂移檢查）。"""
    from patrol_cards import discover_tickers

    gate = pg.load_gate()
    core = discover_tickers(pg.MODELS_DIR, filter_tier="core")
    assert set(gate["zero_tolerance"]) <= set(core)


def test_cli_returns_1_on_missing_patrol_file(tmp_path, capsys):
    rc = pg.main([str(tmp_path / "nope.json")])
    assert rc == 1
    assert "讀取 patrol.json 失敗" in capsys.readouterr().err


def test_cli_returns_0_for_healthy_file_against_repo_models(tmp_path):
    """以 repo 的 models/ 產生期望清單；合成的健康 patrol 須在 repo 實際核心清單下才會通過。"""
    from patrol_cards import discover_tickers

    p = _healthy_patrol()
    core = discover_tickers(pg.MODELS_DIR, filter_tier="core")
    fleet_codes = {x["ticker"] for x in p["fleet"]}
    if set(core) != fleet_codes:
        pytest.skip("repo 核心清單已變動，合成 fixture 不再對應；請更新 fixture")
    f = tmp_path / "patrol.json"
    f.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    assert pg.main([str(f)]) == 0
