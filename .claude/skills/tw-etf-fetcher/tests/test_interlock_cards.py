"""高息陷阱互鎖卡片的漂移檢查：卡片內容須等於 interlock_rules.json 依 render_interlock_yml 的產出。

00882 為手寫的完整互鎖卡片（含滯後帶與優先序），不由參數檔產生，故排除在外。
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import etf_model_scaffolder  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]
MODELS = REPO_ROOT / "models"
HANDWRITTEN = {"00882"}

CARDS = sorted(p for p in MODELS.glob("*/cards/interlock_yield_trap.yml") if p.parent.parent.name not in HANDWRITTEN)


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.parent.parent.name)
def test_interlock_card_matches_rules_json(card):
    code = card.parent.parent.name
    assert card.read_text(encoding="utf-8") == etf_model_scaffolder.render_interlock_yml(code)


def test_scaffolder_writes_rendered_interlock_card(tmp_path):
    cards_dir = etf_model_scaffolder.scaffold_etf_model(
        "00999",
        tmp_path,
        {"constituents": []},
        etf_info={"name": "測試高息ETF"},
        custom_models_dir=tmp_path / "models",
        strategy_type="DIVIDEND_INCOME",
    )
    text = (cards_dir / "interlock_yield_trap.yml").read_text(encoding="utf-8")
    assert text == etf_model_scaffolder.render_interlock_yml("00999")


def test_render_reads_thresholds_from_rules():
    rules = json.loads(etf_model_scaffolder.INTERLOCK_RULES_PATH.read_text(encoding="utf-8"))
    rules["yield_trap"].update(yield_min=0.09, net_score_below=45, div_score_below=35, valve_action="測試處置")
    text = etf_model_scaffolder.render_interlock_yml("00999", rules)
    assert "IF yield_pct >= 9.0 AND (netScore < 45 OR divScore < 35)" in text
    assert 'valve_action: "測試處置"' in text
