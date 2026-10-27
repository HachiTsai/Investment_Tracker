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

    # 4. 產生 interlock_yield_trap.yml (槓桿衍生型除外)
    if strat != "HEDGING_OR_DERIVATIVE":
        interlock_yml = f"""id: card:interlock:yield_trap
type: interlock
schema_version: 1.0.0
target_ticker: "{code}"
description: "高息陷阱與成分股集中度防禦互鎖"
trigger_rule: "IF yield_pct > 12.0 AND dividend_sustainability < 40 THEN alert"
valve_action: "暫停額外單筆加碼，維持例行再投入"
"""
        (target_cards_dir / "interlock_yield_trap.yml").write_text(interlock_yml, encoding="utf-8")

    return target_cards_dir
