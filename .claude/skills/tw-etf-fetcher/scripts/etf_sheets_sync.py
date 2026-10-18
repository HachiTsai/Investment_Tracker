#!/usr/bin/env python3
"""全市場 ETF 成分股與摘要 Google Sheets 雲端同步模組 (ETF Sheets Sync)。

職責：
1. 遍歷 models/*/cards/ 下的所有標的，解析 ticker.yml 與 constituents.jsonl。
2. 匯總輸出兩大標準資料集：
   - ETF_Constituents: 全市場 ETF 扁平化成分股清單（依 tw-etf-architecture.md 規格）
   - ETF_Summary: 全市場 ETF 基本資料與前三大持倉精華摘要
3. 輸出本機 CSV 報告，並透過 gsheets CLI 將數據同步回填至雲端試算表。
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 預設 SSOT 試算表 ID（Project_財商工程/All_Market/全市場_ETF成分股資料庫）
DEFAULT_SHEET_ID = os.environ.get(
    "ETF_CONSTITUENTS_SHEET_ID",
    "1GIhbRyL-h96ACVjlSSW9YUFMiAItg_SP9Wi0o3WwG70",
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]


def load_yaml_simple(path: Path) -> Dict[str, Any]:
    """YAML 讀取器：簡易純文字卡片解析器。"""
    content = path.read_text(encoding="utf-8")
    result: Dict[str, Any] = {}
    current_section: Optional[Dict[str, Any]] = None

    for line in content.splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        stripped = line.strip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())
        if ":" in stripped:
            k, v = stripped.split(":", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")

            parsed_v: Any = v
            if k in ("ticker", "id", "target_ticker", "code", "etf_id"):
                parsed_v = str(v)
            elif v.isdigit():
                parsed_v = int(v)
            elif re.match(r"^-?\d+\.\d+$", v):
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

    return result


def load_all_etf_models(models_dir: Path) -> List[Dict[str, Any]]:
    """掃描 models 目錄下所有具備 cards/ 的標的資料。"""
    models: List[Dict[str, Any]] = []
    if not models_dir.exists():
        return models

    for model_path in sorted(models_dir.iterdir()):
        if not model_path.is_dir():
            continue

        cards_dir = model_path / "cards"
        ticker_file = cards_dir / "ticker.yml"
        constituents_file = cards_dir / "constituents.jsonl"

        if not ticker_file.exists():
            continue

        ticker_info = load_yaml_simple(ticker_file)
        ticker_code = model_path.name
        ticker_name = str(ticker_info.get("title", ticker_code))

        constituents: List[Dict[str, Any]] = []
        if constituents_file.exists():
            for line in constituents_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        constituents.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # 排序權重高者在前
        constituents.sort(key=lambda x: float(x.get("weight_pct", 0.0)), reverse=True)

        models.append({
            "ticker": ticker_code,
            "title": ticker_name,
            "full_name": ticker_info.get("full_name", ""),
            "currency": ticker_info.get("currency", "TWD"),
            "exchange": ticker_info.get("exchange", "TWSE"),
            "category": ticker_info.get("category", "ETF"),
            "manager": ticker_info.get("manager", ""),
            "benchmark": ticker_info.get("benchmark", ""),
            "last_model_update": ticker_info.get("last_model_update", ""),
            "constituents": constituents,
        })

    return models


def generate_flattened_constituents(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """產生符合架構規範的扁平化成分股清單。
    
    欄位：etf_id | etf_name | constituent_ticker | constituent_name | weight_pct | shares | update_date
    """
    rows: List[Dict[str, Any]] = []
    for m in models:
        etf_id = m["ticker"]
        etf_name = m["title"]
        update_date = m["last_model_update"]

        for c in m["constituents"]:
            rows.append({
                "etf_id": etf_id,
                "etf_name": etf_name,
                "constituent_ticker": c.get("ticker", ""),
                "constituent_name": c.get("name", ""),
                "weight_pct": f"{float(c.get('weight_pct', 0.0)):.2f}",
                "shares": c.get("shares", ""),
                "update_date": update_date,
            })

    return rows


def generate_summary_rows(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """產生全市場 ETF 摘要清單。"""
    rows: List[Dict[str, Any]] = []
    for m in models:
        constituents = m["constituents"]
        top1 = constituents[0] if len(constituents) > 0 else {}
        top2 = constituents[1] if len(constituents) > 1 else {}
        top3 = constituents[2] if len(constituents) > 2 else {}

        def format_top(c: Dict[str, Any]) -> str:
            if not c:
                return "-"
            return f"{c.get('name', '')} ({c.get('weight_pct', 0.0)}%)"

        rows.append({
            "etf_id": m["ticker"],
            "etf_name": m["title"],
            "exchange": m["exchange"],
            "category": m["category"],
            "benchmark": m["benchmark"],
            "constituent_count": len(constituents),
            "top1_holding": format_top(top1),
            "top2_holding": format_top(top2),
            "top3_holding": format_top(top3),
            "last_model_update": m["last_model_update"],
        })

    return rows


def write_csv(data: List[Dict[str, Any]], fieldnames: List[str], target_path: Path) -> Path:
    """寫入本機 CSV 檔案。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    return target_path


def find_gsheets_bin() -> Optional[str]:
    """尋找 gsheets CLI 執行檔路徑。"""
    bin_path = shutil.which("gsheets")
    if bin_path:
        return bin_path

    # 檢查 Antigravity 插件目錄
    candidate = Path.home() / ".gemini/config/plugins/gsheets/skills/gsheets/scripts/gsheets"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)

    return None


def sync_to_google_sheets(
    sheet_id: str,
    summary_csv: Path,
    constituents_csv: Path,
    gsheets_bin: Optional[str] = None,
) -> Tuple[bool, str]:
    """透過 gsheets CLI 將 CSV 回填至 Google Sheets 雲端試算表。"""
    bin_cmd = gsheets_bin or find_gsheets_bin()
    if not bin_cmd:
        return False, "找不到 gsheets CLI 工具，無法執行雲端同步。"

    # 1. 匯入 ETF_Summary
    cmd_summary = [bin_cmd, "mutate", "import-csv", sheet_id, str(summary_csv), "--sheet", "ETF_Summary"]
    res1 = subprocess.run(cmd_summary, capture_output=True, text=True)
    if res1.returncode != 0:
        return False, f"匯入 ETF_Summary 失敗：{res1.stderr or res1.stdout}"

    # 2. 匯入 ETF_Constituents
    cmd_constituents = [bin_cmd, "mutate", "import-csv", sheet_id, str(constituents_csv), "--sheet", "ETF_Constituents"]
    res2 = subprocess.run(cmd_constituents, capture_output=True, text=True)
    if res2.returncode != 0:
        return False, f"匯入 ETF_Constituents 失敗：{res2.stderr or res2.stdout}"

    return True, f"成功同步至 Google Sheets (ID: {sheet_id})"


def run_sync_pipeline(
    models_dir: Path,
    output_dir: Path,
    sheet_id: str,
    export_only: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """執行全套同步管線流程。"""
    models = load_all_etf_models(models_dir)
    if not models:
        return {"status": "error", "message": f"在 {models_dir} 未發現任何 ETF 模型。"}

    constituents_rows = generate_flattened_constituents(models)
    summary_rows = generate_summary_rows(models)

    summary_fields = [
        "etf_id",
        "etf_name",
        "exchange",
        "category",
        "benchmark",
        "constituent_count",
        "top1_holding",
        "top2_holding",
        "top3_holding",
        "last_model_update",
    ]
    constituents_fields = [
        "etf_id",
        "etf_name",
        "constituent_ticker",
        "constituent_name",
        "weight_pct",
        "shares",
        "update_date",
    ]

    summary_csv = output_dir / "etf_summary.csv"
    constituents_csv = output_dir / "etf_constituents.csv"

    write_csv(summary_rows, summary_fields, summary_csv)
    write_csv(constituents_rows, constituents_fields, constituents_csv)

    result = {
        "status": "success",
        "etf_count": len(models),
        "constituents_count": len(constituents_rows),
        "summary_csv": str(summary_csv),
        "constituents_csv": str(constituents_csv),
        "sheet_id": sheet_id,
        "synced": False,
    }

    if export_only or dry_run:
        result["message"] = f"已導出本機 CSV（ETF 數：{len(models)}，成分股數：{len(constituents_rows)}），未上傳雲端。"
        return result

    success, msg = sync_to_google_sheets(sheet_id, summary_csv, constituents_csv)
    result["synced"] = success
    result["message"] = msg
    if not success:
        result["status"] = "error"

    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="全市場 ETF 成分股與摘要 Google Sheets 雲端同步模組")
    parser.add_argument("--models-dir", default=str(REPO_ROOT / "models"), help="models 目錄路徑")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "reports"), help="CSV 匯出目錄路徑")
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID, help="目標 Google Sheet ID")
    parser.add_argument("--export-only", action="store_true", help="僅產出本機 CSV，不上傳雲端")
    parser.add_argument("--dry-run", action="store_true", help="模擬執行，不變更雲端試算表")

    args = parser.parse_args(argv)

    print("🚀 啟動全市場 ETF 成分股資料管線同步...")
    res = run_sync_pipeline(
        models_dir=Path(args.models_dir),
        output_dir=Path(args.output_dir),
        sheet_id=args.sheet_id,
        export_only=args.export_only,
        dry_run=args.dry_run,
    )

    if res["status"] == "success":
        print(f"✅ 處理完成：涵蓋 {res['etf_count']} 檔 ETF，共 {res['constituents_count']} 筆底層成分股紀錄。")
        print(f"   📁 摘要 CSV：{res['summary_csv']}")
        print(f"   📁 成分股 CSV：{res['constituents_csv']}")
        if res.get("synced"):
            print(f"   ☁️ 雲端同步成功：試算表 ID [{res['sheet_id']}]")
            print(f"      - 分頁：ETF_Summary 與 ETF_Constituents")
        else:
            print(f"   ℹ️ {res.get('message', '')}")
        return 0
    else:
        print(f"❌ 同步失敗：{res.get('message', '未知錯誤')}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
