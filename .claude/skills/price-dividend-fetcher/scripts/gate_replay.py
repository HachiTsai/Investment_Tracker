#!/usr/bin/env python3
"""波段 Sheet 門檻重播：拿排程留下的真實掃描結果，用目前的 check_gate 重新判定，和當時的結果比對。僅用標準函式庫。

為什麼需要：單元測試用的是人造資料，改門檻時看不出對真實資料的影響（2026-11-13 事故：#248 測試全過，卻讓每天的排程失敗）。
排程（swing-patrol.yml）每次把掃描結果與當時的判定存成 artifact `swing-scan`；PR 的 CI 下載最近幾份重播。
- 當時放行（退出碼 0）、現在被擋：退步，退出碼 1。確屬刻意收緊時，PR 描述寫上「重播例外」並說明原因即可放行。
- 當時被擋、現在放行：改善，只列出。
沒有任何 artifact（新 repo、已過保存期）只印提示，不當成失敗。

用法：
    python3 gate_replay.py                       # CI：用 GITHUB_REPOSITORY、GITHUB_TOKEN 下載最近的 artifact
    python3 gate_replay.py --dir 資料夾          # 本機：資料夾內每個子資料夾放 scan.json 與 scan_gate.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import swing  # noqa: E402

ARTIFACT_NAME = "swing-scan"
ARTIFACTS_API = "https://api.github.com/repos/{repo}/actions/artifacts?name={name}&per_page={n}"
SKIP_MARK = "重播例外"


def parse_time(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def replay_one(rows: List[Dict[str, Any]], verdict: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """用目前的 check_gate 重判一次，回傳 (現在是否放行, 理由)。判定時間取當時掃描時間，資料日年齡才不會因為重播而失真。"""
    now = parse_time(verdict["scanned_at"]) if verdict.get("scanned_at") else None
    healthy, _closed, reasons = swing.check_gate(rows, block_ratio=swing.GATE_BLOCK_RATIO, require_fresh=True, now=now)
    return healthy, reasons


def compare(runs: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """runs：[{name, rows, verdict}]。回傳 (退步, 改善) 說明清單。"""
    regress, improved = [], []
    for run in runs:
        was_ok = run["verdict"].get("returncode") == 0
        now_ok, reasons = replay_one(run["rows"], run["verdict"])
        if was_ok and not now_ok:
            regress.append(f"{run['name']}：當時放行，現在被擋：{'；'.join(reasons)}")
        elif not was_ok and now_ok:
            improved.append(f"{run['name']}：當時被擋，現在放行")
    return regress, improved


def load_dir(path: Path) -> List[Dict[str, Any]]:
    runs = []
    for d in sorted(p for p in path.iterdir() if p.is_dir()):
        scan, verdict = d / "scan.json", d / "scan_gate.json"
        if scan.exists() and verdict.exists():
            runs.append({"name": d.name, "rows": json.loads(scan.read_text(encoding="utf-8")),
                         "verdict": json.loads(verdict.read_text(encoding="utf-8"))})
    return runs


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # noqa: D401
        return None


def _api(url: str, token: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _download(url: str, token: str) -> bytes:
    """artifact 下載會 302 到儲存空間；轉址後不能再帶 Authorization，所以先擋下轉址、取出 Location 再單獨抓。"""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        if e.code not in (301, 302, 303, 307, 308) or not loc:
            raise
    with urllib.request.urlopen(loc, timeout=60) as resp:
        return resp.read()


def fetch_runs(repo: str, token: str, limit: int = 5) -> List[Dict[str, Any]]:
    runs = []
    listing = _api(ARTIFACTS_API.format(repo=repo, name=ARTIFACT_NAME, n=limit), token).get("artifacts") or []
    for art in listing:
        if art.get("expired"):
            continue
        with zipfile.ZipFile(io.BytesIO(_download(art["archive_download_url"], token))) as z:
            names = set(z.namelist())
            if not {"scan.json", "scan_gate.json"} <= names:
                continue
            runs.append({"name": f"{art.get('created_at', '')} run {art.get('workflow_run', {}).get('id', '?')}",
                         "rows": json.loads(z.read("scan.json")), "verdict": json.loads(z.read("scan_gate.json"))})
    return runs


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="波段 Sheet 門檻重播")
    ap.add_argument("--dir", help="本機資料夾，內含各次執行的子資料夾（scan.json、scan_gate.json）")
    ap.add_argument("--limit", type=int, default=5, help="下載最近幾份 artifact（預設 5）")
    a = ap.parse_args(argv)
    try:
        if a.dir:
            runs = load_dir(Path(a.dir))
        else:
            repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_TOKEN", "")
            if not repo or not token:
                print("❌ 缺少 GITHUB_REPOSITORY 或 GITHUB_TOKEN，無法下載掃描結果。", file=sys.stderr)
                return 2
            runs = fetch_runs(repo, token, a.limit)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
        # 重播是額外的保險，下載失敗不應該擋住所有 PR；明確印出，讓人看得到這次沒有重播
        print(f"⚠️ 門檻重播略過（取得掃描結果失敗）：{str(e)[:150]}")
        return 0
    if not runs:
        print("ℹ️ 門檻重播：沒有可用的掃描結果（尚無排程留存，或已過保存期），略過。")
        return 0
    regress, improved = compare(runs)
    print(f"門檻重播：{len(runs)} 份真實掃描結果，退步 {len(regress)}、改善 {len(improved)}")
    for line in improved:
        print(f"  ✅ {line}")
    for line in regress:
        print(f"  ❌ {line}", file=sys.stderr)
    if regress:
        if SKIP_MARK in os.environ.get("PR_BODY", ""):
            print(f"⚠️ PR 描述含「{SKIP_MARK}」，退步已知，放行。")
            return 0
        print(f"❌ 門檻變更會擋下過去放行的真實資料。確屬刻意收緊，請在 PR 描述寫「{SKIP_MARK}」並說明原因。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
