#!/usr/bin/env python3
"""排程失敗即時通報：失敗當下在 GitHub 開 Issue（Hachi 會收到通知信），恢復後自動留言並關閉。僅用標準函式庫。

為什麼：失敗通報原本只靠每日 20:17 的健康檢查，且訊息分不出「沒跑」與「跑了但失敗」；2026-11-13 的失敗發生在台北凌晨，
到隔天有人問才被查。現在排程的最後一步在失敗當下呼叫本腳本，Issue 內附失敗原因與執行連結。
同一個工作流同時只維持一個未關閉的失敗 Issue（標籤 `schedule-failure`、標題含工作流檔名），再次失敗只追加留言，避免洗版。

用法（工作流最後一步，需 permissions: issues: write）：
    python3 schedule_notify.py fail    --workflow swing-patrol.yml --log /tmp/run.log
    python3 schedule_notify.py resolve --workflow swing-patrol.yml
環境變數：GITHUB_REPOSITORY、GITHUB_TOKEN、GITHUB_SERVER_URL、GITHUB_RUN_ID、GITHUB_EVENT_NAME（工作流內建）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

LABEL = "schedule-failure"
API = "https://api.github.com/repos/{repo}"
KEY_MARKS = ("❌", "⚠️", "Error", "Traceback", "error:", "超標", "異常")


def title_of(workflow: str) -> str:
    return f"排程失敗：{workflow}"


def failure_excerpt(log_text: str, max_lines: int = 25, max_chars: int = 3000) -> str:
    """從日誌取失敗原因：優先含 ❌／⚠️／Error 的行，沒有就取最後幾行。不含任何 secrets（日誌本身已被 Actions 遮蔽），仍限制長度。"""
    lines = [ln.rstrip() for ln in log_text.splitlines() if ln.strip()]
    key = [ln for ln in lines if any(m in ln for m in KEY_MARKS)]
    picked = (key or lines)[-max_lines:]
    return "\n".join(picked)[-max_chars:]


def build_body(workflow: str, run_url: str, event: str, excerpt: str) -> str:
    return (
        f"`{workflow}` 這次**已執行但失敗**（觸發方式：{event}），不是漏跑。\n\n"
        f"- 執行紀錄：{run_url}\n\n"
        f"失敗原因（取自日誌）：\n\n```text\n{excerpt or '（日誌沒有可擷取的內容，請直接看執行紀錄）'}\n```\n\n"
        "同一個工作流恢復成功後，這個 Issue 會自動留言並關閉；失敗期間再次失敗只會追加留言。\n"
    )


def _req(method: str, url: str, token: str, body: Optional[dict] = None) -> Any:
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def find_open_issue(repo: str, token: str, workflow: str, req=_req) -> Optional[Dict[str, Any]]:
    items: List[Dict[str, Any]] = req("GET", API.format(repo=repo) + f"/issues?state=open&labels={LABEL}&per_page=50", token)
    return next((i for i in items if i.get("title") == title_of(workflow) and "pull_request" not in i), None)


def notify_fail(repo: str, token: str, workflow: str, run_url: str, event: str, excerpt: str, req=_req) -> str:
    body = build_body(workflow, run_url, event, excerpt)
    found = find_open_issue(repo, token, workflow, req)
    base = API.format(repo=repo)
    if found:
        req("POST", f"{base}/issues/{found['number']}/comments", token, {"body": body})
        return f"已在 Issue #{found['number']} 追加留言"
    made = req("POST", f"{base}/issues", token, {"title": title_of(workflow), "body": body, "labels": [LABEL]})
    return f"已開 Issue #{made.get('number')}"


def notify_resolve(repo: str, token: str, workflow: str, run_url: str, req=_req) -> str:
    found = find_open_issue(repo, token, workflow, req)
    if not found:
        return "沒有未關閉的失敗 Issue"
    base = API.format(repo=repo)
    req("POST", f"{base}/issues/{found['number']}/comments", token, {"body": f"已恢復：最近一次執行成功（{run_url}），自動關閉。"})
    req("PATCH", f"{base}/issues/{found['number']}", token, {"state": "closed", "state_reason": "completed"})
    return f"已關閉 Issue #{found['number']}"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="排程失敗即時通報")
    ap.add_argument("mode", choices=["fail", "resolve"])
    ap.add_argument("--workflow", required=True, help="工作流檔名，例如 swing-patrol.yml")
    ap.add_argument("--log", help="fail 模式：執行日誌檔，用來擷取失敗原因")
    a = ap.parse_args(argv)
    repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_TOKEN", "")
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    if not repo or not token:
        print("❌ 缺少 GITHUB_REPOSITORY 或 GITHUB_TOKEN，無法通報。", file=sys.stderr)
        return 2
    try:
        if a.mode == "fail":
            text = Path(a.log).read_text(encoding="utf-8", errors="replace") if a.log and Path(a.log).exists() else ""
            print(notify_fail(repo, token, a.workflow, run_url, os.environ.get("GITHUB_EVENT_NAME", "未知"), failure_excerpt(text)))
        else:
            print(notify_resolve(repo, token, a.workflow, run_url))
    except OSError as e:
        # 通報本身失敗不該讓成功的排程變紅，也不該掩蓋原本的失敗；印出來即可
        print(f"⚠️ 通報失敗：{str(e)[:150]}", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
