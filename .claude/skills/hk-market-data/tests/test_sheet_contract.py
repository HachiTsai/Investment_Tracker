import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import sheet_contract as sc  # noqa: E402

CORE_ID = "1QBEgUi-kTOuLgj2yGHmP-0g_ug-Sl_M21SN0g93b6xI"


def _row(code, px=8.3, w=3.65, q=30698000):
    return dict(c=code, n=f"名稱{code}", w=w, q=q, px=px, ttm=0.4268, lfy=0.4268, chg=0, y=5.14, i26="派息 0.235 港元")


def _table(rows=None, gate=True):
    rows = [_row("998"), _row("1658", px=None, w=3.53, q=44160000)] if rows is None else rows
    table = dict(asof="2026-10-28", holdings_asof="2026/10/22", fx=4.1582, nav=14.77, units=1932849000.0,
                 ttm_unit=0.847, lfy_unit=0.869, has26=39, rows=rows, fails=[])
    if gate is not None:
        table["gate"] = dict(ok=gate, reasons=[] if gate else ["測試用未通過"])
    return table


def _write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _as_readback(payload):
    """模擬 get_values：字串去掉 ' 前綴、數字變成文字，尾端空格與空列被裁掉。"""
    out = []
    for write in payload["writes"]:
        grid = []
        for row in write["values"]:
            cells = [(v[1:] if v.startswith("'") else v) if isinstance(v, str) else str(v) for v in row]
            while cells and cells[-1] == "":
                cells.pop()
            grid.append(cells)
        while grid and not grid[-1]:
            grid.pop()
        tab, cells_range = write["range"].split("!")
        out.append(dict(range=f"'{tab}'!{cells_range}", values=grid))
    return out


def test_payload_layout_matches_contract():
    payload = sc.build_payload(_table())
    con, summary = payload["writes"]
    assert payload["spreadsheetId"] == sc.SHEET_ID
    assert con["range"] == "成分股!A1:J100" and len(con["values"]) == 100
    assert all(len(row) == 10 for row in con["values"])
    assert con["values"][0] == sc.HEADER_CONSTITUENTS
    assert con["values"][1] == ["'998", "名稱998", 3.65, 30698000, 8.3, 0.4268, 0.4268, 0, 5.14, "派息 0.235 港元"]
    assert con["values"][2][4] == ""  # px 為 null 寫空字串
    assert con["values"][3:] == [[""] * 10] * 97  # 沒用到的列清成空字串，不刪列
    assert summary["range"] == "摘要!A1:C13"
    assert [row[0] for row in summary["values"][1:]] == sc.SUMMARY_KEYS
    by_key = {row[0]: row for row in summary["values"][1:]}
    assert by_key["holdingsAsOf"][1] == "'2026-10-22"
    assert by_key["unitsOutstanding"][1] == "'1932849000"
    assert by_key["rows"][1] == "'2"
    assert by_key["lastUpdated"][1] == "'2026-10-28"
    assert by_key["note"][1] == "'推估，不是官方配息；未扣管理費與預扣稅"
    assert all(row[2] == "" for row in summary["values"][1:])


def test_header_and_summary_keys_match_workflow_doc():
    doc = (REPO / ".claude" / "workflows" / "hk-00882-dividend.md").read_text(encoding="utf-8")
    assert "`" + ",".join(sc.HEADER_CONSTITUENTS) + "`" in doc
    assert all(f"`{key}`" in doc for key in sc.SUMMARY_KEYS)


def test_build_refuses_failed_gate(tmp_path):
    out = tmp_path / "payload.json"
    table = _write(tmp_path / "table.json", _table(gate=False))
    assert sc.main(["build", table, str(out)]) == 1
    assert not out.exists()


def test_build_refuses_table_without_gate(tmp_path):
    out = tmp_path / "payload.json"
    table = _write(tmp_path / "table.json", _table(gate=None))
    assert sc.main(["build", table, str(out)]) == 1
    assert not out.exists()


def test_build_refuses_core_sheet(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "SHEET_ID", CORE_ID)
    out = tmp_path / "payload.json"
    table = _write(tmp_path / "table.json", _table())
    assert sc.main(["build", table, str(out)]) == 1
    assert not out.exists()


def test_build_refuses_more_rows_than_the_tab_holds(tmp_path):
    out = tmp_path / "payload.json"
    table = _write(tmp_path / "table.json", _table(rows=[_row(str(i)) for i in range(100)]))
    assert sc.main(["build", table, str(out)]) == 1
    assert not out.exists()


def test_normalize_date_accepts_both_separators():
    assert sc.normalize_date("2026/10/22") == "2026-10-22"
    assert sc.normalize_date("2026-10-22") == "2026-10-22"


def test_cell_matching_rules():
    assert sc._cell_matches(0.4268, "0.4268")
    assert not sc._cell_matches(0.4268, "0")  # 差超過寫入值小數位數的半個最小單位就不算相同
    assert not sc._cell_matches(3.65, "3.66")
    assert sc._cell_matches(30698000, "30698000")
    assert not sc._cell_matches(30698000, "30698001")
    assert sc._cell_matches("'998", "998")
    assert sc._cell_matches("", "")
    assert sc._cell_matches("", None)
    assert not sc._cell_matches(8.3, "")


def test_verify_passes_when_readback_matches():
    payload = sc.build_payload(_table())
    assert sc.verify(payload, _as_readback(payload)) == []


def test_verify_catches_a_wrong_summary_cell():
    payload = sc.build_payload(_table())
    readback = _as_readback(payload)
    summary = readback[1]["values"]
    summary[[row[0] for row in summary].index("rows")][1] = "48"
    problems = sc.verify(payload, readback)
    assert len(problems) == 1 and problems[0].startswith("摘要!B10")


def test_verify_flags_a_missing_range():
    payload = sc.build_payload(_table())
    problems = sc.verify(payload, _as_readback(payload)[:1])
    assert problems == ["摘要!A1:C13：讀回結果沒有這個範圍"]


def test_cli_build_then_verify(tmp_path):
    table = _write(tmp_path / "table.json", _table())
    payload = tmp_path / "payload.json"
    assert sc.main(["build", table, str(payload)]) == 0
    readback = _write(tmp_path / "readback.json", _as_readback(json.loads(payload.read_text(encoding="utf-8"))))
    assert sc.main(["verify", str(payload), readback]) == 0
    bad = json.loads(Path(readback).read_text(encoding="utf-8"))
    bad[0]["values"][1][3] = "1"  # 998 的 qty 被寫錯
    bad_path = _write(tmp_path / "bad.json", bad)
    assert sc.main(["verify", str(payload), bad_path]) == 1
