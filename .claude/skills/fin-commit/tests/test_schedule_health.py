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
    assert sh.evaluate(latest, CREATED, NOW) == ["swing-patrol.yml：最近一次執行結論為 failure"]


def test_running_job_has_no_conclusion_problem():
    latest = {
        "swing-patrol.yml": _run("2026-10-28T09:00:00Z", conclusion=None, status="in_progress"),
        "market-etf.yml": _run("2026-10-24T09:10:00Z"),
    }
    assert sh.evaluate(latest, CREATED, NOW) == []


def test_recent_runs_keeps_schedule_and_dispatch(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Authorization")
        runs = [dict(_run("2026-10-27T09:00:00Z"), event="schedule"), dict(_run("2026-10-26T09:00:00Z"), event="push"),
                dict(_run("2026-10-25T09:00:00Z"), event="workflow_dispatch")]
        return io.BytesIO(json.dumps({"workflow_runs": runs}).encode())

    monkeypatch.setattr(sh.urllib.request, "urlopen", fake_urlopen)
    runs = sh.recent_runs("owner/repo", "swing-patrol.yml", "tok")
    assert [r["event"] for r in runs] == ["schedule", "workflow_dispatch"]
    assert seen["url"] == "https://api.github.com/repos/owner/repo/actions/workflows/swing-patrol.yml/runs?per_page=20"
    assert seen["auth"] == "Bearer tok"


def _ev(created, event="schedule", conclusion="success", status="completed"):
    return {"created_at": created, "event": event, "conclusion": conclusion, "status": status}


def test_parse_cron_weekdays_and_single_day():
    assert sh.parse_cron("23 9 * * 1-5") == (23, 9, {1, 2, 3, 4, 5})
    assert sh.parse_cron("37 9 * * 5") == (37, 9, {5})
    assert sh.parse_cron("0 1 * * 7") == (0, 1, {0})


def test_read_cron_matches_repo_yml():
    assert sh.parse_cron(sh.read_cron("swing-patrol.yml"))[2] == {1, 2, 3, 4, 5}


def test_last_due_respects_grace_and_weekend():
    cron = "23 9 * * 1-5"
    # 週六 2026-11-07 17:45Z：週五 09:23Z 已過 12 小時 → 週五
    assert sh.last_due(cron, datetime(2026, 11, 7, 17, 45, tzinfo=timezone.utc)) == datetime(2026, 11, 6, 9, 23, tzinfo=timezone.utc)
    # 週一 2026-11-09 17:45Z：當天 09:23Z 才過 8 小時 → 仍是上週五
    assert sh.last_due(cron, datetime(2026, 11, 9, 17, 45, tzinfo=timezone.utc)) == datetime(2026, 11, 6, 9, 23, tzinfo=timezone.utc)
    # 週二 2026-11-10 22:00Z：週二 09:23Z 已過 12 小時 → 週二
    assert sh.last_due(cron, datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc)) == datetime(2026, 11, 10, 9, 23, tzinfo=timezone.utc)


def test_missed_friday_run_needs_dispatch():
    """2026-11-06 實例：週五排程被吃掉，只有當天早上的手動執行（早於 cron 時點），週六應補送。"""
    due = datetime(2026, 11, 6, 9, 23, tzinfo=timezone.utc)
    runs = [_ev("2026-11-06T07:35:47Z", "workflow_dispatch"), _ev("2026-11-05T17:13:28Z")]
    assert sh.needs_dispatch(runs, due) is True


def test_delayed_success_or_manual_rerun_counts():
    due = datetime(2026, 11, 6, 9, 23, tzinfo=timezone.utc)
    assert sh.needs_dispatch([_ev("2026-11-06T16:57:00Z")], due) is False
    assert sh.needs_dispatch([_ev("2026-11-07T18:00:00Z", "workflow_dispatch")], due) is False


def test_in_flight_or_failed_runs():
    due = datetime(2026, 11, 6, 9, 23, tzinfo=timezone.utc)
    assert sh.needs_dispatch([_ev("2026-11-07T18:00:00Z", conclusion=None, status="in_progress")], due) is False
    assert sh.needs_dispatch([_ev("2026-11-06T17:00:00Z", conclusion="failure")], due) is True


def test_dispatch_posts_ref_and_inputs(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["method"], seen["body"] = req.full_url, req.get_method(), json.loads(req.data)
        return io.BytesIO(b"")

    monkeypatch.setattr(sh.urllib.request, "urlopen", fake_urlopen)
    sh.dispatch("owner/repo", "swing-patrol.yml", "tok", {"force": "true"})
    assert seen["url"] == "https://api.github.com/repos/owner/repo/actions/workflows/swing-patrol.yml/dispatches"
    assert seen["method"] == "POST"
    assert seen["body"] == {"ref": "main", "inputs": {"force": "true"}}


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
