"""DCS 建模卡片自動生成模組 (ETF Model Card Scaffolder)。

為指定 ETF 自動建立符合 DCS 控制系統規範的 models/<ticker>/cards/ 卡片架構。
"""

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional


def detect_strategy_type(name: str, full_name: str, category: str) -> str:
    """依據標的名稱與類型自動推導策略資產類別。"""
    combined = f"{name} {full_name} {category}"
    if any(k in combined for k in ("債", "債券", "美債", "公債", "公司債")):
        return "BOND_DEFENSE"
    if any(k in combined for k in ("反1", "反向", "正2", "槓桿", "期貨")) or name.startswith("期"):
        return "HEDGING_OR_DERIVATIVE"
    if any(k in combined for k in ("高息", "高股息", "息收", "紅利", "優息", "配息")):
        return "DIVIDEND_INCOME"
    return "CAPITAL_GROWTH"


# 高息陷阱門檻的單一來源（與巡檢程式 patrol_evaluator 共用同一份參數檔）
INTERLOCK_RULES_PATH = Path(__file__).resolve().parents[2] / "portfolio-patrol" / "references" / "interlock_rules.json"


def load_interlock_rules(path: Path = INTERLOCK_RULES_PATH) -> Dict[str, Any]:
    """讀取互鎖門檻參數檔。"""
    return json.loads(path.read_text(encoding="utf-8"))


def render_interlock_yml(code: str, rules: Optional[Dict[str, Any]] = None) -> str:
    """依參數檔產生高息陷阱互鎖卡片；卡片不寫死門檻，避免與巡檢程式分叉。"""
    trap = (rules or load_interlock_rules())["yield_trap"]
    return f"""id: card:interlock:yield_trap
type: interlock
schema_version: 1.0.0
target_ticker: "{code}"
description: "高息陷阱互鎖：殖利率與多空、股利評分雙條件"
rule_source: "portfolio-patrol/references/interlock_rules.json"
trigger_rule: "IF yield_pct >= {trap['yield_min'] * 100:.1f} AND (netScore < {trap['net_score_below']} OR divScore < {trap['div_score_below']}) THEN TRAP_WATCH；次一交易日仍成立則 TRAP_ALERT"
valve_action: "{trap['valve_action']}"
"""


def scaffold_etf_model(
    ticker: str,
    repo_root: Path,
    holdings_data: Dict[str, Any],
    etf_info: Optional[Dict[str, Any]] = None,
    custom_models_dir: Optional[Path] = None,
    tier: str = "pool",
    strategy_type: Optional[str] = None,
) -> Path:
    """自動為 ETF 建立或更新 models/<ticker>/cards/ 標準卡片庫。"""
    code = ticker.strip().upper()
    models_root = custom_models_dir or (repo_root / "models")
    target_cards_dir = models_root / code / "cards"
    target_cards_dir.mkdir(parents=True, exist_ok=True)

    info = etf_info or {}
    name = info.get("name") or holdings_data.get("name") or code
    full_name = info.get("full_name") or name
    manager = info.get("manager") or "投信發行"
    benchmark = info.get("benchmark") or "對應指數"
    cat_str = info.get("category") or "ETF"

    strat = strategy_type or detect_strategy_type(name, full_name, cat_str)

    # 1. 產生 ticker.yml
    ticker_yml = f"""id: card:ticker:{code}
type: ticker
schema_version: 1.0.0
ticker: "{code}"
title: "{name}"
full_name: "{full_name}"
tier: {tier}
currency: TWD
exchange: TWSE
category: ETF
strategy_type: {strat}
manager: "{manager}"
benchmark: "{benchmark}"
last_model_update: "{date.today().isoformat()}"
"""
    (target_cards_dir / "ticker.yml").write_text(ticker_yml, encoding="utf-8")

    # 2. 產生 constituents.jsonl
    constituents = holdings_data.get("constituents", [])
    lines = []
    for c in constituents:
        record = {
            "ticker": c["symbol"],
            "name": c["name"],
            "weight_pct": c["weight_pct"],
            "shares": c.get("shares", 0),
        }
        lines.append(json.dumps(record, ensure_ascii=False))

    (target_cards_dir / "constituents.jsonl").write_text(
        "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )

    # 3. 產生 loop_dividend_500k.yml (僅高息/收息型 ETF 適用)
    if strat == "DIVIDEND_INCOME":
        loop_yml = f"""id: card:loop:passive_income_500k
type: control_loop
schema_version: 1.0.0
target_ticker: "{code}"
description: "50 萬被動股利目標收斂迴路"
setpoint_dividend_twd: 500000
control_strategy: "reinvest_and_dca"
"""
        (target_cards_dir / "loop_dividend_500k.yml").write_text(loop_yml, encoding="utf-8")

    # 4. 產生 interlock_yield_trap.yml (槓桿衍生型除外)，門檻由參數檔產生
    if strat != "HEDGING_OR_DERIVATIVE":
        (target_cards_dir / "interlock_yield_trap.yml").write_text(render_interlock_yml(code), encoding="utf-8")

    return target_cards_dir
