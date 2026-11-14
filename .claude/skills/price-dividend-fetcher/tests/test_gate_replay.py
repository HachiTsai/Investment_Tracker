import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import gate_replay as gr  # noqa: E402


def _row(t, state="UPTREND"):
    return {"ticker": t, "state": state, "fresh": True, "market": "台股", "last_date": "2026-11-13"}


def _run(name, n_ok, n_bad, rc):
    rows = [_row(f"O{i}") for i in range(n_ok)] + [_row(f"E{i}", "ERROR") for i in range(n_bad)]
    return {"name": name, "rows": rows, "verdict": {"returncode": rc, "scanned_at": "2026-11-13T09:30:00Z"}}


def test_compare_detects_regression_and_improvement():
    ok_then_ok = _run("a", 100, 5, 0)
    ok_then_blocked = _run("b", 70, 30, 0)   # 30%：現行門檻會擋，當時放行 -> 退步
    blocked_then_ok = _run("c", 100, 5, 1)   # 當時被擋、現在放行 -> 改善
    regress, improved = gr.compare([ok_then_ok, ok_then_blocked, blocked_then_ok])
    assert len(regress) == 1 and regress[0].startswith("b：")
    assert len(improved) == 1 and improved[0].startswith("c：")


def test_main_dir_and_skip_mark(tmp_path, monkeypatch, capsys):
    for name, run in (("r1", _run("r1", 70, 30, 0)),):
        d = tmp_path / name
        d.mkdir()
        (d / "scan.json").write_text(json.dumps(run["rows"]), encoding="utf-8")
        (d / "scan_gate.json").write_text(json.dumps(run["verdict"]), encoding="utf-8")
    monkeypatch.delenv("PR_BODY", raising=False)
    assert gr.main(["--dir", str(tmp_path)]) == 1
    monkeypatch.setenv("PR_BODY", "刻意收緊。重播例外：改為更嚴格的比例")
    assert gr.main(["--dir", str(tmp_path)]) == 0


def test_main_empty_dir_is_not_failure(tmp_path, capsys):
    assert gr.main(["--dir", str(tmp_path)]) == 0
    assert "沒有可用" in capsys.readouterr().out


def test_fetch_runs_reads_zip(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("scan.json", json.dumps([_row("A")]))
        z.writestr("scan_gate.json", json.dumps({"returncode": 0}))
    monkeypatch.setattr(gr, "_api", lambda url, token: {"artifacts": [
        {"archive_download_url": "u1", "created_at": "2026-11-13T09:00:00Z", "workflow_run": {"id": 9}},
        {"archive_download_url": "u2", "expired": True}]})
    monkeypatch.setattr(gr, "_download", lambda url, token: buf.getvalue())
    runs = gr.fetch_runs("o/r", "t")
    assert len(runs) == 1 and runs[0]["verdict"]["returncode"] == 0 and "run 9" in runs[0]["name"]


def test_main_download_failure_does_not_block(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(gr, "fetch_runs", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert gr.main([]) == 0
    assert "略過" in capsys.readouterr().out
