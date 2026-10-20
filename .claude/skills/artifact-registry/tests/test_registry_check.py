import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import registry_check as rc  # noqa: E402

NOW = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)


def _reg(tmp_path):
    f = tmp_path / "s.py"
    f.write_text("x")
    return {
        "artifacts": [
            {"name": "A", "url": "u1", "kind": "scheduled", "trigger": "T", "max_age_hours": 30, "files": ["s.py"]},
            {"name": "M", "url": "u2", "kind": "manual"},
        ],
        "triggers": ["T"],
        "drive_public": [{"id": "d1", "name": "Sheet", "reason": "APP"}],
    }


def _live(**over):
    live = {
        "artifacts": [{"url": "u1", "updated_at": "2026-10-20T01:00:00Z"}, {"url": "u2", "updated_at": "2026-01-01T00:00:00Z"}],
        "triggers": [{"name": "T", "enabled": True, "last_run_ok": True}],
        "drive": [{"id": "d1", "public": True}],
    }
    live.update(over)
    return live


def codes(alerts):
    return sorted(a["code"] for a in alerts)


def test_all_good(tmp_path):
    assert rc.check(_reg(tmp_path), _live(), tmp_path, NOW) == []


def test_stale_only_for_scheduled(tmp_path):
    live = _live(artifacts=[{"url": "u1", "updated_at": "2026-10-18T00:00:00Z"}, {"url": "u2", "updated_at": "2020-01-01T00:00:00Z"}])
    assert codes(rc.check(_reg(tmp_path), live, tmp_path, NOW)) == ["stale"]


def test_missing_script(tmp_path):
    reg = _reg(tmp_path)
    (tmp_path / "s.py").unlink()
    assert codes(rc.check(reg, _live(), tmp_path, NOW)) == ["script_missing"]


def test_trigger_disabled_failed_missing(tmp_path):
    reg = _reg(tmp_path)
    live = _live(triggers=[{"name": "T", "enabled": False, "last_run_ok": False}])
    assert codes(rc.check(reg, live, tmp_path, NOW)) == ["trigger_disabled", "trigger_failed"]
    assert "trigger_missing" in codes(rc.check(reg, _live(triggers=[]), tmp_path, NOW))


def test_unregistered_and_missing_artifact(tmp_path):
    live = _live(artifacts=[{"url": "u9", "updated_at": "2026-10-20T00:00:00Z"}])
    assert codes(rc.check(_reg(tmp_path), live, tmp_path, NOW)) == [
        "artifact_missing", "artifact_missing", "unregistered_artifact"]


def test_unregistered_trigger(tmp_path):
    live = _live(triggers=[{"name": "T"}, {"name": "X"}])
    assert codes(rc.check(_reg(tmp_path), live, tmp_path, NOW)) == ["unregistered_trigger"]


def test_drive_not_public(tmp_path):
    assert codes(rc.check(_reg(tmp_path), _live(drive=[{"id": "d1", "public": False}]), tmp_path, NOW)) == ["drive_not_public"]


def test_real_registry_is_consistent():
    reg = json.loads((ROOT / "references" / "registry.json").read_text(encoding="utf-8"))
    repo = ROOT.parent.parent.parent
    sched = [a for a in reg["artifacts"] if a["kind"] == "scheduled"]
    assert {a["trigger"] for a in sched} == set(reg["triggers"])
    for a in sched:
        for f in a["files"]:
            assert (repo / f).exists(), f


def test_main_exit_code(tmp_path, capsys):
    reg = tmp_path / "r.json"
    reg.write_text(json.dumps(_reg(tmp_path)))
    live = tmp_path / "l.json"
    live.write_text(json.dumps(_live(drive=[])))
    assert rc.main(["--registry", str(reg), "--live", str(live), "--root", str(tmp_path), "--now", "2026-10-20T08:00:00Z"]) == 1
    assert "drive_not_public" in capsys.readouterr().out
