"""Stock_AIStudio 波段觀察 Google Sheets 自動同步管線。

由 GitHub Actions 定時或手動觸發，亦可於本機執行：
1. 自 Google Sheets「波段觀察」讀取現況快照 A1:X 組成 prev.json
2. 執行 swing.py --scan --gate 進行技術面與三週期組合掃描
3. 判定市場開休市與互鎖（全市場休市，或開市標的資料日已入庫，則略過；--force 穿透）
4. 三週期組合轉為關鍵組合的開市標的（alert）先追加至「告警紀錄」分頁，並列入 GitHub 執行摘要；寫入失敗即停止，不覆寫 A:X
5. 整列覆寫開市標的並精確維持 A:X 24 欄前端契約，將執行元資訊寫於 Z1:AA2
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RANGE = "Untitled!A1:X"
MARKET_UNIVERSE_MAX = 100  # 全市場 ETF 納入波段觀察的檔數上限，與 Stock_AIStudio 雷達矩陣快照同一份清單
# 報價來源查不到資料的代號（疑似已下市或槓桿／期貨型），與 Stock_AIStudio scripts/fetch-etf-data.ts 的 EXCLUDED_IDS 同步
MARKET_EXCLUDED = {"0054", "0058", "0059", "0060", "00649", "00658L", "00659R", "00667"}
_TW_CODE = re.compile(r"^\d{4,6}[A-Z]?$")
GATE_VERDICT_PATH = Path("/tmp/scan_gate.json")
ALERT_TAB = "告警紀錄"
ALERT_HEADER = ["偵測時間", "代號", "名稱", "上次組合", "這次組合", "狀態", "收盤", "2xATR停損價"]

try:
    from google_sheets import GoogleSheetsClient
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from google_sheets import GoogleSheetsClient

import etf_market  # noqa: E402  google_sheets 已把 tw-etf-fetcher/scripts 放進路徑


def market_universe(summary_rows: List[List[Any]], limit: int = MARKET_UNIVERSE_MAX) -> List[Dict[str, str]]:
    """全市場 ETF 清單：ETF_Summary 的 A 欄代號、B 欄名稱，只留台股 ETF 代號並排除查不到資料者，取前 limit 檔（純函式）。"""
    out: List[Dict[str, str]] = []
    seen = set()
    for row in summary_rows:
        code = str(row[0]).strip().upper() if row else ""
        if not _TW_CODE.match(code) or code in MARKET_EXCLUDED or code in seen:
            continue
        seen.add(code)
        out.append({"ticker": f"TPE:{code}", "name": str(row[1]).strip() if len(row) > 1 else ""})
        if len(out) >= limit:
            break
    return out


def load_market_universe(client: Any) -> List[Dict[str, str]]:
    """讀全市場 ETF 成分股資料庫的 ETF_Summary（只讀）；讀不到就回空清單，只掃口袋名單。"""
    try:
        rows = client.get_values(etf_market.drive_id("MARKET_ETF_SHEET_ID"), "ETF_Summary!A2:B")
    except Exception as e:  # noqa: BLE001
        print(f"   ⚠️ 讀不到全市場 ETF 清單，本次只掃口袋名單：{e}")
        return []
    return market_universe(rows)


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


def _cell(value: Any) -> Any:
    return "" if value is None else value


def _alert_range(a1: str) -> str:
    """分頁名含中文，範圍一律加單引號（A1 標準寫法），避免 Sheets 解析失敗。"""
    return f"'{ALERT_TAB}'!{a1}"


def fresh_alerts(scan_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """三週期組合變成關鍵組合，且本次有寫入新資料的標的。休市標的不記，免得每次執行重複記錄。"""
    return [r for r in scan_results if r.get("alert") and r.get("fresh")]


_YMD_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _ymd(value: Any) -> Optional[str]:
    """把更新日統一成 YYYY-MM-DD。Sheet 讀回的是依地區顯示的日期（2026-10-28 或 2026/10/28），認不得就回傳 None。"""
    m = _YMD_RE.match(str(value or "").strip())
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def apply_interlock(scan_results: List[Dict[str, Any]], existing_rows: List[List[Any]]) -> List[str]:
    """互鎖：開市標的的 last_date 不晚於 Sheet 該列的更新日（Q 欄），即視為已入庫，改為不寫入、不告警（fresh 設為 False）。
    更新日無法解讀時照常寫入，寧可重寫也不漏寫。回傳被略過的代號。"""
    stored = {str(r[0]).strip(): (r[16] if len(r) > 16 else "") for r in existing_rows[1:] if r and r[0]}
    skipped: List[str] = []
    unreadable: List[str] = []
    for r in scan_results:
        ticker = r.get("ticker")
        incoming = _ymd(r.get("last_date"))
        if not r.get("fresh") or incoming is None or ticker not in stored:
            continue
        raw = str(stored[ticker] or "").strip()
        known = _ymd(raw)
        if known is None:
            if raw:
                unreadable.append(raw)
            continue
        if known >= incoming:
            r["fresh"] = False
            skipped.append(ticker)
    if unreadable:
        print(f"   ℹ️ 互鎖：{len(unreadable)} 檔更新日無法解讀（例：{unreadable[0]}），視為未入庫照常寫入")
    return skipped


def append_alert_rows(client: GoogleSheetsClient, sheet_id: str, alerts: List[Dict[str, Any]], detected_at: str) -> None:
    """把告警追加到「告警紀錄」分頁；分頁不存在就先建立並寫入表頭。只動該分頁，不碰 A:X。"""
    titles = {s["properties"]["title"] for s in client.get_spreadsheet(sheet_id).get("sheets", [])}
    if ALERT_TAB not in titles:
        client.batch_update(sheet_id, [{"addSheet": {"properties": {"title": ALERT_TAB}}}])
    existing = client.get_values(sheet_id, _alert_range("A:A"))
    if not existing:
        client.update_values(sheet_id, _alert_range("A1:H1"), [ALERT_HEADER])
    rows = [
        [detected_at, f"'{r['ticker']}", _cell(r.get("name")), _cell(r.get("prev_combo")), _cell(r.get("combo")),
         _cell(r.get("label")), _cell(r.get("close")), _cell(r.get("stop_price"))]
        for r in alerts
    ]
    start = max(len(existing), 1) + 1
    client.update_values(sheet_id, _alert_range(f"A{start}:H{start + len(rows) - 1}"), rows)


def report_new_listings(scan_results: List[Dict[str, Any]]) -> List[str]:
    """每次執行都列出新掛牌（日線不足、門檻不計入）的標的、日線根數與上市日。回傳代號清單。
    有上市日的以證交所清單驗證；沒有的（上櫃、海外、清單讀取失敗）只憑日線根數推測，標「未驗證」，需人工留意是否為來源只回部分資料。"""
    rows = [r for r in scan_results if r.get("state") == "NO_DATA" and r.get("short_history") and r.get("last_date")]
    if not rows:
        print("   🆕 新掛牌（日線不足，門檻不計入）：0 檔")
        return []

    def one(r: Dict[str, Any]) -> str:
        note = f"上市 {r['listed']}" if r.get("listed") else "未驗證"
        return f"{r.get('ticker')}（{r.get('bars')} 根，{note}）"

    print(f"   🆕 新掛牌（日線不足，門檻不計入）：{len(rows)} 檔：{'、'.join(one(r) for r in rows)}")
    return [r.get("ticker") for r in rows]


BAD_STATES = ("ERROR", "NO_DATA")
PUBLISH_GATE_PATH = REPO_ROOT / ".claude/skills/portfolio-patrol/references/publish_gate.json"


def report_anomalies(scan_results: List[Dict[str, Any]]) -> List[str]:
    """每次執行都列出計入異常的列（ERROR，或不是新掛牌的 NO_DATA）與原因。這些列不擋整張表：保留舊值並標記。回傳代號清單。"""
    new_listed = {r.get("ticker") for r in scan_results if r.get("state") == "NO_DATA" and r.get("short_history") and r.get("last_date")}
    rows = [r for r in scan_results if r.get("state") in BAD_STATES and r.get("ticker") not in new_listed]
    total = len(scan_results) or 1
    if not rows:
        print("   🩺 異常列：0 檔")
        return []
    detail = "、".join(f"{r.get('ticker')}（{r.get('state')}：{str(r.get('reason') or '')[:40]}）" for r in rows)
    print(f"   🩺 異常列：{len(rows)}/{len(scan_results)} 檔（{len(rows) / total:.0%}），保留舊值不覆寫：{detail}")
    return [r.get("ticker") for r in rows]


def core_tickers(path: Optional[Path] = None) -> List[str]:
    """核心持股（零容忍）代號，來源同每日巡檢頁的 publish_gate.json。缺檔或格式錯誤即拋錯（fail-closed）。"""
    gate = json.loads((path or PUBLISH_GATE_PATH).read_text(encoding="utf-8"))
    codes = gate.get("zero_tolerance")
    if not isinstance(codes, list) or not codes or not all(isinstance(c, str) and c for c in codes):
        raise ValueError("publish_gate.json 的 zero_tolerance 必須是非空的代號清單")
    return [f"TPE:{c}" for c in codes]


def core_problems(scan_results: List[Dict[str, Any]], core: List[str]) -> List[str]:
    """核心持股零容忍：缺列、ERROR、NO_DATA（含新掛牌）任一即回報。其餘列照常寫入，但這次執行要標為失敗，讓通報機制送出。"""
    by_ticker = {r.get("ticker"): r for r in scan_results}
    problems = []
    for t in core:
        r = by_ticker.get(t)
        if r is None:
            problems.append(f"{t} 缺列")
        elif r.get("state") in BAD_STATES:
            problems.append(f"{t} {r.get('state')}（{str(r.get('reason') or '')[:60]}）")
    return problems


def _exit_code(scan_results: List[Dict[str, Any]]) -> int:
    """收尾：核心持股有異常就回傳 1（其餘列已照常處理），否則 0。"""
    try:
        problems = core_problems(scan_results, core_tickers())
    except (OSError, ValueError) as e:
        print(f"❌ [Core Check Failed] 核心持股清單讀取失敗（fail-closed）：{e}", file=sys.stderr)
        return 1
    if problems:
        print(f"❌ [Core Check Failed] 核心持股資料異常（零容忍），其餘列已照常處理：{'；'.join(problems)}", file=sys.stderr)
        return 1
    return 0


def report_alerts(alerts: List[Dict[str, Any]]) -> None:
    """告警列在 GitHub Actions 執行頁：warning 註解與執行摘要表格；不在 GitHub 環境時只印到終端機。"""
    for r in alerts:
        print(f"::warning title=波段關鍵組合::{r['ticker']} 由 {r.get('prev_combo')} 轉為 {r.get('combo')}")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## 波段關鍵組合告警",
        "",
        "| 代號 | 名稱 | 上次組合 | 這次組合 | 狀態 | 收盤 | 2xATR停損價 |",
        "| :-- | :-- | :-- | :-- | :-- | --: | --: |",
    ]
    for r in alerts:
        cells = [r["ticker"], r.get("name"), r.get("prev_combo"), r.get("combo"), r.get("label"), r.get("close"), r.get("stop_price")]
        lines.append("| " + " | ".join(str(_cell(c)) for c in cells) + " |")
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        print(f"   ℹ️ 寫入 GitHub 執行摘要失敗：{e}")


def _stamp_patrol(client: GoogleSheetsClient, sheet_id: str, status: str) -> str:
    """休市或互鎖略過時只更新 Z1:AA2 的巡檢時間與狀態（A:X 範圍外），不動標的數據。回傳寫入的時間。"""
    now_tpe = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S (TPE)")
    meta_values = [
        ["最後巡檢時間", now_tpe],
        ["狀態", status],
    ]
    try:
        client.update_values(sheet_id, "Untitled!Z1:AA2", meta_values, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"   ℹ️ 寫入元資料欄位提示：{e}")
    return now_tpe


def run_swing_pipeline(
    sheet_id: str = "",
    force: bool = False,
    client: Optional[GoogleSheetsClient] = None,
) -> int:
    """執行波段觀察排程與雲端 Sheet 回寫完整管線。"""
    if not sheet_id:
        sheet_id = etf_market.drive_id("SWING_SHEET_ID")
    print("🚀 [Swing Sync] 啟動波段觀察同步管線（目標：DRIVE_IDS 的 SWING_SHEET_ID 或 --sheet-id 指定）...")
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

    universe = load_market_universe(client)
    extra_path = Path("/tmp/extra_tickers.json")
    extra_path.write_text(json.dumps(universe, ensure_ascii=False), encoding="utf-8")
    print(f"   🌐 全市場 ETF 納入 {len(universe)} 檔")

    cmd = [
        sys.executable,
        str(swing_script),
        "--scan",
        "00882:15",
        "--tier",
        "all",
        "--extra-tickers",
        str(extra_path),
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
    # 門檻判定結果另存一份，連同掃描結果供 CI 重播（gate_replay.py）：之後改門檻時，拿真實掃描結果比對新舊判定
    GATE_VERDICT_PATH.write_text(json.dumps({
        "returncode": res.returncode,
        "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "force": force,
    }), encoding="utf-8")
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

    report_new_listings(scan_results)
    report_anomalies(scan_results)

    is_all_closed = len(scan_results) > 0 and all(not r.get("fresh", False) for r in scan_results)
    if is_all_closed and not force:
        now_tpe = _stamp_patrol(client, sheet_id, "休市略過（維持最新交易日數據）")
        print(f"ℹ️ [Market Closed] 今日所有市場均為休市，已更新巡檢時間戳記至 Z1:AA2（{now_tpe}），略過覆寫標的數據。")
        return _exit_code(scan_results)

    # 互鎖：開市標的的資料日已入庫即略過（--force 穿透）。仍有抓取失敗列時照常寫入，讓失敗標記落到 Sheet
    skipped = [] if force else apply_interlock(scan_results, existing_values)
    if force:
        print("⚡ [Force] 已穿透休市與互鎖判定，強制整表刷新。")
    has_error = any(r.get("state") == "ERROR" for r in scan_results)
    if skipped and not has_error and not any(r.get("fresh") for r in scan_results):
        now_tpe = _stamp_patrol(client, sheet_id, "互鎖略過（資料日已入庫，維持既有數據）")
        print(f"ℹ️ [Interlock] 開市標的資料日已入庫（{len(skipped)} 檔），略過覆寫與告警，已更新巡檢時間戳記至 Z1:AA2（{now_tpe}）。")
        return _exit_code(scan_results)

    if not sheet_out_path.exists():
        print("❌ 未產出 /tmp/sheet.json，無法進行同步。", file=sys.stderr)
        return 1

    # 4. 告警先寫入「告警紀錄」分頁，成功後才覆寫 A:X。寫入失敗就停手：prev 未更新，下次執行會再觸發，告警不會悄悄消失。
    alerts = fresh_alerts(scan_results)
    if alerts:
        detected_at = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S (TPE)")
        try:
            append_alert_rows(client, sheet_id, alerts, detected_at)
        except Exception as e:
            print(f"❌ [Alert Failed] 告警紀錄寫入失敗，未覆寫 A:X：{e}", file=sys.stderr)
            return 1
        report_alerts(alerts)

    new_sheet_table = json.loads(sheet_out_path.read_text(encoding="utf-8"))
    final_table = merge_sheet_rows(existing_values, new_sheet_table, scan_results)

    # 5. 回寫 Google Sheet
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

    # 6. 寫入執行元資料至 Z1:AA2（A:X 範圍外）
    now_tpe = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S (TPE)")
    meta_values = [
        ["lastUpdated", now_tpe],
        ["executor", "GitHub Actions"],
    ]
    try:
        client.update_values(sheet_id, "Untitled!Z1:AA2", meta_values, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"   ℹ️ 寫入元資料欄位提示：{e}")

    code = _exit_code(scan_results)
    if code == 0:
        print(f"✅ [Swing Sync] 成功同步波段觀察資料庫至 Google Sheet（{now_tpe}）！")
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Stock_AIStudio 波段觀察 Google Sheets 自動同步管線")
    parser.add_argument("--sheet-id", default="", help="目標 Google Sheet ID（預設取 DRIVE_IDS 的 SWING_SHEET_ID）")
    parser.add_argument("--force", action="store_true", help="強制整表刷新，穿透休市與互鎖判定（補跑用）")
    args = parser.parse_args(argv)

    return run_swing_pipeline(sheet_id=args.sheet_id, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
