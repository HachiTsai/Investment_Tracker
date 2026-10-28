"""波段同步互鎖：開市標的的資料日已入庫就不重寫、不重複告警；--force 穿透。"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from swing_sync import _ymd, apply_interlock, run_swing_pipeline  # noqa: E402

HEADER = ["代號", "名稱", "市場", "來源", "狀態", "收盤"] + [""] * 10 + ["更新日"] + [""] * 7


def _row(ticker, updated="", state="舊狀態"):
    return [ticker, "名稱", "TW", "核心", state, "900.0"] + [""] * 10 + [updated] + [""] * 7


def _scan(ticker, last_date, fresh=True, **extra):
    return dict(ticker=ticker, last_date=last_date, fresh=fresh, state="OK", **extra)


def _run(client, scan_rows, new_rows, force=False):
    Path("/tmp/sheet.json").write_text(json.dumps([HEADER] + new_rows), encoding="utf-8")
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0, stdout=json.dumps(scan_rows))
        return run_swing_pipeline(sheet_id="fake_id", force=force, client=client)


def test_ymd_reads_sheet_display_dates():
    assert _ymd("2026-10-28") == "2026-10-28"
    assert _ymd("2026/10/28") == "2026-10-28"
    assert _ymd(" 2026/1/5 ") == "2026-01-05"
    assert _ymd("10/28/2026") is None  # 月日順序不確定就不猜
    assert _ymd("") is None
    assert _ymd(None) is None


def test_interlock_skips_rows_already_ingested():
    existing = [HEADER, _row("TPE:2330", "2026/10/28"), _row("HKG:1919", "2026-10-27")]
    scan = [_scan("TPE:2330", "2026-10-28"), _scan("HKG:1919", "2026-10-28")]

    assert apply_interlock(scan, existing) == ["TPE:2330"]
    assert [r["fresh"] for r in scan] == [False, True]


def test_interlock_lets_new_and_unknown_tickers_through():
    existing = [HEADER, _row("TPE:2330", "2026-10-27")]
    scan = [_scan("TPE:2330", "2026-10-28"), _scan("TPE:0050", "2026-10-28")]

    assert apply_interlock(scan, existing) == []
    assert all(r["fresh"] for r in scan)


def test_interlock_never_overwrites_with_older_data():
    existing = [HEADER, _row("TPE:2330", "2026-10-29")]
    scan = [_scan("TPE:2330", "2026-10-28")]

    assert apply_interlock(scan, existing) == ["TPE:2330"]
    assert scan[0]["fresh"] is False


def test_interlock_leaves_closed_and_unreadable_rows_alone(capsys):
    existing = [HEADER, _row("TPE:2330", "2026-10-28"), _row("TPE:0050", "十月底")]
    scan = [
        _scan("TPE:2330", "2026-10-28", fresh=False),
        _scan("TPE:0050", "2026-10-28"),
    ]

    assert apply_interlock(scan, existing) == []
    assert [r["fresh"] for r in scan] == [False, True]
    assert "無法解讀" in capsys.readouterr().out


def test_rerun_with_ingested_data_only_stamps_status(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    client = MagicMock()
    client.get_values.return_value = [HEADER, _row("TPE:2330", "2026-10-28")]
    scan = [_scan("TPE:2330", "2026-10-28", alert=True, prev_combo="長多短回檔", combo="共振偏多")]

    assert _run(client, scan, [_row("TPE:2330", "2026-10-28", state="新狀態")]) == 0

    client.update_values.assert_called_once()
    rng, values = client.update_values.call_args[0][1:3]
    assert rng == "Untitled!Z1:AA2"
    assert values[1] == ["狀態", "互鎖略過（資料日已入庫，維持既有數據）"]
    client.batch_update.assert_not_called()


def test_only_new_rows_are_alerted_and_written(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    client = MagicMock()
    client.get_values.return_value = [HEADER, _row("TPE:2330", "2026-10-28")]
    scan = [
        _scan("TPE:2330", "2026-10-28", alert=True),
        _scan("TPE:0050", "2026-10-28", alert=True),
    ]
    new_rows = [_row("TPE:2330", "2026-10-28", state="新狀態"), _row("TPE:0050", "2026-10-28", state="新狀態")]

    with patch("swing_sync.append_alert_rows") as mock_alerts:
        assert _run(client, scan, new_rows) == 0

    assert [r["ticker"] for r in mock_alerts.call_args[0][2]] == ["TPE:0050"]
    final_table = client.update_values.call_args_list[0][0][2]
    assert final_table[1][4] == "舊狀態"  # 已入庫的列保留既有值，不重寫
    assert final_table[2][0] == "TPE:0050" and final_table[2][4] == "新狀態"


def test_force_bypasses_interlock_and_overwrites_ingested_rows(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    client = MagicMock()
    client.get_values.return_value = [HEADER, _row("TPE:2330", "2026-10-28")]
    scan = [_scan("TPE:2330", "2026-10-28")]

    assert _run(client, scan, [_row("TPE:2330", "2026-10-28", state="新狀態")], force=True) == 0

    first_write = client.update_values.call_args_list[0][0]
    assert first_write[1] == "Untitled!A1:X2"
    assert first_write[2][1][4] == "新狀態"  # 強制補跑：整列以本次結果覆寫
