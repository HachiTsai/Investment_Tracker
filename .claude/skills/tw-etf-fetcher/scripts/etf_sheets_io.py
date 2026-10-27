"""ETF 資料庫寫出層：本機 CSV 與 Google Sheets 同步（Google Sheets API 或 gsheets CLI）。

寫入前一律先過 etf_market.guard_sheet_id，目標是 Core 就拒絕、不連網。
"""

import csv
import os
from datetime import datetime, timedelta, timezone
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import etf_market  # noqa: E402


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


def sync_via_google_api(
    sheet_id: str,
    summary_csv: Path,
    constituents_csv: Path,
    summary_width: int = 16,
) -> Tuple[bool, str]:
    """使用輕量 Google Sheets API 客戶端將 CSV 批次同步至 Google Sheets。"""
    try:
        etf_market.guard_sheet_id(sheet_id)
    except etf_market.CoreWriteRefused as e:
        return False, str(e)
    try:
        sys.path.insert(0, str(REPO_ROOT / ".claude/skills/price-dividend-fetcher/scripts"))
        from google_sheets import GoogleSheetsClient
        client = GoogleSheetsClient()
    except Exception as e:
        return False, f"無法初始化 Google Sheets API 客戶端：{e}"

    try:
        # 1. 解析 CSV 內容
        with open(summary_csv, "r", encoding="utf-8") as f:
            summary_rows = list(csv.reader(f))
        with open(constituents_csv, "r", encoding="utf-8") as f:
            constituents_rows = list(csv.reader(f))

        # 2. 獲取試算表元資料並動態確保網格容量與設定代號純文字格式；外幣市場的分頁若還沒建立，先補上（台股的分頁已存在，不動）
        meta = client.get_spreadsheet(sheet_id)
        existing_titles = {s.get("properties", {}).get("title") for s in meta.get("sheets", [])}
        missing_tabs = [t for t in ("ETF_Summary", "ETF_Constituents") if t not in existing_titles]
        if missing_tabs:
            client.batch_update(sheet_id, [{"addSheet": {"properties": {"title": t}}} for t in missing_tabs])
            meta = client.get_spreadsheet(sheet_id)
        sheets_list = meta.get("sheets", [])
        summary_sheet_id = next(
            (s["properties"]["sheetId"] for s in sheets_list if s.get("properties", {}).get("title") == "ETF_Summary"),
            0,
        )
        constituents_sheet_id = next(
            (s["properties"]["sheetId"] for s in sheets_list if s.get("properties", {}).get("title") == "ETF_Constituents"),
            1048345883,
        )

        # 確保網格容量足夠（避免超出 grid limits）
        if summary_rows:
            client.ensure_sheet_capacity(sheet_id, summary_sheet_id, len(summary_rows) + 50)
        if constituents_rows:
            client.ensure_sheet_capacity(sheet_id, constituents_sheet_id, len(constituents_rows) + 500)

        # 設定代號欄位為純文字（TEXT），防止 0 開頭代號（如 0050, 0056）被 Google 轉型為整數
        try:
            client.format_columns_as_text(sheet_id, summary_sheet_id, [0])
            client.format_columns_as_text(sheet_id, constituents_sheet_id, [0, 2])
            print("   🔤 已鎖定代號欄位為純文字格式（保護 0050、0056 等前導零完整性）")
        except Exception as e:
            print(f"   ℹ️ 設定純文字格式提示：{e}")

        # 3. 寫入 ETF_Summary（台股為 A:P；外幣市場多 coverage 與 holdings_asof，為 A:R）
        summary_last_col = chr(ord("A") + summary_width - 1)
        if summary_rows:
            print(f"   📤 正在寫入 ETF_Summary：共 {len(summary_rows)} 筆標的摘要...", flush=True)
            client.update_values(
                sheet_id,
                f"ETF_Summary!A1:{summary_last_col}{len(summary_rows)}",
                summary_rows,
                value_input_option="USER_ENTERED",
            )

        # 4. 寫入 ETF_Constituents (每批 1,500 列)
        if constituents_rows:
            chunk_size = 1500
            total_len = len(constituents_rows)
            for idx in range(0, total_len, chunk_size):
                chunk = constituents_rows[idx : idx + chunk_size]
                start_row = idx + 1
                end_row = idx + len(chunk)
                range_str = f"ETF_Constituents!A{start_row}:G{end_row}"
                print(f"   📤 正在寫入 ETF_Constituents：第 {start_row} 至 {end_row} 列（共 {total_len} 筆）...", flush=True)
                client.update_values(
                    sheet_id,
                    range_str,
                    chunk,
                    value_input_option="USER_ENTERED",
                )

        # 5. 清除 ETF_Constituents 超連結，防止代號（如 2330.TW、NVDA.US）被 Google 誤判為可疑連結
        try:
            client.clear_hyperlinks(
                sheet_id=sheet_id,
                sheet_tab_id=constituents_sheet_id,
                start_row_index=1,
                end_row_index=len(constituents_rows) + 1,
                start_column_index=0,
                end_column_index=7,
            )
            print(f"   🧹 已清除 ETF_Constituents 超連結樣式，防範 Google Drive 安全警報")
        except Exception as e:
            print(f"   ℹ️ 清除 ETF_Constituents 超連結提示：{e}")

        # 6. 寫入同步元資訊：ETF_Summary 放在資料欄右側（台股 R1:S2；外幣市場的 A:R 已是資料欄，改放 T1:U2，舊的 S1:S2 先清掉），
        #    ETF_Constituents 在 I1:J2（資料欄位外側）
        meta_col = chr(ord("A") + summary_width + 1)
        meta_end = chr(ord(meta_col) + 1)
        now_tpe = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S (TPE)")
        meta_values = [
            ["最後同步時間", now_tpe],
            ["執行者", "GitHub Actions"],
        ]
        try:
            if summary_width > 16:
                client.update_values(sheet_id, "ETF_Summary!S1:S2", [[""], [""]], value_input_option="USER_ENTERED")
            client.update_values(
                sheet_id,
                f"ETF_Summary!{meta_col}1:{meta_end}2",
                meta_values,
                value_input_option="USER_ENTERED",
            )
        except Exception as e:
            print(f"   ℹ️ 寫入 ETF_Summary 元資訊欄位提示：{e}")

        try:
            client.update_values(
                sheet_id,
                "ETF_Constituents!I1:J2",
                meta_values,
                value_input_option="USER_ENTERED",
            )
        except Exception as e:
            print(f"   ℹ️ 寫入 ETF_Constituents 元資訊欄位提示：{e}")

        return True, f"成功透過 Google API 批次同步至 Google Sheets (ID: {sheet_id})"
    except Exception as e:
        return False, f"Google API 同步失敗：{e}"


def sync_to_google_sheets(
    sheet_id: str,
    summary_csv: Path,
    constituents_csv: Path,
    gsheets_bin: Optional[str] = None,
    summary_width: int = 16,
) -> Tuple[bool, str]:
    """透過 Google API 或 gsheets CLI 將 CSV 回填至 Google Sheets 雲端試算表。"""
    try:
        etf_market.guard_sheet_id(sheet_id)
    except etf_market.CoreWriteRefused as e:
        return False, str(e)
    if os.environ.get("GCP_SA_KEY") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return sync_via_google_api(sheet_id, summary_csv, constituents_csv, summary_width)

    bin_cmd = gsheets_bin or find_gsheets_bin()
    if not bin_cmd:
        return False, "未提供 GCP_SA_KEY 且找不到 gsheets CLI 工具，無法執行雲端同步。"

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
