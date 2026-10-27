"""單標的深潛運算與滾雪球複利模擬模組 (Patrol Inspector & Snowball Simulator)。

負責單一標的深入評估（包含個人持股張數、目標控制偏差 Error、補足缺口所需本金與 C 引擎複利滾雪球年限模擬）。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from patrol_cards import load_cards
from patrol_evaluator import evaluate_ticker_posture, fetch_ticker_live_data


def simulate_snowball(
    shares: float,
    annual_div: float,
    tax_retention: float,
    price: float,
    target_income: float = 500000.0,
    annual_dca_twd: float = 0.0,
    max_years: int = 30,
) -> Tuple[float, List[Dict[str, Any]]]:
    """C 引擎：股息再投入複利滾雪球時間線模擬。"""
    timeline: List[Dict[str, Any]] = []
    current_shares = shares

    for year in range(1, max_years + 1):
        # 假設每年配息兩次（各 50%）
        semi_div = (annual_div * current_shares * tax_retention) / 2.0
        # 兩次再投入
        reinvested_shares = (semi_div * 2.0 + annual_dca_twd) / price if price > 0 else 0.0
        current_shares += reinvested_shares
        projected_income = current_shares * annual_div * tax_retention

        timeline.append({
            "year": year,
            "shares": round(current_shares),
            "projected_income": round(projected_income),
            "is_goal_met": projected_income >= target_income,
        })

        if projected_income >= target_income:
            # 內插推算具體年數
            return round(year - 0.5 if (projected_income - semi_div) >= target_income else float(year), 1), timeline

    return float(max_years), timeline


def inspect_ticker(
    ticker: str,
    repo_root: Path,
    shares: Optional[float] = None,
    price_override: Optional[float] = None,
    dca: float = 0.0,
    custom_models_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """執行單標的個人深潛求值運算。"""
    models_root = custom_models_dir if custom_models_dir else repo_root / "models"
    cards = load_cards(models_root, ticker)
    ticker_spec = cards.get("ticker", {})
    title = ticker_spec.get("title", f"{ticker} 模型標的")

    # 讀取迴路設定
    loops = cards.get("loops", [])
    first_loop = loops[0] if loops else {}
    loop_params = first_loop.get("parameters", {})
    setpoint_sp = float(loop_params.get("setpoint_sp", 500000.0))
    snowball_cfg = first_loop.get("snowball_simulator", {})

    base_shares = float(snowball_cfg.get("base_shares", 300000.0))
    eval_shares = shares if shares is not None else base_shares

    # 即時行情
    live_data = fetch_ticker_live_data(ticker, cards, repo_root)
    if price_override is not None and price_override > 0:
        live_data["price"] = price_override
        live_data["source_notes"] = f"手動指定 (--price {price_override})"

    price = live_data["price"]
    annual_div = live_data["annual_dividend"]
    tax_retention = live_data["tax_retention"]
    scores = live_data.get("scores", {})

    # 姿態判定 (BLS)
    posture_res = evaluate_ticker_posture(cards, live_data)
    current_yield = annual_div / price if price > 0 else 0.0

    # 控制迴路誤差運算 (SP, PV, Error)
    current_pv = eval_shares * annual_div * tax_retention
    error = max(0.0, setpoint_sp - current_pv)
    achievement_rate = (current_pv / setpoint_sp) * 100.0 if setpoint_sp > 0 else 0.0
    capital_needed = (error / current_yield) if current_yield > 0 else 0.0
    shares_needed = capital_needed / price if price > 0 else 0.0

    # C 引擎複利滾雪球時間線
    years_to_goal, timeline = simulate_snowball(
        shares=eval_shares,
        annual_div=annual_div,
        tax_retention=tax_retention,
        price=price,
        target_income=setpoint_sp,
        annual_dca_twd=dca,
    )

    return {
        "ticker": ticker,
        "name": title,
        "sensors": {
            "current_price": price,
            "price_source": live_data.get("source_notes", "基準值"),
            "price_is_live": bool(live_data.get("price_is_live")),
            "scores": scores,
        },
        "loop_state": {
            "goal_title": first_loop.get("title", "50萬被動股利目標"),
            "setpoint_sp": setpoint_sp,
            "process_value_pv": round(current_pv),
            "system_error": round(error),
            "achievement_rate_pct": round(achievement_rate, 2),
            "current_shares": eval_shares,
            "annual_dividend": annual_div,
            "current_yield_pct": round(current_yield * 100, 2),
            "capital_needed_twd": round(capital_needed),
            "shares_needed_boards": round(shares_needed / 1000.0, 1),
        },
        "interlock_state": {
            "posture_key": posture_res["posture_key"],
            "posture_label": posture_res["posture_label"],
            "posture_name": posture_res["posture_name"],
            "valve_action": posture_res["valve_action"],
        },
        "snowball_simulation": {
            "years_to_goal": years_to_goal,
            "annual_dca_twd": dca,
            "timeline": timeline,
        },
    }


def format_inspect_ascii(report: Dict[str, Any]) -> str:
    """格式化個人深潛終端儀表板。"""
    lines = []
    lines.append("=" * 72)
    lines.append(f"  🔍 【{report['name']}】目標控制迴路與個人深度試算")
    lines.append(f"  報價來源: {report['sensors']['price_source']}")
    lines.append("-" * 72)

    loop = report["loop_state"]
    sensors = report["sensors"]
    scores = sensors.get("scores", {})
    interlock = report["interlock_state"]
    snowball = report["snowball_simulation"]

    lines.append(f"🎯 [{loop['goal_title']}]")
    lines.append(f"  • 目標值 (SP) : {loop['setpoint_sp']:>10,.0f} TWD/年")
    lines.append(f"  • 測量值 (PV) : {loop['process_value_pv']:>10,.0f} TWD/年 (達成率: {loop['achievement_rate_pct']:.2f}%)")
    lines.append(f"  • 系統偏差 (E): {loop['system_error']:>10,.0f} TWD/年")
    lines.append(f"  • 當前試算規模: {loop['current_shares']/1000:.1f} 張 ({loop['current_shares']:,.0f} 股)")
    lines.append(f"  • 補足缺口本金: 約 {loop['capital_needed_twd']:,.0f} TWD (約需追加 {loop['shares_needed_boards']:.1f} 張)")
    lines.append("-" * 72)

    lines.append("📊 [底層感測與量化指標]")
    lines.append(f"  • 即時現價    : {sensors['current_price']:.2f} TWD")
    lines.append(f"  • 底層模型配息: {loop['annual_dividend']:.2f} TWD/股")
    lines.append(f"  • 模型殖利率  : {loop['current_yield_pct']:.2f}%")
    lines.append(f"  • 情報庫評分  : netScore {scores.get('netScore', '-')} ｜ divScore {scores.get('divScore', '-')} ｜ valScore {scores.get('valScore', '-')}")
    lines.append("-" * 72)

    lines.append("🛡️ [風控互鎖狀態與策略狀態]")
    lines.append(f"  • 當前策略狀態: {interlock['posture_label']} ({interlock['posture_name']})")
    lines.append(f"  • 執行動作指引: {interlock['valve_action']}")
    lines.append("-" * 72)

    lines.append("⏳ [複利滾雪球時間線 (C 引擎)]")
    if snowball["annual_dca_twd"] > 0:
        lines.append(f"  • 在當前策略 + 每年額外加碼 {snowball['annual_dca_twd']:,.0f} TWD 下：")
    else:
        lines.append("  • 在當前策略 + 純股利再投入 (零額外本金) 下：")
    lines.append(f"  • 預估達成「年被動股利 {loop['setpoint_sp']:,.0f} 萬」所需時間: 約 【{snowball['years_to_goal']}】 年")
    lines.append("=" * 72)

    return "\n".join(lines)
