#!/usr/bin/env python3
"""排程健康檢查：確認 GitHub Actions 排程工作流近期有如期成功執行。僅用標準函式庫。

每個被檢查的工作流，取它最近一次 event=schedule 的執行，必須同時符合：
- 距今不超過該工作流的容許時數（見 WINDOWS，已含週末與排程延遲的餘裕）；
- 已完成的執行結論必須是 success（仍在進行中則不判定結論）。
還沒有任何排程執行的工作流，從它的建立時間起算，超過容許時數才算失敗（新工作流還沒輪到第一次排程）。

資料來源：GitHub REST API，需要 GITHUB_TOKEN（工作流 permissions 需 actions: read）。
只涵蓋 GitHub Actions 排程；雲端排程不在 GitHub 上，不在此檢查範圍。

用法（CI 的 schedule-health 工作會呼叫）：
    GITHUB_REPOSITORY=owner/repo GITHUB_TOKEN=... python3 schedule_health.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# 工作流檔名 → 容許時數。平日排程容許週末與排程延遲（週五 17:00 的執行到週一中午已超過 72 小時）；
# 週五排程容許一週再加餘裕。
WINDOWS = {"swing-patrol.yml": 96, "market-etf.yml": 192}
RUNS_API = "https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?event=schedule&per_page=1"
WORKFLOW_API = "https://api.github.com/repos/{repo}/actions/workflows/{wf}"


def parse_time(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def evaluate(latest: dict, created: dict, now: datetime, windows: dict = WINDOWS) -> list:
    """latest：{工作流檔名: 最近一次排程執行（dict），沒有則為 None}；created：{工作流檔名: 工作流建立時間}。
    回傳問題清單，空清單代表正常。"""
    problems = []
    for wf, max_hours in windows.items():
        run = latest.get(wf)
        if not run:
            waited = (now - created[wf]).total_seconds() / 3600
            if waited > max_hours:
                problems.append(f"{wf}：建立 {waited:.0f} 小時後仍沒有任何排程執行紀錄（容許 {max_hours} 小時）")
            continue
        age = (now - parse_time(run["created_at"])).total_seconds() / 3600
        if age > max_hours:
            problems.append(f"{wf}：最近一次排程在 {age:.0f} 小時前（容許 {max_hours} 小時）")
        if run.get("status") == "completed" and run.get("conclusion") != "success":
            problems.append(f"{wf}：最近一次排程結論為 {run.get('conclusion')}")
    return problems


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def latest_schedule_run(repo: str, wf: str, token: str):
    runs = _get(RUNS_API.format(repo=repo, wf=wf), token).get("workflow_runs") or []
    return runs[0] if runs else None


def workflow_created_at(repo: str, wf: str, token: str) -> datetime:
    return datetime.fromisoformat(_get(WORKFLOW_API.format(repo=repo, wf=wf), token)["created_at"])


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        print("❌ 缺少 GITHUB_REPOSITORY 或 GITHUB_TOKEN，無法查詢排程紀錄。", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    latest = {wf: latest_schedule_run(repo, wf, token) for wf in WINDOWS}
    created = {wf: workflow_created_at(repo, wf, token) for wf in WINDOWS}
    for wf, run in latest.items():
        if run:
            print(f"  {wf}：最近一次排程 {run['created_at']}，狀態 {run.get('conclusion') or run.get('status')}")
        else:
            print(f"  {wf}：沒有排程紀錄（工作流建立於 {created[wf]:%Y-%m-%d}）")
    problems = evaluate(latest, created, now)
    for p in problems:
        print(f"❌ {p}", file=sys.stderr)
    if problems:
        return 1
    print("✅ 排程近期都有如期成功執行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
