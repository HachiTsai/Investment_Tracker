#!/usr/bin/env python3
"""Artifact／排程／腳本斷鏈檢查（唯讀，只用標準函式庫）。

用法：registry_check.py --live live.json [--registry PATH] [--root REPO] [--now ISO8601]
live.json 由排程 session 現場蒐集後寫入：
  {"artifacts": [{"url", "updated_at"}], "triggers": [{"name", "enabled", "last_run_ok"}],
   "drive": [{"id", "public"}]}
輸出 JSON：{"alerts": [{"level", "code", "subject", "message"}]}；有 alert 時結束碼 1。
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "references" / "registry.json"


def _parse(ts):
    d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _alert(level, code, subject, message):
    return {"level": level, "code": code, "subject": subject, "message": message}


def check(registry, live, root, now):
    alerts = []
    arts = {a["url"]: a for a in live.get("artifacts", [])}
    trigs = {t["name"]: t for t in live.get("triggers", [])}
    drive = {d["id"]: d for d in live.get("drive", [])}
    reg_urls = {a["url"] for a in registry["artifacts"]}

    for a in registry["artifacts"]:
        name = a["name"]
        live_a = arts.get(a["url"])
        if live_a is None:
            alerts.append(_alert("high", "artifact_missing", name, "登記簿有，但帳號 Artifact 清單找不到（被刪除或網址改變）"))
        elif a["kind"] == "scheduled" and live_a.get("updated_at"):
            age_h = (now - _parse(live_a["updated_at"])).total_seconds() / 3600
            if age_h > a["max_age_hours"]:
                alerts.append(_alert("high", "stale", name, f"已 {age_h:.0f} 小時沒更新（上限 {a['max_age_hours']} 小時）"))
        if a["kind"] == "scheduled":
            t = trigs.get(a["trigger"])
            if t is None:
                alerts.append(_alert("high", "trigger_missing", name, f"排程「{a['trigger']}」不存在"))
            else:
                if not t.get("enabled", True):
                    alerts.append(_alert("high", "trigger_disabled", name, f"排程「{a['trigger']}」已停用"))
                if t.get("last_run_ok") is False:
                    alerts.append(_alert("high", "trigger_failed", name, f"排程「{a['trigger']}」最近一次執行失敗"))
            for f in a.get("files", []):
                if not (Path(root) / f).exists():
                    alerts.append(_alert("high", "script_missing", name, f"repo 找不到 {f}"))

    for url, live_a in arts.items():
        if url not in reg_urls:
            alerts.append(_alert("medium", "unregistered_artifact", live_a.get("name", url), f"帳號有但登記簿沒有：{url}"))
    for tname in trigs:
        if tname not in registry["triggers"]:
            alerts.append(_alert("medium", "unregistered_trigger", tname, "排程存在但登記簿沒有"))
    for tname in registry["triggers"]:
        if tname not in trigs:
            alerts.append(_alert("high", "trigger_missing", tname, "登記簿有此排程，但清單找不到"))

    for d in registry.get("drive_public", []):
        live_d = drive.get(d["id"])
        if live_d is None or not live_d.get("public"):
            alerts.append(_alert("high", "drive_not_public", d["name"], f"未公開，影響：{d['reason']}"))
    return alerts


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    p.add_argument("--live", required=True)
    p.add_argument("--root", default=".")
    p.add_argument("--now")
    a = p.parse_args(argv)
    registry = json.loads(Path(a.registry).read_text(encoding="utf-8"))
    live = json.loads(Path(a.live).read_text(encoding="utf-8"))
    now = _parse(a.now) if a.now else datetime.now(timezone.utc)
    alerts = check(registry, live, a.root, now)
    print(json.dumps({"alerts": alerts}, ensure_ascii=False, indent=2))
    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
