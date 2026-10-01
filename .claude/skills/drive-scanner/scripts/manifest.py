#!/usr/bin/env python3
"""drive-scanner：比對 Google Drive 掃描結果與上次記錄（manifest），找出新增、修改、刪除的內容。

Drive 只能經由 MCP 連接器讀取，所以由 Claude 呼叫連接器取得清單，寫成 scan JSON 後交給本腳本比對。

用法：
  manifest.py reminder                  開工提醒（SessionStart hook 呼叫）
  manifest.py diff SCAN.json            比對本次掃描與 manifest，輸出變動
  manifest.py update SCAN.json          以本次掃描覆寫 manifest（匯報後執行）
  manifest.py link FILE_ID REPO_PATH    記錄某個 Drive 檔已轉存到 REPO 的位置

SCAN.json 格式：
  {
    "scanned_at": "2026-10-01T06:50:00Z",
    "files": [{"id": "...", "title": "...", "mimeType": "...", "modifiedTime": "...", "source": "folder"}],
    "core_rows": {"Transactions": ["Tx_ID", ...], "Stock_Journal": ["Note_ID", ...]}   # 選填
  }
"""

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

if sys.platform == "win32" and hasattr(sys.stdout, "buffer") and "pytest" not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = SKILL_DIR / "state" / "drive-manifest.json"

FOLDER_ID = "1HCnLX7B1szkAEB0XWpji63ifuexEd1pZ"   # Project_財商工程
CORE_ID = "1QBEgUi-kTOuLgj2yGHmP-0g_ug-Sl_M21SN0g93b6xI"   # Investment_Tracker_Core（唯讀）
CORE_SHEETS = ("Transactions", "Stock_Journal")
FILE_KEYS = ("id", "title", "mimeType", "modifiedTime")


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest(path: Optional[Path] = None) -> Dict:
    path = path or MANIFEST_PATH   # 呼叫時才取全域值，測試可替換路徑
    if not path.exists():
        return {"last_scan": None, "files": {}, "core_rows": {}}
    return load_json(path)


def save_manifest(manifest: Dict, path: Optional[Path] = None) -> None:
    path = path or MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_scan(scan: Dict) -> List[str]:
    errors = []
    if not scan.get("scanned_at"):
        errors.append("scan 缺少 scanned_at")
    files = scan.get("files")
    if not isinstance(files, list):
        return errors + ["scan 缺少 files 清單"]
    for i, f in enumerate(files):
        missing = [k for k in FILE_KEYS if not f.get(k)]
        if missing:
            errors.append(f"files[{i}] 缺少 {', '.join(missing)}")
    if not any(f.get("id") == CORE_ID for f in files):
        errors.append("scan 未包含 Investment_Tracker_Core 的 metadata")
    rows = scan.get("core_rows")
    if rows is not None and (not isinstance(rows, dict) or any(not isinstance(v, list) for v in rows.values())):
        errors.append("core_rows 必須是 {分頁: [ID, ...]}")
    return errors


def diff(manifest: Dict, scan: Dict) -> Dict:
    """回傳 new / modified / deleted 檔案、Core 新增的列 ID，以及是否還需要讀取 Core 的列。"""
    old = manifest.get("files", {})
    now = {f["id"]: f for f in scan["files"]}
    result: Dict = {
        "new": [now[i] for i in now if i not in old],
        "modified": [now[i] for i in now if i in old and now[i]["modifiedTime"] != old[i]["modifiedTime"]],
        "deleted": [old[i] for i in old if i not in now],
        "core_new_rows": [],
    }
    core_changed = any(f["id"] == CORE_ID for f in result["modified"] + result["new"])
    rows = scan.get("core_rows")
    if rows:
        known = manifest.get("core_rows", {})
        for sheet, ids in rows.items():
            seen = set(known.get(sheet, []))
            result["core_new_rows"] += [{"sheet": sheet, "id": i} for i in ids if i not in seen]
    result["core_rows_needed"] = core_changed and not rows
    return result


def apply_scan(manifest: Dict, scan: Dict) -> Dict:
    """以本次掃描更新 manifest；保留既有的 imported_to 紀錄，未提供 core_rows 時保留舊值。"""
    old = manifest.get("files", {})
    files = {}
    for f in scan["files"]:
        entry = {k: f[k] for k in FILE_KEYS}
        entry["source"] = f.get("source", "folder")
        if old.get(f["id"], {}).get("imported_to"):
            entry["imported_to"] = old[f["id"]]["imported_to"]
        files[f["id"]] = entry
    return {
        "last_scan": scan["scanned_at"],
        "files": files,
        "core_rows": scan.get("core_rows") or manifest.get("core_rows", {}),
    }


def describe(f: Dict) -> str:
    where = "Core 試算表" if f["id"] == CORE_ID else "Project_財商工程"
    imported = f"，已轉存：{f['imported_to']}" if f.get("imported_to") else ""
    return f"{f['title']}（{where}，modifiedTime {f['modifiedTime']}{imported}）"


def cmd_reminder(_args) -> int:
    m = load_manifest()
    last = m.get("last_scan") or "從未掃描"
    print(
        "【開工儀式】請先執行 drive-scanner skill：掃描 Google Drive 的 Project_財商工程 資料夾"
        f"與 Investment_Tracker_Core（唯讀），向使用者匯報新內容。上次掃描：{last}。"
    )
    return 0


def cmd_diff(args) -> int:
    scan = load_json(Path(args.scan))
    errors = validate_scan(scan)
    if errors:
        for e in errors:
            print(f"❌ {e}", file=sys.stderr)
        return 1
    m = load_manifest()
    d = diff(m, scan)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0
    print(f"上次掃描：{m.get('last_scan') or '從未掃描'}；本次：{scan['scanned_at']}")
    labels = (("new", "🆕 新增"), ("modified", "✏️  修改"), ("deleted", "🗑️  刪除"))
    for key, label in labels:
        for f in d[key]:
            print(f"{label}：{describe(f)}")
    for r in d["core_new_rows"]:
        print(f"🆕 Core 新紀錄：{r['sheet']} {r['id']}")
    if d["core_rows_needed"]:
        print("⚠️  Core 已更新但 scan 未附 core_rows：請讀取 Transactions／Stock_Journal 後重跑 diff")
    if not any(d[k] for k in ("new", "modified", "deleted", "core_new_rows", "core_rows_needed")):
        print("✅ 沒有新內容")
    return 0


def cmd_update(args) -> int:
    scan = load_json(Path(args.scan))
    errors = validate_scan(scan)
    if errors:
        for e in errors:
            print(f"❌ {e}", file=sys.stderr)
        return 1
    save_manifest(apply_scan(load_manifest(), scan))
    print(f"✅ manifest 已更新（last_scan {scan['scanned_at']}）")
    return 0


def cmd_link(args) -> int:
    m = load_manifest()
    if args.file_id not in m.get("files", {}):
        print(f"❌ manifest 中沒有 {args.file_id}，請先 update", file=sys.stderr)
        return 1
    m["files"][args.file_id]["imported_to"] = args.repo_path
    save_manifest(m)
    print(f"✅ 已記錄 {m['files'][args.file_id]['title']} → {args.repo_path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Drive 掃描比對（drive-scanner）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("reminder", help="開工提醒").set_defaults(func=cmd_reminder)
    d = sub.add_parser("diff", help="比對掃描結果")
    d.add_argument("scan")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_diff)
    u = sub.add_parser("update", help="更新 manifest")
    u.add_argument("scan")
    u.set_defaults(func=cmd_update)
    ln = sub.add_parser("link", help="記錄轉存位置")
    ln.add_argument("file_id")
    ln.add_argument("repo_path")
    ln.set_defaults(func=cmd_link)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
