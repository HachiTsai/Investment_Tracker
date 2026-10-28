import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location("it_schedule_health", Path(__file__).parent.parent / "scripts" / "schedule_health.py")
sh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sh)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
OLD = datetime(2026, 10, 1, tzinfo=timezone.utc)
CREATED = {"swing-patrol.yml": OLD, "market-etf.yml": OLD}


def _run(created, conclusion="success", status="completed"):
    return {"created_at": created, "conclusion": conclusion, "status": status}


def test_recent_successful_runs_pass():
    latest = {"swing-patrol.yml": _run("2026-10-27T09:00:00Z"), "market-etf.yml": _run("2026-10-24T09:10:00Z")}
    assert sh.evaluate(latest, CREATED, NOW) == []


def test_weekend_gap_is_allowed():
    monday_noon = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    latest = {"swing-patrol.yml": _run("2026-10-23T09:00:00Z"), "market-etf.yml": _run("2026-10-23T09:10:00Z")}
    assert sh.evaluate(latest, CREATED, monday_noon) == []


def test_new_workflow_without_runs_is_not_due_yet():
    created = {"swing-patrol.yml": OLD, "market-etf.yml": datetime(2026, 10, 25, 3, 18, tzinfo=timezone.utc)}
    latest = {"swing-patrol.yml": _run("2026-10-27T15:13:34Z"), "market-etf.yml": None}
    assert sh.evaluate(latest, created, NOW) == []


def test_workflow_without_runs_past_window_is_reported():
    created = {"swing-patrol.yml": OLD, "market-etf.yml": datetime(2026, 10, 15, tzinfo=timezone.utc)}
    latest = {"swing-patrol.yml": _run("2026-10-27T09:00:00Z"), "market-etf.yml": None}
    problems = sh.evaluate(latest, created, NOW)
    assert len(problems) == 1 and problems[0].startswith("market-etf.yml") and "容許 192 小時" in problems[0]


def test_stale_run_is_reported():
    latest = {"swing-patrol.yml": _run("2026-10-22T09:00:00Z"), "market-etf.yml": _run("2026-10-24T09:10:00Z")}
    problems = sh.evaluate(latest, CREATED, NOW)
    assert len(problems) == 1 and "swing-patrol.yml" in problems[0] and "容許 96 小時" in problems[0]


def test_failed_conclusion_is_reported():
    latest = {"swing-patrol.yml": _run("2026-10-27T09:00:00Z", conclusion="failure"), "market-etf.yml": _run("2026-10-24T09:10:00Z")}
    assert sh.evaluate(latest, CREATED, NOW) == ["swing-patrol.yml：最近一次排程結論為 failure"]


def test_running_job_has_no_conclusion_problem():
    latest = {
        "swing-patrol.yml": _run("2026-10-28T09:00:00Z", conclusion=None, status="in_progress"),
        "market-etf.yml": _run("2026-10-24T09:10:00Z"),
    }
    assert sh.evaluate(latest, CREATED, NOW) == []


def test_latest_schedule_run_queries_schedule_events(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Authorization")
        return io.BytesIO(json.dumps({"workflow_runs": [_run("2026-10-27T09:00:00Z")]}).encode())

    monkeypatch.setattr(sh.urllib.request, "urlopen", fake_urlopen)
    run = sh.latest_schedule_run("owner/repo", "swing-patrol.yml", "tok")
    assert run["created_at"] == "2026-10-27T09:00:00Z"
    assert seen["url"] == "https://api.github.com/repos/owner/repo/actions/workflows/swing-patrol.yml/runs?event=schedule&per_page=1"
    assert seen["auth"] == "Bearer tok"


def test_workflow_created_at_reads_creation_time(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return io.BytesIO(json.dumps({"created_at": "2026-10-25T11:18:50.000+08:00"}).encode())

    monkeypatch.setattr(sh.urllib.request, "urlopen", fake_urlopen)
    created = sh.workflow_created_at("owner/repo", "market-etf.yml", "tok")
    assert created == datetime(2026, 10, 25, 3, 18, 50, tzinfo=timezone.utc)
    assert seen["url"] == "https://api.github.com/repos/owner/repo/actions/workflows/market-etf.yml"


def test_main_requires_repo_and_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert sh.main() == 2
