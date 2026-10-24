"""Stock_AIStudio 波段觀察 Google Sheets 自動同步管線。

由 GitHub Actions 定時或手動觸發，亦可於本機執行：
1. 自 Google Sheets「波段觀察」讀取現況快照 A1:X 組成 prev.json
2. 執行 swing.py --scan --gate 進行技術面與三週期組合掃描
3. 判定市場開休市與門檻（全市場休市則正常略過）
4. 整列覆寫開市標的並精確維持 A:X 24 欄前端契約，將執行元資訊寫於 Z1:AA2
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SHEET_ID = "1pyGzkgaspYMYdXOPYerkLsxOMwNwa2yOKuNDrOrrhtQ"
DEFAULT_RANGE = "Untitled!A1:X"

try:
    from google_sheets import GoogleSheetsClient
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from google_sheets import GoogleSheetsClient


def extract_prev_from_sheet(sheet_values: List[List[Any]]) -> List[Dict[str, Any]]:
    """從 Sheet 現有列解析出 prev.json 格式。"""
    if not sheet_values or len(sheet_values) <= 1:
        return []
    prev = []
    for row in sheet_values[1:]:
        if not row or not row[0]:
            continue
        ticker = str(row[0]).strip()
        label = str(row[4]).strip() if len(row) > 4 and row[4] != "" else None
        combo = str(row[23]).strip() if len(row) > 23 and row[23] != "" else None
        item: Dict[str, Any] = {"ticker": ticker, "label": label}
        if combo:
            item["combo"] = combo
        prev.append(item)
    return prev


def merge_sheet_rows(
    existing_rows: List[List[Any]],
    new_sheet_table: List[List[Any]],
    scan_results: List[Dict[str, Any]],
) -> List[List[Any]]:
    """依據開休市狀態與健康指標合併 Sheet 列，嚴格保護休市市場舊資料與 A:X 契約。"""
    if not new_sheet_table:
        return existing_rows

    header = new_sheet_table[0]
    scan_by_ticker = {r["ticker"]: r for r in scan_results if "ticker" in r}

    if not existing_rows or len(existing_rows) <= 1:
        return new_sheet_table

    # 現有資料以代號為索引，補齊至 24 欄
    existing_by_ticker: Dict[str, List[Any]] = {}
    ordered_tickers: List[str] = []
    for r in existing_rows[1:]:
        if not r or not r[0]:
            continue
        t = str(r[0]).strip()
        padded = list(r) + [""] * max(0, 24 - len(r))
        existing_by_ticker[t] = padded[:24]
        ordered_tickers.append(t)

    new_rows_by_ticker: Dict[str, List[Any]] = {}
    for r in new_sheet_table[1:]:
        if not r or not r[0]:
            continue
        t = str(r[0]).strip()
        padded = list(r) + [""] * max(0, 24 - len(r))
        new_rows_by_ticker[t] = padded[:24]
        if t not in existing_by_ticker and t not in ordered_tickers:
            ordered_tickers.append(t)

    merged_data_rows: List[List[Any]] = []
    for t in ordered_tickers:
        scan_info = scan_by_ticker.get(t, {})
        is_fresh = scan_info.get("fresh", False)
        state = scan_info.get("state", "")

        if t in existing_by_ticker:
            old_row = existing_by_ticker[t]
            if is_fresh and t in new_rows_by_ticker:
                # 正常開市：整列覆寫為新資料
                merged_data_rows.append(new_rows_by_ticker[t])
            elif state == "ERROR":
                # 抓取失敗：第 5 欄標記失敗、第 16 欄寫入原因，其餘保留舊值
                err_row = list(old_row)
                err_row[4] = "⚠️ 抓取失敗"
                err_row[15] = scan_info.get("reason", "抓取異常")[:80]
                merged_data_rows.append(err_row)
            else:
                # 休市或未更新：保持舊資料不動
                merged_data_rows.append(old_row)
        elif t in new_rows_by_ticker:
            # 清單新增標的：直接追加
            merged_data_rows.append(new_rows_by_ticker[t])

    return [header] + merged_data_rows


def run_swing_pipeline(
    sheet_id: str = DEFAULT_SHEET_ID,
    force: bool = False,
    client: Optional[GoogleSheetsClient] = None,
) -> int:
    """執行波段觀察排程與雲端 Sheet 回寫完整管線。"""
    print(f"🚀 [Swing Sync] 啟動波段觀察同步管線（目標 Sheet ID: {sheet_id}）...")
    client = client or GoogleSheetsClient()

    # 1. 讀取現有 Sheet 資料
    existing_values: List[List[Any]] = []
    try:
        existing_values = client.get_values(sheet_id, DEFAULT_RANGE)
        print(f"   📊 成功讀取現有 Sheet：共 {len(existing_values)} 列（含表頭）")
    except Exception as e:
        print(f"   ⚠️ 讀取現有 Sheet 失敗或為空，將建立新表：{e}")

    prev_data = extract_prev_from_sheet(existing_values)
    prev_json_path = Path("/tmp/prev.json")
    prev_json_path.write_text(json.dumps(prev_data, ensure_ascii=False), encoding="utf-8")

    # 2. 執行核心掃描指令
    sheet_out_path = Path("/tmp/sheet.json")
    scan_out_path = Path("/tmp/scan.json")
    swing_script = REPO_ROOT / ".claude/skills/price-dividend-fetcher/scripts/swing.py"

    cmd = [
        sys.executable,
        str(swing_script),
        "--scan",
        "00882:15",
        "--prev",
        str(prev_json_path),
        "--sheet",
        str(sheet_out_path),
        "--gate",
    ]
    print(f"   🔍 執行波段掃描核心指令...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.stdout:
        scan_out_path.write_text(res.stdout, encoding="utf-8")
    if res.returncode != 0:
        print(f"❌ [Gate Failed] 核心掃描退出碼非 0：\n{res.stderr or res.stdout}", file=sys.stderr)
        return res.returncode

    # 3. 檢查開休市狀態
    scan_results: List[Dict[str, Any]] = []
    if scan_out_path.exists() and scan_out_path.stat().st_size > 0:
        try:
            scan_results = json.loads(scan_out_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    is_all_closed = len(scan_results) > 0 and all(not r.get("fresh", False) for r in scan_results)
    if is_all_closed and not force:
        print("ℹ️ [Market Closed] 今日所有市場均為休市，略過寫入 Sheet。")
        return 0

    if not sheet_out_path.exists():
        print("❌ 未產出 /tmp/sheet.json，無法進行同步。", file=sys.stderr)
        return 1

    new_sheet_table = json.loads(sheet_out_path.read_text(encoding="utf-8"))
    final_table = merge_sheet_rows(existing_values, new_sheet_table, scan_results)

    # 4. 回寫 Google Sheet
    target_range = f"Untitled!A1:X{len(final_table)}"
    print(f"   📝 正在回寫 Google Sheet（共 {len(final_table)} 列）至 {target_range}...")
    client.update_values(sheet_id, target_range, final_table, value_input_option="USER_ENTERED")

    # 若舊列數大於新列數，清空多餘列防殘留
    old_len = len(existing_values)
    new_len = len(final_table)
    if old_len > new_len:
        clear_range = f"Untitled!A{new_len + 1}:X{old_len}"
        print(f"   🧹 清空多餘舊列：{clear_range}")
        client.clear_values(sheet_id, clear_range)

    # 5. 寫入執行元資料至 Z1:AA2（A:X 範圍外）
    now_tpe = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S (TPE)")
    meta_values = [
        ["lastUpdated", now_tpe],
        ["executor", "GitHub Actions"],
    ]
    try:
        client.update_values(sheet_id, "Untitled!Z1:AA2", meta_values, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"   ℹ️ 寫入元資料欄位提示：{e}")

    print(f"✅ [Swing Sync] 成功同步波段觀察資料庫至 Google Sheet（{now_tpe}）！")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Stock_AIStudio 波段觀察 Google Sheets 自動同步管線")
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID, help="目標 Google Sheet ID")
    parser.add_argument("--force", action="store_true", help="強制覆寫，忽略休市略過機制")
    args = parser.parse_args(argv)

    return run_swing_pipeline(sheet_id=args.sheet_id, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
