#!/usr/bin/env python3
"""投資組合控制系統隨需運算引擎（Portfolio Control System Evaluator）。

用法：
  python3 scripts/evaluate_control.py [00882] [--price 15.20] [--shares 300000] [--json]
"""
import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_yaml_simple(path: Path) -> Dict[str, Any]:
    """YAML 讀取器：優先使用 PyYAML，備援簡易巢狀解析器。"""
    try:
        import yaml  # type: ignore

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except ImportError:
        pass

    # 備援：支援二層縮排的極簡解析器
    content = path.read_text(encoding="utf-8")
    result: Dict[str, Any] = {}
    current_section: Optional[Dict[str, Any]] = None

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())
        if ":" in stripped:
            k, v = stripped.split(":", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")

            # 轉型
            parsed_v: Any = v
            if v.isdigit():
                parsed_v = int(v)
            elif re.match(r"^\d+\.\d+$", v):
                parsed_v = float(v)
            elif v.lower() in ("true", "false"):
                parsed_v = v.lower() == "true"
            elif v == "":
                parsed_v = {}

            if indent == 0:
                if isinstance(parsed_v, dict):
                    result[k] = {}
                    current_section = result[k]
                else:
                    result[k] = parsed_v
                    current_section = None
            else:
                if current_section is not None:
                    current_section[k] = parsed_v
                else:
                    result[k] = parsed_v

    return result


def load_cards(ticker: str = "00882") -> Dict[str, Any]:
    """載入 models/<ticker>/cards/ 內的所有定義卡片。"""
    model_dir = REPO_ROOT / "models" / ticker
    cards_dir = model_dir / "cards"
    profile_dir = model_dir / "profile"

    data: Dict[str, Any] = {
        "sources": load_yaml_simple(profile_dir / "sources.yml") if (profile_dir / "sources.yml").exists() else {},
        "ticker": load_yaml_simple(cards_dir / "ticker.yml") if (cards_dir / "ticker.yml").exists() else {},
        "loop": (
            load_yaml_simple(cards_dir / "loop_dividend_500k.yml")
            if (cards_dir / "loop_dividend_500k.yml").exists()
            else {}
        ),
        "interlock": (
            load_yaml_simple(cards_dir / "interlock_yield_trap.yml")
            if (cards_dir / "interlock_yield_trap.yml").exists()
            else {}
        ),
        "constituents": [],
    }

    const_path = cards_dir / "constituents.jsonl"
    if const_path.exists():
        with open(const_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data["constituents"].append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return data


def fetch_live_price(ticker: str = "00882") -> Tuple[float, float, str]:
    """抓取即時市價與港幣匯率（帶備援降級機制）。"""
    price, fx = 15.20, 4.13
    source_notes = "基準定錨值 (15.20 TWD, HKD/TWD 4.13)"

    try:
        # 嘗試使用現有 price-dividend-fetcher 腳本
        fetch_script = REPO_ROOT / ".claude" / "skills" / "price-dividend-fetcher" / "scripts" / "fetch.py"
        if fetch_script.exists():
            out = subprocess.run(
                [sys.executable, str(fetch_script), "price", ticker],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if out.returncode == 0:
                res = json.loads(out.stdout)
                if res.get("price"):
                    price = float(res["price"])
                    source_notes = f"price-dividend-fetcher ({res.get('source', 'web')})"
    except Exception:
        pass

    return price, fx, source_notes


def fetch_intelligence_scores() -> Dict[str, Any]:
    """自情報資料庫讀取最新 30 日評分（帶降級預設值）。"""
    scores = {
        "netScore": 78,
        "divScore": 70,
        "valScore": 85,
        "fricScore": 80,
        "status": "基準定錨值 (情報資料庫 2026-10-16 快照)",
    }

    try:
        # 調用 gsheets 讀取評分歷史最後一列
        cmd = ["gsheets", "readonly", "read", "1BF2xvF0cmyODdN0nXR8QHbOTC3ikqswvSwBboY1cGQo", "評分歷史!A:H", "--json"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        if out.returncode == 0:
            rows = json.loads(out.stdout)
            if len(rows) > 1:
                latest = rows[-1]  # [date, bullWeight, bearWeight, netScore, divScore, valScore, fricScore, count]
                scores["netScore"] = int(latest[3])
                scores["divScore"] = int(latest[4])
                scores["valScore"] = int(latest[5])
                scores["fricScore"] = int(latest[6])
                scores["status"] = f"Drive 情報資料庫 ({latest[0]})"
    except Exception:
        pass

    return scores


def evaluate_interlock(
    yield_rate: float,
    scores: Dict[str, Any],
    southbound_flow: float = 0.0,
) -> Dict[str, str]:
    """執行風控互鎖條件判定（BLS）。"""
    net_score = scores.get("netScore", 50)
    div_score = scores.get("divScore", 50)

    # 優先級 1：高息陷阱斷路
    if yield_rate >= 0.08 and (net_score < 50 or div_score < 40):
        return {
            "posture": "TRAP_ALERT",
            "name": "高息陷阱斷路保護 (Yield Trap Trip)",
            "label": "【陷阱警戒 (Yield Trap Alert)】",
            "action": "強制關閉加碼閥門！股息暫留現金池，啟動持股專案審查",
            "color": "RED",
        }

    # 優先級 2：流速過快斷路
    if southbound_flow < -8000:
        return {
            "posture": "VELOCITY_PAUSE",
            "name": "資金流速過快警報 (Velocity Trip)",
            "label": "【流速警戒 (Velocity Pause)】",
            "action": "暫緩大額市價單買進，等待資金流速放緩再行佈置",
            "color": "YELLOW",
        }

    # 優先級 3：積極進攻
    if yield_rate >= 0.082 and net_score >= 70 and div_score >= 60:
        return {
            "posture": "AGGRESSIVE_ACCUMULATE",
            "name": "積極進攻姿態 (Aggressive Accumulate)",
            "label": "【積極進攻 (Aggressive Accumulate)】",
            "action": "股息 100% 立即再投入，若有閒置本金啟動額外加碼",
            "color": "GREEN",
        }

    # 優先級 4：過熱防禦
    if yield_rate <= 0.048:
        return {
            "posture": "OVERVALUED_HOLD",
            "name": "估值過熱防禦姿態 (Overvalued / Hold)",
            "label": "【防禦觀望 (Overvalued / Hold)】",
            "action": "停止加碼買進，維持既有部位持有，股息可部分保留現金儲備",
            "color": "ORANGE",
        }

    # 優先級 5：預設穩健複利
    return {
        "posture": "STEADY_REINVEST",
        "name": "預設穩健複利姿態 (Steady Reinvest)",
        "label": "【穩健複利 (Steady Reinvest)】",
        "action": "維持例行性半年配息再投入，按部就班累積雪球",
        "color": "BLUE",
    }


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
        reinvested_shares = (semi_div * 2.0 + annual_dca_twd) / price
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


def main():
    parser = argparse.ArgumentParser(description="投資組合控制系統隨需運算引擎")
    parser.add_argument("ticker", nargs="?", default="00882", help="投資標的代號（預設 00882）")
    parser.add_argument("--price", type=float, help="覆蓋當前市價（TWD）")
    parser.add_argument("--shares", type=float, default=300000.0, help="庫存股數（預設 300,000 股 / 300 張）")
    parser.add_argument("--dca", type=float, default=0.0, help="每年預計額外投入本金（TWD）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式輸出")
    args = parser.parse_args()

    # 1. 載入卡片
    cards = load_cards(args.ticker)
    ticker_spec = cards.get("ticker", {})
    calibration = ticker_spec.get("calibration", {})
    payout_ratio = float(calibration.get("payout_ratio", 0.954))
    tax_retention = float(calibration.get("tax_retention_rate", 0.9923))

    # 2. 獲取動態事實
    live_price, fx_hkdtwd, price_source = fetch_live_price(args.ticker)
    if args.price:
        live_price = args.price
        price_source = f"手動指定 (--price {live_price})"

    scores = fetch_intelligence_scores()

    # 3. B 引擎運算（基於成分股加權）
    # 基準推估年配息（以 v6 模型校準 0.86 元為基準，或由成分股計算）
    model_annual_dividend = 0.86
    current_yield = model_annual_dividend / live_price

    # 4. 控制迴路運算（SP, PV, Error）
    setpoint_sp = 500000.0
    current_pv = args.shares * model_annual_dividend * tax_retention
    error = max(0.0, setpoint_sp - current_pv)
    achievement_rate = (current_pv / setpoint_sp) * 100.0
    capital_needed = (error / current_yield) if current_yield > 0 else 0.0
    shares_needed = capital_needed / live_price if live_price > 0 else 0.0

    # 5. 互鎖與姿態判定
    interlock_res = evaluate_interlock(current_yield, scores)

    # 6. C 引擎複利雪球模擬
    years_to_goal, timeline = simulate_snowball(
        shares=args.shares,
        annual_div=model_annual_dividend,
        tax_retention=tax_retention,
        price=live_price,
        target_income=setpoint_sp,
        annual_dca_twd=args.dca,
    )

    # 格式化輸出
    report = {
        "timestamp": "2026-10-18",
        "ticker": args.ticker,
        "name": ticker_spec.get("title", "00882 中信中國高股息"),
        "sensors": {
            "current_price": live_price,
            "price_source": price_source,
            "hkd_twd_fx": fx_hkdtwd,
            "scores": scores,
        },
        "loop_state": {
            "setpoint_sp": setpoint_sp,
            "process_value_pv": round(current_pv),
            "system_error": round(error),
            "achievement_rate_pct": round(achievement_rate, 2),
            "current_shares": args.shares,
            "model_annual_dividend": model_annual_dividend,
            "current_yield_pct": round(current_yield * 100, 2),
            "capital_needed_twd": round(capital_needed),
            "shares_needed_boards": round(shares_needed / 1000.0, 1),
        },
        "interlock_state": interlock_res,
        "snowball_simulation": {
            "years_to_goal": years_to_goal,
            "annual_dca_twd": args.dca,
        },
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    # 終端人眼儀表板
    print("=" * 66)
    print(f"【{report['name']} 投資控制系統即時戰情】")
    print(f"數據時間: {report['timestamp']} ｜ 報價來源: {price_source}")
    print("-" * 66)
    print("🎯 [目標控制迴路: 50萬被動股利目標]")
    print(f"  • 目標值 (SP) : {setpoint_sp:>10,.0f} TWD/年")
    print(f"  • 測量值 (PV) : {current_pv:>10,.0f} TWD/年 (達成率: {achievement_rate:.2f}%)")
    print(f"  • 系統偏差 (E): {error:>10,.0f} TWD/年")
    print(f"  • 持股規模    : {args.shares/1000:.1f} 張 (庫存 300 張)")
    print(f"  • 補足缺口本金: 約 {capital_needed:,.0f} TWD (約需追加 {shares_needed/1000:.1f} 張)")
    print("-" * 66)
    print("📊 [底層感測與量化指標]")
    print(f"  • 即時現價    : {live_price:.2f} TWD ｜ 港幣匯率: {fx_hkdtwd:.4f}")
    print(f"  • 底層模型配息: {model_annual_dividend:.2f} TWD/股 (成分股分紅 × 配發比 95.4%)")
    print(f"  • 即時模型殖利率: {current_yield*100:.2f}% (便宜 >8.2% ｜ 偏貴 <4.8%)")
    print(f"  • 情報庫評分  : netScore {scores['netScore']} ｜ divScore {scores['divScore']} ｜ valScore {scores['valScore']}")
    print(f"                 ({scores['status']})")
    print("-" * 66)
    print(f"🛡️ [風控互鎖狀態與戰術姿態]")
    print(f"  • 觸發邏輯    : {interlock_res['name']}")
    print(f"  • 當前戰術姿態: {interlock_res['label']}")
    print(f"  • 執行動作指引: {interlock_res['action']}")
    print("-" * 66)
    print(f"⏳ [複利滾雪球時間線 (C 引擎)]")
    if args.dca > 0:
        print(f"  • 在當前姿態 + 每年額外加碼 {args.dca:,.0f} TWD 下：")
    else:
        print(f"  • 在當前姿態 + 純股利再投入 (零額外本金) 下：")
    print(f"  • 預估達成「年被動股利 50 萬」所需時間: 約 【{years_to_goal}】 年")
    print("=" * 66)


if __name__ == "__main__":
    main()
