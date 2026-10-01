import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import manifest as m  # noqa: E402

SNAP = {"id": "doc1", "title": "持股快照_2026-10-01", "mimeType": "application/vnd.google-apps.document",
        "modifiedTime": "2026-10-01T05:38:44.160Z", "source": "folder"}
CORE = {"id": m.CORE_ID, "title": "Investment_Tracker_Core", "mimeType": "application/vnd.google-apps.spreadsheet",
        "modifiedTime": "2026-08-11T01:29:06.606Z", "source": "core"}
ROWS = {"Transactions": ["202601001", "ad364a04"], "Stock_Journal": ["03cf539a"]}


def scan(files, rows=None, at="2026-10-01T07:00:00Z"):
    s = {"scanned_at": at, "files": files}
    if rows is not None:
        s["core_rows"] = rows
    return s


def baseline():
    return m.apply_scan(m.load_manifest(Path("/nonexistent")), scan([SNAP, CORE], ROWS))


def test_first_scan_reports_everything_new():
    d = m.diff({"files": {}, "core_rows": {}}, scan([SNAP, CORE], ROWS))
    assert {f["id"] for f in d["new"]} == {"doc1", m.CORE_ID}
    assert len(d["core_new_rows"]) == 3


def test_no_changes():
    d = m.diff(baseline(), scan([SNAP, CORE]))
    assert d == {"new": [], "modified": [], "deleted": [], "core_new_rows": [], "core_rows_needed": False}


def test_new_modified_deleted_files():
    new_doc = dict(SNAP, id="doc2", title="持股快照_2026-11-01")
    d = m.diff(baseline(), scan([new_doc, CORE]))
    assert [f["id"] for f in d["new"]] == ["doc2"]
    assert [f["id"] for f in d["deleted"]] == ["doc1"]
    edited = dict(SNAP, modifiedTime="2026-10-02T00:00:00Z")
    assert [f["id"] for f in m.diff(baseline(), scan([edited, CORE]))["modified"]] == ["doc1"]


def test_core_change_requires_rows_then_reports_new_ids():
    core2 = dict(CORE, modifiedTime="2026-10-15T00:00:00Z")
    assert m.diff(baseline(), scan([SNAP, core2]))["core_rows_needed"] is True
    rows2 = {"Transactions": ROWS["Transactions"] + ["newtx01"], "Stock_Journal": ROWS["Stock_Journal"]}
    d = m.diff(baseline(), scan([SNAP, core2], rows2))
    assert d["core_new_rows"] == [{"sheet": "Transactions", "id": "newtx01"}]
    assert d["core_rows_needed"] is False


def test_apply_scan_keeps_imported_to_and_old_rows():
    base = baseline()
    base["files"]["doc1"]["imported_to"] = "portfolio/snapshots/2026-10-01.md"
    updated = m.apply_scan(base, scan([SNAP, CORE], at="2026-10-02T00:00:00Z"))
    assert updated["files"]["doc1"]["imported_to"] == "portfolio/snapshots/2026-10-01.md"
    assert updated["core_rows"] == ROWS
    assert updated["last_scan"] == "2026-10-02T00:00:00Z"


def test_validate_scan():
    assert m.validate_scan(scan([SNAP, CORE])) == []
    assert any("Investment_Tracker_Core" in e for e in m.validate_scan(scan([SNAP])))
    assert any("modifiedTime" in e for e in m.validate_scan(scan([dict(SNAP, modifiedTime=""), CORE])))
    assert m.validate_scan({"files": []})


def test_cli_update_diff_link_roundtrip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(m, "MANIFEST_PATH", tmp_path / "manifest.json")
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(scan([SNAP, CORE], ROWS)), encoding="utf-8")
    assert m.main(["update", str(path)]) == 0
    assert m.main(["link", "doc1", "portfolio/snapshots/2026-10-01.md"]) == 0
    capsys.readouterr()
    assert m.main(["diff", str(path)]) == 0
    assert "沒有新內容" in capsys.readouterr().out
    assert m.main(["reminder"]) == 0
    assert "2026-10-01T07:00:00Z" in capsys.readouterr().out


def test_tests_do_not_touch_committed_manifest(tmp_path, monkeypatch):
    real = m.MANIFEST_PATH.read_text(encoding="utf-8")
    monkeypatch.setattr(m, "MANIFEST_PATH", tmp_path / "manifest.json")
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(scan([SNAP, CORE], ROWS, at="1999-01-01T00:00:00Z")), encoding="utf-8")
    m.main(["update", str(path)])
    monkeypatch.undo()
    assert m.MANIFEST_PATH.read_text(encoding="utf-8") == real


def test_committed_manifest_is_valid():
    manifest = m.load_manifest()
    assert m.CORE_ID in manifest["files"]
    assert set(manifest["core_rows"]) == set(m.CORE_SHEETS)
