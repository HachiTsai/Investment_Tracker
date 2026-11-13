#!/usr/bin/env python3
"""patrol.json 發布前門檻（fail-closed）。通過才可寫回 trap_state、才可發布。

用法：python3 patrol_gate.py <patrol.json> [--models-dir DIR]
退出碼：0 通過；1 未通過或讀取失敗（原因印在 stderr）。

- 門檻來源：references/publish_gate.json（與每日巡檢頁共用，單一來源）。
- 期望清單：models/*/cards 中 tier 為 core 的標的，與 patrol 的探索範圍相同，但由本程式獨立計算，
  不取自 patrol.json 本身，避免循環檢查。
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from patrol_cards import discover_tickers  # noqa: E402

REFS_DIR = SCRIPT_DIR.parent / "references"
GATE_PATH = REFS_DIR / "publish_gate.json"
REPO_ROOT = SCRIPT_DIR.parents[3]  # .claude/skills/portfolio-patrol/scripts → 專案根目錄
MODELS_DIR = REPO_ROOT / "models"


def load_gate(path: Path = GATE_PATH) -> Dict[str, Any]:
    """讀取發布門檻。缺檔或格式錯誤即拋錯，不以預設值放行（fail-closed）。"""
    gate = json.loads(path.read_text(encoding="utf-8"))
    zero = gate.get("zero_tolerance")
    if not isinstance(zero, list) or not zero or not all(isinstance(c, str) and c for c in zero):
        raise ValueError("publish_gate.json 的 zero_tolerance 必須是非空的代號清單")
    general = gate.get("general_max_anomalies")
    if not isinstance(general, int) or isinstance(general, bool) or general < 0:
        raise ValueError("publish_gate.json 的 general_max_anomalies 必須是非負整數")
    max_age = gate.get("max_age_days")
    if not isinstance(max_age, int) or isinstance(max_age, bool) or max_age <= 0:
        raise ValueError("publish_gate.json 的 max_age_days 必須是正整數")
    return gate


def _anomalies(item: Dict[str, Any]) -> List[str]:
    """單一標的的異常項目；空清單代表正常。"""
    probs = []
    if (item.get("watchdog") or {}).get("is_stale"):
        probs.append("行情過舊")
    if item.get("price") is None:
        probs.append("無現價")
    if not item.get("posture_label"):
        probs.append("無配置狀態")
    if not item.get("scores"):
        probs.append("無評分")
    if item.get("strategy_type") == "DIVIDEND_INCOME" and item.get("yield_pct") is None:
        probs.append("收息標的缺殖利率（高息陷阱互鎖無法判定）")
    return probs


def check_patrol_gate(patrol: Dict[str, Any], expected: List[str], gate: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    """回傳 (ok, reasons, warnings)。reasons 任一項即不通過；warnings 只提示。"""
    reasons: List[str] = []
    warnings: List[str] = []
    zero = set(gate["zero_tolerance"])
    exp = set(expected)

    if not zero <= exp:
        reasons.append(f"零容忍標的不在核心清單內：{sorted(zero - exp)}")

    fleet = patrol.get("fleet") or []
    codes = [str(x.get("ticker")) for x in fleet]
    if not codes:
        reasons.append("patrol.json 沒有任何標的（fleet 為空）")
    if len(set(codes)) != len(codes):
        reasons.append("fleet 有重複代號")
    if set(codes) != exp:
        missing = sorted(exp - set(codes))
        extra = sorted(set(codes) - exp)
        if missing:
            reasons.append(f"缺少核心標的：{missing}")
        if extra:
            reasons.append(f"出現非核心標的：{extra}")
    # patrol.py 的 targets 為 dict 清單（含 ticker），與 fleet 同一組代號
    targets = {str(t.get("ticker")) if isinstance(t, dict) else str(t) for t in (patrol.get("targets") or [])}
    if targets != set(codes):
        reasons.append("targets 與 fleet 不一致")
    trap = patrol.get("trap_state") or {}
    if set(trap.keys()) != set(codes):
        reasons.append("trap_state 與 fleet 不一致")
    run_dates = {str(v.get("run_date")) for v in trap.values() if isinstance(v, dict)}
    day = str(patrol.get("date_str", ""))[:10]
    if run_dates != {day}:
        reasons.append(f"trap_state 資料日 {sorted(run_dates)} 與巡檢日期 {day} 不一致")

    anomalies = {str(x.get("ticker")): _anomalies(x) for x in fleet}
    anomalies = {code: probs for code, probs in anomalies.items() if probs}
    held_bad = {c: p for c, p in anomalies.items() if c in zero}
    if held_bad:
        reasons.append("核心持股異常（零容忍）：" + "；".join(f"{c}（{'、'.join(p)}）" for c, p in sorted(held_bad.items())))
    general_bad = {c: p for c, p in anomalies.items() if c not in zero}
    if len(general_bad) > gate["general_max_anomalies"]:
        reasons.append(
            f"一般標的異常 {len(general_bad)} 檔，超過上限 {gate['general_max_anomalies']}："
            + "；".join(f"{c}（{'、'.join(p)}）" for c, p in sorted(general_bad.items()))
        )

    for key, value in (patrol.get("macro_data") or {}).items():
        if value in (None, "", "-"):
            warnings.append(f"總經資料缺：{key}")
    return (not reasons), reasons, warnings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="patrol.json 發布前門檻（fail-closed）")
    p.add_argument("patrol_json", help="patrol.py --json 的輸出檔")
    p.add_argument("--models-dir", default=str(MODELS_DIR), help="標的卡片根目錄（預設專案 models/）")
    a = p.parse_args(argv)
    try:
        gate = load_gate()
    except (OSError, ValueError) as e:
        print(f"❌ [Patrol Gate] 門檻設定讀取失敗（fail-closed）：{e}", file=sys.stderr)
        return 1
    try:
        patrol = json.loads(Path(a.patrol_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"❌ [Patrol Gate] 讀取 patrol.json 失敗：{e}", file=sys.stderr)
        return 1
    expected = sorted(discover_tickers(Path(a.models_dir), filter_tier="core"))
    ok, reasons, warnings = check_patrol_gate(patrol, expected, gate)
    for w in warnings:
        print(f"⚠️ [Patrol Gate] {w}", file=sys.stderr)
    if not ok:
        print("❌ [Patrol Gate] 未通過：" + "；".join(reasons), file=sys.stderr)
        return 1
    print(f"✅ [Patrol Gate] 通過：核心標的 {len(expected)} 檔", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
