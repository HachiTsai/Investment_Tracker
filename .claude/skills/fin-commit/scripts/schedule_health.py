#!/usr/bin/env python3
"""排程健康檢查：確認 GitHub Actions 排程工作流近期有如期成功執行。僅用標準函式庫。

每個被檢查的工作流，取它最近一次排程或手動（workflow_dispatch）執行，必須同時符合：
- 距今不超過該工作流的容許時數（見 WINDOWS，已含週末與排程延遲的餘裕）；
- 已完成的執行結論必須是 success（仍在進行中則不判定結論）。
還沒有任何排程執行的工作流，從它的建立時間起算，超過容許時數才算失敗（新工作流還沒輪到第一次排程）。

漏跑自動補跑（--dispatch，2026-11-09 Hachi 同意，見 Issue #232）：DISPATCH 內的工作流，若自「最近一個已過寬限時數的
cron 時點」以來沒有任何成功執行、也沒有執行中的 run，就補送一次 workflow_dispatch（需 actions: write）。
cron 直接讀 .github/workflows/<檔名>，不另寫一份。補送成功只印警告不算失敗；補送失敗才算問題。

資料來源：GitHub REST API，需要 GITHUB_TOKEN（工作流 permissions 需 actions: read；--dispatch 需 actions: write）。
只涵蓋 GitHub Actions 排程；雲端排程不在 GitHub 上，不在此檢查範圍。

用法（CI 的 schedule-health 工作會呼叫）：
    GITHUB_REPOSITORY=owner/repo GITHUB_TOKEN=... python3 schedule_health.py [--dispatch]
"""
from __future__ import annotations

import json
import os
import sys
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 工作流檔名 → 容許時數。平日排程容許週末與排程延遲（週五 17:00 的執行到週一中午已超過 72 小時）；
# 週五排程容許一週再加餘裕。
WINDOWS = {"swing-patrol.yml": 96, "market-etf.yml": 192}
RUNS_API = "https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?per_page=20"
WORKFLOW_API = "https://api.github.com/repos/{repo}/actions/workflows/{wf}"
DISPATCH_API = "https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches"
COUNTED_EVENTS = ("schedule", "workflow_dispatch")
IN_FLIGHT = ("queued", "in_progress", "waiting", "requested", "pending")
# 漏跑自動補跑的工作流與 dispatch inputs。swing-patrol 帶 force：補跑多半落在週末，不穿透休市判定會略過不寫。
# market-etf 不自動補：手動執行常指定其他市場（hk/us/jp），從執行紀錄分不出是否等同排程，只回報。
DISPATCH = {"swing-patrol.yml": {"force": "true"}}
GRACE_HOURS = 12  # GitHub 排程常晚 6～10 小時才建立，cron 時點過 12 小時仍沒成功才算漏跑
WORKFLOWS_DIR = Path(__file__).resolve().parents[4] / ".github" / "workflows"


def parse_time(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_cron(expr: str):
    """只支援本 repo 用到的形式：`分 時 * * 星期`（星期為 *、單一數字、a-b 或逗號清單，0 與 7 皆為週日）。"""
    minute, hour, _dom, _mon, dow = expr.split()
    days = set()
    for part in (dow.split(",") if dow != "*" else ["0-6"]):
        a, _, b = part.partition("-")
        days.update(range(int(a), int(b or a) + 1))
    return int(minute), int(hour), {d % 7 for d in days}


def read_cron(wf: str, workflows_dir: Path = WORKFLOWS_DIR) -> str:
    m = re.search(r"""-\s*cron:\s*["']([^"']+)["']""", (workflows_dir / wf).read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"{wf} 沒有 cron")
    return m.group(1)


def last_due(cron: str, now: datetime, grace_hours: float = GRACE_HOURS) -> datetime:
    """回傳不晚於 now - grace 的最近一個 cron 時點（UTC）。"""
    minute, hour, days = parse_cron(cron)
    limit = now - timedelta(hours=grace_hours)
    for back in range(0, 9):
        d = (limit - timedelta(days=back)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if d <= limit and d.isoweekday() % 7 in days:
            return d
    raise ValueError(f"cron `{cron}` 一週內沒有時點")


def needs_dispatch(runs: list, due: datetime) -> bool:
    """due 之後沒有任何成功的排程或手動執行，且目前沒有執行中的 run，才需要補送。"""
    runs = [r for r in runs if r.get("event") in COUNTED_EVENTS]
    if any(r.get("status") in IN_FLIGHT for r in runs):
        return False
    return not any(r.get("conclusion") == "success" and parse_time(r["created_at"]) >= due for r in runs)


def evaluate(latest: dict, created: dict, now: datetime, windows: dict = WINDOWS) -> list:
    """latest：{工作流檔名: 最近一次排程執行（dict），沒有則為 None}；created：{工作流檔名: 工作流建立時間}。
    回傳問題清單，空清單代表正常。"""
    problems = []
    for wf, max_hours in windows.items():
        run = latest.get(wf)
        if not run:
            waited = (now - created[wf]).total_seconds() / 3600
            if waited > max_hours:
                problems.append(f"{wf}：建立 {waited:.0f} 小時後仍沒有任何執行紀錄（容許 {max_hours} 小時）")
            continue
        age = (now - parse_time(run["created_at"])).total_seconds() / 3600
        if age > max_hours:
            problems.append(f"{wf}：最近一次執行在 {age:.0f} 小時前（容許 {max_hours} 小時）")
        if run.get("status") == "completed" and run.get("conclusion") != "success":
            problems.append(f"{wf}：最近一次執行結論為 {run.get('conclusion')}")
    return problems


def _get(url: str, token: str, body: dict = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def recent_runs(repo: str, wf: str, token: str) -> list:
    """最近的排程與手動執行（新到舊）。"""
    runs = _get(RUNS_API.format(repo=repo, wf=wf), token).get("workflow_runs") or []
    return [r for r in runs if r.get("event") in COUNTED_EVENTS]


def dispatch(repo: str, wf: str, token: str, inputs: dict, ref: str = "main") -> None:
    _get(DISPATCH_API.format(repo=repo, wf=wf), token, body={"ref": ref, "inputs": inputs})


def workflow_created_at(repo: str, wf: str, token: str) -> datetime:
    return datetime.fromisoformat(_get(WORKFLOW_API.format(repo=repo, wf=wf), token)["created_at"])


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        print("❌ 缺少 GITHUB_REPOSITORY 或 GITHUB_TOKEN，無法查詢排程紀錄。", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    runs = {wf: recent_runs(repo, wf, token) for wf in WINDOWS}
    latest = {wf: (r[0] if r else None) for wf, r in runs.items()}
    created = {wf: workflow_created_at(repo, wf, token) for wf in WINDOWS}
    for wf, run in latest.items():
        if run:
            print(f"  {wf}：最近一次執行（{run.get('event')}）{run['created_at']}，狀態 {run.get('conclusion') or run.get('status')}")
        else:
            print(f"  {wf}：沒有執行紀錄（工作流建立於 {created[wf]:%Y-%m-%d}）")
    problems = evaluate(latest, created, now)
    for wf, inputs in DISPATCH.items():
        due = last_due(read_cron(wf), now)
        if not needs_dispatch(runs.get(wf) or [], due):
            continue
        if "--dispatch" not in sys.argv[1:]:
            print(f"⚠️ {wf}：{due:%Y-%m-%d %H:%M}Z 的排程之後沒有成功執行（未加 --dispatch，不補送）")
            continue
        try:
            dispatch(repo, wf, token, inputs)
            print(f"⚠️ {wf}：{due:%Y-%m-%d %H:%M}Z 的排程之後沒有成功執行，已補送 workflow_dispatch（inputs {inputs}）")
        except OSError as e:
            problems.append(f"{wf}：漏跑但補送 workflow_dispatch 失敗：{str(e)[:120]}")
    for p in problems:
        print(f"❌ {p}", file=sys.stderr)
    if problems:
        return 1
    print("✅ 排程近期都有如期成功執行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
